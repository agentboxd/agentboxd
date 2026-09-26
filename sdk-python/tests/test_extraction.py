"""Attachment extraction: extracted text and structured extraction."""

import asyncio
from typing import get_args

import pytest

from agentboxd import (
    Agentboxd,
    AgentboxdError,
    Attachment,
    AttachmentText,
    PermissionDeniedError,
    StructuredExtraction,
    UnprocessableEntityError,
    WebhookEventType,
)

from .conftest import Recorder, make_async

TEXT: AttachmentText = {
    "attachment_id": "a_1",
    "message_id": "m_1",
    "filename": "invoice.pdf",
    "content_type": "application/pdf",
    "extraction": {
        "status": "done",
        "method": "text",
        "pages": 2,
        "chars": 21,
        "language": "en",
        "truncated": False,
        "error": None,
        "updated_at": "2026-09-25T09:14:06.410Z",
    },
    "text": "Total due: 180.00 EUR",
    "offset": 0,
    "total_chars": 21,
    "next_offset": None,
    "untrusted": True,
}


def test_attachment_text(client: Agentboxd, rec: Recorder) -> None:
    rec.reply(TEXT)
    out = client.messages.attachment_text("m_1", "a_1")
    assert out["text"] == "Total due: 180.00 EUR"
    assert (rec.last.method, rec.last.url.path) == ("GET", "/v1/messages/m_1/attachments/a_1/text")
    assert rec.last_params() == {}

    client.messages.attachment_text("m_1", "a_1", offset=100, max_chars=50)
    assert rec.last_params() == {"offset": "100", "max_chars": "50"}


def test_extract_attachment(client: Agentboxd, rec: Recorder) -> None:
    result: StructuredExtraction = {
        "attachment_id": "a_1",
        "message_id": "m_1",
        "schema": "invoice",
        "data": {"total": 180},
        "model": "deepseek-flash",
        "repaired": False,
        "truncated": False,
        "untrusted": True,
    }
    rec.reply(result)
    out = client.messages.extract_attachment("m_1", "a_1", "invoice", instructions="EUR")
    assert out["data"]["total"] == 180
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/messages/m_1/attachments/a_1/extract")
    assert rec.last_json() == {"schema": "invoice", "instructions": "EUR"}

    custom = {"type": "object", "properties": {"po": {"type": ["string", "null"]}}, "required": ["po"]}
    client.messages.extract_attachment("m_1", "a_1", custom)
    assert rec.last_json() == {"schema": custom}


def test_extract_attachment_errors(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"error": {"code": "ai_disabled", "message": "needs full"}}, status=403)
    with pytest.raises(PermissionDeniedError) as denied:
        client.messages.extract_attachment("m_1", "a_1", "receipt")
    assert denied.value.code == "ai_disabled"

    rec.reply({"error": {"code": "extraction_pending", "message": "still extracting"}}, status=409)
    with pytest.raises(AgentboxdError) as pending:
        client.messages.extract_attachment("m_1", "a_1", "receipt")
    assert pending.value.code == "extraction_pending"

    rec.reply(
        {"error": {"code": "structured_output_invalid", "message": "no", "details": {"errors": ["/total"]}}},
        status=422,
    )
    with pytest.raises(UnprocessableEntityError) as invalid:
        client.messages.extract_attachment("m_1", "a_1", "tax_form")
    assert invalid.value.code == "structured_output_invalid"


def test_async_extraction(rec: Recorder) -> None:
    async def main() -> None:
        async with make_async(rec) as mr:
            rec.reply(TEXT)
            out = await mr.messages.attachment_text("m_1", "a_1", max_chars=10)
            assert out["extraction"] is not None
            assert rec.last_params() == {"max_chars": "10"}
            await mr.messages.extract_attachment("m_1", "a_1", "invoice")
            assert rec.last.url.path == "/v1/messages/m_1/attachments/a_1/extract"
            assert rec.last_json() == {"schema": "invoice"}

    asyncio.run(main())


def test_types() -> None:
    assert "extraction" in Attachment.__optional_keys__
    assert {"attachment.extracted", "attachment.extraction_failed"} <= set(get_args(WebhookEventType))
