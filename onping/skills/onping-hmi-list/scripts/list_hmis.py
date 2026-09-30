# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""List the OnPing HMIs available to the authenticated user.

`GET /hmi/list` returns a JSON array of `HmiInfo` records — one per HMI placed on
a dashboard panel the user can see:

  { hmiInfoName, hmiInfoUuid, hmiInfoDashboardName (nullable), hmiInfoPanelName }

Read-only. This is the discovery entry point: the `hmiInfoUuid` values feed
`onping-hmi-export` / `onping-hmi-export-data` / `onping-hmi-delete`.

Note: the list is scoped to HMIs embedded on dashboard panels. A freshly
upserted HMI (e.g. an `onping-hmi-import --new` copy) that is not placed on a
panel will NOT appear here — retrieve it directly by its UUID instead.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the skills root
from _hmi_routes.hmi_http import _fail, get_json
from _hmi_routes.routes import ROUTES


def _truncate(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def main() -> None:
    p = argparse.ArgumentParser(
        description="List available OnPing HMIs via GET /hmi/list. Read-only.",
    )
    p.add_argument("access_token", help="OnPing OAuth bearer token")
    p.add_argument("--json", action="store_true", help="emit the raw JSON array")
    p.add_argument(
        "--uuids-only",
        action="store_true",
        help="print just the HMI UUIDs, space-separated (pipe into export/delete)",
    )
    p.add_argument(
        "--panel-only",
        action="store_true",
        help="only rows with a non-empty panel name",
    )
    args = p.parse_args()

    data = get_json(args.access_token, ROUTES["list"]["endpoint"])
    if not isinstance(data, list):
        _fail(f"Expected a JSON array from /hmi/list, got {type(data).__name__}.")

    if args.panel_only:
        data = [h for h in data if (h.get("hmiInfoPanelName") or "").strip()]

    if args.uuids_only:
        print(" ".join(h.get("hmiInfoUuid", "") for h in data))
        print(f"{len(data)} HMI(s)", file=sys.stderr)
        sys.exit(0)

    if args.json:
        print(json.dumps(data, indent=2))
        print(f"{len(data)} HMI(s)", file=sys.stderr)
        sys.exit(0)

    # Default: a table (uuid, name, panel, dashboard).
    if not data:
        print("No HMIs found.", file=sys.stderr)
        sys.exit(0)

    header = f"{'UUID':36}  {'NAME':24}  {'PANEL':16}  DASHBOARD"
    print(header)
    print("-" * len(header))
    for h in data:
        print(
            f"{h.get('hmiInfoUuid', ''):36}  "
            f"{_truncate(h.get('hmiInfoName'), 24):24}  "
            f"{_truncate(h.get('hmiInfoPanelName'), 16):16}  "
            f"{h.get('hmiInfoDashboardName') or ''}"
        )
    print(f"{len(data)} HMI(s)", file=sys.stderr)


if __name__ == "__main__":
    main()
