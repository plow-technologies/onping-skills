---
name: onping-doc-write
description: Publish markdown to a page on the OnPing customer-facing documentation site (Payload CMS) via updateDocWithMarkdown, under a controlled-language standard and the three canonical OnPing personas. MUTATING — requires --yes. Also carries --trash for marking a discarded document the API cannot delete.
allowed-tools: Bash(gpg *), Bash(uv run *)
---

# OnPing Doc Write

Publish markdown to a page on the OnPing documentation site at
`https://onping.plowtech.net/onping-doc`.

**MUTATING.** Requires `--yes`. **The target is a live customer-facing
documentation site** — an operator sees a bad setpoint, but a customer reads a bad
page.

`updateDocWithMarkdown` is the only tool that accepts markdown, and **there is no
`updateDocs` tool at all**, so this is the only way to change a document's body.
The server converts markdown to Lexical rich text. Never hand-author Lexical.

## Usage

```bash
uv run ~/.claude/skills/onping-doc-write/scripts/write_doc.py \
  --id 14 --markdown guide.md --audience Builders --yes
```

| Option | Description |
| --- | --- |
| `--id N` | **Required.** Target document id |
| `--markdown PATH` | Required unless `--trash`. Read from disk, never from argv |
| `--audience VAL` | A persona or a job title. Required unless the markdown declares one |
| `--title` / `--description` / `--slug` | Also update these fields |
| `--section-rationale` | One sentence justifying a sixth top-level section |
| `--trash` | Mark a discarded document instead of publishing content |
| `--yes` | Actually publish |

## Three hard gates, and one advisory report

**The script blocks a publish for exactly three reasons.** Everything about the
prose is advisory.

| Blocks (exit 1) | Only reports (exit unchanged) |
| --- | --- |
| No audience declaration | Banned modals, semicolons, contractions |
| An `Open Questions` heading | Filler, Latin abbreviations |
| A sixth section with no rationale | Over-cap sentences, trailing conditions |
| | Synonym rotation, a missing section |

**No script checks the prose.** The self-check below is the only enforcement before
a customer reads the page.

That split is deliberate and it was earned. The `explainer` skill works the same
way: its `--validate` checks structure only — file extension, residency, the
content marker, required elements — and never reads a sentence. A mechanical gate
on a judgment rule produces prose that is compliant and lifeless. The explainer
measured this across 93 documents: banned modals fell 96 %, and at the same time
the 18-to-25-word band fell from 24.1 % to 19.2 %, em dashes fell 88 %, and
first-person reference fell 37 %. **The rules worked and the prose got worse.** So
the report here informs the writer and never overrides them.

## Language — the fourteen constraints

The prose follows the mechanical rules of ASD-STE100 Simplified Technical English,
adapted for documentation. These are authoring obligations on you.

1. **Classification.** Classify each passage as procedural (tells the reader what to
   do) or descriptive (explains what a thing is or does) before writing it. Every
   other rule depends on it. Do not mix the two in one passage.
2. **Sentence caps.** Procedural 20 words. Descriptive 25 words. Notes and captions
   take the descriptive limit. Per Rule 8.6 each of these counts as **one** word: a
   backticked identifier or command, a number, a number with units, an
   abbreviation, quoted text, a title, a label, a proper noun, a hyphenated word, a
   product name with a version number, and the whole of a parenthesised aside.
   **The caps are ceilings, never targets.**
3. **Paragraphs.** One topic, maximum six sentences.
4. **Verbs.** Infinitive, imperative, simple present, simple past, simple future,
   and the past participle as an adjective. No present perfect ("has been updated"
   → "we updated"). No `-ing` form as a verb.
5. **Voice.** Active. Passive only in descriptive text, and only when the agent is
   genuinely unknown.
6. **Modals.** Permitted: `can`, `will`, `must`. Banned: `should`, `would`, `may`,
   `might`, `could`. A requirement becomes `must`. A possibility becomes `can`. A
   recommendation is stated as a fact or deleted.
7. **Condition before command.** Every `if` or `when` stands at the start of its
   sentence, with a comma. "Increase the timeout if the network is slow" → "If the
   network is slow, increase the timeout."
8. **One word, one meaning.** Fix the vocabulary **before** drafting. Pick one term
   for the check / verify / confirm / validate concept and one for the config /
   settings concept, then use no other anywhere in the document.
