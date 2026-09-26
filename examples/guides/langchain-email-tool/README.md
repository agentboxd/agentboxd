# LangChain email tools

Guide: https://agentboxd.com/guides/langchain-email-tool

| File | What |
|---|---|
| `email_tools.py` | `make_email_tools(mr, inbox_id)`: six `@tool` functions bound to one inbox (list, read, wait, verification code, send, reply), with a send budget and untrusted-content marking. |
| `agent.py` | `create_agent(model="openai:gpt-4.1-mini", tools=…, system_prompt=…)` working the inbox. |
| `smoke.py` | Calls every tool against a local Agentboxd dev stack without a model, then builds the agent. |

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt          # until agentboxd is on PyPI: pip install -e ../../../sdk-python
cp .env.example .env                     # fill in, then export the variables
python agent.py "Check for new email and answer simple questions"
```

Written against Python 3.10+, `langchain` 1.4.2, `langchain-core` 1.6.5, `langchain-openai` 1.6.6
(checked 25 September 2026).
