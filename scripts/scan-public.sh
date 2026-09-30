#!/usr/bin/env bash
# Scan a tree for private markers that must never reach the public repository.
#
# THE ONE implementation of the content check. scripts/export-public.sh,
# .githooks/pre-push, and any CI check all call this script. Three copies of a
# regex list diverge, so there is exactly one copy.
#
# Patterns are the markers a repo audit actually found here, not generic
# secret-scanning heuristics. Secrets are already handled: credential blobs are
# GPG-encrypted, gitignored, and absent from history. The exposure this guards
# against is customer and internal-infrastructure data.
#
# Usage:
#   scan-public.sh <dir>                 scan a directory tree
#   scan-public.sh --paths <f1> <f2> ...  scan specific files
#   scan-public.sh --ref <git-ref>       scan a committed tree
#
# Exit 0 = clean. Exit 1 = at least one match (reported). Exit 2 = usage error.

set -euo pipefail

# Patterns live OUTSIDE this script, in a tab-separated file:
#   <section> <regex> <why> [<allow-regex>]
# section `marker` rows skip the exempt files below; `name` rows check every
# file. All rows match case-insensitively. An optional allow-regex (lowercase)
# is deleted from the lowercased line before the marker is tested, so only the
# allowed occurrence is excused (POSIX ERE has no lookarounds). Allow regexes
# must not contain `#`.
#
# Keeping the list out of the engine lets the engine be published and run as a
# CI check in a public repository while the list itself stays private: it names
# the very strings it guards against. The file defaults to scan-patterns.tsv
# beside this script; SCAN_PATTERNS_FILE overrides it. With no pattern file the
# scanner fails (exit 2) rather than pass an unchecked tree.
#
# SCAN_REDACT=1 reports only file, line, and category, never the pattern, for
# logs that other people can read.

SCAN_PATTERNS_FILE="${SCAN_PATTERNS_FILE:-$(dirname "$0")/scan-patterns.tsv}"
[ -s "$SCAN_PATTERNS_FILE" ] || {
  echo "scan-public: no pattern file at $SCAN_PATTERNS_FILE (set SCAN_PATTERNS_FILE); refusing to report clean" >&2
  exit 2
}
section_rows() { # section -> "regex<TAB>why[<TAB>allow]" lines
  grep -v '^#' "$SCAN_PATTERNS_FILE" | awk -F'\t' -v s="$1" 'BEGIN{OFS="\t"} $1==s {$1=""; sub(/^\t/,""); print}'
}
PATTERNS=$(section_rows marker)
NAME_PATTERNS=$(section_rows name)
[ -n "$PATTERNS$NAME_PATTERNS" ] || { echo "scan-public: pattern file has no rows" >&2; exit 2; }

# Inferno script hashes are 43 base64url characters plus '='. A real one is an
# opaque production identifier that resolves against a live instance, and eight
# of them survived two hand review passes because they read as noise rather than
# as data. This check is SHAPE-based rather than a denylist, so it catches the
# next one too. A synthetic replacement is one letter repeated 43 times, so
# scan_hashes() reports only strings that are NOT a single repeated character.
HASH_SHAPE='[A-Za-z0-9_-]{43}='

