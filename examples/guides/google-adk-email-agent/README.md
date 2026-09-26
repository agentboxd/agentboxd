# Google ADK agent with its own inbox

Guide: https://agentboxd.com/guides/google-adk-email-agent

| File | What it is |
|---|---|
| `email_agent/tools.py` | Six async function tools over the async Agentboxd client, one inbox per agent |
| `email_agent/agent.py` | `root_agent`: Gemini with the tools; `send_email` and `reply_to_email` wrapped in `FunctionTool(..., require_confirmation=True)` |
| `email_agent/__init__.py`, `email_agent/.env.example` | The layout `adk run` / `adk web` expect |
| `smoke.py` | Runs the tools against a local Agentboxd dev stack, then a real ADK `Runner` turn with a scripted model: confirmation requested, approved, reply sent |

```bash
python -m venv .venv && . .venv/bin/activate      # .venv\Scripts\activate on Windows
pip install -r requirements.txt                   # in this repository: pip install -e ../../../sdk-python first
cp email_agent/.env.example email_agent/.env      # fill in GOOGLE_API_KEY and AGENTBOXD_API_KEY
adk web                                           # from this folder; pick email_agent
adk run email_agent                               # or in the terminal
```

Check it without Gemini:

```bash
AGENTBOXD_API_KEY=mr_... AGENTBOXD_BASE_URL=http://localhost:3000 python smoke.py
```

Written against `google-adk` 2.10.0 (Python) and the ADK docs at adk.dev as of 2026-09.
