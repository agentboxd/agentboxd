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
    "AGENT_MESSAGE_TYP",
    "AUTHOR_JWS_TYP",
    "DEFAULT_AGENT_MESSAGE_MAX_AGE_SECONDS",
    "DEFAULT_IDENTITY_ISSUER",
    "KEY_PROOF_AUD",
    "KEY_PROOF_TYP",
    "AgentKeyPair",
    "AgentMessageVerificationError",
    "AuthorSignatureCoverage",
    "AuthorSignatureVerificationError",
    "MemoryReplayCache",
    "ReplayCache",
    "RevocationCheck",
    "VerifiedAgentMessage",
    "VerifiedAuthorSignature",
    "averify_agent_message",
    "create_key_proof",
    "generate_agent_key",
    "jwk_thumbprint",
    "sign_agent_message",
    "verify_agent_message",
    "verify_author_signature",
]

DEFAULT_IDENTITY_ISSUER = "https://id.agentboxd.com"
AGENT_MESSAGE_TYP = "agentboxd-msg+jwt"
DEFAULT_AGENT_MESSAGE_MAX_AGE_SECONDS = 900
"""Default freshness window for ``task`` and ``event`` messages; plain messages have none by default."""
_REPLAY_WITHOUT_MAX_AGE_SECONDS = 86_400
_KEY_CACHE_SECONDS = 300.0

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
    (e.g. ``SET nonce 1 NX EXAT expires_at``)."""

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


def _fetch_keys(uri: str, fresh: bool) -> Mapping[str, Any]:
    hit = _key_cache.get(uri)
    if hit and not fresh and time.time() - hit[0] < _KEY_CACHE_SECONDS:
        return hit[1]
    res = httpx.get(uri, headers={"Accept": "application/json"}, timeout=10)
    if res.status_code != 200:
        raise AgentMessageVerificationError("unknown_key", f"could not fetch {uri}: HTTP {res.status_code}")
    keys = cast(Mapping[str, Any], res.json())
    _key_cache[uri] = (time.time(), keys)
    return keys


async def _afetch_keys(uri: str, fresh: bool) -> Mapping[str, Any]:
    hit = _key_cache.get(uri)
    if hit and not fresh and time.time() - hit[0] < _KEY_CACHE_SECONDS:
        return hit[1]
    async with httpx.AsyncClient(timeout=10) as http:
        res = await http.get(uri, headers={"Accept": "application/json"})
    if res.status_code != 200:
        raise AgentMessageVerificationError("unknown_key", f"could not fetch {uri}: HTTP {res.status_code}")
    keys = cast(Mapping[str, Any], res.json())
    _key_cache[uri] = (time.time(), keys)
    return keys


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
    replay_cache: Optional[ReplayCache],
    clock_tolerance: float,
    now: Optional[float],
) -> VerifiedAgentMessage:
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
    revoked_at = key.get("revoked_at")
    if key.get("status") == "revoked" and isinstance(revoked_at, str):
        from datetime import datetime

        revoked = datetime.fromisoformat(revoked_at.replace("Z", "+00:00")).timestamp()
        if revoked <= iat:
            raise AgentMessageVerificationError(
                "key_revoked", f"key {kid} was revoked at {revoked_at}, before this signature"
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
    # aSIM phase 2: the delivery signature binds the sender's own author signature.
    if (
        isinstance(agent_sig, Mapping)
        and isinstance(author_sig, str)
        and author_sig
        and agent_sig.get("jws_sha256") != _sha(re.sub(r"\s+", "", author_sig))
    ):
        bad.append("author")
    if bad:
        raise AgentMessageVerificationError(
            "content_mismatch", f"the message differs from what was signed: {', '.join(bad)}"
        )
    current = time.time() if now is None else now
    if iat > current + clock_tolerance:
        raise AgentMessageVerificationError("issued_in_future", "signature iat is in the future")
    if isinstance(max_age_seconds, _Default):
        max_age: Optional[float] = (
            None if claims.get("type") == "message" else DEFAULT_AGENT_MESSAGE_MAX_AGE_SECONDS
        )
    else:
        max_age = max_age_seconds
    if max_age is not None and current - iat > max_age + clock_tolerance:
        raise AgentMessageVerificationError(
            "too_old", f"signed {round(current - iat)} s ago; the limit is {max_age} s"
        )
    if replay_cache is not None and not replay_cache.use(
        str(claims["nonce"]), iat + (max_age if max_age is not None else _REPLAY_WITHOUT_MAX_AGE_SECONDS)
    ):
        raise AgentMessageVerificationError(
            "replayed", "this signature was already accepted (nonce seen before)"
        )
    return {
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
    ``iat`` fails), ``typ``, ``iss``, ``aud`` equals ``recipient`` (your address), the content hashes against
    ``message`` (an API message dict), freshness (``max_age_seconds``: 900 by default for ``task``/``event``,
    none for ``message``; ``None`` turns it off) and replay (``replay_cache``, keyed by ``nonce``). With
    ``check_revocation`` the directory also confirms the sender is still active (codes ``agent_revoked``,
    ``agent_suspended``, ``agent_deleted``, ``revocation_check_failed``). ``now`` (epoch seconds) is for
    tests.
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
    result = _check(
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
        replay_cache=replay_cache,
        clock_tolerance=clock_tolerance,
        now=now,
    )
    if check_revocation is not None:
        _check_standing(check_revocation, sig)
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
    result = _check(
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
        replay_cache=replay_cache,
        clock_tolerance=clock_tolerance,
        now=now,
    )
    if check_revocation is not None:
        await _acheck_standing(check_revocation, sig)
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

AuthorErrorCode = Literal[
    "dependencies_missing",
    "no_signature",
    "malformed",
    "wrong_type",
    "unknown_key",
    "key_revoked",
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
    give them on a send (a reply's subject and recipients are computed by Agentboxd). Valid for 5 minutes,
    once.
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
    if to_list is not None:
        claims["to"] = to_list
    cc_list = _recipient_list(cc)
    if cc_list is not None:
        claims["cc"] = cc_list
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
) -> VerifiedAuthorSignature:
    """Verify a message's author signature with the agent's own public keys. Raises
    :class:`AuthorSignatureVerificationError`.

    ``keys``: the agent's keys, e.g. ``card["keys"]["agent"]`` from ``directory.resolve`` or
    ``public_directory.keys(address)`` (a key revoked at or before ``iat`` fails). Checks the signature, that
    it is from the message's sender, and every claimed hash against ``message`` (an API message dict). The
    result says what was ``covered``: the automatic text of a data-only message, for instance, is not."""
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
    if claims.get("v") != 1 or not isinstance(iat, int):
        raise AuthorSignatureVerificationError("malformed", "missing v or iat")
    revoked_at = key.get("revoked_at")
    if key.get("status") == "revoked" and isinstance(revoked_at, str):
        from datetime import datetime

        if datetime.fromisoformat(revoked_at.replace("Z", "+00:00")).timestamp() <= iat:
            raise AuthorSignatureVerificationError(
                "key_revoked", f"key {kid} was revoked at {revoked_at}, before this signature"
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
    recipients = "to" in claims or "cc" in claims
    if "to" in claims and _address_set(message.get("to") or []) != list(claims["to"] or []):
        bad.append("to")
    if "cc" in claims and _address_set(message.get("cc") or []) != list(claims["cc"] or []):
        bad.append("cc")
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
