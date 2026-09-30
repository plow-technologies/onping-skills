# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Publish markdown to a document on the OnPing documentation site.

MUTATING — requires --yes. The target is a LIVE CUSTOMER-FACING site.

`updateDocWithMarkdown` is the only tool that accepts markdown, and there is no
`updateDocs` tool at all, so this is the only way to change a document's body. The
server converts the markdown to Lexical rich text; the caller never authors Lexical.

WHAT THIS SCRIPT ENFORCES (hard, blocks the publish):

  - an audience declaration naming a canonical persona
  - no "Open Questions" heading in a published document
  - a rationale when a sixth top-level section appears

WHAT IT ONLY REPORTS (soft, never blocks, never changes the exit code):

  - the prose self-check findings: banned modals, semicolons, contractions,
    Latin abbreviations, over-cap sentences, missing sections

THE SOFT/HARD SPLIT IS DELIBERATE, and it mirrors the `explainer` skill exactly.
There, `--validate` checks structure only and never reads a sentence; all 14
language constraints are authoring obligations enforced by a self-check ritual. A
mechanical gate on a judgment rule produces prose that is compliant and lifeless —
the explainer measured that across 93 documents, where banned modals fell 96 %
while the long-sentence band fell from 24.1 % to 19.2 %, em dashes fell 88 %, and
first-person reference fell 37 %. The rules worked and the prose got worse. So the
report here informs the writer and never overrides them. The only hard gate on
publication is `--yes`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _docs_routes.docs_http import call_tool, extract_json_blocks
from _docs_routes.routes import resolve_key

# ── the canonical OnPing personas ────────────────────────────────────────────
#
# Restated here rather than only cited, because the canonical taxonomy lives in
# the OnPing design documentation, outside this repository, and a skill must work
# from a fresh clone. They are PEERS, not a
# hierarchy, and there are no sub-personas.
PERSONAS = ("Users", "Builders", "Platformers")

# Customer-facing job titles -> persona. An unrecognized title maps to the closest
# fit and the mapping is REPORTED; a new persona label is never invented.
TITLE_MAP = {
    "production manager": "Users",
    "business analyst": "Users",
    "operations specialist": "Users",
    "operator": "Users",
    "i&e tech": "Builders",
    "ie tech": "Builders",
    "automation tech": "Builders",
    "scada tech": "Builders",
    "technician": "Builders",
    "integrator": "Builders",
    "ceo": "Platformers",
    "business development": "Platformers",
    "software developer": "Platformers",
    "developer": "Platformers",
}

FIVE_SECTIONS = (
    "Introduction",
    "Setup Walkthrough",
    "Field Reference",
    "Troubleshooting",
    "See Also",
)

# Trash convention — see onping-doc-list. Nothing can delete a document here, and
# `category` is not settable, so a discarded document is MARKED, not moved.
#
# The slug marker is `trash-`, with a HYPHEN. A slash makes the nested-docs plugin
# treat the first segment as a parent document, and the next update to that
# document then fails with `The following field is invalid: Breadcrumbs 1 > Doc`.
TRASH_SLUG_PREFIX = "trash-"
TRASH_TITLE_PREFIX = "TRASH"

TRASH_BODY = """# TRASH — safe to delete

This is a discarded artifact, not documentation. It is a DRAFT, so it is not
published and no customer can reach it.

## Why it is still here

Nothing can delete it through the API. The MCP plugin acts as the API key's
related user, who holds role `admin`, and the docs access rule permits an admin to
delete only when `data.deletedAt` is set — but no field defines that value and
trash is never enabled, so the branch is unreachable. The delete control is hidden
in the admin UI for every admin.

This is a known server-side bug. An `owner`-role account can delete this today.

## Finding every trash document

Filter the docs list by a slug beginning `trash-`, or a title beginning `TRASH`.
"""

# Literal strings from Part A step 3 of the explainer self-check. The list is
# CLOSED as written: the em dash and the colon are deliberately NOT on it, because
# Rule 8.1 bans the semicolon and nothing else.
LITERAL_SWEEP = (
    "'ll", "'re", "'ve", "n't", "it's",
    "has been", "have been", "had been",
    "should", "would", "may", "might", "could",
    "is being", ", making", ", allowing", ", enabling", ", ensuring",
    ";", "e.g.", "i.e.", "etc.",
)

