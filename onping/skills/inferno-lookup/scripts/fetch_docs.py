# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Fetch Inferno documentation from OnPing and save as markdown - takes ACCESS_TOKEN."""

import json
import sys
from pathlib import Path

import requests


DOCS_DIR = Path(__file__).parent.parent / "docs"

ENDPOINTS = {
    "inferno-virtual-control.md": "https://onping.plowtech.net/script/docs",
    "inferno-ml.md": "https://onping.plowtech.net/script/ml/docs",
}


def fetch_page(url: str, access_token: str) -> str | None:
    """Fetch a page using Bearer token auth."""
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        )
        response.raise_for_status()
        content = response.text

        # The API returns JSON-encoded string, decode it
        if content.startswith('"') and content.endswith('"'):
            content = json.loads(content)

        return content
    except requests.RequestException as e:
        print(f"Error fetching {url}: {e}", file=sys.stderr)
        return None
    except json.JSONDecodeError:
        # If it's not JSON, return as-is
        return response.text


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: fetch_docs.py ACCESS_TOKEN", file=sys.stderr)
        sys.exit(1)

    access_token = sys.argv[1]
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    success_count = 0

    for filename, url in ENDPOINTS.items():
        print(f"Fetching {url}...", file=sys.stderr)
        content = fetch_page(url, access_token)

        if not content:
            print(f"Failed to fetch {url}", file=sys.stderr)
            continue

        output_path = DOCS_DIR / filename
        output_path.write_text(content)
        print(f"Saved {output_path}", file=sys.stderr)
        success_count += 1

    if success_count == len(ENDPOINTS):
        print(f"Successfully fetched {success_count} documentation files")
    else:
        print(f"Fetched {success_count}/{len(ENDPOINTS)} documentation files", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
