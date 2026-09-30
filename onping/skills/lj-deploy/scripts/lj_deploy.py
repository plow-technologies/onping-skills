# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""List, install, update, and monitor packages on Lumberjack edge devices."""

import argparse
import json
import sys
from typing import Any

import requests

BASE_URL = "https://onping.plowtech.net"


def _request(
    method: str,
    path: str,
    access_token: str,
    *,
    json_body: Any = None,
    data_body: str | None = None,
    params: dict[str, str] | None = None,
) -> Any:
    """Make an authenticated request to the OnPing deploy API with retry logic."""
    url = f"{BASE_URL}{path}"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}",
    }
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    elif data_body is not None:
        headers["Content-Type"] = "text/plain;charset=UTF-8"

    tries = 0
    while True:
        try:
            resp = requests.request(
                method,
                url,
                headers=headers,
                json=json_body,
                data=data_body,
                params=params,
                allow_redirects=False,
                timeout=30,
            )
        except requests.RequestException as e:
            print(f"Request error: {e}", file=sys.stderr)
            sys.exit(1)

        if 300 <= resp.status_code < 500:
            tries += 1
            if tries >= 3:
                print(
                    f"Authentication failed too many times (status {resp.status_code}).",
                    file=sys.stderr,
                )
                sys.exit(1)
            continue

        if resp.status_code != 200:
            print(f"HTTP {resp.status_code}:\n{resp.text}", file=sys.stderr)
            sys.exit(1)

        if not resp.text.strip():
            return None

        try:
            return resp.json()
        except ValueError as e:
            print(f"Failed to decode JSON response: {e}", file=sys.stderr)
            print(f"Raw response:\n{resp.text}", file=sys.stderr)
            sys.exit(1)


def cmd_packages(access_token: str, filter_name: str | None) -> None:
    """List available packages."""
    data = _request("GET", "/lumberjack/deploy/packages", access_token)
    if filter_name:
        data = [
            p
            for p in data
            if filter_name.lower() in p.get("metadata", {}).get("pname", "").lower()
        ]
    print(json.dumps(data, indent=2))


def cmd_installed(access_token: str, serials: list[int]) -> None:
    """List installed packages on lumberjacks."""
    data = _request(
        "POST",
        "/lumberjack/deploy/packages/installed",
        access_token,
        json_body=serials,
    )
    if len(serials) == 1:
        print(json.dumps(data, indent=2))
    else:
        print(json.dumps(data, indent=2))


# Known Nix architecture triples, longest-first so a substring search matches
# the full triple (e.g. armv7l-unknown-linux-gnueabihf before any shorter prefix).
_ARCH_TRIPLES = [
    "armv7l-unknown-linux-gnueabihf",
    "aarch64-unknown-linux-gnu",
    "x86_64-unknown-linux-gnu",
    "aarch64-unknown-linux-musl",
    "x86_64-unknown-linux-musl",
]


def _parse_store_path(path: str) -> tuple[str, str] | None:
    """Parse a Nix store path into (pname, arch_triple).

    Store paths look like /nix/store/<hash>-<pname>-<arch-triple>-<version>.
    Returns None if no known arch triple is present (caller treats as unmatched).
    """
    base = path.rsplit("/", 1)[-1]
    # Strip the leading Nix hash (everything up to and including the first '-').
    _, _, rest = base.partition("-")
    for triple in _ARCH_TRIPLES:
        marker = f"-{triple}-"
        idx = rest.find(marker)
        if idx != -1:
            pname = rest[:idx]
            return pname, triple
    return None


def _fetch_installed(access_token: str, serial: int) -> list[str]:
    """Read the installed store paths for a serial.

    Returns the ordered list of installed store paths from the
    /lumberjack/deploy/packages/installed response element for this serial.
    """
    data = _request(
        "POST",
        "/lumberjack/deploy/packages/installed",
        access_token,
        json_body=[serial],
    )
    element = None
    for el in data or []:
        if el.get("lumberjack-serial") == serial:
            element = el
            break
    if element is None:
        print(
            f"No installed package set found for serial {serial}.",
            file=sys.stderr,
        )
        sys.exit(1)

    return [p["store-path"] for p in element.get("packages", [])]


