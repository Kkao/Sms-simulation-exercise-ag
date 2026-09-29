import pytest
from pydantic import ValidationError

from services.producer import ProducerConfig


def test_defaults_and_boundaries() -> None:
    assert ProducerConfig().count == 1000
    assert ProducerConfig().body_length == 100
    assert ProducerConfig().batch_size == 1
    assert ProducerConfig(batch_size=1000).batch_size == 1000
    assert ProducerConfig(count=0, body_length=0, max_retries=0).count == 0
    assert ProducerConfig(body_length=100, rate=1).rate == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [("count", value) for value in (-1, 1.5, True, "2")]
    + [("batch_size", value) for value in (0, -1, 1001, True, 1.5, "5")]
    + [("body_length", value) for value in (-1, 101, True, 1.5)]
    + [
        (field, value)
        for field in ("rate", "timeout")
        for value in (0, -1, float("inf"), float("nan"), True)
    ]
    + [
        ("rate", 5e-324),
        ("max_retries", -1),
        ("max_retries", True),
        ("max_retries", 1.5),
        ("broker_url", "not a url"),
        ("broker_url", "ftp://localhost"),
        ("unknown", 1),
    ],
)
def test_invalid_settings(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        ProducerConfig(**{field: value})


def test_batch_interval_must_be_finite() -> None:
    with pytest.raises(ValidationError, match="finite interval"):
        ProducerConfig(batch_size=1000, rate=1e-307)
