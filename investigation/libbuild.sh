#!/usr/bin/env bash
# Build a libwallaby (libkipr) variant for the Wombat without touching the repo.
#
#   investigation/libbuild.sh <label> <git-ref> [patch ...]
#
# Exports <git-ref> of ../libwallaby with `git archive`, applies each patch in
# order, cross-compiles for aarch64 (toolchain/aarch64-linux-gnu.cmake), and
# leaves investigation/libbuilds/<label>/ with libkipr.so, build-info.txt
# (ref, SHA, patch md5s, toolchain, .so sha256) and copies of the patches.
# src/ and build/ are scratch. Does not deploy anything.
set -euo pipefail

label=${1:?usage: libbuild.sh <label> <git-ref> [patch ...]}
ref=${2:?usage: libbuild.sh <label> <git-ref> [patch ...]}
shift 2
here=$(cd "$(dirname "$0")" && pwd)
repo=$(dirname "$here")/libwallaby
out="$here/libbuilds/$label"

[ -e "$out" ] && { echo "$out exists; pick a new label" >&2; exit 1; }
mkdir -p "$out/src" "$out/patches"
git -C "$repo" archive "$ref" | tar -x -C "$out/src"
for patch in "$@"; do
    cp "$patch" "$out/patches/"
    patch -d "$out/src" -p1 --no-backup-if-mismatch < "$patch"
done

cmake -S "$out/src" -B "$out/build" -DCMAKE_TOOLCHAIN_FILE=toolchain/aarch64-linux-gnu.cmake > "$out/cmake.log" 2>&1 \
    || { tail -30 "$out/cmake.log" >&2; exit 1; }
cmake --build "$out/build" -j "$(nproc)" > "$out/build.log" 2>&1 || { tail -30 "$out/build.log" >&2; exit 1; }
so=$(find "$out/build" -name 'libkipr.so' -type f | head -1)
[ -n "$so" ] || { echo "libkipr.so not found in build output" >&2; exit 1; }
cp "$so" "$out/libkipr.so"

{
    echo "label: $label"
    echo "ref: $ref = $(git -C "$repo" rev-parse "$ref")"
    for patch in "$@"; do echo "patch: $(basename "$patch") md5 $(md5sum < "$patch" | cut -d' ' -f1)"; done
    echo "toolchain: $(aarch64-linux-gnu-g++ --version | head -1)"
    echo "built: $(date -u +%FT%TZ)"
    echo "libkipr.so: $(stat -c %s "$out/libkipr.so") bytes, sha256 $(sha256sum < "$out/libkipr.so" | cut -d' ' -f1)"
    echo "warnings: $(grep -c 'warning:' "$out/build.log" || true)"
} | tee "$out/build-info.txt"
