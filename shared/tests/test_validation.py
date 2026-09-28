from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from pydantic import TypeAdapter

from shared.validation import UtcTimestamp, validate_utc_timestamp

EXPECTED = datetime(2026, 9, 26, 14, 30, 12, 123456, tzinfo=UTC)


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(EXPECTED, id="utc-datetime"),
        pytest.param(
            EXPECTED.replace(tzinfo=timezone(timedelta(0), "custom-zero-offset")),
            id="named-zero-offset-datetime",
        ),
        pytest.param("2026-09-26T14:30:12.123456Z", id="z-suffix"),
        pytest.param("2026-09-26T14:30:12.123456+00:00", id="explicit-zero-offset"),
    ],
)
def test_valid_utc_timestamp_preserves_time_and_normalizes_timezone(
    value: object,
) -> None:
    result = validate_utc_timestamp(value)

    assert result == EXPECTED
    assert result.microsecond == 123456
    assert result.tzinfo is UTC


def test_timestamp_without_fractional_seconds_is_valid() -> None:
    assert validate_utc_timestamp("2026-09-26T14:30:12Z") == EXPECTED.replace(
        microsecond=0
    )


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(datetime(2026, 9, 26, 14, 30), id="naive-datetime"),
        pytest.param("2026-09-26T14:30:12", id="naive-iso-string"),
        pytest.param("2026-09-26", id="date-only-string"),
        pytest.param(date(2026, 9, 26), id="date-object"),
        pytest.param(
            EXPECTED.astimezone(timezone(timedelta(hours=1))),
            id="positive-offset-datetime",
        ),
        pytest.param(
            EXPECTED.astimezone(timezone(timedelta(hours=-5))),
            id="negative-offset-datetime",
        ),
        pytest.param("2026-09-26T15:30:12+01:00", id="positive-offset-string"),
        pytest.param("2026-09-26T09:30:12-05:00", id="negative-offset-string"),
        pytest.param(None, id="none"),
        pytest.param(True, id="boolean"),
        pytest.param(0, id="zero-epoch"),
        pytest.param(1790433012, id="integer-epoch"),
        pytest.param(1790433012.5, id="float-epoch"),
        pytest.param(b"2026-09-26T14:30:12Z", id="bytes"),
        pytest.param([], id="list"),
        pytest.param({}, id="dictionary"),
    ],
)
def test_non_utc_or_non_timestamp_value_is_rejected(value: object) -> None:
    with pytest.raises(ValueError, match="timestamp must include a UTC timezone"):
        validate_utc_timestamp(value)


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("", id="empty-string"),
        pytest.param("not-a-timestamp", id="malformed-string"),
        pytest.param("2026-02-30T14:30:12Z", id="invalid-calendar-date"),
        pytest.param("2026-09-26T25:30:12Z", id="invalid-hour"),
        pytest.param("2026-09-26T14:30:12+25:00", id="invalid-offset"),
        pytest.param("1790433012", id="numeric-string"),
    ],
)
def test_malformed_timestamp_string_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        validate_utc_timestamp(value)


@pytest.mark.parametrize("value", [EXPECTED, "2026-09-26T14:30:12.123456Z"])
def test_timestamp_annotation_accepts_and_normalizes_utc(value: object) -> None:
    result = TypeAdapter(UtcTimestamp).validate_python(value)

    assert result == EXPECTED
    assert result.tzinfo is UTC
