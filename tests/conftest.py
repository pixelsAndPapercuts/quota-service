import os

import pytest_asyncio

# Point tests at a separate DB file and Redis DB index so they can't
# collide with the running uvicorn app that also has its own connections.
os.environ["DB_PATH"] = "/tmp/quota-test.db"
os.environ["REDIS_URL"] = "redis://redis:6379/1"

from quota.config import settings  # noqa: E402
from quota.db import close_db, init_db  # noqa: E402
from quota.redis_client import close_redis, get_redis, init_redis  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def clean_state():
    """Reset Redis and SQLite before every test so counts are deterministic."""
    if os.path.exists(settings.db_path):
        os.remove(settings.db_path)

    await init_db()
    await init_redis()

    r = get_redis()
    await r.flushdb()

    yield

    await close_redis()
    await close_db()
