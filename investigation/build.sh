#!/usr/bin/env bash
# Build a Wombat-Firmware variant without touching the repo's working tree.
#
#   investigation/build.sh <label> <git-ref> [patch ...]
#
# Exports <git-ref> with `git archive`, applies each patch in order, builds
# natively in the devcontainer, and leaves investigation/builds/<label>/ with:
#   wombat.bin, build-info.txt (ref, SHA, patch md5s, toolchain, image md5),
#   and copies of the patches. src/ and build/ are scratch (git-ignored).
# Native builds here are byte-identical to the Docker build (verified for
# 4baf206 against wombat.bin.pr8), so either is fine for comparisons.
set -euo pipefail

label=${1:?usage: build.sh <label> <git-ref> [patch ...]}
ref=${2:?usage: build.sh <label> <git-ref> [patch ...]}
shift 2
here=$(cd "$(dirname "$0")" && pwd)
repo=$(dirname "$here")/Wombat-Firmware
out="$here/builds/$label"

[ -e "$out" ] && { echo "$out exists; pick a new label" >&2; exit 1; }
mkdir -p "$out/src" "$out/patches"
git -C "$repo" archive "$ref" | tar -x -C "$out/src"
for patch in "$@"; do
    cp "$patch" "$out/patches/"
    patch -d "$out/src" -p1 --no-backup-if-mismatch < "$patch"
done

cmake -S "$out/src" -B "$out/build" -DCMAKE_TOOLCHAIN_FILE=CMake/GNU-ARM-Toolchain.cmake > "$out/cmake.log" 2>&1
cmake --build "$out/build" -j "$(nproc)" > "$out/build.log" 2>&1 || { tail -30 "$out/build.log" >&2; exit 1; }
cp "$out/build/Firmware/wombat.bin" "$out/wombat.bin"

{
    echo "label: $label"
    echo "ref: $ref = $(git -C "$repo" rev-parse "$ref")"
    for patch in "$@"; do echo "patch: $(basename "$patch") md5 $(md5sum < "$patch" | cut -d' ' -f1)"; done
    echo "toolchain: $(arm-none-eabi-gcc --version | head -1)"
    echo "built: $(date -u +%FT%TZ)"
    echo "wombat.bin: $(stat -c %s "$out/wombat.bin") bytes, md5 $(md5sum < "$out/wombat.bin" | cut -d' ' -f1)"
    echo "warnings: $(grep -c 'warning:' "$out/build.log" || true)"
} | tee "$out/build-info.txt"