9. **Completeness.** Keep articles. Keep the conjunction "that". No contractions.
   Short sentences with complete grammar, never telegraph style.
10. **Punctuation.** The semicolon is the **only** banned mark. The em dash and the
    colon are legal and do work no other mark does. Replace `e.g.` with "for
    example" and `i.e.` with "that is". Delete `etc.` by naming the items.
11. **Filler.** Delete words that carry no fact: `simply`, `just`, `easily`,
    `seamlessly`, `robust`, `powerful`, `comprehensive`, `it is worth noting that`.
    Replace `leverage` and `utilize` with `use`, `in order to` with `to`, `prior to`
    with `before`.
12. **Safety pattern.** In a warning the command or condition comes **first** and
    the risk second. `WARNING` for injury, `CAUTION` for damage or data loss.
13. **Untouchables.** Never rewrite code blocks, inline code, identifiers, CLI
    commands, flags, file paths, quoted error messages, log lines, product names,
    API endpoint names, or config keys. For an OnPing document this extends to
    **PIDs, Lumberjack serials, driver slugs, and parameter names.**
14. **Pointers.** Gloss every pointer on first use, naming in plain words what it
    points at, in the same sentence. A pointer is a reference whose referent the
    reader cannot recover from the reference itself — a section or step number, a
    rule number, a ticket identifier, an internal code. Apply the **deletion test**:
    remove every pointer from the sentence, and if the sentence collapses, the
    pointers ARE the claim and each must name its referent. Re-gloss after an
    intervening `h2`.

**`agents/skills/explainer/references/simple-english.md` is the authority** for the
full 53-rule catalog, the modal ladder, the part-of-speech rulings, and the
substitution tables. Read it to adjudicate a specific case. **Cite rule numbers
only from that file** — the official numbering is unintuitive and models fabricate
it from memory. That file is not duplicated here, because two copies of a standard
drift.

## The self-check — two parts, in this order

**Both parts are NOT optional.** Run them against the markdown **as it stands in
the file**, never against a draft held in context. A check run before the last edit
does not describe what gets published.

### Part A — violations

1. **Pointer sweep. Run this FIRST, before any length count.** Search for
   `\b[0-9]+[a-z]\b`, `\b[A-Z][0-9]+\b`, `\b[a-z]+[0-9]+[a-z][a-z0-9]*\b`, and for
   `Section`, `Rule`, `Step`, `Table`, `Figure`, and `Appendix` followed by a
   number. Apply the deletion test to each hit, then gloss on first use. **This runs
   first because a gloss ADDS words** — a length count taken before it measures text
   that no longer exists.
2. **Longest sentences.** Count the three longest under the Rule 8.6 count. Split
   any sentence over its cap.
3. **Literal-string sweep.** Search for `'ll`, `'re`, `'ve`, `n't`, `it's`,
   `has been`, `have been`, `had been`, `should`, `would`, `may`, `might`, `could`,
   `is being`, `, making`, `, allowing`, `, enabling`, `, ensuring`, `;`, `e.g.`,
   `i.e.`, `etc.` Every hit outside the Untouchables is a violation. **This list is
   complete as written: the em dash and the colon are NOT on it.**
4. **Condition placement.** Search every `if` and `when`. Move a trailing condition
   to the start of its sentence and add a comma.
5. **Unchosen synonyms.** Search for the members of the check / verify / confirm /
   validate set you did not choose, and for `config` / `settings` if that pair was
   not fixed.

### Part B — texture

Run **after** Part A, because Part A splits and deletes and would undo this work.
Every Part A step searches for material to delete, so Part A cannot fail a document
for being lifeless. Part B can.

6. **Distribution.** Count the Rule 8.6 length of every sentence. If the lengths
   cluster in a band narrower than about 6 words, or fewer than about one sentence
   in five lands at 18 to 25 words, combine related short claims. If more than about
   one in three lands at 18 to 25 words, split the flabbiest. **Never pad with
   filler.**
7. **Devices.** Confirm that a worked example appears wherever a setting has a
   mechanism to make legible.
8. **Re-measure after any repair**, because a repair changes the distribution it was
   measured against.

## Narrative obligations — six carry, two do not

