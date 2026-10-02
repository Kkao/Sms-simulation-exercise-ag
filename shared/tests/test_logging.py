import logging

import pytest

from shared.logging import RoutineRequestFilter


def log_record(
    *, name: str, message: str, arguments: tuple[object, ...] = ()
) -> logging.LogRecord:
    return logging.LogRecord(
        name=name,
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=arguments,
        exc_info=None,
    )


def test_filter_hides_uvicorn_204_access_record() -> None:
    record = log_record(
        name="uvicorn.access",
        message='%s - "%s %s HTTP/%s" %d',
        arguments=("127.0.0.1", "POST", "/messages/claim", "1.1", 204),
    )

    assert not RoutineRequestFilter().filter(record)


def test_filter_hides_httpx_204_request_record() -> None:
    record = log_record(
        name="httpx",
        message='HTTP Request: POST http://broker/messages/claim "HTTP/1.1 204 No Content"',
    )

    assert not RoutineRequestFilter().filter(record)


@pytest.mark.parametrize("path", ["/metrics/summary", "/metrics?limit=25"])
def test_filter_hides_dashboard_polling_records(path: str) -> None:
    record = log_record(
        name="uvicorn.access",
        message='%s - "%s %s HTTP/%s" %d',
        arguments=("127.0.0.1", "GET", path, "1.1", 200),
    )

    assert not RoutineRequestFilter().filter(record)


def test_filter_keeps_other_log_records() -> None:
    record = log_record(
        name="httpx",
        message='HTTP Request: POST http://broker/messages/claim "HTTP/1.1 200 OK"',
    )

    assert RoutineRequestFilter().filter(record)
