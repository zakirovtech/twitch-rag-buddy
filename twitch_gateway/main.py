from __future__ import annotations

import asyncio
import logging
import random
import time

from .config import Settings
from .irc import TwitchIrcClient, IrcMessage
from .redis_bus import RedisBus
from .rate_limit import TokenBucket


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def normalize_channel(ch: str) -> str:
    return ch.strip().lstrip("#").lower()


def extract_user(prefix: str | None) -> str | None:
    # prefix format: nick!nick@nick.tmi.twitch.tv
    if not prefix:
        return None
    if "!" in prefix:
        return prefix.split("!", 1)[0]
    return prefix


async def handle_incoming(bus: RedisBus, msg: IrcMessage) -> None:
    log = logging.getLogger("incoming")

    if msg.command != "PRIVMSG":
        return

    # params[0] = #channel
    if not msg.params:
        return
    channel = normalize_channel(msg.params[0])
    text = msg.trailing or ""
    user = extract_user(msg.prefix) or ""
    tags = msg.tags or {}

    fields = {
        "ts": str(int(time.time())),
        "type": "chat_message",
        "channel": channel,
        "user": user,
        "text": text,
        "msg_id": tags.get("id", ""),
        "user_id": tags.get("user-id", ""),
        "display_name": tags.get("display-name", ""),
        "badges": tags.get("badges", ""),
        "mod": tags.get("mod", ""),
        "subscriber": tags.get("subscriber", ""),
        "vip": tags.get("vip", ""),
        "raw": msg.raw,
    }

    await bus.publish_in(fields)
    log.debug("IN #%s %s: %s", channel, user, text)


async def outgoing_sender(
    irc: TwitchIrcClient,
    bus: RedisBus,
    settings: Settings,
) -> None:
    log = logging.getLogger("outgoing")
    bucket = TokenBucket(settings.rate_limit_count, settings.rate_limit_window_sec)

    # Периодически пытаемся забирать pending (если сервис перезапустился)
    last_claim = 0.0

    while True:
        try:
            now = time.monotonic()
            if now - last_claim > 15:
                stale = await bus.claim_stale_pending(settings.consumer_name, min_idle_ms=60000, count=10)
                if stale:
                    log.warning("Claimed %d stale pending messages", len(stale))
                    for msg_id, data in stale:
                        await process_out_one(irc, bucket, bus, msg_id, data)
                last_claim = now

            items = await bus.read_out(settings.consumer_name, count=10, block_ms=5000, stream_id=">")
            if not items:
                continue

            for msg_id, data in items:
                await process_out_one(irc, bucket, bus, msg_id, data)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("Outgoing loop error: %s", e)
            await asyncio.sleep(1.0)


async def process_out_one(
    irc: TwitchIrcClient,
    bucket: TokenBucket,
    bus: RedisBus,
    msg_id: str,
    data: dict[str, str],
) -> None:
    log = logging.getLogger("outgoing")

    channel = normalize_channel(data.get("channel", ""))
    text = data.get("text", "")
    if not channel or not text:
        log.warning("Bad outgoing message (missing channel/text): id=%s data=%s", msg_id, data)
        await bus.ack_out([msg_id])
        return

    reply_to = data.get("reply_to") or data.get("reply_parent_msg_id") or None

    await bucket.acquire(1.0)
    await irc.privmsg(channel, text, reply_parent_msg_id=reply_to)
    await bus.ack_out([msg_id])
    log.info("Sent to #%s: %s", channel, text)


async def irc_loop(settings: Settings) -> None:
    log = logging.getLogger("main")

    bus = RedisBus(
        redis_url=settings.redis_url,
        stream_in=settings.stream_in,
        stream_out=settings.stream_out,
        group=settings.consumer_group,
    )
    await bus.connect()

    backoff = 1.0
    while True:
        irc = TwitchIrcClient(settings.twitch_nick, settings.twitch_oauth)
        try:
            await irc.connect()

            for ch in settings.twitch_channels:
                await irc.join(ch)
                log.info("Joined #%s", ch)

            backoff = 1.0  # reset after successful connect

            sender_task = asyncio.create_task(outgoing_sender(irc, bus, settings))

            async for msg in irc.lines():
                await handle_incoming(bus, msg)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("IRC connection error: %s", e)
        finally:
            try:
                await irc.close()
            except Exception:
                pass

        # reconnect with jitter
        sleep_for = backoff + random.random()
        log.info("Reconnecting in %.1fs", sleep_for)
        await asyncio.sleep(sleep_for)
        backoff = min(backoff * 2, 60.0)


def main() -> None:
    settings = Settings.load()
    setup_logging(settings.log_level)
    asyncio.run(irc_loop(settings))



if __name__ == "__main__":
    main()
