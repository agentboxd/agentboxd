"""Wave 3 quick wins: inbox pause/resume, DKIM rotation, deliverability."""

import asyncio

from agentboxd import Agentboxd

from .conftest import Recorder, make_async


def test_pause_and_resume(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"id": "i_1", "status": "paused", "paused_reason": "loop"})
    inbox = client.inboxes.pause("i_1", reason="loop")
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/inboxes/i_1/pause")
    assert rec.last_json() == {"reason": "loop"}
    assert inbox["status"] == "paused"

    client.inboxes.pause("i_1")
    assert rec.last_json() == {}

    rec.reply({"id": "i_1", "status": "active", "released_events": 2})
    resumed = client.inboxes.resume("i_1")
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/inboxes/i_1/resume")
    assert resumed["released_events"] == 2


def test_async_pause_and_resume() -> None:
    rec = Recorder()
    client = make_async(rec)

    async def run() -> None:
        await client.inboxes.pause("i_1", reason="x")
        assert rec.last_json() == {"reason": "x"}
        await client.inboxes.resume("i_1")
        assert rec.last.url.path == "/v1/inboxes/i_1/resume"
        await client.close()

    asyncio.run(run())


def test_dkim_rotation(client: Agentboxd, rec: Recorder) -> None:
    client.domains.rotate_dkim("d_1")
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/domains/d_1/dkim/rotate")
    client.domains.activate_dkim("d_1")
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/domains/d_1/dkim/activate")


def test_deliverability(client: Agentboxd, rec: Recorder) -> None:
    client.deliverability()
    assert (rec.last.method, rec.last.url.path) == ("GET", "/v1/deliverability")
