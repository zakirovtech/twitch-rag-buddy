from __future__ import annotations

import time
from typing import Any, Iterable

import redis.asyncio as redis


class RedisBus:
    def __init__(self, redis_url: str, stream_in: str, stream_out: str, group: str) -> None:
        self.redis_url = redis_url
        self.stream_in = stream_in
        self.stream_out = stream_out
        self.group = group
        self.r: redis.Redis | None = None


    async def connect(self) -> None:
        self.r = redis.from_url(self.redis_url, decode_responses=True)

        # Create consumer group for OUT stream (if not exists)
        try:
            await self.r.xgroup_create(name=self.stream_out, groupname=self.group, id="0-0", mkstream=True)
        except Exception as e:
            # BUSYGROUP is ok
            if "BUSYGROUP" not in str(e):
                raise

        # Ensure IN stream exists (mkstream is only for xgroup_create)
        await self.r.xadd(self.stream_in, {"_bootstrap": "1", "ts": str(int(time.time()))})
        # Можно удалить bootstrap запись — не обязательно

    async def close(self) -> None:
        if self.r is not None:
            await self.r.aclose()
        self.r = None

    async def publish_in(self, fields: dict[str, str]) -> str:
        assert self.r is not None
        return await self.r.xadd(self.stream_in, fields)

    async def read_out(
        self,
        consumer: str,
        count: int = 10,
        block_ms: int = 5000,
        stream_id: str = ">"
    ) -> list[tuple[str, dict[str, str]]]:
        """
        Возвращает список (id, fields) из stream_out через consumer group.
        stream_id=">" читает новые, "0" — pending.
        """
        assert self.r is not None
        resp = await self.r.xreadgroup(
            groupname=self.group,
            consumername=consumer,
            streams={self.stream_out: stream_id},
            count=count,
            block=block_ms,
        )
        items: list[tuple[str, dict[str, str]]] = []
        for _stream, msgs in resp:
            for msg_id, data in msgs:
                items.append((msg_id, data))
        return items

    async def ack_out(self, ids: Iterable[str]) -> None:
        assert self.r is not None
        ids_list = list(ids)
        if not ids_list:
            return
        await self.r.xack(self.stream_out, self.group, *ids_list)

    async def claim_stale_pending(self, consumer: str, min_idle_ms: int = 60000, count: int = 10) -> list[tuple[str, dict[str, str]]]:
        """
        Опционально: вытаскивать зависшие pending сообщения.
        """
        assert self.r is not None
        try:
            resp: Any = await self.r.xautoclaim(
                name=self.stream_out,
                groupname=self.group,
                consumername=consumer,
                min_idle_time=min_idle_ms,
                start_id="0-0",
                count=count,
            )
            # redis-py returns: (next_start_id, [(id, {fields})...], deleted_ids)
            msgs = resp[1]
            return [(mid, data) for mid, data in msgs]
        except Exception:
            return []
