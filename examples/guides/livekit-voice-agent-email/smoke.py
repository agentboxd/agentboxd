"""Checks the email side of the voice agent against a local Agentboxd dev stack, without LiveKit or a
model: the tools are registered, a follow-up goes out, the budget and address checks hold, and the
summary email is built from a LiveKit chat history.

    AGENTBOXD_API_KEY=mr_... AGENTBOXD_BASE_URL=http://localhost:3000 python smoke.py
"""

from __future__ import annotations

import asyncio
import os
import time

from agentboxd import AsyncAgentboxd
from livekit.agents import llm

from agent import Receptionist
from email_tools import CallEmail, transcript_from


async def main() -> None:
    base_url = os.environ.get("AGENTBOXD_BASE_URL", "http://localhost:3000")
    async with AsyncAgentboxd(base_url=base_url) as mr:
        inbox = await mr.inboxes.create(client_id=f"livekit-smoke-{int(time.time())}")
        email = CallEmail(mr=mr, inbox_id=inbox["id"], summary_to="team@example.com", max_sends=1)

        agent = Receptionist(email)
        names = sorted(t.info.name for t in agent.tools)
        assert names == ["email_caller", "record_call_summary"], names
        print("tools:", names)

        print("bad address ->", await email.send_follow_up("dana at example", "x", "x"))
        ok = await email.send_follow_up("Dana@Example.com", "Your visit on Friday", "See you at 9am.")
        assert ok.startswith("Sent to dana@example.com"), ok
        print("follow-up ->", ok)
        over = await email.send_follow_up("dana@example.com", "again", "again")
        assert over.startswith("Not sent"), over
        print("over budget ->", over)

        email.record_summary("Dana booked a boiler check. Friday 9am.", ["Confirm the part is in stock", " "])
        history = llm.ChatContext()
        history.add_message(role="system", content="instructions are not part of the transcript")
        history.add_message(role="assistant", content="Acme Plumbing, how can I help?")
        history.add_message(role="user", content="I need someone to look at my boiler.")
        transcript = transcript_from(history.items)
        assert transcript == [
            ("Agent", "Acme Plumbing, how can I help?"),
            ("Caller", "I need someone to look at my boiler."),
        ], transcript
        message_id = await email.email_summary("call-123", transcript)
        assert message_id
        sent = await mr.messages.get(message_id)
        assert sent["to"] == ["team@example.com"], sent["to"]
        assert "Confirm the part is in stock" in (sent["text"] or "")
        assert "Caller: I need someone" in (sent["text"] or "")
        print("summary ->", sent["subject"])
    print("smoke ok")


if __name__ == "__main__":
    asyncio.run(main())
