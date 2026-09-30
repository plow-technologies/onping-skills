"""Spreadsheet schemas for the mqtt-json-integrator XLSX import/export routes.

TWO DIFFERENT 12-COLUMN SHEETS. They look alike — both are 12 columns with
location data in 1-3 and PID data in 4-12 — but the column MEANINGS and two of
the cell encodings differ. Mixing them up produces a sheet the server parses
without complaint into the wrong thing, so the two schemas are kept apart here
and each skill declares which flavor it handles.

Source of truth (re-verify if these drift):
  - Rules:     onping/Handler/MqttJsonIntegrator/Rules/ImportExport.hs
               (GenerationRuleExportable, xlsxSheetHeaders at :100)
  - Artifacts: onping/Handler/MqttJsonIntegrator/Artifacts/ImportExport.hs
               (ArtifactExportable, xlsxSheetHeaders at :140)
  - Sheet mechanics: onping/Handler/Xlsx/Sheet.hs, Cell.hs

SHEET MECHANICS (class defaults; neither integrator module overrides them):
  - sheet name is "Sheet1"
  - headers occupy row 1
  - data starts at row 2
  - the reader FILTERS OUT empty cells and cells holding "" or a single space,
    then reads rows 2..max_populated_row. A styled template can therefore carry
    blank-looking trailing rows without breaking the parse.

THE LOCATION-ONLY ROW. In the rules sheet, a row whose PID columns (4-12) are
all empty is a location rule with no PID rule attached — `allPidColumnsEmpty`
returns True and the PID half parses as Nothing. If SOME but not all PID columns
are filled, the import fails with
`Row <n> has incomplete PID data: <err>`. The artifacts sheet behaves the same
way via `maybePidExportable`.

ROW GROUPING ON IMPORT. Rules import does NOT use the sheet's row order as the
rule identity. `reconstructGenerationRules` groups consecutive rows by the
CONTENT of columns 1-3 (selector name + location name + location match) — so
every PID of one location must sit in a CONTIGUOUS BLOCK of rows repeating that
location's three columns. Non-adjacent rows repeating the same location produce
two separate location rules. Identifiers are then assigned from position, which
is why a round-trip renumbers everything.

CELL ENCODING DIFFERENCE — the one real trap between the two sheets:

    "PID Read Only"   rules sheet     -> BOOLEAN   (preReadOnly :: Bool)
                      artifacts sheet -> "ReadOnly" | "Writeable"

The rules sheet stores a bool because `PidRuleExportable.preReadOnly` is a
`Bool`, converted to/from the `ReadOnly`/`Writeable` sum at the boundary. The
artifacts sheet stores the sum's text directly. The boolean reader is lenient —
`XlsxCell Bool` (Cell.hs) accepts a real bool, the strings "true"/"false"
case-insensitively, and the numbers 0/1 — but the writer emits a real
`CellBool`, so that is what we emit.
"""

from __future__ import annotations

SHEET_NAME = "Sheet1"
HEADER_ROW = 1
FIRST_DATA_ROW = 2

# Columns 4-12 (1-indexed) carry PID data in BOTH sheets. All-empty => the row
# is a location-only row; partially-empty => the import errors.
PID_COLUMN_RANGE = range(4, 13)

# ─────────────────────────── the generation-rule sheet ─────────────────────
# GET .../rules/export/{filename} and POST .../rules/import

RULES_HEADERS = [
    "Location Selector Name",  # 1  lreSelectorName   — internal label, free text
    "Location Name",           # 2  lreRuleName       — MqttRuleText, the location's name
    "Location Match",          # 3  lreLocationId     — MqttRuleText, the UNIQUENESS key
    "PID Selector Name",       # 4  preSelectorName   — internal label, free text
    "PID Topic",               # 5  preId             — MqttRuleText, PID uniqueness key
    "PID Time",                # 6  preTime           — JQ selector
    "PID Time Format",         # 7  preTimeFmt        — TIME_FORMATS (see below)
    "PID Description",         # 8  preDescription    — MqttRuleText
    "PID Value",               # 9  preValue          — JQ selector
    "PID Type",                # 10 preType           — PID_TYPES
    "PID Read Only",           # 11 preReadOnly       — BOOLEAN (see module docstring)
    "PID Local Only",          # 12 preLocalOnly      — LOCAL_ONLY
]

