from __future__ import annotations

import time

from models import PolicyState, Summary


def should_initiate(state: PolicyState, summary: Summary | None) -> bool:
    now = int(time.time())
    if summary is None:
        return False

    if now - state.last_speak_ts < state.cooldown_sec:
        return False

    # не повторять одно и то же
    if summary.topic and summary.topic == state.last_topic:
        return False

    # минимальная “уверенность” — есть ключевые слова и активность
    if len(summary.bullets) < 2:
        return False

    return True


def mark_spoke(state: PolicyState, topic: str) -> None:
    state.last_speak_ts = int(time.time())
    state.last_topic = topic
