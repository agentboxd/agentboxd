"""Runs the CrewAI tools against a local Agentboxd dev stack without a model (no OpenAI key needed),
and builds the crew to check that CrewAI accepts the tools.

    AGENTBOXD_API_KEY=mr_... AGENTBOXD_BASE_URL=http://localhost:3000 python smoke.py
"""

from __future__ import annotations

import json
import os
import time
import uuid

import httpx
from agentboxd import Agentboxd

from crew import build_crew
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


def main() -> None:
    base_url = os.environ.get("AGENTBOXD_BASE_URL", "http://localhost:3000")
    with Agentboxd(base_url=base_url) as mr:
        inbox = mr.inboxes.create(client_id=f"crewai-smoke-{int(time.time())}")
        tools = {t.name: t for t in make_email_tools(mr, inbox["id"], max_sends=1)}
        print("tools:", ", ".join(tools))

        deliver_locally(
            base_url,
            "Dana <dana@example.com>",
            inbox["address"],
            "Order 1042 shipping",
            "Hi, when will order 1042 ship?\r\n\r\n-- \r\nDana Reyes\r\nSent from my phone",
        )
        time.sleep(1)  # ingest is synchronous, but give the worker a moment for search indexing
        listed = json.loads(tools["List unread email"].run(limit=5).split("\n", 1)[1])
        assert len(listed["messages"]) == 1, listed
        msg = listed["messages"][0]
        print("list ->", msg["subject"], "|", msg["text"])

        found = json.loads(tools["Find related email"].run(query="1042").split("\n", 1)[1])
        print("search 1042 ->", [r["subject"] for r in found["results"]])

        first = json.loads(tools["Reply to email"].run(message_id=msg["id"], text="It ships tomorrow."))
        print("reply ->", first["status"])
        second = tools["Reply to email"].run(message_id=msg["id"], text="again")
        assert "limit" in str(second).lower() or "usage" in str(second).lower(), second
        print("reply over max_usage_count ->", second)

        print(tools["Flag for a human"].run(message_id=msg["id"], reason="test"))
        assert "needs-human" in mr.messages.get(msg["id"])["labels"]

        os.environ.setdefault("OPENAI_API_KEY", "sk-not-used")
        crew = build_crew(mr, inbox["id"])
        print("crew ok:", [a.role for a in crew.agents])
    print("smoke ok")


if __name__ == "__main__":
    main()
