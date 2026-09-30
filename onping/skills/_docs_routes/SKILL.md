---
name: _docs_routes
description: Internal helper — do not invoke. Shared Python module (routes.py, docs_http.py) imported by the onping-doc-* skills; this SKILL.md exists only so the Nix bundler ships the module to the skills root for sibling import.
---

# _docs_routes (internal helper — do not invoke)

**This is not a user-facing skill. Do not invoke it.** It has no command and no
standalone behavior.

This directory is a shared Python helper module, not a skill. It exists as a
marker so the `agent-skills-nix` bundler — which only discovers and ships
directories that contain a `SKILL.md` — installs `routes.py` and `docs_http.py`
into the synced skills root.

The `onping-doc-*` skills import this module as a sibling:

```python
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _docs_routes.routes import BASE_URL, KNOWN_TOOLS, resolve_key
from _docs_routes.docs_http import call_tool, list_tools, extract_json_blocks, get_rest
```

- `routes.py` — `BASE_URL` (honors `ONPING_DOCS_BASE_URL`), `MCP_PATH`, the
  `REST_ROUTES` table, both `Authorization` header builders, `USER_AGENT`, and
  `resolve_key()`.
- `docs_http.py` — `call_tool()`, `list_tools()`, `extract_json_blocks()`,
  `get_rest()`, and `auth_failure_hint()`. Owns the SSE de-framing and the
  error-in-a-successful-result detection.

Without this marker, the directory is dropped during sync and every
`onping-doc-*` skill fails on import with `ModuleNotFoundError`. Keep the marker;
the catalog ID (`_docs_routes`) must equal the imported module name.

## The service

A Payload CMS instance at `https://onping.plowtech.net/onping-doc` that publishes
the OnPing customer-facing documentation site. It exposes two surfaces:

- `POST /api/mcp` — a JSON-RPC 2.0 MCP server (`serverInfo.name` is
  `"mcp-typescript server on vercel"`). **The only write path for documents and
  categories.**
- `GET /api/<collection>` — Payload's REST layer. Read-only for `docs` and
  `categories`, but **`media` accepts uploads here** (see the tool-roster note).

The URL that documents the API key, `/api/payload-mcp-api-keys/1?depth=2`, is the
REST record *describing* the key. Reading it is not how the key is used.

## THE FOUR THINGS THAT WILL WASTE YOUR TIME

### 1. The default `requests` User-Agent gets a 404

Verified 2026-08-25. A request whose `User-Agent` begins — case-insensitively —
with `python-requests` receives `404 {"error":"NotFound"}` on **both** `/api/mcp`
and the REST routes. The identical request with any other UA returns `200`.

| User-Agent | Result |
|---|---|
| `python-requests/2.32.3` | `404` |
| `python-requests` | `404` |
| `Python-Requests/2.32` | `404` |
| `PYTHON-REQUESTS/2.32` | `404` |
| `curl/8.7.1` | `200` |
| `Mozilla/5.0` | `200` |
| `python-urllib/3` | `200` |
| `Python/3.11 aiohttp/3.9` | `200` |
| `myapp python-requests/2.32` | `200` |

It is a **prefix** match, so the string is fine when it is not at the start.

**This is the worst trap on the service, because the status code lies.** A `404`
that says `NotFound` reads as a wrong URL or a route that does not exist — the one
failure nobody attributes to a request header. `curl` works, which makes the URL
look right and your code look wrong. `mcp_headers()` and `rest_headers()` both send
an explicit `USER_AGENT`, so any new code MUST go through them.

### 2. Every auth failure is a bodiless 500

`HTTP 500`, zero-byte body, no JSON envelope — for a garbage credential, for the
wrong header form, and for an uncredentialed read of a key-gated route. It names
neither the credential nor the header at fault and is indistinguishable from a
genuine server fault.

`auth_failure_hint()` supplies the only diagnosis available: it reports the header
form that was actually sent and names the likely causes. **There is no `401` on this
service.** An earlier note claimed one; it does not reproduce across five trials.

