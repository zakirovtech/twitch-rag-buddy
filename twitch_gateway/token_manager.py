from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from typing import Any

import requests

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"


class TokenError(RuntimeError):
    pass


@dataclass
class TokenBundle:
    access_token: str
    refresh_token: str | None
    scope: list[str] | None
    token_type: str | None
    expires_in: int | None
    obtained_at: int | None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "TokenBundle":
        return TokenBundle(
            access_token=str(d.get("access_token") or ""),
            refresh_token=(d.get("refresh_token") or None),
            scope=(d.get("scope") or None),
            token_type=(d.get("token_type") or None),
            expires_in=(int(d["expires_in"]) if "expires_in" in d and d["expires_in"] is not None else None),
            obtained_at=(int(d["obtained_at"]) if "obtained_at" in d and d["obtained_at"] is not None else None),
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"access_token": self.access_token}
        if self.refresh_token is not None:
            d["refresh_token"] = self.refresh_token
        if self.scope is not None:
            d["scope"] = self.scope
        if self.token_type is not None:
            d["token_type"] = self.token_type
        if self.expires_in is not None:
            d["expires_in"] = self.expires_in
        if self.obtained_at is not None:
            d["obtained_at"] = self.obtained_at
        return d


class TwitchTokenManager:
    """Loads tokens from a JSON file and refreshes them when needed.

    - Uses Twitch /validate to check TTL.
    - Refresh tokens rotate: always persist the new refresh_token.
    """

    def __init__(
        self,
        token_file: str,
        client_id: str,
        client_secret: str,
        expected_login: str | None = None,
        min_ttl_sec: int = 120,
    ) -> None:
        self.token_file = token_file
        self.client_id = client_id
        self.client_secret = client_secret
        self.expected_login = expected_login.lower() if expected_login else None
        self.min_ttl_sec = min_ttl_sec
        self.log = logging.getLogger("token")

    def _read_file(self) -> TokenBundle:
        if not os.path.exists(self.token_file):
            raise TokenError(f"Token file not found: {self.token_file}")
        with open(self.token_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        tb = TokenBundle.from_dict(data)
        if not tb.access_token:
            raise TokenError("tokens.json missing access_token")
        return tb

    def _write_file_atomic(self, tb: TokenBundle) -> None:
        os.makedirs(os.path.dirname(self.token_file) or ".", exist_ok=True)
        payload = tb.to_dict()

        # Keep any extra fields if present
        try:
            existing = {}
            if os.path.exists(self.token_file):
                with open(self.token_file, "r", encoding="utf-8") as f:
                    existing = json.load(f) or {}
            if isinstance(existing, dict):
                existing.update(payload)
                payload = existing
        except Exception:
            pass

        fd, tmp_path = tempfile.mkstemp(
            prefix="tokens_", suffix=".json", dir=os.path.dirname(self.token_file) or None
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.token_file)
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass

    def _validate(self, access_token: str) -> dict[str, Any] | None:
        try:
            r = requests.get(
                VALIDATE_URL,
                headers={"Authorization": f"OAuth {access_token}"},
                timeout=10,
            )
            if r.status_code != 200:
                return None
            return r.json()
        except Exception:
            return None

    def _refresh(self, refresh_token: str) -> TokenBundle:
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        r = requests.post(TOKEN_URL, data=data, timeout=15)
        if r.status_code != 200:
            raise TokenError(f"Refresh failed: HTTP {r.status_code} {r.text}")

        j = r.json()
        tb = TokenBundle.from_dict(j)
        if not tb.access_token:
            raise TokenError("Refresh response missing access_token")

        # Twitch rotates refresh_token, but just in case:
        if not tb.refresh_token:
            tb.refresh_token = refresh_token

        tb.obtained_at = int(time.time())
        self._write_file_atomic(tb)
        return tb

    def get_valid_access_token(self, force_refresh: bool = False) -> str:
        tb = self._read_file()

        if force_refresh:
            if not tb.refresh_token:
                raise TokenError("force_refresh requested but no refresh_token in file")
            tb = self._refresh(tb.refresh_token)
            return tb.access_token

        info = self._validate(tb.access_token)
        if info is None:
            self.log.warning("Access token validation failed, refreshing...")
            if not tb.refresh_token:
                raise TokenError("Token invalid and no refresh_token available")
            tb = self._refresh(tb.refresh_token)
            return tb.access_token

        login = (info.get("login") or "").lower()
        if self.expected_login and login and login != self.expected_login:
            raise TokenError(
                f"Token belongs to '{login}', but TWITCH_NICK is '{self.expected_login}'. "
                "Re-run OAuth under the bot account."
            )

        ttl = int(info.get("expires_in") or 0)
        if ttl <= self.min_ttl_sec:
            self.log.info("Token expires in %ss (<=%ss), refreshing...", ttl, self.min_ttl_sec)
            if not tb.refresh_token:
                raise TokenError("Token expiring soon and no refresh_token available")
            tb = self._refresh(tb.refresh_token)
            return tb.access_token

        return tb.access_token

    def get_irc_pass(self, force_refresh: bool = False) -> str:
        token = self.get_valid_access_token(force_refresh=force_refresh)
        return f"oauth:{token}" if not token.startswith("oauth:") else token
