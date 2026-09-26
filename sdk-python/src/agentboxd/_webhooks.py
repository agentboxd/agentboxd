"""Webhook signature verification, byte-for-byte compatible with the Agentboxd server.

Signature = hex(HMAC-SHA256(secret, f"{timestamp}.{raw_body}")), sent in ``X-Mailroom-Signature``
alongside the unix-seconds ``X-Mailroom-Timestamp`` (header names kept from the original API).
"""

import hashlib
import hmac
import re
import time
from typing import Optional, Union

__all__ = ["SIGNATURE_HEADER", "TIMESTAMP_HEADER", "compute_signature", "verify_webhook"]

SIGNATURE_HEADER = "X-Mailroom-Signature"
TIMESTAMP_HEADER = "X-Mailroom-Timestamp"

_TIMESTAMP_RE = re.compile(r"[0-9]+")
_SIGNATURE_RE = re.compile(r"[0-9a-fA-F]{64}")


def _to_bytes(value: Union[str, bytes, bytearray, memoryview]) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    raise TypeError(f"expected str or bytes, got {type(value).__name__}")


def compute_signature(
    timestamp: str, body: Union[str, bytes, bytearray, memoryview], secret: Union[str, bytes]
) -> str:
    """Return the hex signature the server would send for ``body`` at ``timestamp``."""
    mac = hmac.new(_to_bytes(secret), digestmod=hashlib.sha256)
    mac.update(timestamp.encode("ascii") + b".")
    mac.update(_to_bytes(body))
    return mac.hexdigest()


def verify_webhook(
    signature: Optional[str],
    timestamp: Optional[str],
    body: Union[str, bytes, bytearray, memoryview],
    secret: Union[str, bytes],
    tolerance_seconds: float = 300,
    *,
    now: Optional[float] = None,
) -> bool:
    """Verify a webhook delivery. Never raises on malformed input; returns ``False`` instead.

    Pass the **raw** request body exactly as received (not re-serialized JSON) and the
    ``X-Mailroom-Signature`` / ``X-Mailroom-Timestamp`` header values. Timestamps further than
    ``tolerance_seconds`` from ``now`` (default: current time) are rejected to limit replays;
    pass ``tolerance_seconds=0`` to skip the freshness check.
    """
    try:
        if not isinstance(signature, str) or not isinstance(timestamp, str):
            return False
        if not _TIMESTAMP_RE.fullmatch(timestamp) or not _SIGNATURE_RE.fullmatch(signature):
            return False
        if tolerance_seconds > 0:
            current = time.time() if now is None else now
            if abs(current - int(timestamp)) > tolerance_seconds:
                return False
        expected = compute_signature(timestamp, body, secret)
        return hmac.compare_digest(expected, signature.lower())
    except (TypeError, ValueError, UnicodeError):
        return False