def _fetch_previously_installed_hash(access_token: str, serial: int) -> str:
    """Read the optimistic-lock hash for the /package/install POST.

    The authoritative hash is the `contents` of the /lumberjack/deploy/package/
    status response (confirmed by live pilot 2026-07-01 — the `installed`
    response's own `previously-installed-hash` field is stale for this purpose).
    """
    data = _request(
        "GET",
        "/lumberjack/deploy/package/status",
        access_token,
        params={"serial": str(serial)},
    )
    if not isinstance(data, dict):
        print(
            f"status for serial {serial} returned no package-set hash "
            f"(response: {json.dumps(data)}); cannot build a safe set-replace "
            "request. The Lumberjack may have no prior install on record.",
            file=sys.stderr,
        )
        sys.exit(1)
    tag = data.get("tag")
    contents = data.get("contents")
    if not isinstance(contents, str):
        print(
            f"status for serial {serial} has tag {tag!r} with no string hash in "
            f"'contents' ({json.dumps(contents)}); cannot obtain the optimistic-"
            "lock hash. Wait for an 'InstallSucceeded' status and retry.",
            file=sys.stderr,
        )
        sys.exit(1)
    if tag not in ("InstallSucceeded", None):
        print(
            f"WARNING: status tag is {tag!r} (an install may be in flight); the "
            "hash may be stale and the POST may be rejected safely.",
            file=sys.stderr,
        )
    return contents


def _post_install(
    access_token: str,
    serial: int,
    packages: list[str],
    hash_token: str,
    yes: bool,
    *,
    keep: list[str],
    remove: list[str],
    change_pairs: list[tuple[str | None, str]],
) -> None:
    """Print the dry-run diff, and POST the set-replace only when yes is True."""
    print(f"Set-replace plan for Lumberjack {serial}:")
    print(f"  KEEP:   {len(keep)} package(s) (unchanged installed paths)")
    if remove:
        print(f"  REMOVE: {len(remove)} package(s)")
        for p in remove:
            print(f"    - {p}")
    if change_pairs:
        print(f"  ADD/UPDATE: {len(change_pairs)} package(s)")
        for old, new in change_pairs:
            if old is None:
                print(f"    + (add)    {new}")
            else:
                print(f"    ~ (update) {old}")
                print(f"               -> {new}")
    print(f"\n  Resulting packages ({len(packages)}):")
    for p in packages:
        print(f"    {p}")
    print(f"\n  previously-installed-hash: {hash_token}")

    if not yes:
        print(
            "\nDRY RUN — no changes sent. Re-run with --yes to POST this "
            "set-replace to /lumberjack/deploy/package/install."
        )
        return

    body = {
        "packages": packages,
        "lumberjack-serial": serial,
        "previously-installed-hash": hash_token,
    }
    data = _request(
        "POST",
        "/lumberjack/deploy/package/install",
        access_token,
        json_body=body,
    )
    print("\nServer response:")
    print(json.dumps(data, indent=2))


def cmd_update(
    access_token: str, serial: int, store_paths: list[str], yes: bool
) -> None:
    """Install or update packages via set-replace on /package/install.

    Reads the installed set, swaps each new path in for the installed path with
    the same package name + architecture (or appends it as an add), and POSTs the
    complete desired set. Kept packages keep their installed paths verbatim.
    """
    installed = _fetch_installed(access_token, serial)
    hash_token = _fetch_previously_installed_hash(access_token, serial)

    # Map installed (pname, arch) -> installed store path, for supersede matching.
    installed_index: dict[tuple[str, str], str] = {}
    for p in installed:
        key = _parse_store_path(p)
        if key is not None:
            installed_index[key] = p

    superseded: dict[str, str] = {}  # installed path -> new path
    adds: list[str] = []
    change_pairs: list[tuple[str | None, str]] = []
    for new_path in store_paths:
        key = _parse_store_path(new_path)
        old_path = installed_index.get(key) if key is not None else None
        if old_path is not None and old_path != new_path:
            superseded[old_path] = new_path
            change_pairs.append((old_path, new_path))
        elif old_path == new_path:
            # Already installed at this exact path; no-op but keep it in the set.
            continue
        else:
            adds.append(new_path)
            change_pairs.append((None, new_path))

    packages = [superseded.get(p, p) for p in installed] + adds
    keep = [p for p in installed if p not in superseded]
    _post_install(
        access_token,
        serial,
        packages,
        hash_token,
        yes,
        keep=keep,
        remove=[],
        change_pairs=change_pairs,
    )


