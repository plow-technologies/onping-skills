# OnPing agent skills

> **⚠️ WARNING: many of these skills change live OnPing data, and some of those
> changes cannot be undone.** Skills that create, update, import, write, delete,
> clear, deploy, or restore act on the OnPing instance and the devices your
> account can reach. Deletions, overwrites, queue clears, and Lumberjack
> restores are permanent, and a few skills act immediately with no preview.
> Each skill that changes data says so at the top of its `SKILL.md`, with what
> it changes, whether it can be undone, and how it is gated. Read that before
> you run it, or before you let an agent run it. Use these skills at your own
> risk; see [LICENSE](LICENSE).

Agent skills for [OnPing](https://onping.plowtech.net): sites, locations, and
parameters; control parameters and virtual parameters; HMI dashboards, line
graphs, custom tables, and log tables; drivers; Lumberjack devices and
restores; the MQTT integrator; ML models; reports; and the OnPing docs site.

Each skill is a directory with a `SKILL.md` (the [Agent Skills](https://agentskills.io)
format) and, usually, `scripts/` that the agent runs with [`uv`](https://docs.astral.sh/uv/).
Python dependencies are declared inline in each script (PEP 723), so `uv run`
fetches them on first use.

## Install

With Nix:

```bash
nix run .#skills-install        # copies every skill into ~/.claude/skills and ~/.agents/skills
nix run .#skills-list           # shows what the bundle contains
```

Without Nix:

```bash
./scripts/install.sh            # same flat layout, bash only
./scripts/install.sh --help     # targets, --dest, --skill, --uninstall
```

Skills install flat (`<skills-root>/<id>/`). The `_*` directories are shared
helper modules that sibling skills import, so install them alongside the rest.

## Authentication

Every API skill authenticates through `onping-login`, which exchanges an OnPing
OAuth2 refresh token for an access token. It looks for the refresh token in
this order:

1. the `ONPING_REFRESH_TOKEN` environment variable (recommended);
2. a plaintext `refresh_token` file, in the nearest ancestor of the current
   directory that has a `pyproject.toml`, then in `~/skills/onping/`, then in the
   directory that contains the installed skills root (for example `~/.claude/`
   when the skills live in `~/.claude/skills/`);
3. a GPG-encrypted `refresh_token.gpg` in the same places, decrypted with `gpg -d`.

A rotated refresh token is written back to the plaintext file it came from.
Encrypted files are never rewritten.

The `onping-doc-*` skills use a separate API key, resolved the same way from
`ONPING_DOCS_API_KEY`, then `onping-docs`, then `onping-docs.gpg`.

The skills call the OnPing API at `https://onping.plowtech.net`.

Keep token files out of version control; this repository's `.gitignore` already
lists them.

## Contributing

This repository is generated. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Copyright (c) 2026 Pak Energy LLC. All Rights Reserved. Provided as is, without
warranty; use at your own risk. See [LICENSE](LICENSE).
