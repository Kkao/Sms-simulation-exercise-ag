import logging
import os

from fastapi import FastAPI, HTTPException, Response, status

from services.message_broker.api_models import (
    BatchMessages,
    ClaimRequest,
    EnqueueResponse,
    ErrorResponse,
    HealthResponse,
)
from services.message_broker.broker import (
    BrokerQueueFull,
    DuplicateMessageError,
    MessageBroker,
)
from shared import BrokerAttempt, SmsMessage

logger = logging.getLogger(__name__)


def create_app(*, capacity: int | None = None) -> FastAPI:

    if capacity is None:
        try:
            capacity = int(os.environ.get("BROKER_QUEUE_CAPACITY", "1000"))
        except ValueError as error:
            raise ValueError(
                "BROKER_QUEUE_CAPACITY must be a positive integer"
            ) from error
    broker = MessageBroker(capacity=capacity)
    app = FastAPI(title="SMS Message Broker", version="0.1.0")

    @app.post(
        "/messages",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=EnqueueResponse,
        responses={
            409: {"model": ErrorResponse, "description": "Conflicting message IDs"},
            503: {"model": ErrorResponse, "description": "Queue capacity exhausted"},
        },
    )
    async def enqueue_message(message: SmsMessage) -> EnqueueResponse:
        """
        Accept an SMS, or acknowledge an identical previous submission.
        """
        try:
            result = broker.enqueue(message)
        except DuplicateMessageError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except BrokerQueueFull as error:
            raise HTTPException(
                status_code=503, detail=str(error), headers={"Retry-After": "1"}
            ) from error
        return EnqueueResponse(
            status=result,
            message_id=message.message_id,
            message_type=message.message_type,
        )

    @app.post(
        "/messages/batch",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=list[EnqueueResponse],
        responses={
            409: {
                "model": ErrorResponse,
                "description": "Conflicting message IDs; batch rejected",
            },
            503: {
                "model": ErrorResponse,
                "description": "Insufficient capacity; batch rejected",
            },
        },
    )
    async def enqueue_batch(messages: BatchMessages) -> list[EnqueueResponse]:
        """Accept an array of messages and return receipts in the same order."""
        try:
            results = broker.enqueue_many(messages)
        except DuplicateMessageError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except BrokerQueueFull as error:
            raise HTTPException(
                status_code=503, detail=str(error), headers={"Retry-After": "1"}
            ) from error
        return [
            EnqueueResponse(
                status=result,
                message_id=message.message_id,
                message_type=message.message_type,
            )
            for message, result in zip(messages, results, strict=True)
        ]

    @app.post(
        "/messages/claim",
        response_model=BrokerAttempt,
        responses={204: {"description": "No matching message available"}},
    )
    async def claim_message(request: ClaimRequest) -> BrokerAttempt | Response:
        """
        Remove the next SMS and return its attempt envelope to an idle sender.
        """
        attempt = broker.claim(request.message_type)
        if attempt is None:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        logger.info(
            "Dispatched attempt_id=%s message_id=%s message_type=%s sender_id=%r",
            attempt.attempt_id,
            attempt.message.message_id,
            attempt.message.message_type,
            request.sender_id,
        )
        return attempt

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        """Report API availability and queued work, excluding dispatched attempts."""
        return HealthResponse(pending_messages=broker.pending_count)

    return app
