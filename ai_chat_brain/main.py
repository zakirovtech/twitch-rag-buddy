from __future__ import annotations

import asyncio
import logging
import time


from filters import TextFilters
from redis_io import RedisIO
from models import ChatItem, Settings
from session_buffer import SessionBuffer
from summarizer import summarize
from policy import PolicyState, should_initiate, mark_spoke


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def allowed_channel(settings: Settings, channel: str) -> bool:
    if not settings.channel_allowlist:
        return True
    return channel.lower() in settings.channel_allowlist


def build_initiation_message(topic: str) -> str:
    # MVP: без LLM, просто аккуратная реплика
    return f"Вижу обсуждаете: {topic}. Хотите, подкину мысль/факт или соберу ответы на вопросы? (пишите !ai ...)"


def build_ai_answer(question: str) -> str:
    # MVP: заглушка. Потом заменим на LLM+RAG.
    return f"Я пока в MVP-режиме без LLM 🙂 Вопрос понял: «{question}». Скоро подключу мозги (RAG/LLM) и отвечу по делу."


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

    buffer = SessionBuffer(window_sec=max(30, settings.batch_sec))
    policy = PolicyState(cooldown_sec=settings.speak_every_sec)

    last_batch_ts = int(time.time())

    while True:
        items = await rio.read_in(settings.consumer_name_in, count=50, block_ms=5000)
        if not items:
            # даже без сообщений можем раз в batch_sec попробовать “инициировать” от накопленного
            await maybe_batch_and_speak(settings, rio, buffer, policy, last_batch_ts)
            continue

        ack_ids = []

        for msg_id, data in items:
            ack_ids.append(msg_id)

            if data.get("type") != "chat_message":
                continue

            channel = (data.get("channel") or "").lower()
            if not channel or not allowed_channel(settings, channel):
                continue

            user = data.get("user") or ""
            text = data.get("text") or ""
            msg_tag_id = data.get("msg_id") or ""

            # trigger logic
            q = filters.parse_ai_command(text)
            if q:
                # ответить обязательно
                out = build_ai_answer(q)
                out = out[: settings.max_out_len]
                await rio.send_out(channel=channel, text=out, reply_to=msg_tag_id or None)
                log.info("Answered !ai in #%s to %s", channel, user)
                continue

            # index filters
            fr = filters.should_index(user=user, text=text)
            if not fr.ok:
                continue

            norm = filters.normalize(text)
            buffer.add(ChatItem(ts=int(time.time()), channel=channel, user=user, text=norm))

        await rio.ack_in(ack_ids)

        last_batch_ts = await maybe_batch_and_speak(settings, rio, buffer, policy, last_batch_ts)


async def maybe_batch_and_speak(
    settings: Settings,
    rio: RedisIO,
    buffer: SessionBuffer,
    policy: PolicyState,
    last_batch_ts: int,
) -> int:
    now = int(time.time())
    if now - last_batch_ts < settings.batch_sec:
        return last_batch_ts

    snap = buffer.snapshot()
    summary = summarize(snap)

    if summary and should_initiate(policy, summary):
        text = build_initiation_message(summary.topic)
        text = text[: settings.max_out_len]
        await rio.send_out(channel=snap[-1].channel if snap else settings.channel_allowlist[0], text=text)
        mark_spoke(policy, summary.topic)

    return now


def main() -> None:
    asyncio.run(brain_loop())


if __name__ == "__main__":
    main()
