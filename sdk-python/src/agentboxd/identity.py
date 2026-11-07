"""Verify agent message signatures outside Agentboxd (https://agentboxd.com/docs/agent-messaging#verify-a-message-outside-agentboxd).

Each copy of an agent-to-agent message carries a JWS that Agentboxd made at delivery
(``message["agent"]["signature"]``): ES256, ``typ: agentboxd-msg+jwt``, bound to that copy's recipient, the
Message-ID and hashes of the content. Inside Agentboxd you don't need this (``message["agent"]["verified"]``
already says so); use it to prove a task's origin to your own backend, an auditor or another service::

    from agentboxd.identity import MemoryReplayCache, verify_agent_message

    replay_cache = MemoryReplayCache()
    result = verify_agent_message(message, recipient="billing-agent@homingbox.net", replay_cache=replay_cache)
    result["from"], result["assurance"], result["type"]

Needs the ``identity`` extra: ``pip install 'agentboxd[identity]'`` (PyJWT with cryptography, and rfc8785 for
RFC 8785 JSON canonicalization). A verified sender is not trustworthy content: treat the text and data as
untrusted input.
"""

import base64
import hashlib
import json
import re
import threading
import time
from collections.abc import Mapping, Sequence
from typing import Any, Literal, Optional, Protocol, TypedDict, Union, cast

import httpx

__all__ = [
    "AGENT_CLAIM",
    "AGENT_MESSAGE_TYP",
    "AUTHOR_JWS_TYP",
    "DEFAULT_AGENT_MESSAGE_MAX_AGE_SECONDS",
    "DEFAULT_IDENTITY_ISSUER",
    "KEY_PROOF_AUD",
    "KEY_PROOF_TYP",
    "MAILBOX_CLAIM",
    "MAX_IDENTITY_TOKEN_SECONDS",
    "RUNBOXD_CLAIM",
    "WORKSPACE_CLAIM",
    "AgentIdentityError",
    "AgentIdentityErrorCode",
    "AgentKeyPair",
    "AgentMessageVerificationError",
    "AgentWorkspace",
    "AuthorSignatureCoverage",
    "AuthorSignatureVerificationError",
    "MemoryReplayCache",
    "ReplayCache",
    "RevocationCheck",
    "RunboxdAllowance",
    "VerifiedAgentIdentity",
    "VerifiedAgentMessage",
    "VerifiedAuthorSignature",
    "averify_agent_identity_token",
    "averify_agent_message",
    "create_key_proof",
    "generate_agent_key",
    "jwk_thumbprint",
    "sign_agent_message",
    "verify_agent_identity_token",
    "verify_agent_message",
    "verify_author_signature",
]

DEFAULT_IDENTITY_ISSUER = "https://id.agentboxd.com"
AGENT_MESSAGE_TYP = "agentboxd-msg+jwt"
DEFAULT_AGENT_MESSAGE_MAX_AGE_SECONDS = 900
"""Default freshness window for ``task`` and ``event`` messages; plain messages have none by default."""
_REPLAY_WITHOUT_MAX_AGE_SECONDS = 86_400
"""With a replay cache and no freshness window, nonces are kept this long, and older signatures are refused
(``too_old``): once its nonce is forgotten, the same signature would verify again."""
_KEY_CACHE_SECONDS = 300.0
_KEY_REFETCH_COOLDOWN_SECONDS = 60.0
"""An unknown ``kid`` fetches the key set again at most once per URI in this window; inside it the cached set
answers, so a sender can't make every verification hit the network."""

AgentMessageErrorCode = Literal[
    "dependencies_missing",
    "no_signature",
    "invalid_signature",
    "unknown_key",
    "key_revoked",
    "wrong_issuer",
    "wrong_audience",
    "content_mismatch",
    "too_old",
    "issued_in_future",
    "replayed",
    "agent_revoked",
    "agent_suspended",
    "agent_deleted",
    "revocation_check_failed",
]


class RevocationCheck(TypedDict, total=False):
    """``check_revocation``: ask the directory whether the sender is still in good standing
    (``POST /v1/directory/verify``, uncached). ``api_key`` (required) needs ``directory:read``."""

    api_key: str
    base_url: str
    """Default https://api.agentboxd.com."""
    http_client: Any
    """An ``httpx.Client`` (sync) or ``httpx.AsyncClient`` (async) to use (tests, proxies)."""


class AgentMessageVerificationError(Exception):
    """Raised when an agent message signature does not verify. ``code`` says why."""

    def __init__(self, code: AgentMessageErrorCode, message: str) -> None:
        super().__init__(message)
        self.code: AgentMessageErrorCode = code


class ReplayCache(Protocol):
    """Remembers accepted nonces until they expire: ``use`` returns True the first time, False for a replay.

    Implement it on Redis or your database when you run more than one process
    (e.g. ``SET nonce 1 NX EXAT expires_at``). ``expires_at`` already includes the clock tolerance: keep the
    entry until then."""

    def use(self, nonce: str, expires_at: float) -> bool: ...


class MemoryReplayCache:
    """An in-process ReplayCache (one Python process). ``expires_at`` is in seconds since the epoch."""

    def __init__(self) -> None:
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def use(self, nonce: str, expires_at: float) -> bool:
        now = time.time()
        with self._lock:
            for key in [k for k, exp in self._seen.items() if exp < now]:
                del self._seen[key]
            if nonce in self._seen:
                return False
            self._seen[nonce] = expires_at
            return True

    def __len__(self) -> int:
        return len(self._seen)


VerifiedAgentMessage = TypedDict(
    "VerifiedAgentMessage",
    {
        # The sender, as Agentboxd verified it at delivery.
        "from": str,
        "recipient": str,
        "assurance": str,
        "type": str,
        "msg_id": str,
        "jti": str,
        "nonce": str,
        "kid": str,
        "iat": int,
        "claims": dict[str, Any],
    },
)


class _Default:
    pass


_DEFAULT = _Default()
MaxAge = Union[float, None, _Default]

_key_cache: dict[str, tuple[float, Mapping[str, Any]]] = {}
_key_fetched_at: dict[str, float] = {}  # last fetch attempt per URI, successful or not


def _deps() -> tuple[Any, Any]:
    try:
        import jwt
        import rfc8785
    except ImportError as err:  # pragma: no cover - exercised only without the extra
        raise AgentMessageVerificationError(
            "dependencies_missing",
            f"verify_agent_message needs the identity extra: pip install 'agentboxd[identity]' ({err})",
        ) from err
    return jwt, rfc8785


