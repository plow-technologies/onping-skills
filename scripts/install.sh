#!/usr/bin/env bash
# Install these skills without Nix.
#
# Nix is the reproducible path (see README.md). This script exists for everyone
# else: it needs only bash, and copies the same flat layout the Nix bundler
# produces, so the two installs are interchangeable.
#
# Skills install FLAT: <provider>/skills/<id>/ becomes <dest>/<id>/. Agent
# tooling scans one level below the skills root, so a nested provider directory
# hides every skill inside it.
#
# Directories are real, never symlinks — discovery walkers reject or silently
# skip symlinked skill directories.
#
# Usage:
#   ./scripts/install.sh                     install to ~/.claude and ~/.agents
#   ./scripts/install.sh --target claude     one target only
#   ./scripts/install.sh --dest DIR          an explicit skills root
#   ./scripts/install.sh --local             ./.claude/skills and ./.agents/skills
#   ./scripts/install.sh --skill explainer   one skill (repeatable)
#   ./scripts/install.sh --list              show what would be installed
#   ./scripts/install.sh --dry-run           print actions, change nothing
#   ./scripts/install.sh --uninstall         remove skills this repo provides

set -euo pipefail

SELF_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(dirname "$SELF_DIR")

DRY_RUN=0
LOCAL=0
UNINSTALL=0
LIST=0
EXPLICIT_DEST=""
TARGETS=""
WANTED=""

die() { printf 'install: %s\n' "$*" >&2; exit 1; }
say() { printf '  %s\n' "$*"; }
run() { if [ "$DRY_RUN" = 1 ]; then printf '  would: %s\n' "$*"; else "$@"; fi; }

usage() { sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dest) EXPLICIT_DEST="${2:?--dest needs a directory}"; shift 2 ;;
    --target) TARGETS="$TARGETS ${2:?--target needs a name}"; shift 2 ;;
    --skill) WANTED="$WANTED ${2:?--skill needs an id}"; shift 2 ;;
    --local) LOCAL=1; shift ;;
    --list) LIST=1; shift ;;
    --dry-run | -n) DRY_RUN=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
done

# --- discover skills --------------------------------------------------------
# Same rule as the Nix walker: a directory one level under <provider>/skills/
# that contains a SKILL.md is a skill. Its basename is the installed id.

SKILL_DIRS=""
for skills_root in "$REPO_ROOT"/*/skills; do
  [ -d "$skills_root" ] || continue
  for cand in "$skills_root"/*; do
    [ -d "$cand" ] || continue
    if [ -f "$cand/SKILL.md" ]; then
      SKILL_DIRS="$SKILL_DIRS $cand"
      continue
    fi
    # A directory with no SKILL.md is a nested GROUP, not a skill: the Nix
    # catalog discovers it via its own `subdir` entry, so its children are real
    # skills with their own ids (onping/skills/lumberjack-restore/lj-restore-*).
    # Without this second level the script installer silently ships fewer skills
    # than the Nix path, which is worse than failing.
    for sub in "$cand"/*; do
      [ -f "$sub/SKILL.md" ] || continue
      SKILL_DIRS="$SKILL_DIRS $sub"
    done
  done
done

[ -n "$SKILL_DIRS" ] || die "no skills found under $REPO_ROOT/*/skills/"

# Reject duplicate ids rather than silently letting one win; the flat layout
# means two providers with the same basename would collide at the destination.
DUPES=$(for d in $SKILL_DIRS; do basename "$d"; done | sort | uniq -d)
[ -z "$DUPES" ] || die "duplicate skill ids across providers: $(echo "$DUPES" | tr '\n' ' ')"

wants() { # id
  [ -z "$WANTED" ] && return 0
  for w in $WANTED; do [ "$w" = "$1" ] && return 0; done
  return 1
}

if [ "$LIST" = 1 ]; then
  echo "Skills in this repository:"
  for d in $SKILL_DIRS; do
    id=$(basename "$d")
    desc=$(sed -n 's/^description: *//p' "$d/SKILL.md" | head -1 | cut -c1-70)
    printf '  %-28s %s\n' "$id" "$desc"
  done
  exit 0
fi

# Validate --skill names before touching anything.
for w in $WANTED; do
  found=0
  for d in $SKILL_DIRS; do [ "$(basename "$d")" = "$w" ] && found=1; done
  [ "$found" = 1 ] || die "no such skill: $w (try --list)"
done

