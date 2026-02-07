from __future__ import annotations

import re
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
    qs = []
    for it in items:
        if "?" in it.text:
            q = it.text.strip()
            if len(q) > 2:
                qs.append(q)
    # простая дедупликация
    uniq = []
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
    if not items:
        return None

    texts = [it.text for it in items]
    keywords = extract_keywords(texts, topk=8)
    questions = extract_questions(items, topk=3)

    if keywords:
        topic = ", ".join(keywords[:3])
    else:
        topic = "чат"

    bullets = []
    if keywords:
        bullets.append(f"Топ ключи: {', '.join(keywords[:6])}")
    if questions:
        bullets.append(f"Вопросы: {questions[0][:120]}{'…' if len(questions[0])>120 else ''}")
    bullets.append(f"Сообщений за окно: {len(items)}")

    return Summary(topic=topic, bullets=bullets, questions=questions)