def _epoch(value: Any) -> Optional[float]:
    """Seconds since the epoch of an ISO time from a key set or a message; None when absent or unreadable."""
    if not isinstance(value, str) or not value:
        return None
    from datetime import datetime, timezone

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _bare(address: str) -> str:
    m = re.search(r"<([^<>]+)>\s*$", address)
    return (m.group(1) if m else address).strip().lower()


def _address_set(values: Sequence[str]) -> list[str]:
    return sorted({_bare(v) for v in values if v and _bare(v)})


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sha(value: Union[str, bytes]) -> str:
    return _b64u(hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).digest())


def _lf(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _content_mismatches(message: Mapping[str, Any], claims: Mapping[str, Any], rfc8785: Any) -> list[str]:
    bad: list[str] = []

    def hashed(value: Optional[str], claim: Optional[str], name: str, normalize: bool = False) -> None:
        expected = None if value is None else _sha(_lf(value) if normalize else value)
        if expected != claim:
            bad.append(name)

    if message.get("rfc_message_id") != claims.get("msg_id"):
        bad.append("msg_id")
    if _bare(str(message.get("from", ""))) != claims.get("from"):
        bad.append("from")
    if _address_set(message.get("to") or []) != list(claims.get("to") or []):
        bad.append("to")
    if _address_set(message.get("cc") or []) != list(claims.get("cc") or []):
        bad.append("cc")
    hashed(message.get("subject"), claims.get("subject_sha256"), "subject")
    hashed(message.get("text"), claims.get("text_sha256"), "text", normalize=True)
    hashed(message.get("html"), claims.get("html_sha256"), "html", normalize=True)
    data = message.get("data")
    expected_data = None if data is None else _sha(cast(bytes, rfc8785.dumps(data)))
    if expected_data != claims.get("data_sha256"):
        bad.append("data")
    att = sorted(_b64u(bytes.fromhex(str(a["sha256"]))) for a in message.get("attachments") or [])
    if att != list(claims.get("att") or []):
        bad.append("attachments")
    if (message.get("type") or "message") != claims.get("type"):
        bad.append("type")
    if message.get("in_reply_to") != claims.get("in_reply_to"):
        bad.append("in_reply_to")
    return bad


def _cached_keys(uri: str, fresh: bool) -> Optional[Mapping[str, Any]]:
    """The cached key set unless it is stale, or ``fresh`` asks again after the refetch cooldown."""
    hit = _key_cache.get(uri)
    now = time.time()
    if not hit or now - hit[0] >= _KEY_CACHE_SECONDS:
        return None
    if fresh and now - _key_fetched_at.get(uri, 0.0) >= _KEY_REFETCH_COOLDOWN_SECONDS:
        return None
    return hit[1]


def _key_set(uri: str, res: httpx.Response) -> Mapping[str, Any]:
    """The fetched key set, cached. A body that isn't one (an HTML error page served with 200, a changed
    format) raises ``unknown_key`` and isn't cached, so the next verification fetches again."""
    if res.status_code != 200:
        raise AgentMessageVerificationError("unknown_key", f"could not fetch {uri}: HTTP {res.status_code}")
    try:
        body = res.json()
    except ValueError:
        body = None
    if not isinstance(body, Mapping) or not isinstance(body.get("keys"), list):
        raise AgentMessageVerificationError("unknown_key", f"malformed key set at {uri}")
    keys = cast(Mapping[str, Any], body)
    _key_cache[uri] = (time.time(), keys)
    return keys


def _fetch_keys(uri: str, fresh: bool) -> Mapping[str, Any]:
    cached = _cached_keys(uri, fresh)
    if cached is not None:
        return cached
    _key_fetched_at[uri] = time.time()
    res = httpx.get(uri, headers={"Accept": "application/json"}, timeout=10)
    return _key_set(uri, res)


async def _afetch_keys(uri: str, fresh: bool) -> Mapping[str, Any]:
    cached = _cached_keys(uri, fresh)
    if cached is not None:
        return cached
    _key_fetched_at[uri] = time.time()
    async with httpx.AsyncClient(timeout=10) as http:
        res = await http.get(uri, headers={"Accept": "application/json"})
    return _key_set(uri, res)


def _find_key(keys: Mapping[str, Any], kid: str) -> Optional[Mapping[str, Any]]:
    for k in keys.get("keys") or []:
        if isinstance(k, Mapping) and k.get("kid") == kid:
            return k
    return None


def _signature_of(message: Mapping[str, Any], signature: Optional[str]) -> str:
    agent = message.get("agent")
    raw = (
        signature
        if signature is not None
        else (agent.get("signature") if isinstance(agent, Mapping) else None)
    )
    sig = re.sub(r"\s+", "", raw or "")
    if not sig:
        raise AgentMessageVerificationError(
            "no_signature", "the message carries no agent signature (not an agent-channel copy)"
        )
    return sig


def _header(jwt: Any, signature: str) -> dict[str, Any]:
    try:
        header = cast(dict[str, Any], jwt.get_unverified_header(signature))
    except Exception as err:
        raise AgentMessageVerificationError("invalid_signature", "not a compact JWS") from err
    if header.get("alg") != "ES256" or header.get("typ") != AGENT_MESSAGE_TYP or not header.get("kid"):
        raise AgentMessageVerificationError(
            "invalid_signature", f"expected alg ES256, typ {AGENT_MESSAGE_TYP} and a kid"
        )
    return header


def _check(
    jwt: Any,
    rfc8785: Any,
    message: Mapping[str, Any],
    signature: str,
    header: Mapping[str, Any],
    key: Optional[Mapping[str, Any]],
    *,
    where: str,
    recipient: str,
    issuer: str,
    max_age_seconds: MaxAge,
    replay: bool,
    clock_tolerance: float,
    now: Optional[float],
) -> tuple[VerifiedAgentMessage, float]:
    """Every check but the directory's and the nonce's. Returns the result and how long its nonce must be kept
    (``iat`` + the window + the clock tolerance) when ``replay``."""
    kid = str(header["kid"])
    if key is None:
        raise AgentMessageVerificationError("unknown_key", f"no agent signing key {kid} at {where}")
    jwk = {k: v for k, v in key.items() if k not in ("status", "revoked_at", "retired_at", "created_at")}
    try:
        public_key = jwt.PyJWK(jwk, algorithm="ES256").key
        payload = jwt.api_jws.decode(signature, key=public_key, algorithms=["ES256"])
        claims = cast(dict[str, Any], json.loads(payload))
    except Exception as err:
        raise AgentMessageVerificationError("invalid_signature", f"signature does not verify: {err}") from err
    iat = claims.get("iat")
    if (
        not isinstance(iat, int)
        or not isinstance(claims.get("nonce"), str)
        or not isinstance(claims.get("aud"), str)
    ):
        raise AgentMessageVerificationError("invalid_signature", "missing iat, nonce or aud")
    if key.get("status") == "revoked":
        # A revoked key without a (readable) revocation time counts as revoked from the start.
        revoked = _epoch(key.get("revoked_at"))
        if revoked is None:
            raise AgentMessageVerificationError("key_revoked", f"key {kid} is revoked (no revocation time)")
        if revoked <= iat:
            raise AgentMessageVerificationError(
                "key_revoked", f"key {kid} was revoked at {key.get('revoked_at')}, before this signature"
            )
    if claims.get("iss") != issuer:
        raise AgentMessageVerificationError(
            "wrong_issuer", f"issuer is {claims.get('iss')}, expected {issuer}"
        )
    if claims["aud"] != _bare(recipient):
        raise AgentMessageVerificationError(
            "wrong_audience", f"this copy was signed for {claims['aud']}, not {_bare(recipient)}"
        )
    bad = _content_mismatches(message, claims, rfc8785)
    agent_sig = claims.get("agent_sig")
    author = message.get("author")
    author_sig = author.get("signature") if isinstance(author, Mapping) else None
    author_jws = re.sub(r"\s+", "", author_sig) if isinstance(author_sig, str) else ""
    # aSIM phase 2: the delivery signature names the author signature it was made with. That one must be
    # there, unchanged: a copy without it (removed by a relay or an export) is refused like a different one.
    if isinstance(agent_sig, Mapping) and (not author_jws or agent_sig.get("jws_sha256") != _sha(author_jws)):
        bad.append("author")
    if bad:
        raise AgentMessageVerificationError(
            "content_mismatch", f"the message differs from what was signed: {', '.join(bad)}"
        )
    current = time.time() if now is None else now
    if iat > current + clock_tolerance:
        raise AgentMessageVerificationError("issued_in_future", "signature iat is in the future")
    if isinstance(max_age_seconds, _Default):
        freshness: Optional[float] = (
            None if claims.get("type") == "message" else DEFAULT_AGENT_MESSAGE_MAX_AGE_SECONDS
        )
    else:
        freshness = max_age_seconds
    # Replay protection lasts only as long as the nonce is remembered: with a replay cache, a signature older
    # than that is refused, or it would verify again once its nonce is forgotten.
    max_age = freshness if freshness is not None else (_REPLAY_WITHOUT_MAX_AGE_SECONDS if replay else None)
    if max_age is not None and current - iat > max_age + clock_tolerance:
        why = " (a replay_cache remembers nonces for a day)" if freshness is None else ""
        raise AgentMessageVerificationError(
            "too_old", f"signed {round(current - iat)} s ago; the limit is {max_age} s{why}"
        )
    keep_until = iat + (max_age if max_age is not None else _REPLAY_WITHOUT_MAX_AGE_SECONDS) + clock_tolerance
    result: VerifiedAgentMessage = {
        "from": str(claims.get("from")),
        "recipient": str(claims["aud"]),
        "assurance": str(claims.get("assurance")),
        "type": str(claims.get("type")),
        "msg_id": str(claims.get("msg_id")),
        "jti": str(claims.get("jti")),
        "nonce": str(claims["nonce"]),
        "kid": kid,
        "iat": iat,
        "claims": claims,
    }
    return result, keep_until


def _use_nonce(replay_cache: Optional[ReplayCache], result: VerifiedAgentMessage, keep_until: float) -> None:
    """Records the nonce. Called last, once every other check passed: burned before a check that failed (the
    directory couldn't be reached), it would turn every retry into ``replayed``."""
    if replay_cache is not None and not replay_cache.use(result["nonce"], keep_until):
        raise AgentMessageVerificationError(
            "replayed", "this signature was already accepted (nonce seen before)"
        )


def _revocation_request(
    check: Mapping[str, Any], signature: str
) -> tuple[str, dict[str, str], dict[str, str]]:
    api_key = check.get("api_key")
    if not isinstance(api_key, str) or not api_key:
        raise ValueError("check_revocation needs an api_key")
    base = str(check.get("base_url") or "https://api.agentboxd.com").rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    return f"{base}/v1/directory/verify", headers, {"signature": signature}


def _standing(res: Optional[httpx.Response], err: Optional[Exception]) -> None:
    if res is None:
        raise AgentMessageVerificationError(
            "revocation_check_failed", f"the directory could not be reached: {err}"
        ) from err
    try:
        body = res.json()
    except ValueError:
        body = {}
    if res.status_code != 200:
        code = (body.get("error") or {}).get("code", "error") if isinstance(body, dict) else "error"
        raise AgentMessageVerificationError(
            "revocation_check_failed", f"directory verify answered HTTP {res.status_code}: {code}"
        )
    status = body.get("status") if isinstance(body, dict) else None
    if status == "revoked":
        raise AgentMessageVerificationError(
            "agent_revoked", "the sender's aSIM is revoked now (directory verify)"
        )
    if status == "suspended":
        raise AgentMessageVerificationError(
            "agent_suspended", "the sender's aSIM is suspended now (directory verify)"
        )
    if status == "deleted":
        raise AgentMessageVerificationError(
            "agent_deleted", "the sender's aSIM is deleted now (directory verify)"
        )
    if status != "active":
        reasons = ", ".join(body.get("reasons") or []) if isinstance(body, dict) else ""
        raise AgentMessageVerificationError(
            "revocation_check_failed", f"the directory did not confirm the signature: {reasons or 'unknown'}"
        )


def _check_standing(check: Mapping[str, Any], signature: str) -> None:
    url, headers, body = _revocation_request(check, signature)
    http = check.get("http_client")
    try:
        res = (http.post if http is not None else httpx.post)(url, headers=headers, json=body, timeout=10)
    except httpx.HTTPError as err:
        _standing(None, err)
        return
    _standing(res, None)


async def _acheck_standing(check: Mapping[str, Any], signature: str) -> None:
    url, headers, body = _revocation_request(check, signature)
    http = check.get("http_client")
    try:
        if http is not None:
            res = await http.post(url, headers=headers, json=body, timeout=10)
        else:
            async with httpx.AsyncClient(timeout=10) as client:
                res = await client.post(url, headers=headers, json=body)
    except httpx.HTTPError as err:
        _standing(None, err)
        return
    _standing(res, None)


def verify_agent_message(
    message: Mapping[str, Any],
    *,
    recipient: str,
    issuer: str = DEFAULT_IDENTITY_ISSUER,
    signature: Optional[str] = None,
    keys: Optional[Mapping[str, Any]] = None,
    keys_uri: Optional[str] = None,
    max_age_seconds: MaxAge = _DEFAULT,
    replay_cache: Optional[ReplayCache] = None,
    clock_tolerance: float = 30,
    now: Optional[float] = None,
    check_revocation: Optional[RevocationCheck] = None,
) -> VerifiedAgentMessage:
    """Verify an agent message's delivery signature. Raises :class:`AgentMessageVerificationError`.

    Checks: ES256 against ``{issuer}/.well-known/agent-keys.json`` (or ``keys``; a key revoked at or before
    ``iat``, or revoked without a time, fails; an answer that isn't a key set fails with ``unknown_key`` and
    isn't cached), ``typ``, ``iss``, ``aud`` equals ``recipient`` (your address), the content hashes against
    ``message`` (an API message dict; when the signature names an author signature with ``agent_sig``,
    ``message["author"]["signature"]`` must be that one), freshness (``max_age_seconds``: 900 by default for
    ``task``/``event``, none for ``message``; ``None`` turns it off). With ``check_revocation`` the directory
    also confirms the sender is still active (codes ``agent_revoked``, ``agent_suspended``, ``agent_deleted``,
    ``revocation_check_failed``). Last, replay (``replay_cache``, keyed by ``nonce``, kept until ``iat`` + the
    window + ``clock_tolerance``): the nonce is recorded only after everything else passed, so a failed
    directory check can be retried. With a ``replay_cache`` and no window, signatures older than a day fail
    with ``too_old``: a nonce is remembered for a day. ``now`` (epoch seconds) is for tests.
    """
    jwt, rfc8785 = _deps()
    issuer = issuer.rstrip("/")
    sig = _signature_of(message, signature)
    header = _header(jwt, sig)
    uri = keys_uri or f"{issuer}/.well-known/agent-keys.json"
    key_set = keys if keys is not None else _fetch_keys(uri, False)
    key = _find_key(key_set, str(header["kid"]))
    if key is None and keys is None:
        key = _find_key(_fetch_keys(uri, True), str(header["kid"]))  # rotated since the last fetch
    result, keep_until = _check(
        jwt,
        rfc8785,
        message,
        sig,
        header,
        key,
        where="the given key set" if keys is not None else uri,
        recipient=recipient,
        issuer=issuer,
        max_age_seconds=max_age_seconds,
        replay=replay_cache is not None,
        clock_tolerance=clock_tolerance,
        now=now,
    )
    if check_revocation is not None:
        _check_standing(check_revocation, sig)
    _use_nonce(replay_cache, result, keep_until)
    return result


async def averify_agent_message(
    message: Mapping[str, Any],
    *,
    recipient: str,
    issuer: str = DEFAULT_IDENTITY_ISSUER,
    signature: Optional[str] = None,
    keys: Optional[Mapping[str, Any]] = None,
    keys_uri: Optional[str] = None,
    max_age_seconds: MaxAge = _DEFAULT,
    replay_cache: Optional[ReplayCache] = None,
    clock_tolerance: float = 30,
    now: Optional[float] = None,
    check_revocation: Optional[RevocationCheck] = None,
) -> VerifiedAgentMessage:
    """:func:`verify_agent_message` that fetches agent-keys.json without blocking the event loop."""
    jwt, rfc8785 = _deps()
    issuer = issuer.rstrip("/")
    sig = _signature_of(message, signature)
    header = _header(jwt, sig)
    uri = keys_uri or f"{issuer}/.well-known/agent-keys.json"
    key_set = keys if keys is not None else await _afetch_keys(uri, False)
    key = _find_key(key_set, str(header["kid"]))
    if key is None and keys is None:
        key = _find_key(await _afetch_keys(uri, True), str(header["kid"]))
    result, keep_until = _check(
        jwt,
        rfc8785,
        message,
        sig,
        header,
        key,
        where="the given key set" if keys is not None else uri,
        recipient=recipient,
        issuer=issuer,
        max_age_seconds=max_age_seconds,
        replay=replay_cache is not None,
        clock_tolerance=clock_tolerance,
        now=now,
    )
    if check_revocation is not None:
        await _acheck_standing(check_revocation, sig)
    _use_nonce(replay_cache, result, keep_until)
    return result


# ---------- aSIM phase 2: agent-held keys and author signatures ----------
# https://agentboxd.com/docs/agent-directory (docs/asim-phase2-contract.md §1). The agent keeps its private
# key; Agentboxd only ever sees the public JWK. An author signature proves who wrote a message, also to
# parties that don't trust Agentboxd; the delivery signature (verify_agent_message) proves who received
# which copy.

AUTHOR_JWS_TYP = "agentboxd-author+jwt"
KEY_PROOF_TYP = "agentboxd-key-proof+jwt"
KEY_PROOF_AUD = "agentboxd:agent-key"
AgentKeyAlg = Literal["EdDSA", "ES256"]
_AUTHOR_FUTURE_SKEW_SECONDS = 60
"""Agentboxd accepts an author signature whose ``iat`` is at most this far ahead of its own clock."""

AuthorErrorCode = Literal[
    "dependencies_missing",
    "no_signature",
    "malformed",
    "wrong_type",
    "unknown_key",
    "key_retired",
    "key_revoked",
    "issued_in_future",
    "bad_signature",
    "wrong_sender",
    "content_mismatch",
]


class AuthorSignatureVerificationError(Exception):
    """Raised when an author signature does not verify. ``code`` says why."""

    def __init__(self, code: AuthorErrorCode, message: str) -> None:
        super().__init__(message)
        self.code: AuthorErrorCode = code


class AgentKeyPair(TypedDict):
    """An agent-held key pair from :func:`generate_agent_key`. Keep ``private_key`` to yourself; register
    ``public_jwk`` (``client.agents.keys.register``)."""

    private_key: Any
    """A ``cryptography`` private key object (Ed25519 or P-256)."""
    public_jwk: dict[str, str]
    kid: str
    """The RFC 7638 thumbprint of ``public_jwk``: the key id Agentboxd uses."""
    alg: AgentKeyAlg


class AuthorSignatureCoverage(TypedDict):
    """Which parts of the message the author signature covers (text of a data-only message is Agentboxd's)."""

    subject: bool
    text: bool
    html: bool
    data: bool
    attachments: bool
    recipients: bool
    in_reply_to: bool


VerifiedAuthorSignature = TypedDict(
    "VerifiedAuthorSignature",
    {
        # The author, as the agent's own key signed it.
        "from": str,
        "kid": str,
        "alg": str,
        "iat": int,
        "covered": AuthorSignatureCoverage,
        "claims": dict[str, Any],
    },
)


def _author_deps() -> tuple[Any, Any]:
    try:
        return _deps()
    except AgentMessageVerificationError as err:  # pragma: no cover - exercised only without the extra
        raise AuthorSignatureVerificationError("dependencies_missing", str(err)) from err


def _key_members(jwk: Mapping[str, Any]) -> dict[str, str]:
    members = ("crv", "kty", "x") if jwk.get("kty") == "OKP" else ("crv", "kty", "x", "y")
    return {k: str(jwk[k]) for k in members}


def jwk_thumbprint(jwk: Mapping[str, Any]) -> str:
    """RFC 7638 thumbprint (SHA-256, base64url) of an Ed25519 (OKP) or P-256 (EC) public JWK."""
    return _sha(json.dumps(_key_members(jwk), separators=(",", ":"), sort_keys=True))


def _alg_of(jwk: Mapping[str, Any]) -> AgentKeyAlg:
    return "EdDSA" if jwk.get("kty") == "OKP" else "ES256"


def generate_agent_key(alg: AgentKeyAlg = "EdDSA") -> AgentKeyPair:
    """A fresh key pair made locally: Ed25519 (``EdDSA``, the default) or P-256 (``ES256``)."""
    _author_deps()
    from cryptography.hazmat.primitives.asymmetric import ec, ed25519
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    if alg == "EdDSA":
        ed_key = ed25519.Ed25519PrivateKey.generate()
        raw = ed_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        jwk = {"kty": "OKP", "crv": "Ed25519", "x": _b64u(raw)}
        return {"private_key": ed_key, "public_jwk": jwk, "kid": jwk_thumbprint(jwk), "alg": "EdDSA"}
    if alg != "ES256":
        raise ValueError("alg must be EdDSA or ES256")
    ec_key = ec.generate_private_key(ec.SECP256R1())
    nums = ec_key.public_key().public_numbers()
    jwk = {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64u(nums.x.to_bytes(32, "big")),
        "y": _b64u(nums.y.to_bytes(32, "big")),
    }
    return {"private_key": ec_key, "public_jwk": jwk, "kid": jwk_thumbprint(jwk), "alg": "ES256"}


def _sign(key: Mapping[str, Any], typ: str, claims: Mapping[str, Any]) -> str:
    jwt, _ = _author_deps()
    private_key = key["private_key"]
    alg = str(key["alg"])
    if isinstance(private_key, Mapping):
        private_key = jwt.PyJWK(dict(private_key), algorithm=alg).key
    payload = json.dumps(dict(claims), separators=(",", ":")).encode("utf-8")
    headers = {"kid": str(key["kid"]), "typ": typ}
    return cast(str, jwt.api_jws.encode(payload, private_key, algorithm=alg, headers=headers))


def _nonce(nonce: Optional[str]) -> str:
    import secrets

    return nonce if nonce is not None else secrets.token_urlsafe(16)


def create_key_proof(
    key: Mapping[str, Any], address: str, *, iat: Optional[int] = None, nonce: Optional[str] = None
) -> str:
    """The proof of possession for ``client.agents.keys.register``: a JWS by the new key, bound to the inbox
    ``address`` and the key's thumbprint, valid 5 minutes and once. ``key``: an :class:`AgentKeyPair`."""
    claims = {
        "aud": KEY_PROOF_AUD,
        "sub": address.strip().lower(),
        "jkt": str(key["kid"]),
        "iat": int(time.time()) if iat is None else iat,
        "nonce": _nonce(nonce),
    }
    return _sign(key, KEY_PROOF_TYP, claims)


Recipients = Union[str, Sequence[str]]


def _recipient_list(value: Optional[Recipients]) -> Optional[list[str]]:
    if value is None:
        return None
    return _address_set([value] if isinstance(value, str) else list(value))


def _attachment_digest(item: Any) -> str:
    """base64url SHA-256 of one attachment: hex ``sha256``, raw bytes, or an attachment dict."""
    if isinstance(item, (bytes, bytearray)):
        return _b64u(hashlib.sha256(bytes(item)).digest())
    if isinstance(item, str):
        return _b64u(bytes.fromhex(item))
    if isinstance(item, Mapping):
        if "sha256" in item:
            return _b64u(bytes.fromhex(str(item["sha256"])))
        if "content_base64" in item:
            return _b64u(hashlib.sha256(base64.b64decode(str(item["content_base64"]))).digest())
    raise ValueError("attachments must be sha256 hex strings, bytes, or dicts with sha256 / content_base64")


def sign_agent_message(
    key: Mapping[str, Any],
    *,
    from_: str,
    subject: Optional[str] = None,
    text: Optional[str] = None,
    html: Optional[str] = None,
    data: Any = None,
    attachments: Optional[Sequence[Any]] = None,
    type: str = "message",
    to: Optional[Recipients] = None,
    cc: Optional[Recipients] = None,
    in_reply_to: Optional[str] = None,
    iat: Optional[int] = None,
    nonce: Optional[str] = None,
) -> str:
    """An author signature (``agent_signature`` on ``messages.send`` / ``reply``) over exactly what you send.

    Pass the same ``text``, ``html``, ``data``, ``attachments`` and ``type`` you send (each is covered iff
    given). ``subject``, ``to``/``cc`` (the final header recipients) and ``in_reply_to`` are optional claims;
    give them on a send (a reply's subject and recipients are computed by Agentboxd). Given either of ``to``
    and ``cc``, both are signed, the one left out as none. Valid for 5 minutes, once.
    ``key``: an :class:`AgentKeyPair` whose public key is registered on the sending inbox."""
    _, rfc8785 = _author_deps()
    claims: dict[str, Any] = {
        "v": 1,
        "from": _bare(from_),
        "iat": int(time.time()) if iat is None else iat,
        "nonce": _nonce(nonce),
        "type": type,
        "att": sorted(_attachment_digest(a) for a in attachments or []),
    }
    if text is not None:
        claims["text_sha256"] = _sha(_lf(text))
    if html is not None:
        claims["html_sha256"] = _sha(_lf(html))
    if data is not None:
        claims["data_sha256"] = _sha(cast(bytes, rfc8785.dumps(data)))
    if subject is not None:
        claims["subject_sha256"] = _sha(subject)
    to_list = _recipient_list(to)
    cc_list = _recipient_list(cc)
    if to_list is not None or cc_list is not None:
        # One statement of who the message goes to: given either, both are signed ([] for the one left
        # out), as every verifier reads them.
        claims["to"] = to_list or []
        claims["cc"] = cc_list or []
    if in_reply_to:
        claims["in_reply_to"] = in_reply_to
    return _sign(key, AUTHOR_JWS_TYP, claims)


def _key_list(keys: Union[Mapping[str, Any], Sequence[Mapping[str, Any]]]) -> list[Mapping[str, Any]]:
    raw = (keys.get("keys") or []) if isinstance(keys, Mapping) else keys
    return [k for k in raw if isinstance(k, Mapping)]


def verify_author_signature(
    message: Mapping[str, Any],
    *,
    keys: Union[Mapping[str, Any], Sequence[Mapping[str, Any]]],
    signature: Optional[str] = None,
    clock_tolerance: float = 30,
    now: Optional[float] = None,
) -> VerifiedAuthorSignature:
    """Verify a message's author signature with the agent's own public keys. Raises
    :class:`AuthorSignatureVerificationError`.

    ``keys``: the agent's keys, e.g. ``card["keys"]["agent"]`` from ``directory.resolve`` or
    ``public_directory.keys(address)``. Checks the key, the signature, that it is from the message's sender,
    and every claimed hash against ``message`` (an API message dict). The result says what was ``covered``:
    the automatic text of a data-only message, for instance, is not.

    The signer picks ``iat``, so a stolen key could backdate it. A revoked key (compromised) fails when
    ``iat`` or the message's ``created_at`` (Agentboxd's time) is at or after ``revoked_at``, when the
    message has no ``created_at``, or when the key has no ``revoked_at``. A retired key (rotated) fails with
    ``key_retired`` when ``iat`` is at or after ``retired_at``: old signatures stay valid, also on a copy
    delivered after the rotation. An ``iat`` in the future (beyond ``clock_tolerance`` seconds), or more than
    60 s after ``created_at``, fails with ``issued_in_future``. Once ``to`` or ``cc`` is signed, both are
    checked, and the one left out means none. ``now`` (epoch seconds) is for tests."""
    jwt, rfc8785 = _author_deps()
    author = message.get("author")
    raw = (
        signature
        if signature is not None
        else (author.get("signature") if isinstance(author, Mapping) else None)
    )
    sig = re.sub(r"\s+", "", raw or "")
    if not sig:
        raise AuthorSignatureVerificationError("no_signature", "the message carries no author signature")
    try:
        header = cast(dict[str, Any], jwt.get_unverified_header(sig))
    except Exception as err:
        raise AuthorSignatureVerificationError("malformed", "not a compact JWS") from err
    alg = header.get("alg")
    kid = header.get("kid")
    if header.get("typ") != AUTHOR_JWS_TYP or alg not in ("EdDSA", "ES256") or not isinstance(kid, str):
        raise AuthorSignatureVerificationError(
            "wrong_type", f"expected typ {AUTHOR_JWS_TYP}, alg EdDSA or ES256 and a kid"
        )
    key = next((k for k in _key_list(keys) if k.get("kid") == kid), None)
    if key is None or _alg_of(key) != alg:
        raise AuthorSignatureVerificationError("unknown_key", f"no key {kid} among the agent's keys")
    try:
        public_key = jwt.PyJWK(_key_members(key), algorithm=alg).key
        claims = cast(dict[str, Any], json.loads(jwt.api_jws.decode(sig, key=public_key, algorithms=[alg])))
    except Exception as err:
        raise AuthorSignatureVerificationError("bad_signature", f"signature does not verify: {err}") from err
    iat = claims.get("iat")
    if claims.get("v") != 1 or not isinstance(iat, int) or isinstance(iat, bool):
        raise AuthorSignatureVerificationError("malformed", "missing v or iat")
    current = time.time() if now is None else now
    if iat > current + clock_tolerance:
        raise AuthorSignatureVerificationError("issued_in_future", "signature iat is in the future")
    # created_at is Agentboxd's clock, which the signer doesn't control. The server accepts an iat at most
    # 60 s ahead of it, and the signature existed before the message did.
    created_at = _epoch(message.get("created_at"))
    if created_at is not None and iat > created_at + _AUTHOR_FUTURE_SKEW_SECONDS + clock_tolerance:
        raise AuthorSignatureVerificationError(
            "issued_in_future", "signature iat is after the message was created"
        )
    if key.get("status") == "revoked":
        # Compromised. A revoked key without a (readable) revocation time counts as revoked from the start.
        # The signer picks iat and a stolen key can backdate it, so only the message's creation (Agentboxd's
        # clock) dates a signature before the revocation: without created_at a revoked key's signature fails,
        # and with it the later of iat and created_at must be before revoked_at (a later copy fails too).
        revoked = _epoch(key.get("revoked_at"))
        if revoked is None:
            raise AuthorSignatureVerificationError(
                "key_revoked", f"key {kid} is revoked (no revocation time)"
            )
        if created_at is None:
            raise AuthorSignatureVerificationError(
                "key_revoked",
                f"key {kid} is revoked, and the message has no created_at to date the signature by",
            )
        if revoked <= max(float(iat), created_at):
            raise AuthorSignatureVerificationError(
                "key_revoked",
                f"key {kid} was revoked at {key.get('revoked_at')}, before this signature or message",
            )
    if key.get("status") == "retired":
        # Rotated, not compromised: signatures made before retired_at stay valid, newer ones don't (Agentboxd
        # refuses them at send). Only iat counts here: a message sent before the rotation may be delivered
        # after it.
        retired = _epoch(key.get("retired_at"))
        if retired is not None and retired <= iat:
            raise AuthorSignatureVerificationError(
                "key_retired", f"key {kid} was retired at {key.get('retired_at')}, before this signature"
            )
    sender = _bare(str(message.get("from", "")))
    if claims.get("from") != sender:
        raise AuthorSignatureVerificationError(
            "wrong_sender", f"signed by {claims.get('from')}, but the message is from {sender}"
        )
    bad: list[str] = []
    if (message.get("type") or "message") != claims.get("type"):
        bad.append("type")
    att = sorted(_b64u(bytes.fromhex(str(a["sha256"]))) for a in message.get("attachments") or [])
    if att != sorted(claims.get("att") or []):
        bad.append("attachments")

    def covered_hash(name: str, value: Any, claim: str, normalize: bool = False) -> bool:
        if claim not in claims:
            return False
        if value is None or _sha(_lf(value) if normalize else value) != claims[claim]:
            bad.append(name)
        return True

    subject = covered_hash("subject", message.get("subject"), "subject_sha256")
    text = covered_hash("text", message.get("text"), "text_sha256", normalize=True)
    html = covered_hash("html", message.get("html"), "html_sha256", normalize=True)
    data = message.get("data")
    expected_data = None if data is None else _sha(cast(bytes, rfc8785.dumps(data)))
    # data is never changed by Agentboxd: present iff signed.
    if expected_data != claims.get("data_sha256"):
        bad.append("data")
    # to and cc together say who the message went to: once either is signed, both are checked, and the
    # one left out means none (as the TypeScript SDK and the server read it), so nothing can be added.
    recipients = "to" in claims or "cc" in claims
    if recipients:
        for field in ("to", "cc"):
            if _address_set(message.get(field) or []) != list(claims.get(field) or []):
                bad.append(field)
    in_reply_to = "in_reply_to" in claims
    if in_reply_to and message.get("in_reply_to") != claims["in_reply_to"]:
        bad.append("in_reply_to")
    if bad:
        raise AuthorSignatureVerificationError(
            "content_mismatch", f"the message differs from what the agent signed: {', '.join(bad)}"
        )
    return {
        "from": sender,
        "kid": kid,
        "alg": str(alg),
        "iat": iat,
        "covered": {
            "subject": subject,
            "text": text,
            "html": html,
            "data": "data_sha256" in claims,
            "attachments": True,
            "recipients": recipients,
            "in_reply_to": in_reply_to,
        },
        "claims": claims,
    }


# ---------- Sign in with Agentboxd: identity tokens (https://agentboxd.com/docs/agent-identity) ----------
# The Python counterpart of the TypeScript SDK's verifyAgentIdentityToken. Needs the identity extra for PyJWT.

MAX_IDENTITY_TOKEN_SECONDS = 300
AGENT_CLAIM = "https://agentboxd.com/claims/agent"
MAILBOX_CLAIM = "https://agentboxd.com/claims/mailbox"
WORKSPACE_CLAIM = "https://agentboxd.com/claims/workspace"
RUNBOXD_CLAIM = "https://agentboxd.com/claims/runboxd"

AgentIdentityErrorCode = Literal[
    "dependencies_missing",
    "invalid_token",
    "token_expired",
    "nonce_mismatch",
    "not_agent",
    "token_replayed",
]


class AgentIdentityError(Exception):
    """Raised when an identity token does not verify. ``code`` says why."""

    def __init__(self, code: AgentIdentityErrorCode, message: str) -> None:
        super().__init__(message)
        self.code: AgentIdentityErrorCode = code


class AgentWorkspace(TypedDict):
    """The workspace claim: scope ``workspace`` when the workspace shares its name, or first-party apps."""

    id: str
    name: str


class RunboxdAllowance(TypedDict):
    """The Runboxd claim: on tokens for first-party apps only. ``None`` means unlimited."""

    v: int
    workspace: str
    plan: str
    computers: Optional[int]
    computer_hours: Optional[int]
    memory_mb: Optional[int]
    vcpus: Optional[int]


class VerifiedAgentIdentity(TypedDict):
    """What ``verify_agent_identity_token`` returns. Key your user record on ``sub``."""

    sub: str
    email: Optional[str]
    """The inbox address (scope ``email``), else None. Always None for an identity without a mailbox."""
    email_verified: bool
    name: Optional[str]
    username: Optional[str]
    is_agent: bool
    mailbox: bool
    """False for an identity without a mailbox."""
    workspace: Optional[AgentWorkspace]
    runboxd: Optional[RunboxdAllowance]
    jti: str
    issuer: str
    audience: str
    issued_at: int
    expires_at: int
    claims: dict[str, Any]


def _identity_jwt() -> Any:
    try:
        import jwt
    except ImportError as err:  # pragma: no cover - exercised only without the extra
        raise AgentIdentityError(
            "dependencies_missing",
            "verify_agent_identity_token needs the identity extra: "
            f"pip install 'agentboxd[identity]' ({err})",
        ) from err
    return jwt


def _identity_header(jwt: Any, token: str) -> str:
    try:
        header = jwt.get_unverified_header(token)
    except Exception as err:
        raise AgentIdentityError("invalid_token", f"invalid identity token: {err}") from err
    if header.get("alg") != "ES256":
        raise AgentIdentityError("invalid_token", "identity tokens are ES256")
    if header.get("typ") not in (None, "JWT"):
        raise AgentIdentityError("invalid_token", f"unexpected token type {header.get('typ')}")
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise AgentIdentityError("invalid_token", "identity token has no kid")
    return kid


def _identity_result(
    jwt: Any,
    token: str,
    key: Optional[Mapping[str, Any]],
    *,
    kid: str,
    audience: str,
    issuer: str,
    nonce: Optional[str],
    replay_cache: Optional[ReplayCache],
    clock_tolerance: float,
    require_agent: bool,
    now: Optional[float],
) -> VerifiedAgentIdentity:
    if key is None:
        raise AgentIdentityError("invalid_token", f"no signing key {kid} in the issuer's JWKS")
    try:
        public_key = jwt.PyJWK(dict(key), algorithm="ES256").key
        claims = cast(
            dict[str, Any],
            jwt.decode(
                token,
                key=public_key,
                algorithms=["ES256"],
                audience=audience,
                issuer=issuer,
                leeway=clock_tolerance,
                options={"require": ["iss", "sub", "aud", "iat", "exp", "jti"]},
            ),
        )
    except jwt.ExpiredSignatureError as err:
        raise AgentIdentityError("token_expired", "identity token expired") from err
    except Exception as err:
        raise AgentIdentityError("invalid_token", f"invalid identity token: {err}") from err
    current = time.time() if now is None else now
    iat, exp = claims["iat"], claims["exp"]
    if not isinstance(iat, (int, float)) or not isinstance(exp, (int, float)):
        raise AgentIdentityError("invalid_token", "identity token iat and exp must be numbers")
    if iat > current + clock_tolerance:
        raise AgentIdentityError("invalid_token", "identity token iat is in the future")
    if exp - iat > MAX_IDENTITY_TOKEN_SECONDS:
        raise AgentIdentityError(
            "invalid_token", f"identity token lives longer than {MAX_IDENTITY_TOKEN_SECONDS} s"
        )
    if nonce is not None and claims.get("nonce") != nonce:
        raise AgentIdentityError("nonce_mismatch", "identity token nonce does not match")
    is_agent = claims.get(AGENT_CLAIM) is True
    if require_agent and not is_agent:
        raise AgentIdentityError("not_agent", "identity token is not an agent identity")
    # PyJWT accepts the token until exp + leeway, so the jti is kept that long too: until exp alone, a
    # captured token would verify again in the last ``clock_tolerance`` seconds.
    if replay_cache is not None and not replay_cache.use(str(claims["jti"]), float(exp) + clock_tolerance):
        raise AgentIdentityError("token_replayed", "identity token was already used")
    ws = claims.get(WORKSPACE_CLAIM)
    workspace: Optional[AgentWorkspace] = (
        {"id": ws["id"], "name": ws["name"]}
        if isinstance(ws, Mapping) and isinstance(ws.get("id"), str) and isinstance(ws.get("name"), str)
        else None
    )
    rb = claims.get(RUNBOXD_CLAIM)
    runboxd = cast(
        Optional[RunboxdAllowance], dict(rb) if isinstance(rb, Mapping) and rb.get("v") == 1 else None
    )
    return {
        "sub": str(claims["sub"]),
        "email": claims["email"] if isinstance(claims.get("email"), str) else None,
        "email_verified": claims.get("email_verified") is True,
        "name": claims["name"] if isinstance(claims.get("name"), str) else None,
        "username": claims["preferred_username"]
        if isinstance(claims.get("preferred_username"), str)
        else None,
        "is_agent": is_agent,
        "mailbox": claims.get(MAILBOX_CLAIM) is not False,
        "workspace": workspace,
        "runboxd": runboxd,
        "jti": str(claims["jti"]),
        "issuer": str(claims["iss"]),
        "audience": audience,
        "issued_at": int(iat),
        "expires_at": int(exp),
        "claims": claims,
    }


def _identity_keys(uri: str, fresh: bool) -> Mapping[str, Any]:
    try:
        return _fetch_keys(uri, fresh)
    except (AgentMessageVerificationError, httpx.HTTPError) as err:
        raise AgentIdentityError("invalid_token", f"could not fetch the issuer's keys: {err}") from err


async def _aidentity_keys(uri: str, fresh: bool) -> Mapping[str, Any]:
    try:
        return await _afetch_keys(uri, fresh)
    except (AgentMessageVerificationError, httpx.HTTPError) as err:
        raise AgentIdentityError("invalid_token", f"could not fetch the issuer's keys: {err}") from err


def verify_agent_identity_token(
    token: str,
    *,
    audience: str,
    issuer: str = DEFAULT_IDENTITY_ISSUER,
    nonce: Optional[str] = None,
    replay_cache: Optional[ReplayCache] = None,
    clock_tolerance: float = 30,
    require_agent: bool = True,
    jwks_uri: Optional[str] = None,
    jwks: Optional[Mapping[str, Any]] = None,
    now: Optional[float] = None,
) -> VerifiedAgentIdentity:
    """Verify an Agentboxd identity token ("Sign in with Agentboxd").

    Checks the ES256 signature against the issuer's JWKS (fetched again for an unknown ``kid``, after a key
    rotation, at most once a minute), ``iss``, ``aud`` (your ``client_id``), ``exp`` and ``iat`` with
    ``clock_tolerance`` seconds and at most 300 s of lifetime, ``nonce`` when given, the agent claim, and
    single use through ``replay_cache``::

        from agentboxd.identity import MemoryReplayCache, verify_agent_identity_token

        replay_cache = MemoryReplayCache()  # several processes: implement ReplayCache on Redis
        agent = verify_agent_identity_token(
            id_token, audience="abxc_...", nonce=nonce, replay_cache=replay_cache
        )
        agent["sub"], agent["email"], agent["workspace"]

    Pass a ``replay_cache`` unless you exchange the token at the issuer's ``/token`` (JWT bearer grant), which
    enforces single use there. Raises ``AgentIdentityError``. Needs ``pip install 'agentboxd[identity]'``.
    """
    if not audience:
        raise TypeError("verify_agent_identity_token: audience (your client_id) is required")
    jwt = _identity_jwt()
    iss = issuer.rstrip("/")
    kid = _identity_header(jwt, token)
    if jwks is not None:
        key = _find_key(jwks, kid)
    else:
        uri = jwks_uri or f"{iss}/.well-known/jwks.json"
        key = _find_key(_identity_keys(uri, False), kid) or _find_key(_identity_keys(uri, True), kid)
    return _identity_result(
        jwt,
        token,
        key,
        kid=kid,
        audience=audience,
        issuer=iss,
        nonce=nonce,
        replay_cache=replay_cache,
        clock_tolerance=clock_tolerance,
        require_agent=require_agent,
        now=now,
    )


async def averify_agent_identity_token(
    token: str,
    *,
    audience: str,
    issuer: str = DEFAULT_IDENTITY_ISSUER,
    nonce: Optional[str] = None,
    replay_cache: Optional[ReplayCache] = None,
    clock_tolerance: float = 30,
    require_agent: bool = True,
    jwks_uri: Optional[str] = None,
    jwks: Optional[Mapping[str, Any]] = None,
    now: Optional[float] = None,
) -> VerifiedAgentIdentity:
    """The async form of ``verify_agent_identity_token`` (fetches the key set with ``httpx.AsyncClient``)."""
    if not audience:
        raise TypeError("averify_agent_identity_token: audience (your client_id) is required")
    jwt = _identity_jwt()
    iss = issuer.rstrip("/")
    kid = _identity_header(jwt, token)
    if jwks is not None:
        key = _find_key(jwks, kid)
    else:
        uri = jwks_uri or f"{iss}/.well-known/jwks.json"
        key = _find_key(await _aidentity_keys(uri, False), kid) or _find_key(
            await _aidentity_keys(uri, True), kid
        )
    return _identity_result(
        jwt,
        token,
        key,
        kid=kid,
        audience=audience,
        issuer=iss,
        nonce=nonce,
        replay_cache=replay_cache,
        clock_tolerance=clock_tolerance,
        require_agent=require_agent,
        now=now,
    )
