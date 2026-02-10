import os
from dataclasses import dataclass
from config import _env


# ===== runtime state =====


@dataclass
class PolicyState:
    """Per-channel speaking policy state (anti-spam + topic tracking)."""

    last_speak_ts: int = 0
    last_topic_fp: str = ""
    last_topic_ts: int = 0

    # separate cooldowns for "direct" replies
    last_mention_reply_ts: int = 0
    last_ai_reply_ts: int = 0


# ===== data passed around inside brain =====


@dataclass
class Summary:
    channel: str

    topic: str
    keywords: list[str]
    questions: list[str]

    # for topic shift detection (stable-ish string)
    topic_fingerprint: str

    # activity signals
    msgs_last_10s: int
    msgs_last_60s: int
    last_message_age_sec: int

    bullets: list[str]


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


@dataclass
class GenerationRequest:
    purpose: str  # "initiate" | "mention" | "answer_ai"
    channel: str
    bot_nick: str

    # user inputs
    user: str | None = None
    user_text: str | None = None

    # chat context
    summary: Summary | None = None
    recent: list[ChatItem] | None = None

    # reserved for future RAG
    retrieval_context: list[dict] | None = None

    # hard constraints
    max_len: int = 350


# ===== settings =====


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

    # context
    window_sec: int
    max_items: int
    max_context_msgs: int

    # speaking / anti-spam
    batch_sec: int
    quiet_after_sec: int
    busy_chat_msgs_10s: int

    speak_every_sec: int
    topic_cooldown_sec: int
    mention_cooldown_sec: int
    ai_cooldown_sec: int

    max_out_len: int
    auto_speak_enabled: bool

    # ollama (optional)
    ollama_url: str
    ollama_model: str
    ollama_temperature: float

    log_level: str

    @staticmethod
    def load() -> "Settings":
        allow_raw = os.getenv("CHANNEL_ALLOWLIST", "").strip()
        allow = [c.strip().lstrip("#").lower() for c in allow_raw.split(",") if c.strip()]

        def _bool(name: str, default: str = "true") -> bool:
            return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "y", "on"}

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

            window_sec=int(os.getenv("WINDOW_SEC", "120")),
            max_items=int(os.getenv("MAX_ITEMS", "200")),
            max_context_msgs=int(os.getenv("MAX_CONTEXT_MSGS", "15")),

            batch_sec=int(_env("BATCH_SEC", "15")),
            quiet_after_sec=int(os.getenv("QUIET_AFTER_SEC", "30")),
            busy_chat_msgs_10s=int(os.getenv("BUSY_CHAT_MSGS_10S", "8")),

            speak_every_sec=int(_env("SPEAK_EVERY_SEC", "180")),
            topic_cooldown_sec=int(os.getenv("TOPIC_COOLDOWN_SEC", "600")),
            mention_cooldown_sec=int(os.getenv("MENTION_COOLDOWN_SEC", "30")),
            ai_cooldown_sec=int(os.getenv("AI_COOLDOWN_SEC", "8")),

            max_out_len=int(_env("MAX_OUT_LEN", "350")),
            auto_speak_enabled=_bool("AUTO_SPEAK_ENABLED", "true"),

            ollama_url=os.getenv("OLLAMA_URL", "").strip(),
            ollama_model=os.getenv("OLLAMA_MODEL", "llama3.1:8b").strip(),
            ollama_temperature=float(os.getenv("OLLAMA_TEMPERATURE", "0.7")),

            log_level=_env("LOG_LEVEL", "INFO"),
        )
