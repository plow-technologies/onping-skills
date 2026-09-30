"""Route table, auth headers, and key resolution for the OnPing documentation site.

This module is the single source of truth for reaching the Payload CMS instance at
`https://onping.plowtech.net/onping-doc` that publishes the OnPing customer-facing
documentation. Every `onping-doc-*` skill imports from here; nothing redefines a
route, a header, or the key lookup inline.

THE AUTH MATRIX (re-verified 2026-08-25 with a no-auth control on every row).

    Route                                        no auth   Bearer   API-Key
    POST /api/mcp                                  500      200       500
    GET  /api/docs, /categories, /media            200      200       200
    GET  /api/access                               200*     200*      200*
    GET  /api/users, /payload-mcp-api-keys         500      500       200
    POST /api/docs                                  -        -        500

    * /api/access returns MORE with a credential (1780 bytes vs 1136) because it
      reports the caller's own permissions. The other rows are byte-identical
      across all three columns.

Three consequences drive this module's shape:

1. `Bearer <key>` is the ONLY form that reaches `/api/mcp`, and MCP is the only
   write path. A garbage Bearer returns 500, so the credential is really checked.
   The `<collection> API-Key <key>` form — which is what Payload's REST layer
   wants — fails on `/api/mcp`.

2. THE DOCUMENTATION COLLECTIONS ARE WORLD-READABLE. `/api/docs` returns
   byte-identical payloads with no Authorization header, with a garbage token, or
   with the real key; document 14's full body is retrievable unauthenticated. The
   key is NOT what makes a document read succeed. `rest_headers()` is therefore
   sent DEFENSIVELY — so a future tightening of the server's access rules does not
   break the read skills — and is genuinely required only for `/api/users` and
   `/api/payload-mcp-api-keys`. This is the server's access posture; these skills
   neither introduce it nor can change it.

3. EVERY AUTH FAILURE IS A BODILESS 500 — zero-byte body, no JSON envelope, no
   indication of which header form was wrong, indistinguishable from a genuine
   server fault. See `docs_http.auth_failure_hint`, which supplies the only
   diagnosis available.

A first pass at this matrix was wrong in three cells because it probed only the
credentialed cases: it recorded a `401` on `/api/mcp` with the API-Key form, a
`403` on `/api/docs` with Bearer, and credited the key for a public endpoint's
success. None of the three reproduce. Do not document a `401` for this service.
Any future auth claim here needs the no-auth control run alongside it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BASE_URL = os.environ.get(
    "ONPING_DOCS_BASE_URL", "https://onping.plowtech.net/onping-doc"
)
TIMEOUT_SECONDS = 60

# The JSON-RPC / MCP endpoint. Bearer-only, SSE responses, and the only write path.
MCP_PATH = "/api/mcp"

# Read-only REST routes. Public in practice (see the module docstring); the
# `requires_key` flag records which ones genuinely 500 without the API-Key form.
REST_ROUTES: dict[str, dict] = {
    "docs": {
        "endpoint": "GET /api/docs",
        "requires_key": False,
        "notes": "World-readable. Paginated: docs[], totalDocs, hasNextPage, page.",
    },
    "doc": {
        "endpoint": "GET /api/docs/{id}",
        "requires_key": False,
        "notes": "World-readable. `content` is Lexical rich text, not markdown.",
    },
    "categories": {
        "endpoint": "GET /api/categories",
        "requires_key": False,
        "notes": "World-readable. A category is a sidebar tab: title, slug, icon, order.",
    },
    "media": {
        "endpoint": "GET /api/media",
        "requires_key": False,
        "notes": "World-readable listing. No upload path — the key grants no media access.",
    },
    "access": {
        "endpoint": "GET /api/access",
        "requires_key": False,
        "notes": "Reports MORE when credentialed. Its `media` entry is the COLLECTION's "
        "access config, NOT this key's capability — reading it as one is a trap.",
    },
    "api-key": {
        "endpoint": "GET /api/payload-mcp-api-keys/{id}",
        "requires_key": True,
        "notes": "The key's own record, including the grants that determine the MCP "
        "tool roster. 500 without the API-Key form.",
    },
    "users": {
        "endpoint": "GET /api/users",
        "requires_key": True,
        "notes": "500 without the API-Key form.",
    },
}

# Tools observed on 2026-08-25. REFERENCE ONLY — never a completeness claim.
# The roster is a function of the API key's grants: `docs` is granted
# find/create/delete and NOT update, so there is no `updateDocs` and a body edit
# must go through `updateDocWithMarkdown`; `media` is absent from the grants
# entirely, so no upload tool exists. Call `docs_http.list_tools()` for truth.
KNOWN_TOOLS: tuple[str, ...] = (
    "findDocs",
    "createDocs",
    "deleteDocs",
    "findCategories",
    "createCategories",
    "updateCategories",
    "deleteCategories",
    "getDocsByCategory",
    "updateDocWithMarkdown",
    "compareDoc",  # BROKEN — renders every body as "[object Object]". Not wrapped.
)

KEY_ENV_VAR = "ONPING_DOCS_API_KEY"
KEY_BASENAME = "onping-docs"

# THE EDGE BLOCKS THE DEFAULT `requests` USER-AGENT WITH A 404.
#
# Verified 2026-08-25. A request whose User-Agent begins (case-insensitively)
# with "python-requests" gets `404 {"error":"NotFound"}` on BOTH /api/mcp and the
# REST routes, while the identical request with any other UA returns 200:
#
#     python-requests/2.32.3        -> 404      curl/8.7.1                -> 200
#     python-requests               -> 404      Mozilla/5.0               -> 200
#     Python-Requests/2.32          -> 404      python-urllib/3           -> 200
#     PYTHON-REQUESTS/2.32          -> 404      Python/3.11 aiohttp/3.9   -> 200
#                                               myapp python-requests/2.32 -> 200
#
# It is a case-insensitive PREFIX match: the string is fine when not at the start.
#
# The 404 is the trap. It says "NotFound", so it reads as a wrong URL or a route
# that does not exist — the one failure a reader will not attribute to a header.
# curl works, which makes it look like the URL is right and the code is wrong.
# ALWAYS send an explicit User-Agent on this service.
USER_AGENT = "onping-doc-skill/1.0"

# Matches onping-login/scripts/login.py: when this file lives at
# {root}/skills/_docs_routes/routes.py, parents[2] is the skills root's parent.
SKILLS_ROOT = Path(__file__).resolve().parent.parent.parent


# ────────────────────────────────── headers ─────────────────────────────────


def mcp_headers(key: str) -> dict[str, str]:
    """Headers for POST /api/mcp.

    Bearer is the only form this route accepts. The Accept header MUST carry BOTH
    media types: `Accept: application/json` alone (or a missing Accept) returns
    `406 Not Acceptable: Client must accept both application/json and
    text/event-stream`. Responses are SSE, not plain JSON.

    The explicit User-Agent is REQUIRED, not cosmetic: the default
    `python-requests/*` UA gets a 404 from the edge. See `USER_AGENT`.
    """
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": USER_AGENT,
    }


def rest_headers(key: str | None) -> dict[str, str]:
    """Headers for the read-only REST routes.

    Payload's collection-scoped API key scheme. Sent DEFENSIVELY: the docs
    collections are world-readable, so this is not what makes a read succeed. It
    is required only for `/api/users` and `/api/payload-mcp-api-keys`, and it is
    sent everywhere so a future tightening of the server's rules does not break
    the read skills.

    The explicit User-Agent is REQUIRED here too — the `python-requests/*` 404
    applies to the REST routes as well as to /api/mcp. See `USER_AGENT`.
    """
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if key:
        headers["Authorization"] = f"payload-mcp-api-keys API-Key {key}"
    return headers


def rest_url(route: str, **path_params: object) -> str:
    """Build an absolute URL from a REST_ROUTES key."""
    try:
        endpoint = REST_ROUTES[route]["endpoint"]
    except KeyError:
        raise ValueError(
            f"unknown REST route {route!r}; known: {sorted(REST_ROUTES)}"
        ) from None
    path = endpoint.split(" ", 1)[1]
    for name, value in path_params.items():
        path = path.replace("{" + name + "}", str(value))
    if "{" in path:
        raise ValueError(f"unresolved path placeholder in {path!r}")
    return BASE_URL + path


def mcp_url() -> str:
    return BASE_URL + MCP_PATH


# ─────────────────────────────── key resolution ─────────────────────────────


def _candidate_roots() -> list[Path]:
    """Ordered directories to search for onping-docs / onping-docs.gpg.

    Mirrors `onping-login/scripts/login.py::_candidate_roots` deliberately,
    including its ordering rationale. SKILLS_ROOT comes LAST because the
    nix-bundled copy at ~/.claude/skills/... walks up to ~/.claude, where a stale
    credential can otherwise silently shadow a fresh one at the canonical source
    path (that bug was observed with refresh_token.gpg on 2026-07-28).
    """
    roots: list[Path] = []
    seen: set[Path] = set()

    def add(p: Path | None) -> None:
        if p is None:
            return
        try:
            resolved = p.resolve()
        except (OSError, RuntimeError):
            return
        if resolved in seen:
            return
        seen.add(resolved)
        roots.append(resolved)

    add(_project_root_from_cwd())
    add(Path.home() / "skills" / "onping")
    add(SKILLS_ROOT)
    return roots


def _project_root_from_cwd() -> Path | None:
    """Walk up from cwd looking for pyproject.toml. None if not found."""
    try:
        current = Path.cwd().resolve()
    except (OSError, RuntimeError):
        return None
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    return None


def _try_plaintext(root: Path) -> str | None:
    p = root / KEY_BASENAME
    if not p.exists():
        return None
    return p.read_text().strip() or None


def _try_gpg(root: Path) -> str | None:
    p = root / f"{KEY_BASENAME}.gpg"
    if not p.exists():
        return None
    try:
        result = subprocess.run(
            ["gpg", "-d", str(p)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        print(
            f"gpg not found; cannot decrypt {KEY_BASENAME}.gpg",
            file=sys.stderr,
        )
        return None
    except subprocess.TimeoutExpired:
        print(f"GPG decryption timed out on {p}", file=sys.stderr)
        return None
    if result.returncode == 0:
        return result.stdout.strip() or None
    print(f"GPG decryption failed for {p}: {result.stderr}", file=sys.stderr)
    return None


def resolve_key() -> str:
    """Resolve the documentation-site API key, or exit non-zero.

    Order: ONPING_DOCS_API_KEY, then a plaintext `onping-docs` file, then an
    encrypted `onping-docs.gpg`, each across `_candidate_roots()`.

    The decrypted value is a BARE UUID with no JSON wrapper — unlike the
    JSON-wrapped credential files some other skills use, which decrypt to
    objects. It is treated as an opaque string and never parsed as JSON. The
    encrypted file is never written to or re-encrypted.

    The key itself is never printed, on success or failure.
    """
    key = os.environ.get(KEY_ENV_VAR, "").strip()
    if key:
        return key

    roots = _candidate_roots()

    for root in roots:
        key = _try_plaintext(root)
        if key:
            return key

    for root in roots:
        key = _try_gpg(root)
        if key:
            return key

    checked = "\n".join(f"  - {root}/{KEY_BASENAME}(.gpg)" for root in roots)
    print(
        f"No OnPing docs API key found. Set {KEY_ENV_VAR}, or place a "
        f"{KEY_BASENAME} / {KEY_BASENAME}.gpg file in one of:\n" + checked,
        file=sys.stderr,
    )
    sys.exit(1)
