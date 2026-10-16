import React,{useEffect,useState} from 'react';
import {Settings2,Save} from 'lucide-react';
import {GlassSelect} from './GlassSelect';
type Config={channel?:string;destination_type?:string;destination?:string;message?:string;timeout_seconds?:number};
type Api=<T>(path:string,init?:RequestInit)=>Promise<T>;
type Connection={channel:string;configured:boolean;has_token:boolean;url:string};
function Field({title,children}:{title:string;children:React.ReactNode}){return <label className="feature-field"><span>{title}</span>{children}</label>}
export function NotificationEditor({api,config,edit}:{api:Api;config:Config;edit:(patch:Partial<Config>)=>void}){
  const [connections,setConnections]=useState<Connection[]>([]),[settings,setSettings]=useState(false),[url,setUrl]=useState(''),[token,setToken]=useState(''),[clearToken,setClearToken]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const channel=config.channel||'whatsapp',current=connections.find(c=>c.channel===channel);
  useEffect(()=>{let alive=true;api<Connection[]>('/notification-connections').then(c=>{if(alive)setConnections(c)}).catch(e=>{if(alive)setError((e as Error).message)});return()=>{alive=false}},[api]);
  useEffect(()=>{setUrl(current?.url||'');setToken('');setClearToken(false);setError('');setNotice('');setSettings(false)},[channel,current?.url]);
  return <div className="notification-editor">
    <Field title="Canal de notificação"><GlassSelect label="Canal de notificação" value={channel} onChange={channel=>edit({channel,destination_type:channel==='telegram'?'chat_id':'phone',destination:''})} options={[{value:'whatsapp',label:'WhatsApp'},{value:'telegram',label:'Telegram'},{value:'webhook',label:'Webhook HTTP'}]}/></Field>
    <div className="notification-connection"><span className={current?.configured?'ready':''}>{current?.configured?'Conexão configurada':'Conexão pendente'}</span><button onClick={()=>setSettings(v=>!v)}><Settings2 size={13}/>Configurar</button></div>
    {settings&&<section className="notification-settings"><h3>Conexão {channel==='whatsapp'?'WhatsApp':channel==='telegram'?'Telegram':'Webhook'}</h3>
      {channel!=='telegram'&&<Field title={channel==='whatsapp'?'URL da API WhatsApp':'URL de destino do webhook'}><input aria-label="URL da conexão" value={url} onChange={e=>setUrl(e.target.value)} placeholder={channel==='whatsapp'?'http://172.16.0.59:3011':current?.configured?'URL já salva; deixe vazio para manter':'https://seu-servidor/webhook'} autoComplete="off"/></Field>}
      <Field title={channel==='telegram'?'Token do bot Telegram':'Bearer token'+(channel==='webhook'?' (opcional)':'')}><input aria-label="Token da conexão" type="password" value={token} onChange={e=>setToken(e.target.value)} autoComplete="new-password" placeholder={current?.has_token?'Token salvo; deixe vazio para manter':'Informe o token'}/></Field>
      {current?.has_token&&<label className="feature-check"><input type="checkbox" checked={clearToken} onChange={e=>setClearToken(e.target.checked)}/><span>Remover token salvo</span></label>}
      <p>Conexão compartilhada pelos blocos deste canal. Credenciais salvas no servidor e separadas do fluxo.</p>
      <button className="outline-button" disabled={busy} onClick={async()=>{setBusy(true);setError('');setNotice('');try{const row=await api<Connection>('/notification-connections/'+channel,{method:'PUT',body:JSON.stringify({url,token,clear_token:clearToken})});setConnections(old=>[...old.filter(c=>c.channel!==channel),row]);setToken('');setClearToken(false);setSettings(false);setNotice('Conexão salva. Nenhuma mensagem enviada.')}catch(e){setError((e as Error).message)}finally{setBusy(false)}}}><Save size={13}/>{busy?'Salvando…':'Salvar conexão'}</button>
    </section>}
    {channel==='whatsapp'&&<Field title="Tipo de destinatário"><GlassSelect label="Tipo de destinatário" value={config.destination_type||'phone'} onChange={destination_type=>edit({destination_type})} options={[{value:'phone',label:'Telefone com DDI e DDD'},{value:'group_id',label:'Grupo (group_id)'},{value:'chat_id',label:'Conversa ou contato (chat_id)'}]}/></Field>}
    {channel!=='webhook'&&<Field title={channel==='telegram'?'Chat ID ou @canal':'Destinatário'}><input aria-label="Destinatário da notificação" value={config.destination||''} onChange={e=>edit({destination:e.target.value})} maxLength={160} placeholder={channel==='telegram'?'-1001234567890':config.destination_type==='group_id'?'120363…@g.us':'5511999999999'} autoComplete="off"/></Field>}
    <Field title="Mensagem"><textarea aria-label="Mensagem da notificação" value={config.message||''} onChange={e=>edit({message:e.target.value})} maxLength={4096} rows={6} placeholder="Ex.: A temperatura do ambiente ultrapassou o limite."/></Field><div className="notification-length">{config.message?.length||0} / 4096</div>
    <Field title="Timeout do envio (segundos)"><input type="number" min={3} max={30} value={config.timeout_seconds||20} onChange={e=>edit({timeout_seconds:Number(e.target.value)})}/></Field>
    {channel==='webhook'&&<p>Envia POST JSON com message, event, run_id, node_id, flow_name, revision e timestamp. O destino precisa aceitar esse formato.</p>}
    {channel==='telegram'&&<p>O bot precisa ter acesso à conversa. Em conversas privadas, inicie o bot pelo Telegram antes de usar.</p>}
    <p>O bloco envia uma vez quando o fluxo chegar até ele. Aceitação pelo serviço não confirma leitura. Timeout ou resultado desconhecido interrompe a execução sem reenviar.</p>
    {error&&<p role="alert" className="notification-error">{error}</p>}{notice&&<p role="status" className="notification-success">{notice}</p>}
  </div>
}
