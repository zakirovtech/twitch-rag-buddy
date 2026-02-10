from __future__ import annotations

import asyncio
import logging

import requests

from models import GenerationRequest, Settings, ChatItem


def _format_recent(recent: list[ChatItem] | None, max_n: int = 15) -> str:
    if not recent:
        return ""
    msgs = recent[-max_n:]
    return "\n".join(f"{m.user}: {m.text}" for m in msgs)


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

        # initiate
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
            "Если не хватает контекста — задай один уточняющий вопрос."
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

    def _call_ollama_sync(self, req: GenerationRequest) -> str:
        url = self.settings.ollama_url.rstrip("/")
        payload = {
            "model": self.settings.ollama_model,
            "messages": self._build_messages(req),
            "stream": False,
            "options": {"temperature": self.settings.ollama_temperature},
        }

        resp = requests.post(f"{url}/api/chat", json=payload, timeout=45)
        resp.raise_for_status()
        data = resp.json()
        content = ((data.get("message") or {}).get("content") or data.get("response") or "").strip()
        return content

    async def generate(self, req: GenerationRequest) -> str:
        try:
            text = await asyncio.to_thread(self._call_ollama_sync, req)
        except Exception as e:
            self.log.warning("Ollama failed (%s). Falling back.", e)
            return await RuleBasedGenerator().generate(req)

        text = " ".join(text.split())
        if len(text) > req.max_len:
            text = text[: req.max_len].rsplit(" ", 1)[0] + "…"
        return text


def build_generator(settings: Settings) -> BaseGenerator:
    if settings.ollama_url:
        return OllamaGenerator(settings)
    return RuleBasedGenerator()
