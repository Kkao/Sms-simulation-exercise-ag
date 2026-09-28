from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.validation import UtcTimestamp

MessageType = Literal["sms_message"]


class _Contract(BaseModel):
    model_config = ConfigDict(frozen=True, revalidate_instances="always")

    schema_version: Literal[1]
    message_type: MessageType

    @field_validator("schema_version", mode="before")
    @classmethod
    def require_integer_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("schema_version must be the integer 1")
        return value


class SmsMessage(_Contract):
    message_id: UUID
    created_at: UtcTimestamp
    body: Annotated[str, Field(strict=True, max_length=100)]


class BrokerAttempt(_Contract):
    attempt_id: UUID
    attempt_number: Annotated[int, Field(strict=True, ge=1)]
    enqueued_at: UtcTimestamp
    dispatched_at: UtcTimestamp
    message: SmsMessage


class SenderResult(_Contract):
    event_id: UUID
    event_type: Literal["sms.attempt_completed"]
    message_id: UUID
    attempt_id: UUID
    sender_id: Annotated[str, Field(strict=True, min_length=1)]
    occurred_at: UtcTimestamp
    status: Literal["sent", "failed"]
    processing_duration_ms: Annotated[
        float, Field(strict=True, ge=0, allow_inf_nan=False)
    ]
    error_code: Annotated[str, Field(strict=True, min_length=1)] | None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.status == "sent" and self.error_code is not None:
            raise ValueError("a sent result must have error_code=null")
        if self.status == "failed" and self.error_code is None:
            raise ValueError("a failed result must include an error_code")
        return self