# WHICH COLUMN IS THE KEY. Column 3 ("Location Match") is the uniqueness key —
# a location is identified by the result of running that rule against a
# topic/message pair (README.md; data-lifetime-and-uniqueness-rules.md,
# "Creatable locations are uniquely defined by the result of the executing the
# 'Location Match' rule"). Column 2 ("Location Name") is the display name and
# need not be unique.
#
# Column 3's backing field is confusingly named `locationRuleLocationId` (via
# `lreLocationId`) even though it holds the match expression, not an id —
# verified in `convertGenerationRule`, where
# `lreLocationId = locationRuleLocationId` and `lreRuleName = locationRuleName`,
# read against the column order in `toXlsxRow`. Do not trust the `-- ^` comments
# on the `LocationRule` record in Types.hs: they are shifted by one field
# relative to what they describe.

# ───────────────────────────── the artifacts sheet ─────────────────────────
# GET .../artifacts/export/{filename} and POST .../artifacts/import

ARTIFACTS_HEADERS = [
    "Location Unique Identifier",  # 1  sleUniqueIdentifier — the location key
    "Location Name",               # 2  sleName
    "Location ID Ref",             # 3  sleLocationIdRef    — INT, OnPing's real location refId
    "PID Description",             # 4  speDescription
    "PID Topic",                   # 5  speTopic            — resolved topic, not a rule
    "PID Value Selector",          # 6  speValueSelector    — JQ
    "PID Time Selector",           # 7  speTimeSelector     — JQ
    "PID Time Format",             # 8  speTimeFormat       — TIME_FORMATS
    "PID Value Type",              # 9  speValueType        — PID_TYPES
    "PID Value",                   # 10 speValue            — the captured value, as text
    "PID Read Only",               # 11 speReadOnly         — READ_ONLY strings, NOT a bool
    "PID Local Only",              # 12 speLocalOnly        — LOCAL_ONLY
]

# The artifacts sheet holds RESOLVED values, not rules: column 5 is an actual
# MQTT topic and columns 6-7 are plain JQ selectors, whereas the rules sheet's
# equivalents are rule expressions that may contain {topic|s#...#...#} and
# template fields.
#
# Column 3 is an integer OnPing location refId. On import it is trusted
# verbatim and becomes both storedLocationIdRef and every PID's
# storedPidLocationIdRef — the integrator does not verify it exists.

# ────────────────────────────── cell vocabularies ──────────────────────────
# All verified against the XlsxCell instances in both ImportExport modules.

# Column 10 (rules) / 9 (artifacts). Note the sheet spellings are SHORT — the
# JSON wire form for the same values is the longer `*ValueType` (e.g. the sheet
# says "Double" where JSON says {"unPidType": "DoubleValueType"}).
PID_TYPES = ("Bool", "Double", "Utf8Text24", "Utf8Text40", "Utf8Text184")

# Column 12. Same spelling in the sheet and in JSON.
LOCAL_ONLY = ("LocalOnly", "PushToRTUClient")

# Column 11 of the ARTIFACTS sheet only. The rules sheet uses a boolean.
READ_ONLY = ("ReadOnly", "Writeable")

# Column 7 (rules) / 8 (artifacts). "ISO" and "LumberjackTime" are bare; a
# custom format is the literal prefix "Format: " plus a Data.Time format
# string. The reader drops exactly 8 characters to recover the format, so the
# prefix must be spelled with that single trailing space.
TIME_FORMAT_ISO = "ISO"
TIME_FORMAT_LUMBERJACK = "LumberjackTime"
TIME_FORMAT_CUSTOM_PREFIX = "Format: "
TIME_FORMATS = (TIME_FORMAT_ISO, TIME_FORMAT_LUMBERJACK)


def is_valid_time_format(value: str) -> bool:
    """True if a PID Time Format cell is one the server can parse."""
    return value in TIME_FORMATS or value.startswith(TIME_FORMAT_CUSTOM_PREFIX)