### 3. A failed tool call arrives as HTTP 200 with a `result`

Every tool returns its payload as a human-readable string at
`result.content[0].text`. A failure returns a JSON-RPC **`result`** — not an
`error` member — whose text merely begins with an error sentence:

| Call | Returned text |
|---|---|
| `findDocs` with a missing id | `Error: Document with ID "99999" not found in collection "docs"` |
| `getDocsByCategory` with a slug | `Error fetching documents by category: Failed query: … params: NaN` |
| `compareDoc` with no id or slug | `Error: Could not find document with ID "undefined"` |

A client that checks only for a JSON-RPC `error` member reports **every one of these
as success**. `call_tool()` inspects the text and exits non-zero, surfacing the
server's wording verbatim because it carries the SQL parameter and column that
identify the cause.

### 4. `/api/mcp` needs both Accept media types, and answers in SSE

`Accept: application/json, text/event-stream` — both, or the server returns
`406 Not Acceptable: Client must accept both application/json and text/event-stream`.

Responses are Server-Sent Events, so the `data: ` prefix must be stripped before
parsing. A client that parses the raw body fails on an HTTP `200`.

No `initialize` handshake is needed. `tools/call` works as the first request on a
fresh connection and the server returns no session id, so the client is stateless.

## Authentication

Re-verified 2026-08-25 **with a no-auth control on every row**, which is what makes
the table trustworthy.

| Route | no auth | `Bearer <key>` | `payload-mcp-api-keys API-Key <key>` |
|---|---|---|---|
| `POST /api/mcp` | `500` | **works** | `500` |
| `GET /api/docs`, `/api/categories`, `/api/media` | **works** | works | works |
| `GET /api/access` | works | works | works (returns more) |
| `GET /api/users`, `/api/payload-mcp-api-keys` | `500` | `500` | **works** |
| `POST /api/docs` | — | — | `500` |
| `POST /api/media` | — | — | **`201 Created`** |

Three rulings follow:

1. **`Bearer <key>` is the only form that reaches `/api/mcp`**, and MCP is the only
   write path. A garbage Bearer returns `500`, so the credential is genuinely
   checked there.
2. **The `API-Key` form is required only for `/api/users` and
   `/api/payload-mcp-api-keys`.** `rest_headers()` sends it everywhere anyway, so a
   future tightening of the server's rules does not break the read skills.
3. **No REST write works for `docs` or `categories`.** `POST /api/docs` returns
   `500`. **`POST /api/media` is the exception and returns `201`** — media is
   writable over REST even though no MCP tool exposes it.

### The documentation collections are world-readable

`/api/docs`, `/api/categories`, and `/api/media` return `200` with **no
`Authorization` header at all**, and return byte-identical payloads with a garbage
token, a valid key, or no header. Document 14's full body is retrievable
unauthenticated. `/api/access` is the only route whose payload differs by
credential (1136 bytes unauthenticated against 1780 with the key), because it
reports the caller's own permissions.

**The key is not what makes a document read succeed.** Anything that can reach the
host can enumerate every document. This is the server's access posture — these
skills neither introduce it nor can change it — and it is recorded because a reader
must not assume the key gates reads, and because anyone weighing what to publish
should know the audience is unauthenticated.

**A first pass at this matrix was wrong in three cells** because it probed only the
credentialed cases: it recorded a `401` on `/api/mcp` with the API-Key form, a `403`
on `/api/docs` with Bearer, and credited the key for a public endpoint's success.
Any future auth claim about this service needs the no-auth control run beside it.

## Key resolution

`resolve_key()` checks, stopping at the first hit:

1. The `ONPING_DOCS_API_KEY` environment variable.
2. A plaintext `onping-docs` file.
3. A GPG-encrypted `onping-docs.gpg` file, via `gpg -d`.

For the file sources it walks the same ordered roots as
`onping-login/scripts/login.py`: the project root from `cwd`, then the source
checkout, then the bundled skills root **last** — because the bundled copy walks
up to the shared skills parent, where a stale credential can otherwise silently
shadow a fresh one at the canonical path.