FILLER = (
    "simply", "just", "easily", "seamlessly", "effortlessly",
    "robust", "powerful", "comprehensive", "performant",
    "it is worth noting that", "it is important to",
    "leverage", "utilize", "in order to", "prior to",
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Publish markdown to an OnPing documentation page (MUTATING).",
    )
    p.add_argument("--id", required=True, help="Target document id")
    p.add_argument(
        "--markdown",
        help="Path to the markdown file. Required unless --trash is passed.",
    )
    p.add_argument("--title", help="Also update the document title")
    p.add_argument("--description", help="Also update the description")
    p.add_argument("--slug", help="Also update the slug (the site's URL path)")
    p.add_argument(
        "--audience",
        help="Primary persona or a job title: Users, Builders, Platformers. "
        "Required unless the markdown declares one, or --trash is passed.",
    )
    p.add_argument(
        "--section-rationale",
        help="One sentence justifying a sixth top-level section",
    )
    p.add_argument(
        "--trash",
        action="store_true",
        help="Mark this document as trash instead of publishing content: "
        "prefixes the slug with 'trash/' and the title with 'TRASH'.",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Actually publish. Without this, print the report and exit.",
    )
    return p.parse_args()


# ── audience ─────────────────────────────────────────────────────────────────


def resolve_audience(value: str) -> tuple[str, str | None]:
    """Return (persona, note). A job title maps to the closest persona."""
    v = value.strip()
    for persona in PERSONAS:
        if v.lower() == persona.lower():
            return persona, None

    mapped = TITLE_MAP.get(v.lower())
    if mapped:
        return mapped, f"mapped job title {v!r} to persona {mapped}"

    # Unrecognized title: map to the CLOSEST FIT and flag the mapping. The
    # taxonomy is explicit that a local title variation ("Reliability Engineer",
    # "Data Analyst", "Field Coordinator") maps to the nearest persona rather than
    # growing a new label, so refusing here would contradict it.
    lowered = v.lower()
    for title, persona in TITLE_MAP.items():
        if title in lowered or lowered in title:
            return persona, f"mapped unrecognized title {v!r} to nearest persona {persona}"

    # Keyword heuristics for the common families of local title variation.
    #
    # The short executive acronyms MUST match on a word boundary. Plain substring
    # matching sent "Field Coordinator" to Platformers, because "coordinator"
    # contains "coo".
    ENGINEERING = ("engineer", "tech", "automation", "scada", "integrat", "developer")
    OPERATIONS = ("analyst", "operat", "manager", "coordinator", "planner", "specialist")
    EXECUTIVE_WORDS = ("ceo", "cto", "coo", "cio", "vp", "president", "founder")
    EXECUTIVE_SUBSTR = ("director", "business development")

    def has_word(text: str, words: tuple[str, ...]) -> bool:
        return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)

    # Engineering before operations, because a "SCADA Operations Tech" builds.
    if has_word(lowered, EXECUTIVE_WORDS) or any(k in lowered for k in EXECUTIVE_SUBSTR):
        persona = "Platformers"
    elif any(k in lowered for k in ENGINEERING):
        persona = "Builders"
    elif any(k in lowered for k in OPERATIONS):
        persona = "Users"
    else:
        return "", (
            f"could not map {v!r} to any persona. The three canonical personas are "
            f"{', '.join(PERSONAS)} — they are peers, not a hierarchy, and a new "
            "persona label is never invented. Pass one of the three directly, or "
            "a recognized job title."
        )
    return persona, (
        f"NOT a recognized title: mapped {v!r} to nearest persona {persona} by "
        "keyword. CONFIRM this mapping is right before publishing."
    )


def audience_from_markdown(md: str) -> str | None:
    """Find an audience declaration the writer put in the document itself."""
    m = re.search(
        r"(?im)^\s*(?:[*_#>\s-]*)?(?:target\s+audience|audience|primary)\s*[:\-]\s*(.+)$",
        md,
    )
    if not m:
        return None
    line = m.group(1)
    for persona in PERSONAS:
        if re.search(rf"\b{persona}\b", line, re.I):
            return persona
    return line.strip(" *_`") or None


# ── hard gates ───────────────────────────────────────────────────────────────


def find_open_questions(md: str) -> str | None:
    m = re.search(r"(?im)^\s{0,3}#{1,6}\s*.*open\s+questions.*$", md)
    return m.group(0).strip() if m else None


