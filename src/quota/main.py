import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from .db import close_db, init_db
from .demo_routes import demo_router
from .redis_client import close_redis, init_redis
from .routes import admin_router, quota_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await init_redis()
    yield
    await close_redis()
    await close_db()


app = FastAPI(title="Portcast Quota Metering", lifespan=lifespan)


@app.middleware("http")
async def server_timing_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Processing-Time-Ms"] = f"{duration_ms:.3f}"
    return response


app.include_router(admin_router)
app.include_router(quota_router)
app.include_router(demo_router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
