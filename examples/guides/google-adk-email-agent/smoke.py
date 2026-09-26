"""Runs the ADK email agent against a local Agentboxd dev stack with a scripted model instead of Gemini
(no Google key): the read tools directly, then a real ADK Runner turn in which the model asks to reply,
ADK pauses for confirmation, the test approves, and the reply is sent.

    AGENTBOXD_API_KEY=mr_... AGENTBOXD_BASE_URL=http://localhost:3000 AGENTBOXD_INBOX=adk-smoke python smoke.py
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

import httpx
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

os.environ.setdefault("AGENTBOXD_INBOX", f"adk-smoke-{int(time.time())}")

from email_agent import tools
from email_agent.agent import root_agent


def deliver_locally(base_url: str, to: str, subject: str, text: str) -> None:
    """Dev stack only: hand a raw email to POST /dev/inbound."""
    raw = (
        f"From: Dana <dana@example.com>\r\nTo: {to}\r\nSubject: {subject}\r\n"
        f"Message-ID: <{uuid.uuid4()}@example.test>\r\nMIME-Version: 1.0\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n\r\n{text}\r\n"
    )
    httpx.post(
        f"{base_url}/dev/inbound", content=raw.encode(), headers={"Content-Type": "message/rfc822"}
    ).raise_for_status()


class ScriptedModel(BaseLlm):
    """Asks for reply_to_email once, then answers with text."""

    message_id: str = ""

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        answered = any(p.function_response for c in llm_request.contents for p in (c.parts or []))
        if answered:
            part = types.Part(text="Replied to Dana.")
        else:
            call = types.FunctionCall(
                name="reply_to_email", args={"message_id": self.message_id, "text": "Yes, 10 to 2."}
            )
            part = types.Part(function_call=call)
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


async def main() -> None:
    base_url = os.environ.get("AGENTBOXD_BASE_URL", "http://localhost:3000")
    names = sorted(getattr(t, "name", getattr(t, "__name__", "")) for t in root_agent.tools)
    print("tools:", names)
    confirm = {t.name: t._require_confirmation for t in root_agent.tools if hasattr(t, "_require_confirmation")}
    assert confirm == {"send_email": True, "reply_to_email": True}, confirm

    from agentboxd import AsyncAgentboxd

    async with AsyncAgentboxd(base_url=base_url) as mr:
        address = (await mr.inboxes.create(client_id=os.environ["AGENTBOXD_INBOX"]))["address"]

    since = datetime.now(timezone.utc).isoformat()
    deliver_locally(base_url, address, "Opening hours", "Are you open on Saturday?\r\n\r\n> old quoted text")
    waited = await tools.wait_for_email(since=since, timeout_seconds=10)
    assert waited["status"] == "success", waited
    email = waited["email"]
    assert email["text"] == "Are you open on Saturday?", email
    print("wait_for_email ->", email["subject"], "|", email["text"])
    listed = await tools.list_unread_emails()
    assert any(e["id"] == email["id"] for e in listed["emails"]), listed

    since = datetime.now(timezone.utc).isoformat()
    deliver_locally(base_url, address, "Your Acme code", "Your verification code is 482913.")
    code = await tools.get_verification_code(since=since, timeout_seconds=10)
    assert code["code"] == "482913", code
    print("get_verification_code ->", code["code"])

    # A real Runner turn with tool confirmation.
    agent = root_agent.model_copy(update={"model": ScriptedModel(model="scripted", message_id=email["id"])})
    sessions = InMemorySessionService()
    session = await sessions.create_session(app_name="smoke", user_id="u1")
    runner = Runner(agent=agent, app_name="smoke", session_service=sessions)

    request: dict[str, Any] | None = None
    ask = types.Content(role="user", parts=[types.Part(text="Answer Dana")])
    async for event in runner.run_async(user_id="u1", session_id=session.id, new_message=ask):
        for part in event.content.parts if event.content and event.content.parts else []:
            if part.function_call and part.function_call.name == "adk_request_confirmation":
                request = {"id": part.function_call.id}
    assert request, "ADK did not ask for confirmation before reply_to_email"
    print("confirmation requested ->", request["id"])

    approve = types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id=request["id"], name="adk_request_confirmation", response={"confirmed": True}
                )
            )
        ],
    )
    final = ""
    async for event in runner.run_async(user_id="u1", session_id=session.id, new_message=approve):
        if event.is_final_response() and event.content and event.content.parts:
            final = event.content.parts[0].text or ""
    assert final == "Replied to Dana.", final

    async with AsyncAgentboxd(base_url=base_url) as mr:
        thread = await mr.threads.get(email["thread_id"])
    assert any(m["direction"] == "outbound" for m in thread["messages"]), "reply was not sent"
    print("reply_to_email after approval -> sent in thread", email["thread_id"])
    print("smoke ok")


if __name__ == "__main__":
    asyncio.run(main())
