"""Mongo-id conversion for the OnPing audit tables.

The same document id appears in three forms across OnPing, and mixing them is a
silent-wrong-answer bug rather than an error:

  1. **HTTP form** — `o000000000000000000000049`. What every `/content/*` route
     wants, and what a user copies out of a dashboard URL.
  2. **Audit form** — `000000000000000000000049`. What `<model>_audit.original_id`
     stores: the same 24 hex characters with the leading `o` removed
     (`keyToMongoIdUtf8NoO`).
  3. **Hex-of-ASCII form** — `\\x303030...`. How postgres renders a bytea column
     holding the ASCII text of form 2. Also how `MongoIdUtf8NoO` foreign-key
     columns such as `dashboard` come back.

A query against `original_id` using form 1 matches nothing and returns an empty
list, which reads exactly like "this record has no history". So the skills accept
either of the first two forms and convert internally; the caller is never asked
to strip a prefix.
"""

from __future__ import annotations

_HEX = set("0123456789abcdefABCDEF")


class IdForm:
    HTTP = "o-prefixed"
    AUDIT = "bare hex"


def parse_mongo_id(raw: str) -> tuple[str, str]:
    """Return (audit_form, which_form_was_given).

    Accepts `o`-prefixed or bare 24-hex. Raises on anything else rather than
    guessing, because a wrong id silently returns zero rows.
    """
    s = raw.strip()
    if s.startswith("o") and len(s) == 25 and all(c in _HEX for c in s[1:]):
        return s[1:].lower(), IdForm.HTTP
    if len(s) == 24 and all(c in _HEX for c in s):
        return s.lower(), IdForm.AUDIT
    raise ValueError(
        f"not a mongo object id: {raw!r} (expected 24 hex characters, "
        "optionally prefixed with 'o')"
    )


def to_http_id(audit_id: str) -> str:
    """Audit form -> HTTP form."""
    body = audit_id[1:] if audit_id.startswith("o") else audit_id
    return "o" + body.lower()


def decode_pg_hex_id(value: str | None) -> str | None:
    """Decode a postgres `\\x…` bytea rendering into an HTTP-form mongo id.

    Used for `MongoIdUtf8NoO` columns such as `dashboard`. The bytes are the ASCII
    text of the bare hex id, so this is a hex decode followed by restoring the
    `o`. Returns the input unchanged when it is not in `\\x` form, so an
    already-decoded value passes through.

    A widget posted with the raw `\\x…` string as its dashboard names a parent
    that cannot resolve, which makes the widget unwritable — so this failing loudly
    matters more than it looks.
    """
    if value is None:
        return None
    if not value.startswith("\\x"):
        return value
    try:
        text = bytes.fromhex(value[2:]).decode("ascii")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"could not decode bytea id {value[:24]!r}: {exc}") from exc
    return to_http_id(text)
