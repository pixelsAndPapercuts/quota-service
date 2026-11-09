from pathlib import Path

from redis.asyncio import Redis
from redis.commands.core import AsyncScript

from .config import settings


_SCRIPTS_DIR = Path(__file__).parent / "scripts"


class RedisState:
    """
    Holds the async Redis connection and registered Lua scripts.
    Populated by init_redis() at app startup, cleared by close_redis().
    """

    client: Redis | None = None
    consume_script: AsyncScript | None = None
    refund_script: AsyncScript | None = None


state = RedisState()


async def init_redis() -> None:
    client = Redis.from_url(
        settings.redis_url,
        decode_responses=False,
        socket_timeout=settings.redis_timeout_ms / 1000,
        socket_connect_timeout=settings.redis_connect_timeout_ms / 1000,
        max_connections=settings.redis_max_connections,
    )
    await client.ping()

    consume_src = (_SCRIPTS_DIR / "consume.lua").read_text()
    refund_src = (_SCRIPTS_DIR / "refund.lua").read_text()

    state.client = client
    state.consume_script = client.register_script(consume_src)
    state.refund_script = client.register_script(refund_src)


async def close_redis() -> None:
    if state.client is not None:
        await state.client.aclose()
        state.client = None
        state.consume_script = None
        state.refund_script = None


def get_redis() -> Redis:
    assert state.client is not None, "Redis not initialized"
    return state.client


def get_consume_script() -> AsyncScript:
    assert state.consume_script is not None, "consume script not registered"
    return state.consume_script


def get_refund_script() -> AsyncScript:
    assert state.refund_script is not None, "refund script not registered"
    return state.refund_script
