from fastapi import APIRouter, Query

from .models import (
    ConsumeRequest,
    ConsumeResponse,
    Duration,
    QuotaResponse,
    RefundRequest,
    RefundResponse,
    SetQuotaRequest,
    UsageResponse,
)
from .service import quota_service


admin_router = APIRouter(prefix="/admin", tags=["admin"])
quota_router = APIRouter(prefix="/quota", tags=["quota"])


@admin_router.post("/quotas", response_model=QuotaResponse)
async def set_quota(req: SetQuotaRequest) -> QuotaResponse:
    return await quota_service.set_quota(
        org_id=req.org_id,
        feature=req.feature,
        duration=req.duration,
        threshold=req.threshold,
    )


@quota_router.post("/consume", response_model=ConsumeResponse)
async def consume(req: ConsumeRequest) -> ConsumeResponse:
    return await quota_service.consume(
        org_id=req.org_id,
        feature=req.feature,
        n=req.n,
        idempotency_key=req.idempotency_key,
    )


@quota_router.post("/refund", response_model=RefundResponse)
async def refund(req: RefundRequest) -> RefundResponse:
    return await quota_service.refund(req.idempotency_key)


@quota_router.get("/usage", response_model=UsageResponse)
async def usage(
    org_id: str = Query(...),
    feature: str = Query(...),
    duration: Duration = Query(Duration.MONTHLY),
) -> UsageResponse:
    return await quota_service.usage(org_id=org_id, feature=feature, duration=duration)
