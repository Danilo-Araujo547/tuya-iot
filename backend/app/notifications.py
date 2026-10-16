"""Server-only notification connections and single-attempt text delivery.

Tokens and webhook URLs never enter workflow definitions, logs or run snapshots.
"""
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, SecretStr, model_validator
from .automations import admin
from .security import authenticate
from .config import secret

router = APIRouter(prefix='/api/v1/notification-connections')
Channel = Literal['whatsapp', 'telegram', 'webhook']
DEFAULTS = {'whatsapp': 'http://172.16.0.59:3011', 'telegram': 'https://api.telegram.org', 'webhook': ''}
# Telegram authenticates in the URL: suppress HTTP client's request URL logging.
logging.getLogger('httpx').setLevel(logging.WARNING)


def directory():
    return Path(os.getenv('NOTIFICATION_CONFIG_DIR', '/var/lib/tuya-notifications'))


def connection(channel):
    path = directory() / (channel+'.json')
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    prefix = channel.upper()
    return {'url': secret(prefix+'_API_URL', DEFAULTS[channel]), 'token': secret(prefix+'_API_TOKEN')}


def valid_url(url):
    try:
        parsed = urlsplit(url)
        return parsed.scheme in ('http', 'https') and bool(parsed.hostname) and parsed.username is None and parsed.password is None and not parsed.fragment and bool(parsed.port or True) and not any(c.isspace() for c in url)
    except ValueError:
        return False


def configured(channel):
    cfg = connection(channel)
    return bool(valid_url(cfg.get('url', '')) and (channel == 'webhook' or cfg.get('token')))


class Notification(BaseModel):
    channel: Channel = 'whatsapp'
    destination_type: Literal['phone', 'group_id', 'chat_id'] = 'phone'
    destination: str = Field(default='', max_length=160)
    message: str = Field(default='', max_length=4096)
    timeout_seconds: int = Field(default=20, ge=3, le=30)


def notification_issues(data):
    errors = []
    if not data['message'].strip(): errors.append('Escreva a mensagem')
    if data['channel'] != 'webhook':
        destination = data['destination'].strip()
        if not destination: errors.append('Informe o destinatário')
        elif data['channel'] == 'telegram' and not re.fullmatch(r'-?\d+|@[A-Za-z0-9_]{5,}', destination): errors.append('Use o chat_id numérico ou @canal do Telegram')
        elif data['channel'] == 'whatsapp':
            kind = data['destination_type']
            if kind == 'phone' and not re.fullmatch(r'[+\d ().-]{8,30}', destination): errors.append('Telefone inválido')
            if kind == 'group_id' and not re.fullmatch(r'\d+(?:-\d+)?(?:@g\.us)?', destination): errors.append('ID do grupo inválido')
    if not configured(data['channel']): errors.append('Configure a conexão '+data['channel']+' no servidor')
    return errors


class ConnectionBody(BaseModel):
    url: str = Field(default='', max_length=2048)
    token: SecretStr = Field(default=SecretStr(''), max_length=1024)
    clear_token: bool = False
    @model_validator(mode='after')
    def check(self):
        if self.url and not valid_url(self.url): raise ValueError('Use uma URL HTTP ou HTTPS sem usuário e senha')
        if any(c in self.token.get_secret_value() for c in '\r\n'): raise ValueError('Token inválido')
        return self


def summary(channel):
    cfg = connection(channel)
    # Webhook URL may carry credentials: it is write-only, just like the token.
    return {'channel': channel, 'configured': configured(channel), 'has_token': bool(cfg.get('token')),
            'url': cfg.get('url', '') if channel == 'whatsapp' else DEFAULTS[channel]}


@router.get('')
def list_connections(request: Request):
    if authenticate(request) != 'admin': raise HTTPException(403, 'Somente o administrador pode consultar conexões')
    return [summary(c) for c in DEFAULTS]


@router.put('/{channel}')
def save_connection(channel: Channel, body: ConnectionBody, request: Request):
    admin(request)
    cfg = connection(channel)
    url = DEFAULTS['telegram'] if channel == 'telegram' else body.url or cfg.get('url', '')
    if not valid_url(url): raise HTTPException(422, 'Informe a URL da conexão')
    token = '' if body.clear_token else body.token.get_secret_value() or cfg.get('token', '')
    if channel == 'telegram' and token and not re.fullmatch(r'\d+:[A-Za-z0-9_-]+', token): raise HTTPException(422, 'Token do bot Telegram inválido')
    folder = directory(); folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=folder, prefix=channel+'-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file: json.dump({'url': url, 'token': token}, file)
        os.chmod(temporary, 0o600)
        os.replace(temporary, folder/(channel+'.json'))
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    return summary(channel)


def send_notification(data, context):
    errors = notification_issues(data)
    if errors: return {'status': 'bloqueada', 'detail': '; '.join(errors), 'channel': data['channel']}
    channel = data['channel']; cfg = connection(channel); token = cfg.get('token', '')
    headers = {'Content-Type': 'application/json'}
    if channel == 'whatsapp':
        url = cfg['url'].rstrip('/')+'/api/send'
        headers['Authorization'] = 'Bearer '+token
        payload = {data['destination_type']: data['destination'].strip(), 'message': data['message']}
    elif channel == 'telegram':
        url = 'https://api.telegram.org/bot'+token+'/sendMessage'
        payload = {'chat_id': data['destination'].strip(), 'text': data['message']}
    else:
        url = cfg['url']
        if token: headers['Authorization'] = 'Bearer '+token
        headers['Idempotency-Key'] = context['run_id']+':'+context['node_id']
        payload = {'event': 'automation.notification', 'message': data['message'], **context}
    try:
        # No redirects, retries or automatic replays. Bound the response before parsing.
        with httpx.Client(timeout=httpx.Timeout(data['timeout_seconds']), follow_redirects=False) as client:
            with client.stream('POST', url, headers=headers, json=payload) as response:
                status = response.status_code; content = bytearray()
                for part in response.iter_bytes():
                    content.extend(part)
                    if len(content) > 65536: return {'status': 'resultado desconhecido', 'channel': channel, 'detail': 'Resposta do provedor excedeu o limite'}
        if not 200 <= status < 300:
            # 5xx may happen after the provider started delivery.
            return {'status': 'resultado desconhecido' if status >= 500 and not (channel == 'whatsapp' and status == 503) else 'falhou', 'channel': channel, 'http_status': status, 'detail': 'Provedor respondeu HTTP '+str(status)+'; envio não repetido'}
        if channel == 'webhook': return {'status': 'aceito pelo provedor', 'channel': channel, 'http_status': status}
        result = json.loads(content)
        accepted = result.get('success') is True and result.get('accepted') is True if channel == 'whatsapp' else result.get('ok') is True
        if not accepted: return {'status': 'falhou', 'channel': channel, 'detail': 'Provedor não aceitou a mensagem'}
        identifier = result.get('whatsapp_message_id') if channel == 'whatsapp' else result.get('result', {}).get('message_id')
        return {'status': 'aceito pelo provedor', 'channel': channel, 'provider_message_id': str(identifier)[:160] if identifier is not None else None, 'delivery': 'recebimento e leitura não confirmados'}
    except Exception:
        # Never expose exception text: it may include URLs, tokens or recipients.
        return {'status': 'resultado desconhecido', 'channel': channel, 'detail': 'Falha de comunicação; envio não repetido'}
