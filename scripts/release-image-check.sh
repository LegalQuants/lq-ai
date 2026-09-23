#!/usr/bin/env bash
# Release-image skills-corpus check: the single source of truth for the
# "Release image (skills corpus)" job in .github/workflows/ci.yml.
#
# api/Dockerfile.release bakes the repo-root skills/ corpus into the published
# api image. Half of that corpus is the skills/community submodule, and a
# checkout without submodules used to produce an image that built, started
# healthy, and simply had no community skills. The Dockerfile now guards
# against that; this script proves the guard works, in both directions:
#
#   1. a recursive checkout (this tree) builds, and the image carries
#      community SKILL.md manifests (and the firm ones);
#   2. an empty skills/community fails the build;
#   3. a skills/community carrying only repository metadata (README,
#      LICENSE) and no skills/ tree also fails the build;
#   4. a skills/community/skills/ tree with a slug directory but no
#      SKILL.md inside also fails the build.
#
# Only the `skills` stage of the Dockerfile is built (--target skills), so
# this needs no dependency install and runs in seconds. The final stage
# copies /skills from that stage verbatim, so what holds here holds for the
# published image. Set FULL_IMAGE=1 to also build the complete api release
# image for case 1 (pulls torch via docling; slow, several GB).
#
# Requirements: docker with BuildKit; a recursive checkout
# (git submodule update --init --recursive).

set -euo pipefail
cd "$(dirname "$0")/.."

DOCKERFILE=api/Dockerfile.release
IMAGE_TAG="lq-ai-release-skills-check:local"
FULL_IMAGE="${FULL_IMAGE:-0}"

# Every negative case builds from a throwaway context that carries only the
# skills tree (plus the repo-root .dockerignore, which docker reads from the
# context root). The Dockerfile itself is passed with -f from the real tree.
TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT

fail() { echo "release-image-check: FAIL: $*" >&2; exit 1; }
pass() { echo "release-image-check: ok: $*"; }

# The guard message the Dockerfile prints; an expected failure must fail
# *here*, not somewhere unrelated (a base-image pull, a syntax error).
GUARD_MARKER="no community skill manifests found"

# expect_guard_failure <case name> <context dir>
expect_guard_failure() {
  local name="$1" ctx="$2" log rc
  log="$TMP_ROOT/$name.log"
  set +e
  docker build --progress=plain --target skills -f "$DOCKERFILE" "$ctx" >"$log" 2>&1
  rc=$?
  set -e
  if [ "$rc" -eq 0 ]; then
    fail "$name: build succeeded but should have been stopped by the guard"
  fi
  if ! grep -qF "$GUARD_MARKER" "$log"; then
    echo "--- build log ($name) ---" >&2
    tail -n 40 "$log" >&2
    fail "$name: build failed, but not at the skills guard"
  fi
  pass "$name: build stopped at the guard"
}

# new_context <name> -> prints a context dir holding skills/ minus community/
new_context() {
  local dir="$TMP_ROOT/$1"
  mkdir -p "$dir/skills"
  [ -f .dockerignore ] && cp .dockerignore "$dir/"
  # Everything under skills/ except the community submodule itself.
  for entry in skills/*; do
    [ "$entry" = "skills/community" ] && continue
    cp -R "$entry" "$dir/skills/"
  done
  echo "$dir"
}

# --- Preconditions --------------------------------------------------------

host_count="$(find skills/community/skills -name SKILL.md 2>/dev/null | wc -l | tr -d ' ')"
if [ "$host_count" -eq 0 ]; then
  fail "no community SKILL.md in this checkout - run 'git submodule update --init --recursive' first"
fi
echo "release-image-check: host checkout has $host_count community skill manifests"

# --- Case 1: recursive checkout builds and carries the corpus --------------

docker build --target skills -f "$DOCKERFILE" -t "$IMAGE_TAG" . >"$TMP_ROOT/positive.log" 2>&1 \
  || { tail -n 40 "$TMP_ROOT/positive.log" >&2; fail "positive: skills stage failed to build"; }

image_community="$(docker run --rm "$IMAGE_TAG" sh -c 'find /skills/community/skills -name SKILL.md | wc -l' | tr -d ' ')"
image_firm="$(docker run --rm "$IMAGE_TAG" sh -c 'find /skills -path /skills/community -prune -o -name SKILL.md -print | wc -l' | tr -d ' ')"
[ "$image_community" -ge 1 ] || fail "positive: image has no community SKILL.md"
[ "$image_firm" -ge 1 ] || fail "positive: image has no firm SKILL.md"
[ "$image_community" -eq "$host_count" ] \
  || fail "positive: image carries $image_community community manifests, host checkout has $host_count"
pass "positive: image carries $image_community community and $image_firm firm skill manifests"

if [ "$FULL_IMAGE" = "1" ]; then
  docker build -f "$DOCKERFILE" -t "$IMAGE_TAG-full" . \
    || fail "positive (full image): api release image failed to build"
  full_count="$(docker run --rm --entrypoint sh "$IMAGE_TAG-full" -c 'find /skills/community/skills -name SKILL.md | wc -l' | tr -d ' ')"
  [ "$full_count" -eq "$host_count" ] \
    || fail "positive (full image): image carries $full_count community manifests, host checkout has $host_count"
  pass "positive (full image): api release image carries $full_count community skill manifests"
fi

# --- Case 2: empty submodule directory (checkout without submodules) ------

ctx="$(new_context empty-submodule)"
mkdir -p "$ctx/skills/community"
expect_guard_failure "empty-submodule" "$ctx"

# --- Case 3: metadata only, no skills/ tree -------------------------------

ctx="$(new_context metadata-only)"
mkdir -p "$ctx/skills/community"
find skills/community -maxdepth 1 -type f -exec cp {} "$ctx/skills/community/" \;
[ -n "$(ls -A "$ctx/skills/community")" ] || fail "metadata-only: fixture is empty; expected README/LICENSE at the submodule root"
expect_guard_failure "metadata-only" "$ctx"

# --- Case 4: skills/ tree present but no manifest in it ------------------

ctx="$(new_context no-manifest)"
mkdir -p "$ctx/skills/community/skills/some-skill"
echo "not a manifest" > "$ctx/skills/community/skills/some-skill/README.md"
expect_guard_failure "no-manifest" "$ctx"

echo "release-image-check: all cases passed"
