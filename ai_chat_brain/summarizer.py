from __future__ import annotations

import time
from collections import Counter
from typing import Iterable

from config import WORD_RE, STOP
from models import ChatItem, Summary


def extract_keywords(texts: Iterable[str], topk: int = 8) -> list[str]:
    c = Counter()
    for t in texts:
        for w in WORD_RE.findall(t.lower()):
            if w in STOP:
                continue
            c[w] += 1
    return [w for w, _ in c.most_common(topk)]


def extract_questions(items: list[ChatItem], topk: int = 3) -> list[str]:
    qs: list[str] = []
    for it in items:
        if "?" in it.text:
            q = it.text.strip()
            if len(q) > 2:
                qs.append(q)

    uniq: list[str] = []
    seen = set()
    for q in qs:
        k = q.lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(q)
        if len(uniq) >= topk:
            break
    return uniq


def summarize(items: list[ChatItem]) -> Summary | None:
    """Heuristic "analysis" of the recent chat window."""
    if not items:
        return None

    now = int(time.time())
    channel = items[-1].channel

    texts = [it.text for it in items]
    keywords = extract_keywords(texts, topk=8)
    questions = extract_questions(items, topk=3)

    topic = ", ".join(keywords[:3]) if keywords else "чат"
    topic_fp = " ".join(keywords[:5]).strip() if keywords else topic

    msgs_last_10s = sum(1 for it in items if it.ts >= now - 10)
    msgs_last_60s = sum(1 for it in items if it.ts >= now - 60)
    last_message_age_sec = max(0, now - items[-1].ts)

    bullets: list[str] = []
    if keywords:
        bullets.append(f"Ключи: {', '.join(keywords[:6])}")
    if questions:
        q0 = questions[0]
        bullets.append(f"Вопрос: {q0[:120]}{'…' if len(q0) > 120 else ''}")
    bullets.append(f"Сообщений в окне: {len(items)}")

    return Summary(
        channel=channel,
        topic=topic,
        keywords=keywords,
        questions=questions,
        topic_fingerprint=topic_fp,
        msgs_last_10s=msgs_last_10s,
        msgs_last_60s=msgs_last_60s,
        last_message_age_sec=last_message_age_sec,
        bullets=bullets,
    )