Carried, with the same force as the constraints above:

- **Vary sentence length below the cap.** Uniform short sentences read as a telegram
  in any genre. The target is two-sided.
- **Keep the worked example.** A worked example makes a configuration field legible,
  and the filler rule does not license removing it.
- **Let each paragraph carry a developed thought.** A thought split across two
  paragraphs to stay under the cap is fragmented, not clarified.
- **Reproduce quoted material exactly** — field names, defaults, error strings, log
  lines.
- **Write captions to the 25-word descriptive limit**, never in the imperative.
- **Leave marketing register out.** An OnPing document explains. It does not sell.

**Deliberately NOT carried**, and the reason matters so a later reader does not
restore them:

- **Assert a thesis.** A field reference has no thesis. Asserting one would
  editorialize a settings table.
- **Write in the author's own voice.** A configuration guide has no author-as-agent,
  so first person is wrong here even though the explainer requires it.

## Audience — the three canonical personas

Every published document declares a target audience. The personas are **peers, not
a hierarchy**, and there are no sub-personas.

| Persona | Who they are | Titles |
| --- | --- | --- |
| **Users** | People who use OnPing to do work: pull reports, respond to alarms, light editing of what others set up | Production Manager, Business Analyst, Operations Specialist |
| **Builders** | People making scripts, dashboards, and integrations, bringing in data and creating durable artifacts | I&E Tech, Automation Tech, SCADA Tech |
| **Platformers** | People who center a business on OnPing as a platform, doing Builder and User work on behalf of their own downstream customers | CEO, Business Development, Software Developer |

A document declares a **Primary** persona (required) and MAY declare a **Secondary**
and a **NOT for** persona. The declaration is document-level, not per-section: tone
and depth are chosen once and the whole document inherits them.

An unrecognized customer job title **maps to the closest persona**, and the mapping
is reported for confirmation. A new persona label is never invented. The script
handles the common local variations — "Reliability Engineer" maps to Builders,
"Field Coordinator" to Users — and flags any keyword-derived guess with a CONFIRM
prompt.

Declare the audience with `--audience`, or put a `Target Audience:` line in the
markdown. Without one, the publish is refused.

The canonical taxonomy lives in the OnPing design documentation and is the
authority for the full title lists. It is restated here because that document is
outside this repository and this skill must work from a fresh clone.

## The five-section shape

A published document carries exactly five top-level sections, in order:

1. **Introduction** — one screen of prose: what the feature is, who it is for, and
   the top three things worth knowing before touching a setting.
2. **Setup Walkthrough** — one step per configuration surface. Each step opens with
   a plain-language goal and closes with a one-sentence "you should now see X"
   success signal.
3. **Field Reference** — every field the reader can set, with a plain-language
   explanation, the valid range or format, the default, and a typical value. See the
   format ruling below.
4. **Troubleshooting** — symptom-first entries: "if X happens, check Y". Actionable,
   not diagnostic.
5. **See Also** — links to related documents and source material.

This is the shape `onping-doc-intake` defines, and document 14 — the RabbitMQ
Forwarder Configuration Guide — already follows it.

A sixth section requires `--section-rationale`.

**A published document SHALL NOT contain an `Open Questions` section.** Open
questions are internal workflow record. An open question naming an **actionable
symptom** is reframed as a Troubleshooting entry with a symptom-first title; the
rest stay in the intake trace. The Troubleshooting section exists **even when no
open questions surfaced**, carrying baseline entries such as connectivity,
credentials, and permissions.

## Field Reference format — check for table support first

**Prefer a real markdown table whenever one renders.** A table is text, so it is
searchable, selectable, and reflowable, and a screen reader announces its rows and
cells. Every fallback gives up one or more of those.

As of 2026-08-25 this server does **not** render tables. Markdown pipes become a
paragraph of literal `|` characters, raw HTML is escaped to visible text, and a
hand-written Lexical `table` node is silently stripped. The cause is upstream of the
markdown converter: `Docs.ts` builds its editor from `...defaultFeatures`, and
Payload's defaults contain no table feature. This is a known server-side bug.

**Re-check rather than assume.** The fix is one import of
`EXPERIMENTAL_TableFeature` and one array entry, so it can land at any time. The
check is one round trip: publish a two-row pipe table to a **draft**, read the
stored `content`, and look at the node types.

