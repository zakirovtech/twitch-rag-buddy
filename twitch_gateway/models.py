from dataclasses import dataclass
import os

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
    # If TWITCH_TOKEN_FILE is used, oauth may be omitted.
    twitch_oauth: str | None
    twitch_channels: list[str]

    # Token-file / refresh (optional, recommended)
    twitch_token_file: str | None
    twitch_app_client_id: str | None
    twitch_app_client_secret: str | None
    token_min_ttl_sec: int

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

        token_file = os.getenv("TWITCH_TOKEN_FILE", "").strip() or None
        oauth = os.getenv("TWITCH_OAUTH", "").strip() or None
        if not oauth and not token_file:
            raise ValueError("Provide TWITCH_OAUTH or TWITCH_TOKEN_FILE")

        client_id = os.getenv("TWITCH_APP_CLIENT_ID", "").strip() or None
        client_secret = os.getenv("TWITCH_APP_CLIENT_SECRET", "").strip() or None
        if token_file and (not client_id or not client_secret):
            raise ValueError("TWITCH_TOKEN_FILE requires TWITCH_APP_CLIENT_ID and TWITCH_APP_CLIENT_SECRET")

        return Settings(
            twitch_nick=_env("TWITCH_NICK"),
            twitch_oauth=oauth,
            twitch_channels=channels,
            twitch_token_file=token_file,
            twitch_app_client_id=client_id,
            twitch_app_client_secret=client_secret,
            token_min_ttl_sec=int(os.getenv("TWITCH_TOKEN_MIN_TTL_SEC", "120")),
            redis_url=_env("REDIS_URL", "redis://redis:6379/0"),
            stream_in=_env("REDIS_STREAM_IN", "twitch:in"),
            stream_out=_env("REDIS_STREAM_OUT", "twitch:out"),
            consumer_group=_env("REDIS_CONSUMER_GROUP", "twitch-gateway"),
            consumer_name=_env("REDIS_CONSUMER_NAME", "gateway-1"),
            rate_limit_count=int(_env("RATE_LIMIT_COUNT", "20")),
            rate_limit_window_sec=int(_env("RATE_LIMIT_WINDOW_SEC", "30")),
            log_level=_env("LOG_LEVEL", "INFO"),
        )
