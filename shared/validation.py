from datetime import UTC, datetime, timedelta
from typing import Annotated

from pydantic import BeforeValidator


def validate_utc_timestamp(value: object) -> datetime:
    """Accept UTC datetime or ISO timestamp; reject numeric epochs."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must include a UTC timezone (Z or +00:00)")
    return value.astimezone(UTC)


UtcTimestamp = Annotated[datetime, BeforeValidator(validate_utc_timestamp)]
