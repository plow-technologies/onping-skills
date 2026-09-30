# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Print the curated /location/add schema for the singlewell-manual driver."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _driver_add_schemas.schemas import SCHEMAS


def main() -> None:
    print(json.dumps(SCHEMAS["singlewell-manual"], indent=2))


if __name__ == "__main__":
    main()
