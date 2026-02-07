import asyncio
import time


class TokenBucket:
    """
    Простой token bucket:
    - capacity = N сообщений
    - refill каждые window_sec до capacity
    """
    def __init__(self, capacity: int, window_sec: int) -> None:
        self.capacity = max(1, capacity)
        self.window_sec = max(1, window_sec)
        self.tokens = float(self.capacity)
        self.updated_at = time.monotonic()
        self._lock = asyncio.Lock()


    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.updated_at
        self.updated_at = now

        refill_rate = self.capacity / self.window_sec  # tokens per sec
        self.tokens = min(self.capacity, self.tokens + elapsed * refill_rate)


    async def acquire(self, amount: float = 1.0) -> None:
        while True:
            async with self._lock:
                self._refill()
                if self.tokens >= amount:
                    self.tokens -= amount
                    return

                # Сколько ждать до 1 токена
                need = amount - self.tokens
                refill_rate = self.capacity / self.window_sec
                wait = max(0.01, need / refill_rate)

            await asyncio.sleep(wait)
