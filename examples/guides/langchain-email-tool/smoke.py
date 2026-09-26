"""Runs the tools against a local Agentboxd dev stack without a model (no OpenAI key needed).

    AGENTBOXD_API_KEY=mr_... AGENTBOXD_BASE_URL=http://localhost:3000 python smoke.py

It creates an inbox, delivers test emails through the dev-only /dev/inbound route, and calls each
tool the way the agent would. It also builds the agent with create_agent to check the tool schemas.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone

import httpx
from agentboxd import Agentboxd
from langchain.agents import create_agent

from email_tools import make_email_tools


def deliver_locally(base_url: str, sender: str, to: str, subject: str, text: str) -> None:
    """Dev stack only: hand a raw email to POST /dev/inbound."""
    raw = (
        f"From: {sender}\r\nTo: {to}\r\nSubject: {subject}\r\n"
        f"Message-ID: <{uuid.uuid4()}@example.test>\r\nMIME-Version: 1.0\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n\r\n{text}\r\n"
    )
    r = httpx.post(f"{base_url}/dev/inbound", content=raw.encode(), headers={"Content-Type": "message/rfc822"})
    r.raise_for_status()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    base_url = os.environ.get("AGENTBOXD_BASE_URL", "http://localhost:3000")
    with Agentboxd(base_url=base_url) as mr:
        inbox = mr.inboxes.create(client_id=f"langchain-smoke-{int(time.time())}")
        tools = {t.name: t for t in make_email_tools(mr, inbox["id"], max_sends=1)}
        print("tools:", ", ".join(tools))

        since = now()
        deliver_locally(
            base_url,
            "Dana <dana@example.com>",
            inbox["address"],
            "Opening hours",
            "Hi, are you open on Saturday?\r\n\r\nOn Mon, Sep 22, 2026 Support wrote:\r\n> Thanks for your order.",
        )
        waited = tools["wait_for_email"].invoke({"since": since, "timeout_seconds": 10})
        assert waited.startswith("UNTRUSTED"), waited
        message = json.loads(waited.split("\n", 1)[1])
        assert message["text"] == "Hi, are you open on Saturday?", message["text"]
        print("wait_for_email ->", message["subject"], "|", message["text"])

        listed = json.loads(tools["list_messages"].invoke({}).split("\n", 1)[1])
        assert len(listed["messages"]) == 1
        tools["read_message"].invoke({"message_id": message["id"]})
        reply = json.loads(
            tools["reply_to_email"].invoke({"message_id": message["id"], "text": "Yes, 10:00 to 14:00."})
        )
        assert reply["thread_id"] == message["thread_id"]
        print("reply_to_email ->", reply["status"], "same thread")

        since = now()
        deliver_locally(
            base_url,
            "Acme <no-reply@acme.example>",
            inbox["address"],
            "Your Acme verification code",
            "Your verification code is 482913. It expires in 10 minutes.",
        )
        code = json.loads(
            tools["get_verification_code"].invoke({"since": since, "timeout_seconds": 10}).split("\n", 1)[1]
        )
        assert code["code"] == "482913", code
        print("get_verification_code ->", code["code"], code["confidence"])

        # Build (don't run) the agent: checks create_agent accepts these tools. Needs no real key.
        os.environ.setdefault("OPENAI_API_KEY", "sk-not-used")
        create_agent(model="openai:gpt-4.1-mini", tools=list(tools.values()), system_prompt="test")
        print("create_agent ok")
    print("smoke ok")


if __name__ == "__main__":
    main()
