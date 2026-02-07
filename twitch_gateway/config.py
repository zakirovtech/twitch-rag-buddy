from dataclasses import dataclass
import os


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)

    if value is None or value == "":
        raise ValueError(f"Missing required doenv var: {name}")
    
    return value

