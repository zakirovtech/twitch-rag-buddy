from __future__ import annotations

import time
from collections import deque
from typing import Deque

from models import ChatItem


class SessionBuffer:
    def __init__(self, window_sec: int = 60) -> None:
        self.window_sec = window_sec
        self.items: Deque[ChatItem] = deque()

    def add(self, item: ChatItem) -> None:
        self.items.append(item)
        self._trim()

    def _trim(self) -> None:
        cutoff = int(time.time()) - self.window_sec
        while self.items and self.items[0].ts < cutoff:
            self.items.popleft()

    def snapshot(self) -> list[ChatItem]:
        self._trim()
        return list(self.items)
