from __future__ import annotations

import asyncio
import logging
import time

from filters import TextFilters
from redis_io import RedisIO
from models import ChatItem, Settings, PolicyState, GenerationRequest
from session_buffer import ChatState
from summarizer import summarize
from policy import (
    decide_autospeak,
    mark_spoke,
    should_reply_ai,
    should_reply_mention,
    mark_ai_replied,
    mark_mention_replied,
)
from generator import build_generator


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def allowed_channel(settings: Settings, channel: str) -> bool:
    if not settings.channel_allowlist:
        return True
    return channel.lower() in settings.channel_allowlist


def has_bot_mention(text: str, bot_nick: str) -> bool:
    t = (text or "").lower()
    return f"@{bot_nick.lower()}" in t


async def brain_loop() -> None:
    settings = Settings.load()
    setup_logging(settings.log_level)
    log = logging.getLogger("brain")

    banwords = [w.strip() for w in settings.banwords_csv.split(",") if w.strip()]
    filters = TextFilters(banwords=banwords, bot_nick=settings.bot_nick, min_len=settings.min_len)

    rio = RedisIO(
        redis_url=settings.redis_url,
        stream_in=settings.stream_in,
        stream_out=settings.stream_out,
        group_in=settings.consumer_group_in,
    )
    await rio.connect()

    chat = ChatState(window_sec=settings.window_sec, max_items=settings.max_items)
    policy_by_channel: dict[str, PolicyState] = {}

    generator = build_generator(settings)

    last_batch_ts = int(time.time())

    while True:
        items = await rio.read_in(settings.consumer_name_in, count=50, block_ms=5000)
        if not items:
            last_batch_ts = await maybe_autospeak_all(settings, rio, chat, policy_by_channel, generator, last_batch_ts)
            continue

        ack_ids: list[str] = []

        for msg_id, data in items:
            ack_ids.append(msg_id)

            if data.get("type") != "chat_message":
                continue

            channel = (data.get("channel") or "").lower()
            if not channel or not allowed_channel(settings, channel):
                continue

            user = data.get("user") or ""
            text_raw = data.get("text") or ""
            msg_tag_id = data.get("msg_id") or ""

            st = policy_by_channel.setdefault(channel, PolicyState())

            # 1) explicit !ai command (direct reply)
            q = filters.parse_ai_command(text_raw)
            if q and should_reply_ai(st, settings):
                recent = chat.buffer(channel).snapshot(last_n=settings.max_context_msgs)
                summary = summarize(chat.buffer(channel).snapshot())

                req = GenerationRequest(
                    purpose="answer_ai",
                    channel=channel,
                    bot_nick=settings.bot_nick,
                    user=user,
                    user_text=q,
                    summary=summary,
                    recent=recent,
                    max_len=settings.max_out_len,
                )
                out = await generator.generate(req)
                await rio.send_out(channel=channel, text=out, reply_to=msg_tag_id or None)
                mark_ai_replied(st)
                log.info("Answered !ai in #%s to %s", channel, user)
                continue

            # 2) mention bot (direct reply, lightweight)
            if has_bot_mention(text_raw, settings.bot_nick) and should_reply_mention(st, settings):
                fr = filters.should_index(user=user, text=text_raw)
                if fr.ok:
                    chat.add(ChatItem(ts=int(time.time()), channel=channel, user=user, text=filters.normalize(text_raw)))

                recent = chat.buffer(channel).snapshot(last_n=settings.max_context_msgs)
                summary = summarize(chat.buffer(channel).snapshot())

                req = GenerationRequest(
                    purpose="mention",
                    channel=channel,
                    bot_nick=settings.bot_nick,
                    user=user,
                    user_text=text_raw,
                    summary=summary,
                    recent=recent,
                    max_len=settings.max_out_len,
                )
                out = await generator.generate(req)
                await rio.send_out(channel=channel, text=out, reply_to=msg_tag_id or None)
                mark_mention_replied(st)
                log.info("Replied to mention in #%s (%s)", channel, user)
                continue

            # 3) normal indexing for topic analysis
            fr = filters.should_index(user=user, text=text_raw)
            if not fr.ok:
                continue

            chat.add(ChatItem(ts=int(time.time()), channel=channel, user=user, text=filters.normalize(text_raw)))

        await rio.ack_in(ack_ids)
        last_batch_ts = await maybe_autospeak_all(settings, rio, chat, policy_by_channel, generator, last_batch_ts)


async def maybe_autospeak_all(
    settings: Settings,
    rio: RedisIO,
    chat: ChatState,
    policy_by_channel: dict[str, PolicyState],
    generator,
    last_batch_ts: int,
) -> int:
    now = int(time.time())
    if now - last_batch_ts < settings.batch_sec:
        return last_batch_ts

    for channel in chat.channels():
        if not allowed_channel(settings, channel):
            continue

        buf = chat.buffer(channel)
        snap = buf.snapshot()
        if not snap:
            continue

        st = policy_by_channel.setdefault(channel, PolicyState())
        summary = summarize(snap)
        reason = decide_autospeak(st, settings, summary)
        if not reason:
            continue

        recent = buf.snapshot(last_n=settings.max_context_msgs)
        req = GenerationRequest(
            purpose="initiate",
            channel=channel,
            bot_nick=settings.bot_nick,
            summary=summary,
            recent=recent,
            max_len=settings.max_out_len,
        )
        out = await generator.generate(req)
        await rio.send_out(channel=channel, text=out)
        mark_spoke(st, summary, reason)

    return now


def main() -> None:
    asyncio.run(brain_loop())


if __name__ == "__main__":
    main()
