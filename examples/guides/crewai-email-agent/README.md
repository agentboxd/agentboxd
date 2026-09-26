# CrewAI email agent

Guide: https://agentboxd.com/guides/crewai-email-agent

| File | What |
|---|---|
| `email_tools.py` | `make_email_tools(mr, inbox_id)`: five `@tool` functions bound to one inbox. The reply tool has `max_usage_count`, so a looping agent can't send more than a few emails per run. |
| `crew.py` | A one-agent support crew: list unread mail, answer simple questions in the thread, flag the rest for a human. |
| `smoke.py` | Calls each tool against a local Agentboxd dev stack without a model, then builds the crew. |

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt          # until agentboxd is on PyPI: pip install -e ../../../sdk-python
cp .env.example .env                     # fill in, then export the variables
python crew.py
```

Written against Python 3.10–3.13 and `crewai` 1.15.22 (checked 25 September 2026).
