"""Simulated SMS delivery, processing delays, and failure outcomes."""

from services.sender.client import MetricsReportError
from services.sender.config import SenderConfig
from services.sender.sender import (
    SenderError,
    SenderServiceError,
    process_attempt,
    run_sender,
    run_senders,
)

__all__ = [
    "SenderConfig",
    "SenderError",
    "SenderServiceError",
    "MetricsReportError",
    "process_attempt",
    "run_sender",
    "run_senders",
]
