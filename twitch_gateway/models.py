from dataclasses import dataclass
from config import _env


@dataclass
class IrcMessage:
    raw: str
    tags: dict[str, str]
    prefix: str | None
    command: str
    params: list[str]
    trailing: str | None


@dataclass(frozen=True)
class Settings:
    twitch_nick: str
    twitch_oauth: str
    twitch_channels: list[str]

    redis_url: str
    stream_in: str
    stream_out: str
    consumer_group: str
    consumer_name: str

    rate_limit_count: int
    rate_limit_window_sec: int

    log_level: str

    @staticmethod
    def load() -> "Settings":
        channels_raw = _env("TWITCH_CHANNELS")
        channels = [c.strip().lstrip("#") for c in channels_raw.split(",") if c.strip()]
        
        if not channels:
            raise ValueError("TWITCH_CHANNELS is empty")

        return Settings(
            twitch_nick=_env("TWITCH_NICK"),
            twitch_oauth=_env("TWITCH_OAUTH"),
            twitch_channels=channels,
            redis_url=_env("REDIS_URL", "redis://redis:6379/0"),
            stream_in=_env("REDIS_STREAM_IN", "twitch:in"),
            stream_out=_env("REDIS_STREAM_OUT", "twitch:out"),
            consumer_group=_env("REDIS_CONSUMER_GROUP", "twitch-gateway"),
            consumer_name=_env("REDIS_CONSUMER_NAME", "gateway-1"),
            rate_limit_count=int(_env("RATE_LIMIT_COUNT", "20")),
            rate_limit_window_sec=int(_env("RATE_LIMIT_WINDOW_SEC", "30")),
            log_level=_env("LOG_LEVEL", "INFO"),
        )
