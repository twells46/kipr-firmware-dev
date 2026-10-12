#!/usr/bin/env bash
# Host-compiled differential test of handle_dma(): master vs PR 12.
#
#   investigation/pr12/harness.sh [base-ref=master] [pr-ref=origin/oscar/dma-write-bounds]
#
# Either ref may be "worktree" (the checked-out wallaby_dma.c, uncommitted).
# MASK_DONE_HI=1 leaves REG_RW_MOT_DONE bits 7:4 (the reject counter) out of
# the register comparisons.
#
# Extracts handle_dma() from each ref, compiles both against the firmware's
# register map with the DMA/IRQ calls stubbed, and feeds them identical
# packets. aRxBuffer, aTxBuffer and a 512-byte guard are laid out
# contiguously as in the STM32 memory map, so out-of-bounds reads/writes are
# observed rather than undefined. Nothing touches the Wombat.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../Wombat-Firmware" && pwd)
base=${1:-master}
pr=${2:-origin/oscar/dma-write-bounds}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

for pair in "m:$base" "p:$pr"; do
    v=${pair%%:*}; ref=${pair#*:}
    if [ "$ref" = worktree ]; then cat "$repo/Firmware/src/wallaby_dma.c"
    else git -C "$repo" show "$ref:Firmware/src/wallaby_dma.c"; fi | tr -d '\r' \
        | awk '/^void handle_dma\(\)/,/^}/' > "$work/hd_$v.c"
    gcc -O1 -w -I"$repo/Firmware/include" -DV="$v" -DSRC="\"$work/hd_$v.c\"" \
        -c "$here/harness_variant.c" -o "$work/v$v.o"
done
gcc -O1 -w -I"$repo/Firmware/include" "$here/harness_main.c" "$work/vm.o" "$work/vp.o" -o "$work/harness"
desc() { [ "$1" = worktree ] && echo "worktree ($(git -C "$repo" rev-parse --short HEAD)+dirty)" || echo "$1 = $(git -C "$repo" rev-parse --short "$1")"; }
echo "base: $(desc "$base")  pr: $(desc "$pr")"
"$work/harness"
