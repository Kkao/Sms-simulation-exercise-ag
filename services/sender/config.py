import math
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class SenderConfig(BaseModel):
    # Prevent reassignment, reject unknown settings, and validate default values.
    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)

    # Positive number of concurrent workers, each processing one attempt at a time.
    sender_count: Annotated[int, Field(strict=True, ge=1)] = 3

    # Mean simulated delay in seconds; sampled uniformly from zero to twice this
    # value. Zero disables the delay; the mean and upper bound must be finite.
    mean_delay: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)] = 0.25

    # Failure probability per attempt: zero always succeeds, one always fails.
    failure_rate: Annotated[
        float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)
    ] = 0.1

    # Positive, finite seconds to wait after an empty broker claim before polling again.
    poll_interval: Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)] = 0.1

    # Broker HTTP(S) base URL; the client appends /messages/claim.
    broker_url: HttpUrl = "http://127.0.0.1:8000"

    # Metrics HTTP(S) URL receiving the shared SenderResult contract.
    metrics_url: HttpUrl = "http://127.0.0.1:8002/metrics"

    # Positive, finite total timeout in seconds per HTTP request.
    timeout: Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)] = 5.0

    # Additional attempts for transient metric submission failures.
    metrics_retries: Annotated[int, Field(strict=True, ge=0)] = 3

    # Positive, finite wait between metric submission attempts.
    retry_delay: Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)] = 0.5

    @model_validator(mode="after")
    def validate_delay_range(self) -> Self:
        if not math.isfinite(2 * self.mean_delay):
            raise ValueError("mean_delay must yield a finite maximum delay")
        return self
