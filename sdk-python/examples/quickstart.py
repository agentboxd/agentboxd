"""Create an inbox and print its address.

    AGENTBOXD_API_KEY=mr_... python examples/quickstart.py [client_id]
    (set AGENTBOXD_BASE_URL=http://localhost:3000 for a local server)

Passing a client_id makes this idempotent: rerunning returns the same inbox.
"""

import sys

from agentboxd import Agentboxd, AgentboxdError


def main() -> int:
    client_id = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        with Agentboxd() as mr:
            inbox = mr.inboxes.create(client_id=client_id)
    except ValueError as exc:  # missing AGENTBOXD_API_KEY
        print(exc, file=sys.stderr)
        return 2
    except AgentboxdError as exc:
        print(f"Agentboxd error: {exc}", file=sys.stderr)
        return 1
    print(f"Inbox {inbox['id']} ready: {inbox['address']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