# Files allowed to contain the `marker` rows, because documenting them IS
# their job. Deliberately narrow: exact repo-relative paths plus the change
# directories that specify this mechanism. NOT a broad `openspec/*` — archived
# changes hold real production fixtures, and the scanner must keep reporting
# those. This exemption does NOT cover the `name` rows.
is_exempt() {
  case "$1" in
    scripts/scan-public.sh | \
    scripts/scan-patterns.tsv | \
    .githooks/pre-push | \
    docs/public-readiness.md | \
    openspec/changes/add-public-skills-subset/* | \
    openspec/changes/add-onping-skills-export/*) return 0 ;;
    *) return 1 ;;
  esac
}

hits=0

report() { # file line pattern why
  if [ "${SCAN_REDACT:-0}" = 1 ]; then
    printf '  %s:%s\n    matched — %s\n' "$1" "$2" "$4" >&2
  else
    printf '  %s:%s\n    matched /%s/ — %s\n' "$1" "$2" "$3" "$4" >&2
  fi
  hits=$((hits + 1))
}

scan_one_list() { # text_file label pattern-list
  local src="$1" label="$2" list="$3" pat why allow hit no line
  while IFS=$'\t' read -r pat why allow; do
    [ -n "$pat" ] || continue
    while IFS= read -r hit; do
      no="${hit%%:*}"
      line="${hit#*:}"
      [ -n "$no" ] || continue
      if [ -n "$allow" ]; then
        printf '%s\n' "$line" | tr '[:upper:]' '[:lower:]' | sed -E "s#$allow##g" \
          | grep -qiE "$pat" || continue
      fi
      report "$label" "$no" "$pat" "$why"
    done < <(grep -niE "$pat" "$src" 2>/dev/null || true)
  done <<<"$list"
}

scan_hashes() { # text_file label
  local src="$1" label="$2" no line tok body squeezed
  while IFS=: read -r no line; do
    [ -n "$no" ] || continue
    for tok in $(printf '%s' "$line" | grep -oE "$HASH_SHAPE" || true); do
      # Strip the '=' and collapse runs: a synthetic hash is one repeated char.
      body=${tok%=}
      squeezed=$(printf '%s' "$body" | tr -s "$(printf '%s' "$body" | cut -c1)")
      [ ${#squeezed} -eq 1 ] && continue
      report "$label" "$no" "$HASH_SHAPE" "real Inferno script hash (43-char base64url)"
    done
  done < <(grep -nE "$HASH_SHAPE" "$src" 2>/dev/null | cut -c1-300 || true)
}

scan_text() { # text_file label repo_rel_path
  local src="$1" label="$2" rel="$3"
  # Customer names are checked in EVERY file, exempt or not.
  scan_one_list "$src" "$label" "$NAME_PATTERNS"
  is_exempt "$rel" && return 0
  scan_one_list "$src" "$label" "$PATTERNS"
  # Skip the vendored minified bundles: base64 sprays false positives there.
  case "$rel" in *.min.js | *.min.css) ;; *) scan_hashes "$src" "$label" ;; esac
}

# Text parts of OOXML documents. They are zip archives, so `grep -I` would skip
# them as binary, yet their cells and paragraphs are exactly where example
# customer data ends up: a real well name sat in a spreadsheet template's
# shared strings after every text file around it had been scrubbed.
OOXML_PARTS='^(xl/sharedStrings\.xml|xl/worksheets/[^/]+\.xml|word/document\.xml)$'

scan_file() { # abs_path rel_path
  local abs="$1" rel="$2" part tmpx
  case "$rel" in
    *.xlsx | *.docx)
      tmpx=$(mktemp)
      for part in $(unzip -Z1 "$abs" 2>/dev/null | grep -E "$OOXML_PARTS" || true); do
        # The parts are single-line XML; break at tags so a hit reports a
        # readable line number instead of the whole document.
        unzip -p "$abs" "$part" 2>/dev/null | tr '<' '\n' >"$tmpx"
        scan_text "$tmpx" "$rel:$part" "$rel"
      done
      rm -f "$tmpx"
      return 0
      ;;
  esac
  # Skip other binaries.
  grep -qI . "$abs" 2>/dev/null || return 0
  scan_text "$abs" "$rel" "$rel"
}

scan_dir() { # root
  local root="$1" abs rel
  # Prune .git entirely. In a linked worktree `.git` is a FILE holding an
  # absolute gitdir path, so excluding only '*/.git/*' leaves it scannable and it
  # trips the /Users/ pattern — git plumbing, not published content.
  while IFS= read -r -d '' abs; do
    rel="${abs#"$root"/}"
    scan_file "$abs" "$rel"
  done < <(find "$root" \( -name .git \) -prune -o -type f -print0)
}

mode="${1:---help}"
case "$mode" in
  --help | -h)
    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
  --paths)
    shift
    [ $# -gt 0 ] || { echo "scan-public: --paths needs at least one file" >&2; exit 2; }
    for f in "$@"; do [ -f "$f" ] && scan_file "$f" "$f"; done
    ;;
  --ref)
    ref="${2:?scan-public: --ref needs a git ref}"
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    git archive "$ref" | tar -x -C "$tmp"
    scan_dir "$tmp"
    ;;
  *)
    [ -d "$mode" ] || { echo "scan-public: not a directory: $mode" >&2; exit 2; }
    scan_dir "${mode%/}"
    ;;
esac

if [ "$hits" -gt 0 ]; then
  echo "" >&2
  echo "scan-public: FAIL — $hits private marker match(es); this tree must not be published" >&2
  exit 1
fi

echo "scan-public: clean"