def parse_bool_cell(value) -> bool | None:
    """Read a rules-sheet 'PID Read Only' cell the way XlsxCell Bool does.

    Accepts a real bool, "true"/"false" in any case, and 0/1. Returns None if
    the value is not one of those, so the caller can report a cell location.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        low = value.strip().lower()
        if low == "true":
            return True
        if low == "false":
            return False
    return None


def validate_row(
    row: list, *, flavor: str, row_number: int
) -> tuple[list[str], bool]:
    """Validate one data row against a sheet flavor.

    `flavor` is "rules" or "artifacts". Returns (errors, is_location_only).
    Mirrors the server's own checks so a bad sheet is caught before the upload
    rather than after a multipart round-trip:

      - location columns 1-3 must be present
      - PID columns are all-empty (location-only) or all-present
      - enum cells must hold a known value
    """
    if flavor not in ("rules", "artifacts"):
        raise ValueError(f"flavor must be 'rules' or 'artifacts', got {flavor!r}")

    errors: list[str] = []
    cells = list(row) + [None] * (12 - len(row))

    def blank(v) -> bool:
        return v is None or (isinstance(v, str) and not v.strip())

    for col in (1, 2, 3):
        if blank(cells[col - 1]):
            errors.append(
                f"row {row_number}, column {col} "
                f"({(RULES_HEADERS if flavor == 'rules' else ARTIFACTS_HEADERS)[col - 1]}) "
                f"is empty; location columns 1-3 are required"
            )

    pid_cells = [cells[c - 1] for c in PID_COLUMN_RANGE]
    filled = [not blank(v) for v in pid_cells]

    if not any(filled):
        return errors, True

    if not all(filled):
        missing = [
            c for c in PID_COLUMN_RANGE if blank(cells[c - 1])
        ]
        headers = RULES_HEADERS if flavor == "rules" else ARTIFACTS_HEADERS
        errors.append(
            f"row {row_number} has incomplete PID data — columns "
            f"{missing} ({', '.join(headers[c - 1] for c in missing)}) are empty. "
            f"A row must fill ALL of columns 4-12 or NONE of them; the server "
            f"rejects the sheet with 'Row {row_number} has incomplete PID data'"
        )
        return errors, False

    # Column indices differ between the flavors.
    if flavor == "rules":
        tf_col, type_col, ro_col, lo_col = 7, 10, 11, 12
    else:
        tf_col, type_col, ro_col, lo_col = 8, 9, 11, 12

    tf = cells[tf_col - 1]
    if isinstance(tf, str) and not is_valid_time_format(tf.strip()):
        errors.append(
            f"row {row_number}, column {tf_col} (PID Time Format): {tf!r} is not "
            f"{TIME_FORMAT_ISO}, {TIME_FORMAT_LUMBERJACK}, or "
            f"'{TIME_FORMAT_CUSTOM_PREFIX}<fmt>'"
        )

    ptype = cells[type_col - 1]
    if isinstance(ptype, str) and ptype.strip() not in PID_TYPES:
        errors.append(
            f"row {row_number}, column {type_col} (PID type): {ptype!r} is not one "
            f"of {', '.join(PID_TYPES)}"
        )

    ro = cells[ro_col - 1]
    if flavor == "rules":
        if parse_bool_cell(ro) is None:
            errors.append(
                f"row {row_number}, column {ro_col} (PID Read Only): {ro!r} is not a "
                f"boolean. The RULES sheet stores this as TRUE/FALSE, unlike the "
                f"artifacts sheet which uses {'/'.join(READ_ONLY)}"
            )
    else:
        if isinstance(ro, str) and ro.strip() not in READ_ONLY:
            errors.append(
                f"row {row_number}, column {ro_col} (PID Read Only): {ro!r} is not "
                f"{' or '.join(READ_ONLY)}. The ARTIFACTS sheet uses these strings, "
                f"unlike the rules sheet which uses a boolean"
            )

    lo = cells[lo_col - 1]
    if isinstance(lo, str) and lo.strip() not in LOCAL_ONLY:
        errors.append(
            f"row {row_number}, column {lo_col} (PID Local Only): {lo!r} is not one "
            f"of {', '.join(LOCAL_ONLY)}"
        )

    return errors, False


def headers_for(flavor: str) -> list:
    """The expected header row for a sheet flavor."""
    if flavor == "rules":
        return RULES_HEADERS
    if flavor == "artifacts":
        return ARTIFACTS_HEADERS
    raise ValueError(f"flavor must be 'rules' or 'artifacts', got {flavor!r}")
