"""Logging helpers shared by the local HTTP services."""

import logging

_QUIET_METRICS_PATHS = frozenset({"/metrics/summary", "/metrics?limit=25"})


class RoutineRequestFilter(logging.Filter):
    """Hide routine polling requests while allowing other HTTP records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == "uvicorn.access":
            request = self._uvicorn_request(record)
            if request is not None:
                method, path, status = request
                if status == 204:
                    return False
                if method == "GET" and path in _QUIET_METRICS_PATHS:
                    return False
        return not (record.name == "httpx" and "204 No Content" in record.getMessage())

    @staticmethod
    def _uvicorn_request(
        record: logging.LogRecord,
    ) -> tuple[object, object, object] | None:
        if isinstance(record.args, tuple) and len(record.args) >= 5:
            return record.args[1], record.args[2], record.args[-1]
        return None


_ROUTINE_REQUEST_FILTER = RoutineRequestFilter()


def suppress_routine_request_logs() -> None:
    """Install filters for expected empty claims and dashboard polling."""
    for logger_name in ("uvicorn.access", "httpx"):
        logger = logging.getLogger(logger_name)
        if _ROUTINE_REQUEST_FILTER not in logger.filters:
            logger.addFilter(_ROUTINE_REQUEST_FILTER)
