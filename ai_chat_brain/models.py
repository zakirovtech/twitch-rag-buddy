import os
from dataclasses import dataclass
from config import _env


@dataclass
class PolicyState:
    last_speak_ts: int = 0
    last_topic: str = ""
    cooldown_sec: int = 180


@dataclass
class Summary:
    topic: str
    bullets: list[str]
    questions: list[str]


@dataclass
class ChatItem:
    ts: int
    channel: str
    user: str
    text: str


@dataclass
class FilterResult:
    ok: bool
    reason: str = ""


@dataclass(frozen=True)
class Settings:
    redis_url: str
    stream_in: str
    stream_out: str

    consumer_group_in: str
    consumer_name_in: str

    bot_nick: str
    channel_allowlist: list[str]  # empty => allow all

    # filters
    banwords_csv: str
    min_len: int

    # batching / speaking
    batch_sec: int
    speak_every_sec: int
    max_out_len: int

    log_level: str

    @staticmethod
    def load() -> "Settings":
        allow_raw = os.getenv("CHANNEL_ALLOWLIST", "").strip()
        allow = [c.strip().lstrip("#").lower() for c in allow_raw.split(",") if c.strip()]

        return Settings(
            redis_url=_env("REDIS_URL", "redis://redis:6379/0"),
            stream_in=_env("REDIS_STREAM_IN", "twitch:in"),
            stream_out=_env("REDIS_STREAM_OUT", "twitch:out"),
            consumer_group_in=_env("REDIS_CONSUMER_GROUP_IN", "ai-brain"),
            consumer_name_in=_env("REDIS_CONSUMER_NAME_IN", "brain-1"),
            bot_nick=_env("BOT_NICK", "mybot").lower(),
            channel_allowlist=allow,
            banwords_csv=os.getenv("BANWORDS", "").strip(),
            min_len=int(_env("MIN_TEXT_LEN", "3")),
            batch_sec=int(_env("BATCH_SEC", "45")),
            speak_every_sec=int(_env("SPEAK_EVERY_SEC", "180")),
            max_out_len=int(_env("MAX_OUT_LEN", "350")),
            log_level=_env("LOG_LEVEL", "INFO"),
        )