- **A `table` node present** → author the Field Reference as a markdown table.
- **Pipes inside a `paragraph`** → fall back, and record which fallback in the
  intake trace.

Fallbacks, in preference order:

1. **Nested list** (default). Each field is a top-level item; default, range, and
   typical value are sub-items. Stays text, keeps every fact, costs vertical space.
2. **Definition-style paragraphs.** Compact, reads as prose, weaker for scanning.
3. **Fixed-width text in a fenced code block.** The only fallback preserving column
   alignment. Permitted above about ten fields. Renders as monospace, and a screen
   reader announces it as code.

**An SVG image of a table is the last resort and is never the default.** SVG works —
an image is opaque to the Lexical schema, so a table inside one survives where
everything else fails. The costs disqualify it for a reference readers look values
up in: the whole table collapses to one `alt` string, the content is invisible to
the site's search, it does not reflow, and its colors are baked in against a site
that styles for dark mode. Use SVG where a picture **is** the content — a diagram, a
wiring layout, a state machine.

## Screenshots work

The Setup Walkthrough wants screenshots, and the path works:

1. `POST /api/media` with the image file and the `payload-mcp-api-keys API-Key`
   header returns `201 Created` with a media id. `Media.ts` sets no `mimeTypes`
   allowlist and no filesize cap, so PNG, JPEG, and SVG are all accepted.
2. Reference it as `![alt text](media:<id>)`, **alone on its own line.** The
   transformer's pattern is anchored at both ends, so a reference sharing a line
   with other content does not convert.
3. An external image works too: `![alt](https://host/path.png)` becomes an
   `externalImage` node, with no extension check on the URL.

**A data URI does not work** — neither transformer pattern matches it, so it stays
literal text.

Every screenshot carries alt text stating what the reader is looking at.

## `--trash` — marking a document the API cannot delete

**Nothing can delete a document on this server.** The MCP plugin acts as the API
key's related user, who holds role `admin`, and `Docs.ts` permits an admin to delete
only when `data.deletedAt` is truthy. No field defines `deletedAt` and `trash: true`
is never enabled, so the branch is unreachable and **the delete control is hidden in
the admin UI for every admin.** Only an `owner`-role account can delete. This is a
known server-side bug.

A trash *category* is unreachable too, because `updateDocWithMarkdown` sets only
`title`, `slug`, `description`, and `content` — **not `category`**.

So `--trash` **marks** a document instead of moving it:

```bash
uv run ~/.claude/skills/onping-doc-write/scripts/write_doc.py --id 19 --trash --yes
```

| Field | Marker |
| --- | --- |
| `slug` | prefixed `trash-` |
| `title` | prefixed `TRASH` |
| `content` | a body explaining what it is and why it is still there |

Both markers show in the admin UI's default columns, and `onping-doc-list --trash`
lists them. The operation is idempotent — a second run does not double-prefix.

**CAUTION: the slug marker uses a hyphen, never a slash.** A slug containing `/`
makes the nested-docs plugin treat the first segment as a parent document, and the
**next** write to that document fails with
`The following field is invalid: Breadcrumbs 1 > Doc`. Field-verified 2026-08-26:
`trash/zz-table-probe` broke the following update, and `trash-zz-table-probe` does
not.

This marker is a **stopgap for a broken delete**, not a feature of the documentation
site. It disappears once an owner deletes the document or the access rule is fixed.

## Relationship to the intake skills

**This skill owns the Payload write path only.** The interview, the intake trace,
the audience decision, and the Drive artifacts belong to `onping-doc-intake` and
`onping-feature-intake`, which live outside this repository and which this
skill does not replace.

Those skills publish to Google Drive through `scripts/org-to-gdoc.sh`. **Payload is
a second destination they never learned to write to**, which is why document 14
reached the site by hand. A document still gets its audience and its content from an
intake session.

## Related

- `onping-doc-list` — find the target id; `--trash` lists marked documents.
- `onping-doc-get` — back up a document with `--json` before overwriting it.
- `onping-doc-create` — create the page first; a new page has no body.
- `_docs_routes` — the shared transport, and every trap on this service.
- `agents/skills/explainer/references/simple-english.md` — the language authority.