def cmd_delete(
    access_token: str, serial: int, store_paths: list[str], yes: bool
) -> None:
    """Delete packages via set-replace on /package/install.

    Reads the installed set, removes each requested path (which MUST match an
    installed path exactly), and POSTs the remaining set. Kept packages keep
    their installed paths verbatim.
    """
    installed = _fetch_installed(access_token, serial)
    hash_token = _fetch_previously_installed_hash(access_token, serial)
    installed_set = set(installed)

    missing = [p for p in store_paths if p not in installed_set]
    if missing:
        print(
            "Refusing to POST: the following path(s) do not match any installed "
            f"store path on serial {serial}:",
            file=sys.stderr,
        )
        for p in missing:
            print(f"  - {p}", file=sys.stderr)
        print("\nInstalled store paths:", file=sys.stderr)
        for p in installed:
            print(f"  {p}", file=sys.stderr)
        sys.exit(1)

    remove_set = set(store_paths)
    packages = [p for p in installed if p not in remove_set]
    _post_install(
        access_token,
        serial,
        packages,
        hash_token,
        yes,
        keep=packages,
        remove=[p for p in installed if p in remove_set],
        change_pairs=[],
    )


def cmd_status(access_token: str, serial: int) -> None:
    """Check installation status."""
    data = _request(
        "GET",
        "/lumberjack/deploy/package/status",
        access_token,
        params={"serial": str(serial)},
    )
    print(json.dumps(data, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List, install, update, and monitor packages on Lumberjack edge devices."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # packages
    p_packages = subparsers.add_parser(
        "packages", help="List available packages"
    )
    p_packages.add_argument("access_token", help="OnPing OAuth2 access token")
    p_packages.add_argument(
        "--filter", dest="filter_name", help="Filter by package name substring"
    )

    # installed
    p_installed = subparsers.add_parser(
        "installed", help="List installed packages on a Lumberjack"
    )
    p_installed.add_argument("access_token", help="OnPing OAuth2 access token")
    p_installed.add_argument(
        "serials", nargs="+", type=int, help="One or more Lumberjack serial numbers"
    )

    # update
    p_update = subparsers.add_parser(
        "update", help="Install or update packages on a Lumberjack"
    )
    p_update.add_argument("access_token", help="OnPing OAuth2 access token")
    p_update.add_argument("serial", type=int, help="Lumberjack serial number")
    p_update.add_argument(
        "store_paths", nargs="+", help="Nix store paths of packages to update"
    )
    p_update.add_argument(
        "--yes",
        action="store_true",
        help="Actually POST the set-replace (default is a dry-run preview)",
    )

    # delete
    p_delete = subparsers.add_parser(
        "delete", help="Delete packages from a Lumberjack"
    )
    p_delete.add_argument("access_token", help="OnPing OAuth2 access token")
    p_delete.add_argument("serial", type=int, help="Lumberjack serial number")
    p_delete.add_argument(
        "store_paths", nargs="+", help="Nix store paths of packages to delete"
    )
    p_delete.add_argument(
        "--yes",
        action="store_true",
        help="Actually POST the set-replace (default is a dry-run preview)",
    )

    # status
    p_status = subparsers.add_parser(
        "status", help="Check installation status"
    )
    p_status.add_argument("access_token", help="OnPing OAuth2 access token")
    p_status.add_argument("serial", type=int, help="Lumberjack serial number")

    args = parser.parse_args()

    if args.command == "packages":
        cmd_packages(args.access_token, args.filter_name)
    elif args.command == "installed":
        cmd_installed(args.access_token, args.serials)
    elif args.command == "update":
        cmd_update(args.access_token, args.serial, args.store_paths, args.yes)
    elif args.command == "delete":
        cmd_delete(args.access_token, args.serial, args.store_paths, args.yes)
    elif args.command == "status":
        cmd_status(args.access_token, args.serial)


if __name__ == "__main__":
    main()
