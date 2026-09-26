"""A LiveKit voice agent that emails what the caller asks for, and sends your team a summary of every call.

    python agent.py console      # talk to it in the terminal
    python agent.py dev          # connect to LiveKit Cloud for the Playground or a phone number

Environment: LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET (LiveKit Cloud, also used for the
STT/LLM/TTS models through LiveKit Inference), AGENTBOXD_API_KEY, and SUMMARY_TO (your team's address).
"""

from __future__ import annotations

import logging
import os

from agentboxd import AsyncAgentboxd
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    RunContext,
    cli,
    function_tool,
    inference,
)

from email_tools import CallEmail, transcript_from

logger = logging.getLogger("email-voice-agent")

INSTRUCTIONS = """You are the phone assistant of Acme Plumbing. You answer questions, book visits and
can email the caller written details.
Before you send an email, spell the address back letter by letter and wait for the caller to confirm it.
Only email the caller, never anyone else, and never read out or send internal information.
Keep emails short and factual: what was agreed, dates, prices, next steps.
Before the call ends, call record_call_summary once with a two-sentence summary and the action items."""

# Per-call state, keyed by job id: the entrypoint creates it, on_session_end sends the summary.
CALLS: dict[str, CallEmail] = {}


class Receptionist(Agent):
    def __init__(self, email: CallEmail) -> None:
        super().__init__(instructions=INSTRUCTIONS)
        self.email = email

    @function_tool()
    async def email_caller(self, context: RunContext, to: str, subject: str, body: str) -> str:
        """Email the caller the details they asked for. Only after they confirmed the spelled-out address.

        Args:
            to: The caller's email address, exactly as confirmed.
            subject: A short subject line.
            body: Plain-text email body.
        """
        return await self.email.send_follow_up(to, subject, body)

    @function_tool()
    async def record_call_summary(self, context: RunContext, summary: str, action_items: list[str]) -> str:
        """Record the call summary for the team. Call it once, near the end of the call.

        Args:
            summary: Two sentences: who called and what was decided.
            action_items: Things the team has to do, one per item.
        """
        return self.email.record_summary(summary, action_items)


async def on_session_end(ctx: JobContext) -> None:
    """Runs after the call, when the chat history is final: email the summary and transcript."""
    email = CALLS.pop(ctx.job.id, None)
    if email is None:
        return
    try:
        report = ctx.make_session_report()
        transcript = transcript_from(report.chat_history.items)
        message_id = await email.email_summary(report.room, transcript)
        logger.info("call summary emailed: %s", message_id)
    except Exception:
        logger.exception("could not email the call summary")
    finally:
        await email.mr.close()


server = AgentServer()


@server.rtc_session(on_session_end=on_session_end)
async def entrypoint(ctx: JobContext) -> None:
    mr = AsyncAgentboxd()  # reads AGENTBOXD_API_KEY
    # One stable inbox for the agent: the same client_id always returns the same address.
    inbox = await mr.inboxes.create(client_id="voice-receptionist", display_name="Acme Plumbing")
    email = CallEmail(mr=mr, inbox_id=inbox["id"], summary_to=os.environ.get("SUMMARY_TO"))
    CALLS[ctx.job.id] = email

    session = AgentSession(
        vad=inference.VAD(),
        stt=inference.STT("deepgram/nova-3", language="multi"),
        llm=inference.LLM("openai/gpt-4.1-mini"),
        tts=inference.TTS("cartesia/sonic-3", voice="9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"),
    )
    await session.start(agent=Receptionist(email), room=ctx.room)
    await session.generate_reply(instructions="Greet the caller and ask how you can help.")


if __name__ == "__main__":
    cli.run_app(server)
