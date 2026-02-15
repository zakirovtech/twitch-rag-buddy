from __future__ import annotations

import asyncio
import logging
import re
from copy import deepcopy

import requests

from models import GenerationRequest, Settings, ChatItem


def _format_recent(recent: list[ChatItem] | None, max_n: int = 15) -> str:
    if not recent:
        return ""
    msgs = recent[-max_n:]
    return "\n".join(f"{m.user}: {m.text}" for m in msgs)


# Лёгкая эвристика: ловим “дрейф” в CJK (китайский/японский/корейский).
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_CYR_RE = re.compile(r"[А-Яа-яЁё]")
_LAT_RE = re.compile(r"[A-Za-z]")


def _looks_russian(text: str) -> bool:
    if not text:
        return True
    if _CJK_RE.search(text):
        return False
    cyr = len(_CYR_RE.findall(text))
    lat = len(_LAT_RE.findall(text))
    if cyr == 0 and lat == 0:  # эмодзи/знаки
        return True
    return cyr >= max(1, lat * 2)


class BaseGenerator:
    async def generate(self, req: GenerationRequest) -> str:
        raise NotImplementedError


class RuleBasedGenerator(BaseGenerator):
    """Non-LLM fallback. Keeps things short."""

    async def generate(self, req: GenerationRequest) -> str:
        s = req.summary
        topic = s.topic if s else "чат"

        if req.purpose == "answer_ai" and req.user_text:
            return (
                f"Понял вопрос про {topic}. Я пока без RAG, но уточню: "
                f"тебе нужен быстрый вывод или разбор по шагам?"
            )

        if req.purpose == "mention":
            if req.user:
                return f"@{req.user} я тут 👀 Про {topic} — что именно обсудить?"
            return f"Я тут 👀 Про {topic} — что именно обсудить?"

        if s and s.questions:
            q = s.questions[0]
            return f"Кстати, по теме ({topic}): {q[:120]}{'…' if len(q) > 120 else ''}"

        return f"Слушаю чат про {topic}. Если хотите — задайте вопрос через !ai …"


