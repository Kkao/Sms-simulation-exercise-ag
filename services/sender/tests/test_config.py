import pytest
from pydantic import ValidationError

from services.sender import SenderConfig


@pytest.mark.parametrize(
    "field,value",
    [
        ("sender_count", 0),
        ("sender_count", -1),
        ("sender_count", True),
        ("sender_count", 1.5),
        ("sender_prefix", "custom"),
        ("mean_delay", -1),
        ("mean_delay", float("nan")),
        ("mean_delay", float("inf")),
        ("mean_delay", 1e308),
        ("failure_rate", -0.1),
        ("failure_rate", 1.1),
        ("failure_rate", float("nan")),
        ("failure_rate", True),
        ("poll_interval", 0),
        ("poll_interval", float("inf")),
        ("timeout", 0),
        ("timeout", float("nan")),
        ("metrics_retries", 3),
        ("retry_delay", 1),
        ("broker_url", "file:///tmp/broker"),
        ("metrics_url", "http://metrics/metrics"),
        ("unknown", 1),
    ],
)
def test_invalid_settings(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        SenderConfig(**{field: value})


@pytest.mark.parametrize("rate", [0, 1])
def test_valid_boundaries(rate: float) -> None:
    config = SenderConfig(
        sender_count=1,
        mean_delay=0,
        failure_rate=rate,
    )
    assert config.failure_rate == rate
    assert config.mean_delay == 0
    with pytest.raises(ValidationError):
        config.sender_count = 2
