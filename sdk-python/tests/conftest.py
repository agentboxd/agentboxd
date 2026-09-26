import json
from typing import Any, Callable, Optional, Union

import httpx
import pytest

from agentboxd import Agentboxd, AsyncAgentboxd

BASE = "http://agentboxd.test"
KEY = "mr_test_key"

Responder = Callable[[httpx.Request], httpx.Response]


class Recorder:
    """Records every request and replies with queued responses (or a default)."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.queue: list[Union[httpx.Response, Responder]] = []
        self.default: Any = {}

    def reply(self, body: Any = None, status: int = 200) -> None:
        if status == 204:
            self.queue.append(httpx.Response(204))
        else:
            self.queue.append(httpx.Response(status, json=body if body is not None else {}))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.queue:
            item = self.queue.pop(0)
            return item(request) if callable(item) else item
        return httpx.Response(200, json=self.default)

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    def last_json(self) -> Any:
        return json.loads(self.last.content)

    def last_params(self) -> dict[str, str]:
        return dict(self.last.url.params)


@pytest.fixture
def rec() -> Recorder:
    return Recorder()


@pytest.fixture
def client(rec: Recorder) -> Agentboxd:
    http = httpx.Client(transport=httpx.MockTransport(rec))
    return Agentboxd(api_key=KEY, base_url=BASE + "/", http_client=http)


def make_async(rec: Recorder, api_key: Optional[str] = KEY) -> AsyncAgentboxd:
    http = httpx.AsyncClient(transport=httpx.MockTransport(rec))
    return AsyncAgentboxd(api_key=api_key, base_url=BASE, http_client=http)