The decrypted value is a **bare UUID with no JSON wrapper**, unlike the
JSON-wrapped credential files some other skills use. It is treated as an opaque
string and never parsed as JSON. The encrypted file is never rewritten,
and the key is never printed.

## The tool roster is a function of the key's grants

Verified as an exact 10-for-10 match on 2026-08-25:

```
docs:             find, create, delete         → findDocs, createDocs, deleteDocs
categories:       find, create, update, delete → findCategories, createCategories,
                                                 updateCategories, deleteCategories
payload-mcp-tool: getDocsByCategory, updateDocWithMarkdown, compareDoc
```

Two absences that a uniform-CRUD assumption gets wrong:

- **There is no `updateDocs`.** `docs` is granted `find, create, delete` and not
  `update`, so a document body is edited only through `updateDocWithMarkdown`.
  `categories` *is* granted `update` and does get `updateCategories`, so the
  asymmetry appears inside one tool list.
- **There is no media MCP tool, but media IS writable over REST.** `media` is
  absent from the key's grants, so no MCP upload tool exists. That is a fact about
  the tool roster only. **`/api/access` reports `media: {create, read, update,
  delete}` and that report is correct.** Verified 2026-08-26: `POST /api/media`
  with an SVG returned `201 Created`, the file served publicly at `200`, and
  `DELETE /api/media/<id>` returned `200`. `collections/Media.ts` declares only
  `read: () => true` and no write functions, so Payload defaults them to
  "authenticated" and this key qualifies. Screenshots are possible — see
  `onping-doc-write`.

  An earlier version of this file claimed the opposite, calling the `/api/access`
  media entry a trap. That was the mirror of the docs-collection error: there the
  key's grant flags were trusted over `/api/access` and overstated, here
  `/api/access` was overruled and understated. **`/api/access` is authoritative in
  both directions.** Test a capability claim against it rather than arguing from
  the collection source.

`KNOWN_TOOLS` in `routes.py` is reference only. Call `list_tools()` for truth: a
grant change alters the roster.

## `compareDoc` is broken and is deliberately not wrapped

`compareDoc` renders **every** document body as the literal string
`[object Object]`. It interpolates the Lexical `content` object into a template
instead of serializing it. Reproduced on document 14 by `documentId` and document
16 by `documentSlug`:

```
**Current Content:**
```markdown
[object Object]
```
```

The rest of its output is an instruction block asking the caller to produce a gap
analysis. **The tool is a prompt template, not a comparison**, and the analysis is
performed by whichever model receives it — against content that is always absent.
Handing a model an empty body plus a demand for gap analysis is a machine for
producing confident fabrication.

No skill wraps it. Revisit only if the server fixes the serialization.

## Response shapes differ between tools in the same collection

- `findDocs` embeds a document as JSON inside a fenced ```json block within a prose
  string. Use `extract_json_blocks()`.
- `getDocsByCategory` returns prose with `Document ID: <n>` lines and **no JSON at
  all**.

A caller must handle both.

## Content is Lexical, not markdown

A document's `content` is `{root: {type: "root", children: [Node], …}}`. Document 14
carries 106 root children — 56 `paragraph`, 34 `heading`, 15 `list`, 1 `block` —
with per-node `format` integer bitfields, where `format: 16` marks inline code.
Document 16's body is four `upload` nodes and no text: a screenshot dump.

`updateDocWithMarkdown` is the only tool accepting markdown, which makes it the only
practical authoring path. See `onping-doc-write`.

At `depth=0` the `category` and `parent` fields are integer foreign keys; at
`depth>=1` they are nested objects. Do not assume one shape.

## Junk records in the collection

Documents 17 and 9 are `_status: "draft"` with `title: null`, `slug: null`, and
`content: null`. Document 17's breadcrumb is `{doc: 17, url: "/null", label: null}`.
`onping-doc-list` hides null-titled documents by default and reports the omitted
count.
