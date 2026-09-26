from typing import Any, Optional

__all__ = [
    "APIConnectionError",
    "AgentboxdError",
    "AuthenticationError",
    "BadRequestError",
    "InternalServerError",
    "MailroomError",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimitError",
    "UnprocessableEntityError",
]


class AgentboxdError(Exception):
    """Raised for every non-2xx API response.

    ``status`` is the HTTP status, ``code`` the API's machine-readable error code
    (e.g. ``recipient_suppressed``) and ``message`` the human-readable message. ``details`` is the
    error's ``details`` object when the server sent one, and ``retry_after`` the seconds to wait
    before retrying a 429 (``Retry-After`` header, else ``details.retry_after_seconds``).
    """

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: Any = None,
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        self.retry_after = retry_after

    def __repr__(self) -> str:
        return f"{type(self).__name__}(status={self.status!r}, code={self.code!r}, message={self.message!r})"

    def __str__(self) -> str:
        return f"[{self.status} {self.code}] {self.message}"


MailroomError = AgentboxdError
"""Deprecated alias of :class:`AgentboxdError` (the same class; kept for backward compatibility)."""


class BadRequestError(AgentboxdError):
    """400."""


class AuthenticationError(AgentboxdError):
    """401: missing or invalid API key."""


class PermissionDeniedError(AgentboxdError):
    """403."""


class NotFoundError(AgentboxdError):
    """404."""


class UnprocessableEntityError(AgentboxdError):
    """422, e.g. ``recipient_suppressed``."""


class RateLimitError(AgentboxdError):
    """429: ``rate_limited`` (request rate, or the workspace burst limit ``sends_per_5min``) or a
    daily send cap. ``retry_after`` says how many seconds to wait."""


class InternalServerError(AgentboxdError):
    """5xx."""


class APIConnectionError(AgentboxdError):
    """The request never got an HTTP response (network error or timeout). ``status`` is 0."""

    def __init__(self, message: str, code: str = "connection_error") -> None:
        super().__init__(0, code, message)


_BY_STATUS: dict[int, type[AgentboxdError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    422: UnprocessableEntityError,
    429: RateLimitError,
}


def error_for_status(
    status: int,
    code: Optional[str],
    message: Optional[str],
    details: Any = None,
    retry_after: Optional[float] = None,
) -> AgentboxdError:
    cls = _BY_STATUS.get(status) or (InternalServerError if status >= 500 else AgentboxdError)
    return cls(status, code or "http_error", message or f"HTTP {status}", details, retry_after)
