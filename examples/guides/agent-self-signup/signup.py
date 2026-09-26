"""An agent with no API key gives itself an email inbox, then asks its human to claim the workspace.

python agent-self-signup/signup.py you@example.com
Prints the key once: store it (e.g. as AGENTBOXD_API_KEY) before doing anything else.
"""

import sys

from agentboxd import Agentboxd

owner_email = sys.argv[1] if len(sys.argv) > 1 else None

# Solves a short proof-of-work challenge (a few seconds of CPU), then creates the workspace.
s = Agentboxd.signup(agent_name="research-agent", owner_email=owner_email)
print(f"AGENTBOXD_API_KEY={s.api_key}  # shown once: store it now")
print(f"inbox: {s.inbox['address']} ({s.inbox['id']})")
print(f"claim: {s.result['claim']['status']}")

mr = s.client
mail = mr.messages.wait(s.inbox["id"], timeout=60)
if mail:
    print(f"from {mail['from']}: {mail['subject']}")
    # Replies in a thread someone started with the agent don't count toward the daily limit.
    mr.messages.reply(s.inbox["id"], mail["id"], text="Thanks, got it.")

if owner_email is None:
    # Later, once your human agrees: they get a single-use link to claim the workspace.
    print("ask your human for their email, then: mr.account.request_claim(email)")
print(mr.account.get()["claim"])
