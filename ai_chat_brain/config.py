import os
import re

URL_RE = re.compile(r"(https?://|www\.)\S+", re.IGNORECASE)
REPEAT_RE = re.compile(r"(.)\1{6,}")  # aaaaaaa
ONLY_EMOJIISH_RE = re.compile(r"^[\W_]+$", re.UNICODE)
WORD_RE = re.compile(r"[A-Za-zА-Яа-я0-9_]{3,}")

STOP = {
    "the","and","that","this","with","have","you","your","but","not","are","for","was","что","это","как","так",
    "там","тут","его","ее","они","она","оно","да","нет","или","уже","ещё","ещe","кто","где","когда","почему",
}


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)

    if value is None or value == "":
        raise ValueError(f"Missing required doenv var: {name}")
    
    return value
