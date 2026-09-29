import math
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class ProducerConfig(BaseModel):
    # Prevent field reassignment, reject unknown settings, and validate defaults.
    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)

    # Total SMS messages to generate, including all batches; zero sends nothing.
    count: Annotated[int, Field(strict=True, ge=0)] = 1000

    # Maximum messages per request (1-1000); above 1 uses /messages/batch API.
    # The final batch is smaller when count is not divisible by batch_size.
    batch_size: Annotated[int, Field(strict=True, ge=1, le=1000)] = 1

    # Exact number of random characters in each SMS body (0-100).
    body_length: Annotated[int, Field(strict=True, ge=0, le=100)] = 100

    # Target SMS messages per second, not requests per second. Request starts
    # are spaced by batch_size / rate seconds; slow requests reduce throughput.
    rate: Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)] = 10.0

    # Broker HTTP(S) base URL; the client appends /messages or /messages/batch.
    broker_url: HttpUrl = "http://127.0.0.1:8000"

    # Maximum seconds for each HTTP request, including each retry separately.
    timeout: Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)] = 30.0

    # Additional attempts after a queue-full (503) response; zero disables retries.
    # Each retry resubmits the same payload. Other failures are not retried.
    max_retries: Annotated[int, Field(strict=True, ge=0)] = 1

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        if not math.isfinite(self.batch_size / self.rate):
            raise ValueError("rate must yield a finite interval")
        return self
