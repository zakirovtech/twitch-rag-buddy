import os, json, secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, urlencode
from pathlib import Path
from dotenv import load_dotenv

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
TWITCH_GATEWAY_DIR = BASE_DIR / "twitch_gateway"

# Для локального запуска нужно подгрузить в окружение
load_dotenv(BASE_DIR / ".env")

CLIENT_ID = os.environ["TWITCH_APP_CLIENT_ID"]
CLIENT_SECRET = os.environ["TWITCH_APP_CLIENT_SECRET"]
REDIRECT_URI = os.environ["TWITCH_CALLBACK_URL"]
SCOPES = os.environ.get("TWITCH_SCOPES", "chat:read chat:edit")

AUTH_URL = "https://id.twitch.tv/oauth2/authorize"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"

STATE = secrets.token_urlsafe(24)

def build_auth_url():
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "state": STATE,
        "force_verify": "true",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str):
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }
    
    r = requests.post(TOKEN_URL, data=data, timeout=15)
    r.raise_for_status()
    
    return r.json()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # ожидаем /oauth/twitch/callback?code=...&state=...
        from urllib.parse import urlparse, parse_qs
        q = urlparse(self.path)
        qs = parse_qs(q.query)

        code = (qs.get("code") or [None])[0]
        state = (qs.get("state") or [None])[0]

        if not code:
            self.send_response(400); self.end_headers()
            self.wfile.write(b"Missing code")
            return
        if state != STATE:
            self.send_response(400); self.end_headers()
            self.wfile.write(b"Bad state")
            return

        tokens = exchange_code(code)
        with open(TWITCH_GATEWAY_DIR, "w", encoding="utf-8") as f:
            json.dump(tokens, f, ensure_ascii=False, indent=2)

        self.send_response(200); self.end_headers()
        self.wfile.write(b"OK. Tokens saved to tokens.json. You can close this tab.")

if __name__ == "__main__":
    print("Open this URL in browser:\n", build_auth_url())
    # вытащим порт из redirect
    
    port = urlparse(REDIRECT_URI).port or 80
    server = HTTPServer(("localhost", port), Handler)
    print(f"Listening on http://localhost:{port} ...")
    server.handle_request()  # один запрос и выходим
