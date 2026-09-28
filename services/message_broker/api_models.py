from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from services.message_broker.broker import EnqueueStatus
from shared import MessageType


class ClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sender_id: Annotated[str, Field(strict=True, min_length=1, pattern=r"\S")]
    message_type: MessageType


class EnqueueResponse(BaseModel):
    status: EnqueueStatus
    message_id: UUID
    message_type: MessageType


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    pending_messages: int


class ErrorResponse(BaseModel):
    detail: str
