"""reply_to on send, reply and forward (the Reply-To header), sync and async."""

import asyncio
import json

from agentboxd import Agentboxd

from .conftest import Recorder, make_async


def test_send_reply_and_forward_carry_reply_to(client: Agentboxd, rec: Recorder) -> None:
    rec.default = {"id": "m1"}
    client.messages.send(
        "i1", to="hello@acme.example", subject="Enquiry", text="Hi", reply_to="Visitor <v@example.com>"
    )
    assert rec.last_json() == {
        "to": "hello@acme.example",
        "subject": "Enquiry",
        "text": "Hi",
        "reply_to": "Visitor <v@example.com>",
    }
    client.messages.reply("i1", "m0", text="Yes", reply_to="billing@example.com")
    assert rec.last_json() == {"text": "Yes", "reply_to": "billing@example.com"}
    client.messages.forward("i1", "m0", to="lee@example.com", reply_to="desk@example.com")
    assert rec.last_json() == {"to": "lee@example.com", "reply_to": "desk@example.com"}


def test_reply_to_is_left_out_when_not_given(client: Agentboxd, rec: Recorder) -> None:
    rec.default = {"id": "m1"}
    client.messages.send("i1", to="b@example.com", subject="Plain", text="hi")
    assert "reply_to" not in rec.last_json()


def test_async_send_carries_reply_to(rec: Recorder) -> None:
    rec.default = {"id": "m1"}

    async def go() -> None:
        async with make_async(rec) as c:
            await c.messages.send("i1", to="b@example.com", subject="S", text="t", reply_to="v@example.com")
            await c.messages.reply("i1", "m0", text="t", reply_to="w@example.com")
            await c.messages.forward("i1", "m0", to="lee@example.com", reply_to="x@example.com")

    asyncio.run(go())
    sent = [json.loads(req.content)["reply_to"] for req in rec.requests[-3:]]
    assert sent == ["v@example.com", "w@example.com", "x@example.com"]
