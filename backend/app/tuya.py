"""Tuya adapters: bounded signed HTTP and SDK Pulsar with durable ACK and TLS."""
import base64
import hashlib
import hmac
import json
import ssl
import threading
import time
from urllib.parse import urlencode
import httpx
from tuya_connector import TuyaOpenPulsar
from . import config
from .db import take_rate, health
from .events import ingest


class Rejected(Exception):
    def __init__(self, code):
        self.code = str(code)
        super().__init__(self.code)


class TuyaHTTP:
    def __init__(self):
        self.access_id = config.tuya_access_id()
        self.secret = config.tuya_access_secret()
        self.token, self.expiry = "", 0
        self.client = httpx.Client(base_url=config.TUYA_ENDPOINT, timeout=12)
        self.lock = threading.Lock()

    def _send(self, method, path, body=None, token=""):
        if not take_rate("tuya", config.CALLS_PER_MINUTE):
            raise Rejected("local_rate_limit")
        raw = json.dumps(body, separators=(",", ":")) if body is not None else ""
        ts = str(int(time.time() * 1000))
        signed = method + "\n" + hashlib.sha256(raw.encode()).hexdigest() + "\n\n" + path
        signature = hmac.new(self.secret.encode(), (self.access_id + token + ts + signed).encode(), hashlib.sha256).hexdigest().upper()
        response = self.client.request(method, path, content=raw, headers={
            "client_id": self.access_id, "access_token": token, "t": ts,
            "sign": signature, "sign_method": "HMAC-SHA256", "Content-Type": "application/json"})
        health("last_http", {"at": time.time(), "status": response.status_code})
        if response.status_code == 429:
            raise Rejected("rate_limit")
        response.raise_for_status()
        data = response.json()
        if not data.get("success"):
            raise Rejected(data.get("code", "tuya_error"))
        return data.get("result")

    def request(self, method, path, body=None):
        with self.lock:
            if time.time() >= self.expiry:
                self.token = ""
                data = self._send("GET", "/v1.0/token?grant_type=1")
                self.token = data["access_token"]
                self.expiry = time.time() + data["expire_time"] - 60
            try:
                return self._send(method, path, body, self.token)
            except Rejected as exc:
                if exc.code in ("1010", "1011"):
                    self.expiry = 0
                    # Only read requests are retried automatically.
                    if method == "GET":
                        data = self._send("GET", "/v1.0/token?grant_type=1")
                        self.token = data["access_token"]
                        self.expiry = time.time() + data["expire_time"] - 60
                        return self._send(method, path, body, self.token)
                raise

    def command(self, device, power):
        cfg = device.config
        adapter = cfg.get("command", {})
        if adapter.get("kind") == "ir":
            # Exact body and path are provisioned after validating this remote.
            return self.request("POST", adapter["path"], adapter["on" if power else "off"])
        return self.request("POST", f"/v1.0/devices/{device.id}/commands",
                            {"commands": [{"code": adapter["code"], "value": power}]})

    def read_status(self, device):
        if device.config.get("api_family", "legacy") == "iot-03":
            status = self.request("GET", f"/v1.0/iot-03/devices/{device.id}/status")
            if not isinstance(status, list):
                raise ValueError("invalid_device_status_response")
            return {"status": status}
        return self.request("GET", f"/v1.0/devices/{device.id}")


class DurablePulsar(TuyaOpenPulsar):
    def __init__(self, reconcile):
        super().__init__(config.tuya_access_id(), config.tuya_access_secret(),
                         config.PULSAR_ENDPOINT, "event")
        self.daemon = True
        self.reconcile = reconcile
        self.ws_app.on_open = self.on_open

    def on_open(self, _):
        health("pulsar", {"connected": True})
        self.reconcile.set()

    def _on_message(self, ws, message):
        try:
            envelope = json.loads(message)
            payload = base64.b64decode(envelope["payload"]).decode("ascii")
            # Reuse the SDK's Tuya AES decoding, but bypass its unconditional ACK.
            wrapped = json.loads(payload)
            clear = self._TuyaOpenPulsar__decrypt_by_aes(wrapped["data"], config.tuya_access_secret())
            ingest(json.loads(clear), "pulsar:" + str(envelope["messageId"]))
            ws.send(json.dumps({"messageId": envelope["messageId"]}))
        except Exception:
            health("pulsar", {"connected": False, "error": "ingest_failed_no_ack"})
            ws.close()  # Broker can redeliver after reconnection.

    def _on_error(self, _, error):
        health("pulsar", {"connected": False, "error": type(error).__name__})

    def _on_close(self, ws, code, message):
        health("pulsar", {"connected": False})

    def run(self):
        delay = 1
        while not self._stop_event.is_set():
            self.ws_app.run_forever(sslopt={"cert_reqs": ssl.CERT_REQUIRED},
                                   ping_interval=30, ping_timeout=10)
            health("pulsar", {"connected": False})
            if self._stop_event.wait(delay):
                break
            delay = min(60, delay * 2)

    def stop(self):
        self._stop_event.set()
        self.ws_app.close()
