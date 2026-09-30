---
name: _ctable_routes
description: Internal helper — do not invoke. Shared Python module (routes.py, ctable_http.py, decode.py) imported by the onping-ctable-* skills; this SKILL.md exists only so the Nix bundler ships the module to the skills root for sibling import.
---

# _ctable_routes (internal helper — do not invoke)

**This is not a user-facing skill. Do not invoke it.** It has no command and no
entry point. It exists so the Nix bundler places the module at the skills root,
where the `onping-ctable-*` scripts import it as a sibling.

| Module | Contents |
|---|---|
| `routes.py` | The `/content/ctable/*` route table, the 8 MiB body cap, the widget key lists, and `normalize_ctable_id` |
| `ctable_http.py` | Bearer auth, the auth-failure guard, and `check_write_response` |
| `decode.py` | The audit-row decoder and the four encoding guards |

Three facts these modules centralize, each verified against a live server:

1. **`cTableId` is a query parameter**, never a path segment. The export route's path
   segment is a download filename.
2. **A write refusal arrives as HTTP 200** with the bare string
   `"insufficient permissions"`, so `check_write_response` inspects the body.
3. **An expired token presents three ways** — a `303` redirect, a 200 HTML login
   page, and `401 {"error":"NotAuthenticated"}` — and all three are detected.

User-facing skills: `onping-ctable-export`, `onping-ctable-import`,
`onping-ctable-audit-history`, `onping-ctable-audit-export`.
