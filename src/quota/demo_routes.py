from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .service import quota_service


demo_router = APIRouter(prefix="/demo", tags=["demo"])


class TrackContainersRequest(BaseModel):
    org_id: str
    container_ids: list[str]
    # Demo-only knobs. In production this endpoint would live inside a
    # product service (e.g. tracking-service) that generates idempotency
    # keys from its own business IDs — never exposing them to customers.
    demo_retry_key: str | None = None
    simulate_failure: bool = False


class SearchScheduleRequest(BaseModel):
    org_id: str
    query: str


@demo_router.post("/track-containers")
async def track_containers(req: TrackContainersRequest):
    key = req.demo_retry_key or str(uuid4())
    result = await quota_service.consume(
        org_id=req.org_id,
        feature="container-tracking",
        n=len(req.container_ids),
        idempotency_key=key,
    )

    if req.simulate_failure and result.allowed:
        refund = await quota_service.refund(key)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "simulated downstream failure",
                "consumed": len(req.container_ids),
                "refunded": refund.refunded,
                "remaining": refund.remaining,
            },
        )

    return {
        "tracked": len(req.container_ids) if result.allowed else 0,
        "allowed": result.allowed,
        "remaining": result.remaining,
    }


@demo_router.post("/search-schedule")
async def search_schedule(req: SearchScheduleRequest):
    result = await quota_service.consume(
        org_id=req.org_id,
        feature="sailing-schedule",
        n=1,
        idempotency_key=str(uuid4()),
    )
    return {
        "results": ["(stubbed)"] if result.allowed else [],
        "allowed": result.allowed,
        "remaining": result.remaining,
    }
