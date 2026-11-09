from enum import Enum

from pydantic import BaseModel, Field


class Duration(str, Enum):
    MONTHLY = "MONTHLY"


class SetQuotaRequest(BaseModel):
    org_id: str
    feature: str
    duration: Duration = Duration.MONTHLY
    threshold: int = Field(gt=0)


class QuotaResponse(BaseModel):
    id: int
    org_id: str
    feature: str
    duration: Duration
    threshold: int
    is_active: bool
    created_at: str
    updated_at: str


class ConsumeRequest(BaseModel):
    org_id: str
    feature: str
    n: int = Field(gt=0)
    idempotency_key: str | None = None


class ConsumeResponse(BaseModel):
    allowed: bool
    remaining: int
    idempotency_key: str | None = None


class RefundRequest(BaseModel):
    idempotency_key: str


class RefundResponse(BaseModel):
    refunded: bool
    remaining: int


class UsageResponse(BaseModel):
    org_id: str
    feature: str
    duration: Duration
    quota: int
    used: int
    remaining: int
    resets_at: str | None = None
