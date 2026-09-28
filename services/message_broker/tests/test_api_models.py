import pytest
from pydantic import ValidationError

from services.message_broker.api_models import ClaimRequest


@pytest.mark.parametrize("sender_id", ["sender-1", " s ", "发送者"])
def test_claim_request_preserves_valid_sender_id(sender_id: str) -> None:
    request = ClaimRequest(sender_id=sender_id, message_type="sms_message")
    assert request.sender_id == sender_id
    assert request.message_type == "sms_message"


@pytest.mark.parametrize("sender_id", ["", " ", "\t\n", None, 1, True])
def test_claim_request_rejects_invalid_sender_id(sender_id: object) -> None:
    with pytest.raises(ValidationError):
        ClaimRequest(sender_id=sender_id, message_type="sms_message")


@pytest.mark.parametrize(
    "payload",
    [
        {"sender_id": "sender-1"},
        {"message_type": "sms_message"},
        {"sender_id": "sender-1", "message_type": "email"},
        {"sender_id": "sender-1", "message_type": "sms_message", "extra": True},
    ],
)
def test_claim_request_requires_supported_type_and_rejects_extra_fields(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ClaimRequest.model_validate(payload)
