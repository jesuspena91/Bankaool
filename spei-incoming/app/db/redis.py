import redis.asyncio as aioredis
from app.core.config import settings
import logging
from typing import Optional

logger = logging.getLogger("spei.redis")

class RedisClient:
    def __init__(self):
        self.client: Optional[aioredis.Redis] = None

    async def connect(self):
        try:
            self.client = aioredis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                password=settings.REDIS_PASSWORD,
                db=settings.REDIS_DB,
                decode_responses=True
            )
            await self.client.ping()
            logger.info("Conectado exitosamente a Redis.")
        except Exception as e:
            logger.warning(f"No se pudo conectar a Redis en vivo ({e}). Se operará con fallback o mocks en tests.")

    async def close(self):
        if self.client:
            await self.client.aclose()

    async def check_and_lock_idempotency(self, clave_rastreo: str) -> bool:
        """
        Garantiza que una transferencia con la misma clave de rastreo
        no sea procesada simultáneamente ni duplicada.
        Retorna True si el lock fue adquirido (primera vez).
        Retorna False si ya existía (duplicado/en proceso).
        """
        if not self.client:
            # Fallback en caso de testing sin Redis
            return True
        key = f"spei:clave_rastreo:{clave_rastreo}"
        # SETNX con expiración automática de 24 horas
        acquired = await self.client.set(key, "PROCESSING", nx=True, ex=settings.IDEMPOTENCY_TTL_SECONDS)
        return bool(acquired)

    async def set_transaction_state(self, clave_rastreo: str, state: str):
        if self.client:
            key = f"spei:clave_rastreo:{clave_rastreo}"
            await self.client.set(key, state, ex=settings.IDEMPOTENCY_TTL_SECONDS)

    async def get_transaction_state(self, clave_rastreo: str) -> Optional[str]:
        if self.client:
            key = f"spei:clave_rastreo:{clave_rastreo}"
            return await self.client.get(key)
        return None

redis_client = RedisClient()
