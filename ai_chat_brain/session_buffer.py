from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict

from models import ChatItem


@dataclass
class ChannelStats:
    last_message_ts: int
    msgs_last_10s: int
    msgs_last_60s: int


class ChannelBuffer:
    """Short-term in-memory buffer per channel.

    We keep both a time window and a max_items cap.
    """

    def __init__(self, window_sec: int = 120, max_items: int = 200) -> None:
        self.window_sec = window_sec
        self.max_items = max_items
        self.items: Deque[ChatItem] = deque()

    def add(self, item: ChatItem) -> None:
        self.items.append(item)
        self._trim()

    def _trim(self) -> None:
        now = int(time.time())
        cutoff = now - self.window_sec
        while self.items and self.items[0].ts < cutoff:
            self.items.popleft()
        while len(self.items) > self.max_items:
            self.items.popleft()

    def snapshot(self, last_n: int | None = None) -> list[ChatItem]:
        self._trim()
        if last_n is None or last_n <= 0:
            return list(self.items)
        return list(self.items)[-last_n:]

    def stats(self) -> ChannelStats:
        self._trim()
        if not self.items:
            return ChannelStats(last_message_ts=0, msgs_last_10s=0, msgs_last_60s=0)

        now = int(time.time())
        msgs_last_10s = sum(1 for it in self.items if it.ts >= now - 10)
        msgs_last_60s = sum(1 for it in self.items if it.ts >= now - 60)
        return ChannelStats(
            last_message_ts=self.items[-1].ts,
            msgs_last_10s=msgs_last_10s,
            msgs_last_60s=msgs_last_60s,
        )


class ChatState:
    """Buffers for multiple channels."""

    def __init__(self, window_sec: int = 120, max_items: int = 200) -> None:
        self.window_sec = window_sec
        self.max_items = max_items
        self._by_channel: Dict[str, ChannelBuffer] = {}

    def add(self, item: ChatItem) -> None:
        ch = item.channel.lower()
        if ch not in self._by_channel:
            self._by_channel[ch] = ChannelBuffer(window_sec=self.window_sec, max_items=self.max_items)
        self._by_channel[ch].add(item)

    def channels(self) -> list[str]:
        return list(self._by_channel.keys())

    def buffer(self, channel: str) -> ChannelBuffer:
        ch = channel.lower()
        if ch not in self._by_channel:
            self._by_channel[ch] = ChannelBuffer(window_sec=self.window_sec, max_items=self.max_items)
        return self._by_channel[ch]
