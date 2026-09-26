"""Agent self-signup: the proof-of-work solver (no I/O).

The API's challenge asks for a decimal ``solution`` such that
``SHA-256(challenge + ":" + solution)`` starts with ``difficulty`` zero bits.
"""

import hashlib
from dataclasses import dataclass
from typing import Generic, Optional, TypeVar

from ._types import Identity, Inbox, SignupResult, SignupWorkspace

__all__ = ["Signup", "leading_zero_bits", "solve_signup_challenge"]

_C = TypeVar("_C")


def leading_zero_bits(digest: bytes) -> int:
    """Number of leading zero bits of a digest."""
    bits = 0
    for byte in digest:
        if byte == 0:
            bits += 8
            continue
        return bits + 8 - byte.bit_length()
    return bits


def solve_signup_challenge(challenge: str, difficulty: int, max_iterations: int = 2**32) -> str:
    """The first decimal solution (counting up from 0): about ``2**difficulty`` hashes.

    At the default difficulty that is a few seconds of CPU.
    """
    prefix = hashlib.sha256(f"{challenge}:".encode())
    for i in range(max_iterations):
        h = prefix.copy()
        h.update(str(i).encode())
        if leading_zero_bits(h.digest()) >= difficulty:
            return str(i)
    raise RuntimeError(f"no solution found in {max_iterations} tries")


@dataclass(frozen=True)
class Signup(Generic[_C]):
    """What :meth:`Agentboxd.signup` returns: a ready client and the API's answer.

    ``api_key`` is shown only once: store it (e.g. as ``AGENTBOXD_API_KEY``).
    """

    client: _C
    result: SignupResult

    @property
    def api_key(self) -> str:
        return self.result["api_key"]

    @property
    def inbox(self) -> Inbox:
        """The inbox (``None`` for a ``kind="identity"`` signup: use :attr:`identity`)."""
        return self.result["inbox"]

    @property
    def identity(self) -> Optional[Identity]:
        """The identity-only agent of a ``kind="identity"`` signup, else ``None``."""
        return self.result.get("identity")

    @property
    def workspace(self) -> SignupWorkspace:
        return self.result["workspace"]
