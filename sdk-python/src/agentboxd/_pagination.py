from collections.abc import AsyncIterator, Awaitable, Iterator
from typing import Any, Callable, Optional, TypeVar

from ._types import Page

__all__ = ["aiter_all", "iter_all"]

_T = TypeVar("_T")


def iter_all(list_fn: Callable[..., Page[_T]], *args: Any, **kwargs: Any) -> Iterator[_T]:
    """Yield every item of a cursor-paginated list, fetching pages lazily.

    >>> for msg in iter_all(mr.messages.list, inbox["id"], is_read=False):
    ...     print(msg["subject"])
    """
    cursor: Optional[str] = kwargs.pop("cursor", None)
    while True:
        page = list_fn(*args, cursor=cursor, **kwargs)
        yield from page["data"]
        cursor = page.get("next_cursor")
        if not cursor:
            return


async def aiter_all(
    list_fn: Callable[..., Awaitable[Page[_T]]], *args: Any, **kwargs: Any
) -> AsyncIterator[_T]:
    """Async version of :func:`iter_all` for :class:`AsyncAgentboxd` list methods."""
    cursor: Optional[str] = kwargs.pop("cursor", None)
    while True:
        page = await list_fn(*args, cursor=cursor, **kwargs)
        for item in page["data"]:
            yield item
        cursor = page.get("next_cursor")
        if not cursor:
            return
