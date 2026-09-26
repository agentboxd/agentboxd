import asyncio
import hashlib
import json
from typing import Any, get_args

import httpx
import pytest

from agentboxd import (
    Agentboxd,
    AsyncAgentboxd,
    RateLimitError,
    WebhookEventType,
    solve_signup_challenge,
)
from agentboxd._signup import leading_zero_bits

from .conftest import BASE

CHALLENGE = "v1.eyJuIjoieCIsImQiOjEwLCJlIjoxfQ.sig"


def _signup_body(owner: bool) -> dict[str, Any]:
    return {
        "api_key": "mr_new",
        "workspace": {
            "id": "w1",
            "name": "Agent workspace",
            "status": "unclaimed",
            "created_at": "",
            "claimed_at": None,
        },
        "inbox": {"id": "i1", "address": "a@agents.test"},
        "claim": {"status": "email_sent", "email": "o***@example.com"}
        if owner
        else {"status": "not_requested", "email": None},
        "restrictions": {"recipients_per_day": 20},
        "docs_url": "https://agentboxd.com/docs/agent-signup",
        "next_steps": [],
    }


class FakeApi:
    def __init__(self, difficulty: int = 10) -> None:
        self.difficulty = difficulty
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/v1/signup/challenge":
            return httpx.Response(
                200, json={"challenge": CHALLENGE, "difficulty": self.difficulty, "algorithm": "sha256"}
            )
        if path == "/v1/signup":
            body = json.loads(request.content)
            digest = hashlib.sha256(f"{body['challenge']}:{body['solution']}".encode()).digest()
            assert leading_zero_bits(digest) >= self.difficulty
            return httpx.Response(201, json=_signup_body("owner_email" in body))
        if path == "/v1/account":
            return httpx.Response(200, json={"claim": {"status": "unclaimed"}})
        if path == "/v1/signup/claim":
            return httpx.Response(
                202, json={"status": "email_sent", "email": "o***@example.com", "expires_at": ""}
            )
        return httpx.Response(404, json={"error": {"code": "not_found", "message": path}})


def test_leading_zero_bits() -> None:
    assert leading_zero_bits(b"\xff") == 0
    assert leading_zero_bits(b"\x0f\xff") == 4
    assert leading_zero_bits(b"\x00\x01") == 15
    assert leading_zero_bits(b"\x00\x00\x00\x00") == 32


def test_solver_matches_the_server_rule() -> None:
    solution = solve_signup_challenge(CHALLENGE, 12)
    digest = hashlib.sha256(f"{CHALLENGE}:{solution}".encode()).digest()
    assert leading_zero_bits(digest) >= 12
    # The first solution counting up from 0: nothing smaller works.
    for i in range(int(solution)):
        assert leading_zero_bits(hashlib.sha256(f"{CHALLENGE}:{i}".encode()).digest()) < 12
    with pytest.raises(RuntimeError):
        solve_signup_challenge(CHALLENGE, 30, max_iterations=5)


def test_sync_signup_needs_no_key_and_returns_a_ready_client() -> None:
    api = FakeApi()
    http = httpx.Client(transport=httpx.MockTransport(api))
    s = Agentboxd.signup(
        agent_name="bot", owner_email="me@example.com", base_url=BASE + "/", http_client=http
    )
    assert s.api_key == "mr_new"
    assert s.inbox["address"] == "a@agents.test"
    assert s.workspace["status"] == "unclaimed"
    assert s.result["claim"]["status"] == "email_sent"
    challenge_req, signup_req = api.requests
    assert "authorization" not in challenge_req.headers
    assert "authorization" not in signup_req.headers
    assert signup_req.url == BASE + "/v1/signup"
    body = json.loads(signup_req.content)
    assert body["challenge"] == CHALLENGE
    assert body["agent_name"] == "bot"
    assert body["owner_email"] == "me@example.com"

    assert s.client.account.get()["claim"]["status"] == "unclaimed"
    assert api.requests[-1].headers["authorization"] == "Bearer mr_new"
    assert s.client.account.request_claim("me@example.com")["status"] == "email_sent"
    assert json.loads(api.requests[-1].content) == {"email": "me@example.com"}


def test_signup_omits_unset_fields() -> None:
    api = FakeApi(difficulty=1)
    Agentboxd.signup(base_url=BASE, http_client=httpx.Client(transport=httpx.MockTransport(api)))
    assert set(json.loads(api.requests[1].content)) == {"challenge", "solution"}


def test_signup_errors_are_typed() -> None:
    def limited(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/challenge"):
            return httpx.Response(200, json={"challenge": CHALLENGE, "difficulty": 1})
        return httpx.Response(
            429,
            json={"error": {"code": "signup_rate_limited", "message": "slow down"}},
            headers={"Retry-After": "120"},
        )

    with pytest.raises(RateLimitError) as exc:
        Agentboxd.signup(base_url=BASE, http_client=httpx.Client(transport=httpx.MockTransport(limited)))
    assert exc.value.code == "signup_rate_limited"
    assert exc.value.retry_after == 120


def test_async_signup() -> None:
    api = FakeApi()

    async def run() -> None:
        http = httpx.AsyncClient(transport=httpx.MockTransport(api))
        s = await AsyncAgentboxd.signup(base_url=BASE, http_client=http)
        assert s.api_key == "mr_new"
        account = await s.client.account.get()
        assert account["claim"]["status"] == "unclaimed"
        assert api.requests[-1].headers["authorization"] == "Bearer mr_new"
        await s.client.account.request_claim("me@example.com")

    asyncio.run(run())


def test_event_types_include_signup() -> None:
    assert {"signup.created", "signup.claimed"} <= set(get_args(WebhookEventType))