def top_level_sections(md: str) -> list[str]:
    """Every h2 heading, ignoring fenced code blocks."""
    out, fenced = [], False
    for line in md.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = re.match(r"^\s{0,3}##\s+(.+?)\s*$", line)
        if m:
            out.append(m.group(1).strip())
    return out


# ── the soft report ──────────────────────────────────────────────────────────


def strip_untouchables(md: str) -> str:
    """Remove code fences and inline code before sweeping for violations.

    Constraint 13: code blocks, inline code, identifiers, commands, flags, paths,
    quoted errors, and log lines are never rewritten, so they are never swept.
    """
    md = re.sub(r"```.*?```", " ", md, flags=re.S)
    md = re.sub(r"`[^`]*`", " ", md)
    return md


def rule_86_words(sentence: str) -> int:
    """Count words under Rule 8.6, where a parenthesised aside, a quoted string,
    a number with units, and a backticked identifier each count as ONE word."""
    s = re.sub(r"\([^)]*\)", "P", sentence)
    s = re.sub(r'"[^"]*"', "Q", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)  # a link is its text
    return len([w for w in s.split() if w.strip()])


def prose_report(md: str) -> list[str]:
    """Mechanical findings only. NEVER blocks, NEVER changes the exit code.

    This is a courtesy to the writer, not enforcement. See the module docstring
    for why a hard gate on these rules was rejected.
    """
    findings: list[str] = []
    body = strip_untouchables(md)

    hits = [t for t in LITERAL_SWEEP if t in body]
    if hits:
        findings.append(
            "literal sweep (Part A step 3): " + ", ".join(repr(h) for h in hits)
        )

    filler = [f for f in FILLER if re.search(rf"\b{re.escape(f)}\b", body, re.I)]
    if filler:
        findings.append("filler (constraint 11): " + ", ".join(filler))

    # Sentence caps: 25 words descriptive. Prose lines only — skip headings,
    # list items, and table rows, which are not sentences.
    over = []
    for para in re.split(r"\n\s*\n", body):
        p = para.strip()
        if not p or p.startswith(("#", "|", ">", "-", "*")) or re.match(r"^\d+\.", p):
            continue
        for sent in re.split(r"(?<=[.!?])\s+", " ".join(p.split())):
            n = rule_86_words(sent)
            if n > 25:
                over.append((n, sent[:70]))
    if over:
        over.sort(reverse=True)
        findings.append(
            f"{len(over)} sentence(s) over the 25-word descriptive cap, longest "
            f"{over[0][0]}: {over[0][1]}..."
        )

    # Trailing conditions (constraint 7).
    trailing = re.findall(r"[^.\n]{18,}?\b(?:if|when)\b[^.\n]{0,50}", body)
    trailing = [t for t in trailing if not t.strip().lower().startswith(("if", "when"))]
    if trailing:
        findings.append(
            f"{len(trailing)} trailing condition(s) (constraint 7): "
            f"{trailing[0].strip()[:70]}..."
        )

    # Synonym rotation (constraint 8).
    for group in (
        ("check", "verify", "confirm", "validate"),
        ("config", "settings", "configuration"),
    ):
        present = [w for w in group if re.search(rf"\b{w}\w*", body, re.I)]
        if len(present) > 1:
            findings.append(
                "synonym rotation (constraint 8): " + " / ".join(present) + " — pick one"
            )

    return findings


def section_report(md: str, rationale: str | None) -> tuple[list[str], str | None]:
    """Return (findings, hard_error)."""
    findings: list[str] = []
    sections = top_level_sections(md)
    lowered = [s.lower() for s in sections]

    missing = [
        want for want in FIVE_SECTIONS if want.lower() not in lowered
    ]
    if missing:
        findings.append("missing section(s): " + ", ".join(missing))

    extra = [
        s for s in sections
        if s.lower() not in {w.lower() for w in FIVE_SECTIONS}
    ]
    if extra and not rationale:
        return findings, (
            "Refusing to publish: the document adds top-level section(s) beyond "
            f"the five: {', '.join(extra)}.\n"
            "Pass --section-rationale '<one sentence>' to justify the addition."
        )
    if extra:
        findings.append(
            f"sixth section accepted with rationale: {', '.join(extra)} — {rationale}"
        )
    return findings, None


