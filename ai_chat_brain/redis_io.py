from __future__ import annotations

import time
from typing import Iterable, Any

import redis.asyncio as redis


class RedisIO:
    def __init__(self, redis_url: str, stream_in: str, stream_out: str, group_in: str) -> None:
        self.redis_url = redis_url
        self.stream_in = stream_in
        self.stream_out = stream_out
        self.group_in = group_in
        self.r: redis.Redis | None = None

    async def connect(self) -> None:
        self.r = redis.from_url(self.redis_url, decode_responses=True)

        # consumer group for IN stream
        try:
            await self.r.xgroup_create(name=self.stream_in, groupname=self.group_in, id="0-0", mkstream=True)
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def close(self) -> None:
        if self.r:
            await self.r.aclose()
        self.r = None

    async def read_in(self, consumer: str, count: int = 50, block_ms: int = 5000) -> list[tuple[str, dict[str, str]]]:
        assert self.r is not None
        resp = await self.r.xreadgroup(
            groupname=self.group_in,
            consumername=consumer,
            streams={self.stream_in: ">"},
            count=count,
            block=block_ms,
        )
        items: list[tuple[str, dict[str, str]]] = []
        for _stream, msgs in resp:
            for msg_id, data in msgs:
                items.append((msg_id, data))
        return items

    async def ack_in(self, ids: Iterable[str]) -> None:
        assert self.r is not None
        ids_list = list(ids)
        if not ids_list:
            return
        await self.r.xack(self.stream_in, self.group_in, *ids_list)

    async def send_out(self, channel: str, text: str, reply_to: str | None = None) -> str:
        assert self.r is not None
        fields: dict[str, str] = {
            "ts": str(int(time.time())),
            "channel": channel,
            "text": text,
        }
        if reply_to:
            fields["reply_to"] = reply_to
        return await self.r.xadd(self.stream_out, fields)