# --- resolve destinations ---------------------------------------------------
# Paths match agent-skills-nix defaultTargets, so a later switch to the Nix
# install lands in the same places.

target_dest() { # name
  case "$1" in
    claude)   printf '%s/skills' "${CLAUDE_CONFIG_DIR:-$HOME/.claude}" ;;
    agents)   printf '%s/.agents/skills' "$HOME" ;;
    codex)    printf '%s/skills' "${CODEX_HOME:-$HOME/.codex}" ;;
    opencode) printf '%s/.config/opencode/skills' "$HOME" ;;
    copilot)  printf '%s/.copilot/skills' "$HOME" ;;
    cursor)   printf '%s/.cursor/skills' "$HOME" ;;
    windsurf) printf '%s/.codeium/windsurf/skills' "$HOME" ;;
    *) die "unknown target: $1 (claude, agents, codex, opencode, copilot, cursor, windsurf)" ;;
  esac
}

DESTS=""
if [ -n "$EXPLICIT_DEST" ]; then
  DESTS="$EXPLICIT_DEST"
elif [ "$LOCAL" = 1 ]; then
  DESTS="$PWD/.claude/skills $PWD/.agents/skills"
elif [ -n "$TARGETS" ]; then
  for t in $TARGETS; do DESTS="$DESTS $(target_dest "$t")"; done
else
  # Default matches the flake: claude + agents.
  DESTS="$(target_dest claude) $(target_dest agents)"
fi

# --- uninstall --------------------------------------------------------------

if [ "$UNINSTALL" = 1 ]; then
  echo "==> Removing skills provided by this repository"
  for dest in $DESTS; do
    [ -d "$dest" ] || { say "skip (absent): $dest"; continue; }
    say "$dest"
    for d in $SKILL_DIRS; do
      id=$(basename "$d")
      wants "$id" || continue
      [ -e "$dest/$id" ] || continue
      run rm -rf "$dest/$id"
      [ "$DRY_RUN" = 1 ] || say "  removed $id"
    done
  done
  echo "==> Done"
  exit 0
fi

# --- install ----------------------------------------------------------------

echo "==> Installing from $REPO_ROOT"
n_skills=0
for d in $SKILL_DIRS; do wants "$(basename "$d")" && n_skills=$((n_skills + 1)); done
say "$n_skills skill(s) -> $(echo "$DESTS" | wc -w | tr -d ' ') destination(s)"

for dest in $DESTS; do
  echo "==> $dest"

  # A symlinked skills ROOT breaks discovery for everything under it.
  if [ -L "${dest%/}" ]; then
    die "$dest is a symlink; remove it and re-run (discovery rejects symlinked skill roots)"
  fi

  run mkdir -p "$dest"

  for d in $SKILL_DIRS; do
    id=$(basename "$d")
    wants "$id" || continue

    # Replace rather than merge, so a file deleted upstream does not survive.
    if [ -e "$dest/$id" ] || [ -L "$dest/$id" ]; then
      run rm -rf "$dest/$id"
    fi

    if [ "$DRY_RUN" = 1 ]; then
      printf '  would: install %s\n' "$id"
      continue
    fi

    # -L dereferences: the destination gets real files even if the source tree
    # contains symlinks. -p keeps the mode bits so scripts stay executable.
    cp -RLp "$d" "$dest/$id"

    # cp -p preserves the Nix store's read-only mode when installing from a
    # /nix/store path, which makes the next install fail. Force it writable.
    chmod -R u+w "$dest/$id" 2>/dev/null || true

    say "installed $id"
  done
done

if [ "$DRY_RUN" = 1 ]; then
  echo "==> Dry run; nothing changed"
  exit 0
fi

# --- verify -----------------------------------------------------------------

echo "==> Verifying"
fail=0
for dest in $DESTS; do
  for d in $SKILL_DIRS; do
    id=$(basename "$d")
    wants "$id" || continue
    if [ ! -f "$dest/$id/SKILL.md" ]; then
      echo "  MISSING: $dest/$id/SKILL.md" >&2
      fail=1
    elif [ -L "$dest/$id" ]; then
      echo "  SYMLINK (discovery will skip it): $dest/$id" >&2
      fail=1
    fi
  done
done

[ "$fail" = 0 ] || die "verification failed"
say "every skill is a real directory with a real SKILL.md"

cat <<EOF

==> Done

Restart your agent (or start a new session) to pick up the new skills.
To remove them:  $0 --uninstall
EOF
