# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Remap pids on an OnPing line-graph widget via /import-data-only.

Wraps `POST /content/widgets/line-graph/import-data-only/{id}` with a Dhall
`[Field]` body. Rewrites `yParam_pid` and `eventParam_pid` where the `from`
field matches; every other field (title, colors, line widths, axis
descriptions, event icons, maxStep, refresh, normalizeValue, …) is untouched
by the handler.

MUTATING: `--yes`-gated. Default is a local preview that parses the input list,
extracts the `from → to` mappings, and prints them as a table. No network call
on preview.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _line_graph_routes.line_graph_http import _fail, extract_error, post_dhall
from _line_graph_routes.routes import ROUTES


# ─────────────── shape check + from/to mapping extraction ────────────────

# Each `from` block: from = { onpingKey = { type = "PID", value = +N }, description = "..." }
FROM_PATTERN = re.compile(
    r'from\s*=\s*\{\s*onpingKey\s*=\s*\{\s*type\s*=\s*"(PID|VPID)"\s*,\s*value\s*=\s*\+?(-?\d+)\s*\}'
    r'\s*,\s*description\s*=\s*"([^"]*)"'
)

# Each `to` block: to = Some { type = "PID", value = +N }  OR  to = None { type : Text, value : Integer }
TO_SOME_PATTERN = re.compile(
    r'to\s*=\s*Some\s*\{\s*type\s*=\s*"(PID|VPID)"\s*,\s*value\s*=\s*\+?(-?\d+)\s*\}'
)
TO_NONE_PATTERN = re.compile(r'to\s*=\s*None\s*\{\s*type\s*:\s*Text')


def _check_list_shape(dhall_text: str) -> list[str]:
    """Return a list of shape errors. Empty list = shape OK."""
    errors: list[str] = []
    stripped = dhall_text.lstrip()
    if stripped.startswith("{"):
        errors.append(
            "Input is a Dhall RECORD (starts with '{'), but /import-data-only "
            "expects a list. This looks like a `-export` output — use "
            "`onping-line-graph-import` instead. See _line_graph_routes/SKILL.md "
            "for the schema gotcha."
        )
        return errors
    if not stripped.startswith("["):
        errors.append(
            f"Input does not start with '[' — not a Dhall list. First 80 chars:\n{stripped[:80]}"
        )
        return errors
    return errors


def _extract_mappings(dhall_text: str) -> list[dict]:
    """Extract each list entry's (from, to) into a friendly dict list.

    Splits the list into per-entry chunks and pairs each `from` with the next
    `to`. Approximate but sufficient for a preview report.
    """
    mappings: list[dict] = []
    # Iterate concurrently: alternate from/to matches through the text.
    from_iter = FROM_PATTERN.finditer(dhall_text)
    for m_from in from_iter:
        from_type, from_val, description = m_from.group(1), int(m_from.group(2)), m_from.group(3)
        # Search for the next `to = ...` after this `from`.
        tail = dhall_text[m_from.end():]
        m_some = TO_SOME_PATTERN.search(tail)
        m_none = TO_NONE_PATTERN.search(tail)
        to_repr: str
        if m_some and (not m_none or m_some.start() < m_none.start()):
            to_repr = f"{m_some.group(1)} {int(m_some.group(2))}"
        elif m_none:
            to_repr = "(unset — no remap)"
        else:
            to_repr = "(no `to` field found — malformed)"
        mappings.append({
            "from_type": from_type,
            "from_value": from_val,
            "description": description,
            "to": to_repr,
        })
    return mappings


# ─────────────────────────────────── main ───────────────────────────────────


def main() -> None:
    p = argparse.ArgumentParser(
        description="Remap pid bindings on an OnPing line-graph widget via "
        "POST /content/widgets/line-graph/import-data-only/{id}. MUTATING; requires --yes.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("--id", dest="widget_id", required=True, help="LineGraphWidgetId to remap")
    p.add_argument("--input", dest="input_path", help="input Dhall file (default: read from stdin)")
    p.add_argument("--yes", action="store_true", help="perform the remap (required to write)")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="explicit preview (default when --yes is not passed); wins over --yes",
    )
    p.add_argument("--json", dest="emit_json", action="store_true", help="emit the imported widget JSON on success")
    args = p.parse_args()

    # ── 1. Read input ──
    if args.input_path:
        dhall_body = Path(args.input_path).read_text()
    else:
        dhall_body = sys.stdin.read()

    # ── 2. Local shape check + mapping extraction ──
    errors = _check_list_shape(dhall_body)
    mappings = _extract_mappings(dhall_body) if not errors else []

    # ── 3. Preview or apply ──
    if args.dry_run or not args.yes:
        print("=== PREVIEW ===")
        print(f"Would REMAP pids on widget: {args.widget_id}")
        print()
        print("Shape check:")
        if errors:
            for e in errors:
                print(f"  ✗ {e}")
        else:
            print("  ✓ Dhall list parses.")
        print()
        if mappings:
            print(f"From → To mapping ({len(mappings)} entries):")
            print(f"  {'from':<20} {'to':<20} description")
            print(f"  {'-'*20} {'-'*20} {'-'*40}")
            for m in mappings:
                left = f"{m['from_type']} {m['from_value']}"
                print(f"  {left:<20} {m['to']:<20} {m['description']}")
        print()
        print("--dry-run — no write performed.")
        if errors:
            sys.exit(2)
        return

    if errors:
        _fail(
            "Local shape check failed; refusing to POST. Fix these issues (or "
            "re-run without --yes for a full preview):\n"
            + "\n".join(f"  ✗ {e}" for e in errors)
        )

    # ── 4. Import the Dhall body ──
    resp = post_dhall(
        args.access_token,
        ROUTES["import-data"]["endpoint"],
        dhall_body,
        widget_id=args.widget_id,
    )
    if not (200 <= resp.status_code < 300):
        _fail(
            f"HTTP {resp.status_code} remapping widget {args.widget_id}: "
            f"{extract_error(resp)}\nThe target widget was NOT modified."
        )

    try:
        widget = resp.json()
    except ValueError:
        _fail(f"Expected JSON widget in response, got: {resp.text[:500]}")

    print(f"Remapped pids on widget {args.widget_id}", file=sys.stderr)
    if args.emit_json:
        print(json.dumps(widget))


if __name__ == "__main__":
    main()