def main() -> int:
    args = parse_args()
    key = resolve_key()

    # Resolve the target so the dry run names what it would overwrite.
    text = call_tool(key, "findDocs", {"id": args.id, "depth": 0})
    target = next(
        (b for b in extract_json_blocks(text) if "title" in b or "id" in b), {}
    )

    payload: dict = {"id": args.id}
    findings: list[str] = []
    notes: list[str] = []

    # ── trash mode: mark, do not publish ──
    if args.trash:
        cur_slug = target.get("slug") or ""
        cur_title = target.get("title") or ""
        new_slug = (
            cur_slug if cur_slug.startswith(TRASH_SLUG_PREFIX)
            else TRASH_SLUG_PREFIX + (cur_slug or f"doc-{args.id}")
        )
        new_title = (
            cur_title if cur_title.startswith(TRASH_TITLE_PREFIX)
            else f"{TRASH_TITLE_PREFIX} - delete me ({cur_title or 'untitled'})"
        )
        payload.update(
            {
                "content": TRASH_BODY,
                "slug": new_slug,
                "title": new_title,
                "description": (
                    "TRASH - safe to delete. Marked because the API cannot delete "
                    "documents (a known server-side bug)."
                ),
            }
        )
        notes.append(
            "TRASH MODE — marking, not moving. This server has no trash folder and "
            "`category` is not settable, so the marker lives on the slug and title."
        )
    else:
        if not args.markdown:
            print(
                "Refusing to run: --markdown <path> is required unless --trash is "
                "passed.",
                file=sys.stderr,
            )
            return 1
        md_path = Path(args.markdown).expanduser()
        if not md_path.is_file():
            print(f"No such markdown file: {md_path}", file=sys.stderr)
            return 1
        md = md_path.read_text(encoding="utf-8")

        # ── HARD GATE: audience ──
        declared = args.audience or audience_from_markdown(md)
        if not declared:
            print(
                "Refusing to publish: no audience declaration.\n"
                f"The three canonical OnPing personas are {', '.join(PERSONAS)}. "
                "They are peers, not a hierarchy.\n"
                "Declare one with --audience, or add a 'Target Audience:' line to "
                "the markdown.",
                file=sys.stderr,
            )
            return 1
        persona, note = resolve_audience(declared)
        if not persona:
            print(f"Refusing to publish: {note}", file=sys.stderr)
            return 1
        if note:
            notes.append(note)
        notes.append(f"audience: Primary = {persona}")

        # ── HARD GATE: no Open Questions in a published document ──
        oq = find_open_questions(md)
        if oq:
            print(
                f"Refusing to publish: the markdown contains {oq!r}.\n"
                "Open Questions are internal workflow record and are never "
                "published. Reframe each ACTIONABLE item as a Troubleshooting "
                "entry with a symptom-first title, and leave the rest in the "
                "intake trace.",
                file=sys.stderr,
            )
            return 1

        # ── HARD GATE: a sixth section needs a rationale ──
        sec_findings, hard = section_report(md, args.section_rationale)
        findings.extend(sec_findings)
        if hard:
            print(hard, file=sys.stderr)
            return 1

        findings.extend(prose_report(md))

        payload["content"] = md
        notes.append(
            f"markdown: {len(md.encode('utf-8'))} bytes, {len(md.split())} words"
        )

    if args.title:
        payload["title"] = args.title
    if args.description:
        payload["description"] = args.description
    if args.slug:
        payload["slug"] = args.slug

    # ── report ──
    print(f"Target document {args.id}:")
    print(f"  current title: {target.get('title')!r}")
    print(f"  current slug:  {target.get('slug')!r}")
    print(f"  status:        {target.get('_status')}")
    for n in notes:
        print(f"  {n}")

    if findings:
        print("\nProse and structure report (ADVISORY — does not block publication):")
        for f in findings:
            print(f"  - {f}")
        print(
            "  These are authoring obligations, not gates. No script checks the "
            "prose;\n  the self-check in SKILL.md is the only enforcement before a "
            "customer reads it."
        )
    else:
        print("\nProse and structure report: no mechanical findings.")

    if not args.yes:
        print(
            "\nDRY RUN — nothing was published. Re-run with --yes.\n"
            "Target is a LIVE customer-facing documentation site."
        )
        return 0

    result = call_tool(key, "updateDocWithMarkdown", payload)
    print()
    print(result.rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