class OllamaGenerator(BaseGenerator):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.log = logging.getLogger("ollama")

    def _build_messages(self, req: GenerationRequest) -> list[dict]:
        s = req.summary
        recent_txt = _format_recent(req.recent, max_n=self.settings.max_context_msgs)

        system = (
            "Ты участник чата Twitch-стрима. "
            "Пиши ОДНО короткое сообщение (1–2 предложения), без простыней, без ссылок, без токсичности. "
            "Не спамь эмодзи. Не повторяйся. "
            "Если не хватает контекста — задай один уточняющий вопрос. "
            "НЕ ПИШИ рассуждения/chain-of-thought. Выведи только финальный ответ."
        )
        if self.settings.ollama_force_ru:
            system += (
                " ВАЖНО: отвечай ТОЛЬКО на русском языке. "
                "Запрещено использовать китайский и английский. "
                "Если начал не на русском — перепиши ответ на русском."
            )

        if req.purpose == "initiate":
            user = (
                f"Текущая тема чата: {s.topic if s else 'чат'}\n"
                f"Ключевые слова: {', '.join(s.keywords[:8]) if s and s.keywords else ''}\n"
                f"Вопросы в чате: {(' | '.join(s.questions[:3])) if s and s.questions else ''}\n\n"
                f"Последние сообщения:\n{recent_txt}\n\n"
                "Сформулируй уместную реплику, чтобы поддержать разговор по теме."
            )
        elif req.purpose == "mention":
            user = (
                f"Тебя упомянули в чате. Пользователь: {req.user or ''}\n"
                f"Сообщение пользователя: {req.user_text or ''}\n\n"
                f"Контекст/тема: {s.topic if s else 'чат'}\n"
                f"Последние сообщения:\n{recent_txt}\n\n"
                "Ответь коротко и по делу (1 сообщение)."
            )
        else:  # answer_ai
            user = (
                f"Пользователь задаёт вопрос через !ai. Пользователь: {req.user or ''}\n"
                f"Вопрос: {req.user_text or ''}\n\n"
                f"Тема чата: {s.topic if s else 'чат'}\n"
                f"Последние сообщения:\n{recent_txt}\n\n"
                "Дай короткий полезный ответ (1–2 предложения)."
            )

        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def _post_chat(self, payload: dict) -> dict:
        url = self.settings.ollama_url.rstrip("/")
        resp = requests.post(
            f"{url}/api/chat",
            json=payload,
            timeout=self.settings.ollama_timeout_sec,
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _extract(data: dict) -> tuple[str, str, str]:
        msg = data.get("message") or {}
        content = (msg.get("content") or data.get("response") or "").strip()
        thinking = (msg.get("thinking") or "").strip()
        done_reason = (data.get("done_reason") or "").strip()
        return content, thinking, done_reason

    def _call_ollama_sync(self, req: GenerationRequest) -> str:
        # Если в Settings нет ollama_think — дефолт False (чтобы не сжирало num_predict на thinking)
        think_flag = bool(getattr(self.settings, "ollama_think", False))

        base_payload = {
            "model": self.settings.ollama_model,
            "messages": self._build_messages(req),
            "stream": False,
            "think": think_flag,  # <-- ключевой фикс для thinking-моделей
            "options": {
                "temperature": self.settings.ollama_temperature,
                "num_ctx": self.settings.ollama_num_ctx,
                "num_predict": self.settings.ollama_num_predict,
                "top_p": self.settings.ollama_top_p,
                "repeat_penalty": self.settings.ollama_repeat_penalty,
            },
        }

        data = self._post_chat(base_payload)
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(f"Ollama error: {data['error']}")

        content, thinking, done_reason = self._extract(data)

        # Если thinking включён (по умолчанию у таких моделей) и num_predict мал — content может не появиться.
        # Делаем 1 retry: think=false + num_predict побольше.
        if not content or done_reason == "length":
            retry = deepcopy(base_payload)
            retry["think"] = False  # принудительно выключаем thinking на ретрае
            retry["options"]["temperature"] = min(0.2, float(retry["options"]["temperature"]))
            retry["options"]["num_predict"] = max(int(self.settings.ollama_num_predict), 192)
            retry["messages"][0]["content"] += (
                " СЕЙЧАС ВЕРНИ ТОЛЬКО ФИНАЛЬНЫЙ ОТВЕТ (БЕЗ РАССУЖДЕНИЙ)."
            )

            data2 = self._post_chat(retry)
            if isinstance(data2, dict) and data2.get("error"):
                raise RuntimeError(f"Ollama error: {data2['error']}")

            content2, thinking2, done_reason2 = self._extract(data2)
            if content2:
                content = content2
                thinking = thinking2
                done_reason = done_reason2
            else:
                self.log.warning(
                    "Ollama empty content (raw). done_reason=%s/%s thinking=%r/%r raw1=%r raw2=%r",
                    done_reason,
                    done_reason2,
                    (thinking[:200] if thinking else ""),
                    (thinking2[:200] if thinking2 else ""),
                    data,
                    data2,
                )
                raise RuntimeError("Empty content from Ollama (thinking-only or truncated)")

        # RU retry (твоя логика)
        if (
            self.settings.ollama_force_ru
            and self.settings.ollama_retry_non_ru
            and content
            and not _looks_russian(content)
        ):
            retry = deepcopy(base_payload)
            retry["think"] = False
            retry["options"]["temperature"] = min(0.2, float(retry["options"]["temperature"]))
            retry["options"]["num_predict"] = max(int(self.settings.ollama_num_predict), 192)
            retry["messages"][0]["content"] += (
                " СЕЙЧАС ВЕРНИ РОВНО ОДНО СООБЩЕНИЕ НА РУССКОМ. НИКАКИХ ДРУГИХ ЯЗЫКОВ."
            )
            data3 = self._post_chat(retry)
            if isinstance(data3, dict) and data3.get("error"):
                raise RuntimeError(f"Ollama error: {data3['error']}")
            content3, _, _ = self._extract(data3)
            if content3:
                return content3

        return content

    async def generate(self, req: GenerationRequest) -> str:
        try:
            text = await asyncio.to_thread(self._call_ollama_sync, req)
        except Exception as e:
            self.log.warning("Ollama failed (%s). Falling back.", e)
            return await RuleBasedGenerator().generate(req)

        text = " ".join(text.split())
        if not text:
            return await RuleBasedGenerator().generate(req)

        if len(text) > req.max_len:
            text = text[: req.max_len].rsplit(" ", 1)[0] + "…"
        return text


def build_generator(settings: Settings) -> BaseGenerator:
    if settings.ollama_url:
        return OllamaGenerator(settings)
    return RuleBasedGenerator()
