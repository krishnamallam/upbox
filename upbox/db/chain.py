"""Tamper-evident hash chain over the audit log.

Every captured request gets a sequence number and a SHA-256 hash computed over
a canonical serialisation of its chained fields plus the previous entry's hash.
Recomputing the chain detects content edits, deletions, insertions, and
reordering after the fact.

The chain covers *hashes of* ``headers_json`` and ``body_excerpt`` rather than
their contents. That is deliberate: retention can null out the stored text
later and the chain still verifies, because the hash that was chained survives
in its own column. See the "Tamper evidence" section of the README.

What this does not do
---------------------
The algorithm is public and keyless. Anyone with write access to the database
and a copy of upbox can recompute a perfectly consistent chain over whatever
contents they like, and tail truncation produces a valid shorter chain. The
chain's evidentiary value comes entirely from a head hash that left the
machine. It converts "trust me, nobody edited this file" into "here is a
64-character hash from 14 July, check it yourself."
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

# Bumped only when the chained field set or the serialisation changes. A bump
# invalidates every historical hash, so it also needs a migration story.
CHAIN_ALGORITHM = "sha256-canonical-v1"

# Prefixed into every digest so a SHA-256 computed elsewhere (a body hash, a
# file checksum) can never be replayed as a chain link.
_DOMAIN_SEPARATOR = b"upbox.chain.v1\n"

GENESIS_PREV_HASH = "0" * 64

# Order is irrelevant to the digest (keys are sorted during canonicalisation)
# but this tuple is the definition of what the chain commits to. Adding a
# field here is a breaking change.
CHAINED_FIELDS = (
    "seq",
    "ts",
    "tool",
    "method",
    "scheme",
    "host",
    "path",
    "req_bytes",
    "resp_bytes",
    "status",
    "headers_sha256",
    "body_hash",
    "body_excerpt_sha256",
    "redactions_applied_json",
    "enforcement",
    "prev_hash",
)


def canonical_json(payload: Mapping[str, Any]) -> bytes:
    """Serialise a chained payload to its one canonical byte string.

    Keys sorted by code point, no whitespace, UTF-8, non-ASCII left as-is.
    Every chained field is a string, an integer, or null, and floats are
    rejected outright: their shortest-round-trip representation is the part of
    RFC 8785 that implementations get wrong, and we never need them. Keeping
    the value set this narrow is what lets stdlib ``json`` be the canonical
    form instead of a hand-rolled canonicaliser.
    """
    for name, value in payload.items():
        if isinstance(value, float):
            raise TypeError(f"chained field {name!r} is a float; chained values must not be floats")
        if not isinstance(value, str | int | type(None)):
            raise TypeError(f"chained field {name!r} has unchainable type {type(value).__name__}")
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def entry_hash(payload: Mapping[str, Any]) -> str:
    """Hex SHA-256 of a chained payload, domain-separated."""
    return hashlib.sha256(_DOMAIN_SEPARATOR + canonical_json(payload)).hexdigest()


def chain_payload(source: Mapping[str, Any]) -> dict[str, Any]:
    """Project a row (or an insert's field dict) down to the chained fields."""
    return {name: source[name] for name in CHAINED_FIELDS}


def hash_text(value: str | None) -> str | None:
    """Hex SHA-256 of a stored text column, or None if the column is null.

    Used for ``headers_json`` and ``body_excerpt`` so the chain commits to
    their content without the content having to survive retention.
    """
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
