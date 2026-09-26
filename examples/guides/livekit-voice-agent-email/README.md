# LiveKit voice agent that emails follow-ups and call summaries

Guide: https://agentboxd.com/guides/livekit-voice-agent-email

| File | What it is |
|---|---|
| `email_tools.py` | `CallEmail`: follow-up emails to the caller (address check, send budget) and the post-call summary, over the async Agentboxd client |
| `agent.py` | The LiveKit agent: `AgentServer`, an `Agent` with two function tools, and `on_session_end`, which emails the summary and transcript |
| `smoke.py` | Runs the email side against a local Agentboxd dev stack, without LiveKit or a model |

```bash
python -m venv .venv && . .venv/bin/activate   # .venv\Scripts\activate on Windows
pip install -r requirements.txt                # in this repository: pip install -e ../../../sdk-python first
cp .env.example .env                           # fill it in and export the variables
python agent.py console                        # talk to it in the terminal
python agent.py dev                            # serve it to LiveKit Cloud (Playground, phone numbers)
```

Check it without LiveKit (no model, no LiveKit key):

```bash
AGENTBOXD_API_KEY=mr_... AGENTBOXD_BASE_URL=http://localhost:3000 python smoke.py
```

Written against `livekit-agents` 1.8.3 (Python) and the LiveKit docs of 2026-09.
