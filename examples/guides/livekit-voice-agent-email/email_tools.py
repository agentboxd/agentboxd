"""Email for a LiveKit voice agent: follow-ups the caller asks for, and a summary of every call.

Plain async functions over the async Agentboxd client, so they never block the audio loop and can be
tested without a LiveKit room (see smoke.py). agent.py turns them into function tools.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from agentboxd import AsyncAgentboxd

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class CallEmail:
    """Per-call email state: one agent inbox, a send budget, and the notes for the summary."""

    mr: AsyncAgentboxd
    inbox_id: str
    #: Where call summaries go (your team). Never chosen by the model.
    summary_to: str | None = None
    max_sends: int = 2
    sent: list[str] = field(default_factory=list)
    summary: str | None = None
    action_items: list[str] = field(default_factory=list)

    async def send_follow_up(self, to: str, subject: str, text: str) -> str:
        """Email the caller. Returns a short status the model can say out loud."""
        to = to.strip().lower()
        if not EMAIL_RE.match(to):
            return f"'{to}' is not a valid email address. Ask the caller to spell it again."
        if len(self.sent) >= self.max_sends:
            return f"Not sent: the limit of {self.max_sends} emails per call is reached."
        m = await self.mr.messages.send(self.inbox_id, to=to, subject=subject, text=text)
        self.sent.append(to)
        return f"Sent to {to} (message {m['id']})."

    def record_summary(self, summary: str, action_items: list[str]) -> str:
        self.summary = summary.strip()
        self.action_items = [a.strip() for a in action_items if a.strip()]
        return "Noted. It will be emailed to the team when the call ends."

    async def email_summary(self, room: str, transcript: list[tuple[str, str]]) -> str | None:
        """After the call: summary, action items and the transcript to `summary_to`. Returns the message id."""
        if not self.summary_to or not transcript:
            return None
        lines = [
            f"Call in room {room}, ended {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC.",
            "",
            "Summary:",
            self.summary or "(the agent did not record one; see the transcript)",
        ]
        if self.action_items:
            lines += ["", "Action items:", *[f"- {a}" for a in self.action_items]]
        if self.sent:
            lines += ["", f"Follow-up emails sent during the call: {', '.join(self.sent)}"]
        lines += ["", "Transcript:", *[f"{role}: {text}" for role, text in transcript]]
        m = await self.mr.messages.send(
            self.inbox_id,
            to=self.summary_to,
            subject=f"Call summary: {self.summary.split('.')[0][:80] if self.summary else room}",
            text="\n".join(lines),
        )
        return str(m["id"])


def transcript_from(items: list[Any]) -> list[tuple[str, str]]:
    """User and assistant turns of a LiveKit chat history (``report.chat_history.items``)."""
    out: list[tuple[str, str]] = []
    for item in items:
        if getattr(item, "type", None) != "message" or item.role not in ("user", "assistant"):
            continue
        text = item.text_content
        if text:
            out.append(("Caller" if item.role == "user" else "Agent", text))
    return out
