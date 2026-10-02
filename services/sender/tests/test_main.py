import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from services.sender import SenderConfig, SenderServiceError
from services.sender import main as entrypoint


@pytest.mark.parametrize(
    "args",
    [
        ["--sender-count", "0"],
        ["--failure-rate", "2"],
        ["--mean-delay", "-1"],
        ["--sender-prefix", "custom"],
        ["--metrics-url", "file:///tmp/metrics"],
        ["--metrics-retries", "-1"],
        ["--retry-delay", "0"],
    ],
)
def test_cli_rejects_configuration_before_starting(
    args: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    run = AsyncMock()
    monkeypatch.setattr(entrypoint, "run", run)
    with pytest.raises(SystemExit) as caught:
        entrypoint.main(args)
    assert caught.value.code == 2
    run.assert_not_called()


def test_cli_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    run = AsyncMock(return_value=0)
    monkeypatch.setattr(entrypoint, "run", run)
    entrypoint.main(
        [
            "--sender-count",
            "2",
            "--mean-delay",
            "0",
            "--failure-rate",
            "1",
            "--metrics-url",
            "http://metrics/metrics",
            "--metrics-retries",
            "2",
        ]
    )
    config = run.await_args.args[0]
    assert config.sender_count == 2
    assert config.mean_delay == 0
    assert config.failure_rate == 1
    assert str(config.metrics_url) == "http://metrics/metrics"
    assert config.metrics_retries == 2


@pytest.mark.parametrize(
    "error,code", [(SenderServiceError([]), 1), (KeyboardInterrupt(), 130)]
)
def test_cli_failure_exit(
    error: BaseException, code: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(entrypoint, "run", AsyncMock(side_effect=error))
    with pytest.raises(SystemExit) as caught:
        entrypoint.main([])
    assert caught.value.code == code


@pytest.mark.parametrize(
    "error", [None, RuntimeError("failed"), asyncio.CancelledError()]
)
def test_http_pool_closed_on_all_exits(
    error: BaseException | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = httpx.AsyncClient()
    monkeypatch.setattr(entrypoint.httpx, "AsyncClient", lambda: client)
    monkeypatch.setattr(
        entrypoint, "run_senders", AsyncMock(side_effect=error, return_value=0)
    )
    if error is None:
        assert asyncio.run(entrypoint.run(SenderConfig())) == 0
    else:
        with pytest.raises(type(error)):
            asyncio.run(entrypoint.run(SenderConfig()))
    assert client.is_closed
