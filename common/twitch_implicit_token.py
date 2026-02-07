#!/usr/bin/env python3
import http.server
import json
import secrets
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass

HOST = "127.0.0.1"
PORT = 3000

@dataclass
class Config:
    client_id: str
    redirect_uri: str
    scope: str  # space-delimited, e.g. "chat:read chat:write"

STATE = secrets.token_hex(16)
TOKEN_BOX = {"token": None, "scope": None, "state": None, "token_type": None}

HTML = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>Twitch OAuth Callback</title></head>
<body>
<h3>Получаем токен…</h3>
<pre id="out"></pre>
<script>
(function() {{
  // Twitch implicit возвращает токен во фрагменте URL: #access_token=...&scope=...&state=...&token_type=...
  const hash = window.location.hash.startsWith('#') ? window.location.hash.slice(1) : window.location.hash;
  const params = new URLSearchParams(hash);

  const payload = {{
    access_token: params.get('access_token'),
    scope: params.get('scope'),
    state: params.get('state'),
    token_type: params.get('token_type')
  }};

  document.getElementById('out').textContent = JSON.stringify(payload, null, 2);

  fetch('/token', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload)
  }}).then(async (r) => {{
    const t = await r.text();
    document.getElementById('out').textContent += "\\n\\n" + t;
  }}).catch(err => {{
    document.getElementById('out').textContent += "\\n\\nERROR: " + err;
  }});
}})();
</script>
</body>
</html>
"""

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML.encode("utf-8"))
            return

    def do_POST(self):
        if self.path != "/token":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Bad JSON")
            return

        TOKEN_BOX["token"] = data.get("access_token")
        TOKEN_BOX["scope"] = data.get("scope")
        TOKEN_BOX["state"] = data.get("state")
        TOKEN_BOX["token_type"] = data.get("token_type")

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"OK. You can close this tab.")

def build_auth_url(cfg: Config) -> str:
    # согласно доке: /authorize?response_type=token&client_id=...&redirect_uri=...&scope=...&state=...
    # scope — пробелами, но в URL будет закодирован
    q = {
        "response_type": "token",
        "client_id": cfg.client_id,
        "redirect_uri": cfg.redirect_uri,
        "scope": cfg.scope,
        "state": STATE,
        "force_verify": "true",
    }
    return "https://id.twitch.tv/oauth2/authorize?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)

def main():
    print("Twitch Implicit OAuth helper")
    client_id = input("Client ID: ").strip()
    # redirect_uri должен совпадать с тем, что добавлен в приложении
    redirect_uri = f"http://{HOST}:{PORT}"
    scope = input("Scopes (через пробел, например: chat:read chat:write): ").strip()

    cfg = Config(client_id=client_id, redirect_uri=redirect_uri, scope=scope)

    httpd = http.server.HTTPServer((HOST, PORT), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

    url = build_auth_url(cfg)
    print("\nОткрой эту ссылку в браузере (или она откроется сама):\n")
    print(url, "\n")

    try:
        webbrowser.open(url)
    except Exception:
        pass

    print("Ждём токен через redirect на", redirect_uri)

    # ждём получения
    while TOKEN_BOX["token"] is None:
        pass

    # проверка state
    if TOKEN_BOX["state"] != STATE:
        print("\n!!! STATE MISMATCH. Игнорируем результат (возможна подмена/не тот таб).")
    else:
        print("\nГотово! Вставь в .env:\n")
        print("TWITCH_OAUTH=oauth:" + TOKEN_BOX["token"])
        print("\nScopes вернулись:", TOKEN_BOX["scope"])
        print("Token type:", TOKEN_BOX["token_type"])
        print("\n(Таб в браузере можно закрыть.)")

    httpd.shutdown()


if __name__ == "__main__":
    main()
