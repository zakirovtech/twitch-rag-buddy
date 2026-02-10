from __future__ import annotations

import time

from models import PolicyState, Settings, Summary


class SpeakReason:
    MENTION = "mention"
    AI_COMMAND = "ai_command"
    SILENCE = "silence"
    TOPIC_SHIFT = "topic_shift"


def should_reply_mention(state: PolicyState, settings: Settings) -> bool:
    now = int(time.time())
    return (now - state.last_mention_reply_ts) >= settings.mention_cooldown_sec


def should_reply_ai(state: PolicyState, settings: Settings) -> bool:
    now = int(time.time())
    return (now - state.last_ai_reply_ts) >= settings.ai_cooldown_sec


def decide_autospeak(state: PolicyState, settings: Settings, summary: Summary | None) -> str | None:
    """Return SpeakReason for an auto message, or None if we should keep silent."""
    if not settings.auto_speak_enabled:
        return None
    if summary is None:
        return None

    now = int(time.time())

    # global cooldown
    if now - state.last_speak_ts < settings.speak_every_sec:
        return None

    # avoid speaking when chat is too fast
    if summary.msgs_last_10s > settings.busy_chat_msgs_10s:
        return None

    # 1) silence-based initiation
    if summary.last_message_age_sec >= settings.quiet_after_sec:
        return SpeakReason.SILENCE

    # 2) topic shift initiation (but not too often)
    if summary.topic_fingerprint and summary.topic_fingerprint != state.last_topic_fp:
        if now - state.last_topic_ts >= settings.topic_cooldown_sec:
            return SpeakReason.TOPIC_SHIFT

    return None


def mark_spoke(state: PolicyState, summary: Summary, reason: str) -> None:
    now = int(time.time())
    state.last_speak_ts = now

    if reason in {SpeakReason.SILENCE, SpeakReason.TOPIC_SHIFT}:
        state.last_topic_fp = summary.topic_fingerprint
        state.last_topic_ts = now


def mark_mention_replied(state: PolicyState) -> None:
    state.last_mention_reply_ts = int(time.time())


def mark_ai_replied(state: PolicyState) -> None:
    state.last_ai_reply_ts = int(time.time())
