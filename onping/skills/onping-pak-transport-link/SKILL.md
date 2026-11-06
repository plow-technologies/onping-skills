---
name: onping-pak-transport-link
description: List, show, export, create, edit and delete the PAK transport Ticket Permissive link between a PAK facility and a Lumberjack, with its bay-to-lane mappings (`--map BAY=LANE`, repeatable). MUTATING with `--yes` (preview by default, `--dry-run` wins). Every write passes a local preflight that mirrors the cloud app's rejections and an ownership check on the stored record, saves a backup first, is sent once, and is read back.
allowed-tools: Bash(uv run *)
---

# OnPing PAK Transport Link

> **⚠️ WARNING: with `--yes` this skill changes live ticket routing.**
> A link tells the cloud which Lumberjack (LJ) receives a PAK facility's ticket permissive requests, and which LJ lane each PAK bay opens. A wrong LJ, address or bay-to-lane mapping sends tickets to the wrong site or opens the wrong lane. Saving also registers the LJ's address in the switcher.
> **You must own the LJ.** Before an edit or delete the skill loads the stored record by its id through the list route and refuses (exit 3) unless you own its LJ. An edit or create also needs you to own the LJ you name. OnPing's repsert handler checks both (the stored record's LJ and the LJ in the request) before it writes anything; its delete handler checks the stored record. The skill checks first, so a refusal sends no write and names the cause.
> **Undo:** every write saves a backup JSON first and prints an `Undo:` line. An edit is undone with `set --from <backup> --yes` (add `--allow-move` when the edit moved the link to another LJ); a create with `delete --id <id> --yes`; a delete with `set --from <backup> --new-id --yes` (delete is hard, so the link comes back under a new id).

A link is one record of seven fields: a client-minted config id (UUID), the PAK facility id (sent to the LJ with each ticket) and display name, the LJ serial, the LJ host and port the switcher should reach, and a list of bay-to-lane mappings. The cloud keeps one link per LJ, lets a bay appear in one link only, and lets several bays share a lane. It stores the mappings sorted by bay id.

## Use This Skill For

- Seeing the links on the LJs you own (`list`, `get`)
- Saving links to a JSON file as a backup or a template (`export`)
- Creating a link, or editing a link's facility, address or bay-to-lane mappings (`set`)
- Moving a link to another LJ (`set --serial N --allow-move`)
- Removing a link (`delete`)

## Do Not Use This Skill For

- LJs you do not own. The list route hides their links, and the skill refuses to write them.
- The older link record (exchange and queue names). The skill supports only the seven-field record and refuses, writing nothing, if the server returns the old one.
- Lane ticket topics on the LJ itself. Use the LJ's LAS configuration.

## Related Skills

- `onping-login`: access tokens
- `lj-profile`: check an LJ's LAS profile, including the URL a create defaults to

## Commands

```bash
export ONPING_ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
LINK=~/.claude/skills/onping-pak-transport-link/scripts/pak_link.py
```

The access token comes from `$ONPING_ACCESS_TOKEN`, or from stdin with `--token-stdin` (`uv run ~/.claude/skills/onping-login/scripts/login.py | uv run … --token-stdin …`). It is never a command-line argument: `ps` shows every argument to other local users. A token as the first argument still works but is deprecated and warns.

```
pak_link.py TOKEN list (--serial N ... | --all-owned) [--json]
pak_link.py TOKEN get --id UUID [--json]
pak_link.py TOKEN export (--serial N ... | --all-owned | --id UUID) -o FILE [--json]
pak_link.py TOKEN set [--id UUID] [--from FILE [--new-id]] [--serial N [--allow-move]]
            [--facility-id TEXT] [--facility-name TEXT] [--url HOST] [--port N]
            [--map BAY=LANE ...] [--backup-dir DIR] [--yes] [--dry-run] [--json]
pak_link.py TOKEN delete --id UUID [--backup-dir DIR] [--yes] [--dry-run] [--json]
```

```bash
uv run "$LINK" list --serial 1234
uv run "$LINK" get --id "$ID"
uv run "$LINK" export --serial 1234 -o links-before.json
# create (preview, then write)
uv run "$LINK" set --serial 1234 --facility-id FAC01 --facility-name "North Yard" --map 38=1 --map 39=1
uv run "$LINK" set --serial 1234 --facility-id FAC01 --facility-name "North Yard" --map 38=1 --map 39=1 --yes
# edit: replace the mappings
uv run "$LINK" set --id "$ID" --map 38=1 --map 39=2 --yes
# restore from a backup or an export
uv run "$LINK" set --from pak-link-backups/pak-link-<id>-<time>.json --yes
uv run "$LINK" delete --id "$ID" --yes
```

- `list --serial` notes each requested LJ with no link as `no link`, or as `not owned` when you do not own it (the list route hides those).
- `get`, `set --id` and `delete` find the link by id among the links on every LJ you own. There is no get-by-id route.
- `--map BAY=LANE` is repeatable. Both are whole numbers from 0 to 2^64-1. On an edit, `--map` replaces the whole list; leave it out to keep the current mappings.
- A create mints a new UUID. `--url` defaults to the LJ's LAS profile URL and `--port` to 13180. The skill refuses if the profile has no URL and you gave no `--url`.
- `--from FILE` reads a bare record, an `export` file (pick one link with `--id` if it holds several) or a backup (it uses the `before` record). The file's id must be a link on an LJ you own; otherwise add `--new-id` to save it as a new link.
- An edit that changes `--serial` needs `--allow-move`. The cloud removes the old LJ's switcher route.
- `--backup-dir` defaults to `./pak-link-backups`. A backup is written and flushed before the write is sent, and is never overwritten.

## Preflight

Before any write, the skill refuses (exit 3, nothing sent) when:

- the mappings are empty;
- a bay appears twice;
- a bay is already in another link on an LJ you own;
- another link already exists on the target LJ;
- the host or port is invalid: the port must be 1-65535; a host of only digits and dots must be a strict IPv4 address (four parts, each 0-255, no leading zeros); any other host must be a valid DNS name (labels of letters, digits and inner hyphens, at most 63 characters each and 253 in total, and the last label not all digits). No scheme, path or port in `--url`;
- you do not own the target LJ.

The cloud also checks bays held by links on LJs you cannot see, so a save can still be refused there.

## Outcomes

- A saved write is read back and must match what was sent (mappings compared sorted by bay id).
- A 502 from the cloud app means a cloud call failed, usually registering the LJ in the switcher. The read-back decides whether anything was saved.
- A failed write is read back too. If the stored link is unchanged, the skill reports `nothing was saved`.
- A no-op (the link already matches) sends nothing and exits 0.

Exit codes: 0 ok, preview or no-op; 1 request failure, nothing written; 2 usage or input file; 3 ownership-guard or preflight refusal, a 403, or the old record shape; 4 unknown outcome or read-back mismatch (check with `get` and the backup).

## Tests

```bash
uv run --with pytest --with requests pytest onping/skills/onping-pak-transport-link/tests
```
