# OpenAI Agents SDK email tools

Guide: https://agentboxd.com/guides/openai-agents-sdk-email

| File | What |
|---|---|
| `email_tools.py` | Six `@function_tool` functions. The Agentboxd client and the inbox come from the run context (`EmailContext`), so the model never picks an inbox. |
| `agent.py` | `Agent[EmailContext]` with dynamic instructions, run with `Runner.run_sync(agent, task, context=…)`. |
| `smoke.py` | Invokes each tool the way the Runner does, against a local Agentboxd dev stack, without a model. |

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt          # until agentboxd is on PyPI: pip install -e ../../../sdk-python
cp .env.example .env                     # fill in, then export the variables
python agent.py "Check for new email and answer simple questions"
```

Written against Python 3.10+ and `openai-agents` 0.22.3 (checked 25 September 2026).
