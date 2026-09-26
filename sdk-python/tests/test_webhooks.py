import hashlib
import hmac
import time
from typing import Any

import pytest

from agentboxd import SIGNATURE_HEADER, TIMESTAMP_HEADER, compute_signature, verify_webhook

SECRET = "whsec_test_secret_value_1234567890"
TIMESTAMP = "1790246400"
BODY = '{"id":"evt_1","type":"message.received","data":{"hello":"wörld"}}'
# Computed with the TypeScript server's signWebhook (node:crypto createHmac, utf8 input):
TS_SIGNATURE = "22b4e097d4864cd7bf7493f4c9c0f5aa442f4c24818227c2f2e99cd476cf5298"
NOW = float(TIMESTAMP) + 10


def _expected() -> str:
    msg = f"{TIMESTAMP}.{BODY}".encode()
    return hmac.new(SECRET.encode(), msg, hashlib.sha256).hexdigest()


def test_vector_matches_python_hmac_and_ts_server() -> None:
    sig = compute_signature(TIMESTAMP, BODY, SECRET)
    assert sig == _expected() == TS_SIGNATURE
    assert len(sig) == 64 and all(c in "0123456789abcdef" for c in sig)
    # str and bytes bodies sign identically (UTF-8).
    assert compute_signature(TIMESTAMP, BODY.encode("utf-8"), SECRET) == sig


def test_headers() -> None:
    assert SIGNATURE_HEADER == "X-Mailroom-Signature"
    assert TIMESTAMP_HEADER == "X-Mailroom-Timestamp"


@pytest.mark.parametrize("body", [BODY, BODY.encode("utf-8"), bytearray(BODY.encode("utf-8"))])
def test_valid(body: Any) -> None:
    assert verify_webhook(TS_SIGNATURE, TIMESTAMP, body, SECRET, now=NOW)


def test_uppercase_hex_accepted() -> None:
    assert verify_webhook(TS_SIGNATURE.upper(), TIMESTAMP, BODY, SECRET, now=NOW)


def test_current_time_default() -> None:
    ts = str(int(time.time()))
    sig = compute_signature(ts, BODY, SECRET)
    assert verify_webhook(sig, ts, BODY, SECRET)


def test_tampered_body() -> None:
    assert not verify_webhook(TS_SIGNATURE, TIMESTAMP, BODY.replace("wörld", "world"), SECRET, now=NOW)
    assert not verify_webhook(TS_SIGNATURE, TIMESTAMP, BODY + " ", SECRET, now=NOW)


def test_wrong_secret() -> None:
    assert not verify_webhook(TS_SIGNATURE, TIMESTAMP, BODY, SECRET + "x", now=NOW)


def test_tampered_timestamp() -> None:
    assert not verify_webhook(TS_SIGNATURE, str(int(TIMESTAMP) + 1), BODY, SECRET, now=NOW)


def test_stale_and_future_timestamps() -> None:
    assert not verify_webhook(TS_SIGNATURE, TIMESTAMP, BODY, SECRET, now=float(TIMESTAMP) + 301)
    assert not verify_webhook(TS_SIGNATURE, TIMESTAMP, BODY, SECRET, now=float(TIMESTAMP) - 301)
    assert verify_webhook(TS_SIGNATURE, TIMESTAMP, BODY, SECRET, now=float(TIMESTAMP) + 300)
    # Real clock: the 2026 vector is stale unless the window is wide enough / disabled.
    assert verify_webhook(TS_SIGNATURE, TIMESTAMP, BODY, SECRET, tolerance_seconds=0)
    assert not verify_webhook(TS_SIGNATURE, TIMESTAMP, BODY, SECRET, tolerance_seconds=5, now=NOW + 60)


@pytest.mark.parametrize(
    ("signature", "timestamp"),
    [
        ("", TIMESTAMP),
        (TS_SIGNATURE[:-1], TIMESTAMP),
        (TS_SIGNATURE + "0", TIMESTAMP),
        ("z" * 64, TIMESTAMP),
        ("sha256=" + TS_SIGNATURE, TIMESTAMP),
        (TS_SIGNATURE, ""),
        (TS_SIGNATURE, "-1790246400"),
        (TS_SIGNATURE, "1790246400.5"),
        (TS_SIGNATURE, " 1790246400"),
        (
            TS_SIGNATURE,
            "".join(chr(0xFF10 + int(d)) for d in TIMESTAMP),
        ),  # full-width digits: \d would match, the server rejects
        (None, TIMESTAMP),
        (TS_SIGNATURE, None),
    ],
)
def test_malformed_input_returns_false(signature: Any, timestamp: Any) -> None:
    assert verify_webhook(signature, timestamp, BODY, SECRET, tolerance_seconds=0) is False


def test_non_text_arguments_do_not_raise() -> None:
    assert verify_webhook(123, TIMESTAMP, BODY, SECRET) is False  # type: ignore[arg-type]
    assert verify_webhook(TS_SIGNATURE, TIMESTAMP, 42, SECRET, tolerance_seconds=0) is False  # type: ignore[arg-type]
    assert verify_webhook(TS_SIGNATURE, TIMESTAMP, BODY, None, tolerance_seconds=0) is False  # type: ignore[arg-type]
