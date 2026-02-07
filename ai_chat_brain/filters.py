from __future__ import annotations

import re
from typing import Iterable

from config import REPEAT_RE, URL_RE, ONLY_EMOJIISH_RE
from models import FilterResult


class TextFilters:
    def __init__(self, banwords: Iterable[str], bot_nick: str, min_len: int = 3) -> None:
        self.bot_nick = bot_nick.lower()
        self.min_len = min_len
        self.banwords = [w.strip().lower() for w in banwords if w.strip()]
        self._ban_re = None
        if self.banwords:
            pattern = r"|".join(re.escape(w) for w in sorted(self.banwords, key=len, reverse=True))
            self._ban_re = re.compile(pattern, re.IGNORECASE)

    def normalize(self, text: str) -> str:
        t = text.strip()
        t = REPEAT_RE.sub(r"\1\1\1", t)          # aaaaaaa -> aaa
        t = re.sub(r"\s+", " ", t)
        return t

    def contains_banword(self, text: str) -> bool:
        if not self._ban_re:
            return False
        return bool(self._ban_re.search(text))

    def should_index(self, user: str, text: str) -> FilterResult:
        t = self.normalize(text)

        if not t or len(t) < self.min_len:
            return FilterResult(False, "too_short")

        if user and user.lower() == self.bot_nick:
            return FilterResult(False, "self_message")

        if self.contains_banword(t):
            return FilterResult(False, "banword")

        if URL_RE.search(t):
            return FilterResult(False, "has_url")

        # слишком “шумно” (только символы/эмодзи)
        if ONLY_EMOJIISH_RE.match(t):
            return FilterResult(False, "noise")

        return FilterResult(True, "ok")

    def is_trigger(self, text: str, bot_nick: str) -> bool:
        t = text.strip()
        if t.lower().startswith("!ai "):
            return True
        if f"@{bot_nick.lower()}" in t.lower():
            return True
        return False

    def parse_ai_command(self, text: str) -> str | None:
        t = text.strip()
        if t.lower().startswith("!ai "):
            return t[4:].strip() or None
        return None
