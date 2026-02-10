from __future__ import annotations

import asyncio
import ssl
from typing import AsyncIterator

from .models import IrcMessage


def parse_irc_line(line: str) -> IrcMessage:
    # RFC-ish parser + Twitch tags
    tags: dict[str, str] = {}
    prefix: str | None = None
    trailing: str | None = None

    rest = line

    # tags
    if rest.startswith("@"):
        tags_part, rest = rest.split(" ", 1)
        tags_part = tags_part[1:]
        if tags_part:
            for kv in tags_part.split(";"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    tags[k] = v
                else:
                    tags[kv] = ""

    # prefix
    if rest.startswith(":"):
        prefix_part, rest = rest.split(" ", 1)
        prefix = prefix_part[1:]

    # trailing
    if " :" in rest:
        head, trailing = rest.split(" :", 1)
    else:
        head = rest

    parts = head.split()
    command = parts[0] if parts else ""
    params = parts[1:] if len(parts) > 1 else []

    return IrcMessage(
        raw=line,
        tags=tags,
        prefix=prefix,
        command=command,
        params=params,
        trailing=trailing,
    )


class TwitchIrcClient:
    def __init__(self, nick: str, oauth: str) -> None:
        self.nick = nick
        self.oauth = oauth
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self._write_lock = asyncio.Lock()

    async def connect(self) -> None:
        ctx = ssl.create_default_context()
        reader, writer = await asyncio.open_connection(
            host="irc.chat.twitch.tv",
            port=6697,
            ssl=ctx,
            ssl_handshake_timeout=15,
        )
        self.reader = reader
        self.writer = writer

        # auth
        await self.send_raw(f"PASS {self.oauth}")
        await self.send_raw(f"NICK {self.nick}")

        # capabilities for tags/commands/membership
        await self.send_raw("CAP REQ :twitch.tv/tags twitch.tv/commands twitch.tv/membership")

    async def close(self) -> None:
        if self.writer is not None:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass
        self.reader = None
        self.writer = None

    async def send_raw(self, line: str) -> None:
        if self.writer is None:
            raise RuntimeError("IRC not connected")
        data = (line + "\r\n").encode("utf-8")
        async with self._write_lock:
            self.writer.write(data)
            await self.writer.drain()

    async def join(self, channel: str) -> None:
        await self.send_raw(f"JOIN #{channel.lstrip('#')}")

    async def privmsg(self, channel: str, text: str, reply_parent_msg_id: str | None = None) -> None:
        ch = f"#{channel.lstrip('#')}"
        if reply_parent_msg_id:
            # Twitch supports message reply via tag reply-parent-msg-id
            await self.send_raw(f"@reply-parent-msg-id={reply_parent_msg_id} PRIVMSG {ch} :{text}")
        else:
            await self.send_raw(f"PRIVMSG {ch} :{text}")

    async def lines(self) -> AsyncIterator[IrcMessage]:
        if self.reader is None:
            raise RuntimeError("IRC not connected")

        while True:
            raw = await self.reader.readline()
            if not raw:
                raise ConnectionError("IRC disconnected")
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            msg = parse_irc_line(line)

            # ping/pong
            if msg.command == "PING":
                payload = msg.trailing or (msg.params[0] if msg.params else "")
                await self.send_raw(f"PONG :{payload}")
                continue

            yield msg
