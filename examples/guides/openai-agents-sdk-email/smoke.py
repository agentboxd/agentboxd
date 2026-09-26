"""Calls the function tools the way the Runner would, against a local Agentboxd dev stack, without a
model (no OpenAI key needed).

    AGENTBOXD_API_KEY=mr_... AGENTBOXD_BASE_URL=http://localhost:3000 python smoke.py
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import datetime, timezone

import httpx
from agentboxd import Agentboxd
from agents import FunctionTool
from agents.tool_context import ToolContext

from agent import agent
from email_tools import EMAIL_TOOLS, EmailContext


def deliver_locally(base_url: str, sender: str, to: str, subject: str, text: str) -> None:
    """Dev stack only: hand a raw email to POST /dev/inbound."""
    raw = (
        f"From: {sender}\r\nTo: {to}\r\nSubject: {subject}\r\n"
        f"Message-ID: <{uuid.uuid4()}@example.test>\r\nMIME-Version: 1.0\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n\r\n{text}\r\n"
    )
    r = httpx.post(f"{base_url}/dev/inbound", content=raw.encode(), headers={"Content-Type": "message/rfc822"})
    r.raise_for_status()


async def call(ctx: EmailContext, tool: FunctionTool, **args: object) -> str:
    payload = json.dumps(args)
    tc = ToolContext(context=ctx, tool_name=tool.name, tool_call_id=f"smoke-{uuid.uuid4()}", tool_arguments=payload)
    return str(await tool.on_invoke_tool(tc, payload))


async def main() -> None:
    base_url = os.environ.get("AGENTBOXD_BASE_URL", "http://localhost:3000")
    tools = {t.name: t for t in EMAIL_TOOLS}
    for t in EMAIL_TOOLS:
        print(f"{t.name}: {sorted(t.params_json_schema['properties'])}")
    assert "ctx" not in tools["read_message"].params_json_schema["properties"]
    assert agent.tools == EMAIL_TOOLS

    with Agentboxd(base_url=base_url) as mr:
        inbox = mr.inboxes.create(client_id=f"oa-smoke-{int(time.time())}")
        ctx = EmailContext(mr=mr, inbox_id=inbox["id"], address=inbox["address"], max_sends=1)

        since = datetime.now(timezone.utc).isoformat()
        deliver_locally(
            base_url,
            "Dana <dana@example.com>",
            inbox["address"],
            "Opening hours",
            "Hi, are you open on Saturday?\r\n\r\nOn Mon, Sep 22, 2026 Support wrote:\r\n> Thanks for your order.",
        )
        waited = await call(ctx, tools["wait_for_email"], since=since, timeout_seconds=10)
        message = json.loads(waited.split("\n", 1)[1])
        assert message["text"] == "Hi, are you open on Saturday?", message
        print("wait_for_email ->", message["subject"], "|", message["text"])

        reply = json.loads(await call(ctx, tools["reply_to_email"], message_id=message["id"], text="Yes, 10 to 2."))
        assert reply["thread_id"] == message["thread_id"]
        print("reply_to_email ->", reply["status"])

        # Over budget: the SDK turns the exception into an error message for the model.
        over = await call(ctx, tools["send_email"], to="x@example.com", subject="x", text="x")
        assert "budget" in over, over
        print("send_email over budget ->", over)

        since = datetime.now(timezone.utc).isoformat()
        deliver_locally(
            base_url,
            "Acme <no-reply@acme.example>",
            inbox["address"],
            "Your Acme verification code",
            "Your verification code is 482913. It expires in 10 minutes.",
        )
        code = json.loads(
            (await call(ctx, tools["get_verification_code"], since=since, timeout_seconds=10)).split("\n", 1)[1]
        )
        assert code["code"] == "482913", code
        print("get_verification_code ->", code["code"], code["confidence"])
    print("smoke ok")


if __name__ == "__main__":
    asyncio.run(main())
