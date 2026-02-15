FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# кладём исходники как пакет: /app/twitch_gateway/...
COPY . ./twitch_gateway

# на всякий случай делаем его "обычным" пакетом
RUN python -c "import pathlib; p=pathlib.Path('/app/twitch_gateway/__init__.py'); p.exists() or p.write_text('')"

CMD ["python", "-m", "twitch_gateway.main"]
