# Contributing

This repository is **export-only**. Its contents are generated from a source
repository and delivered here as pull requests from `export/<sha>` branches.
`main` is protected: every change arrives through a reviewed pull request, and
force-pushes and deletion are disabled.

- **Issues** are welcome here.
- **Pull requests** opened directly against this repository cannot be merged
  as-is: the next export rebuilds the whole tree from the source and would
  revert them. A maintainer ports an accepted change to the source repository,
  and it returns here in the next export.
- **Reviewing an export PR:** the diff is the complete change. A deletion you
  did not expect usually means a skill was dropped from the export allowlist,
  or a change was made here directly and is being reverted.

Every export is checked before it is committed: only whitelisted skills are
copied, a content scanner rejects internal hosts, private addresses, local
paths, and customer data, and the export commit shares no history with the
source repository.

Every pull request must also pass two required checks before it can merge:

- `scan` runs `scripts/scan-public.sh` over the pull request's tree. Its
  pattern list is private and reaches the run as a repository secret, and the
  log reports only file, line, and category.
- `flake-check` runs `nix flake check` and builds the skill bundle.
