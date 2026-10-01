#!/usr/bin/env bash
# One heading of the E6 magnetometer rotation test: 20 s of rawmag.py.
#
#   investigation/rotstep.sh <label>     (e.g. e6-rot-000)
#
# Saves to runs/<UTC>-<label>/. Does not flash, reboot, or write outside /tmp
# on the Wombat.
set -euo pipefail
label=${1:?usage: rotstep.sh <label>}
here=$(cd "$(dirname "$0")" && pwd)
run="$here/runs/$(date -u +%Y%m%dT%H%M%SZ)-$label"
mkdir -p "$run"
{
    echo "label: $label"
    echo "utc: $(date -u +%FT%TZ)"
    echo "tool: rawmag.py md5 $(md5sum < "$here/rawmag.py" | cut -d' ' -f1)"
    ssh wombat 'echo "flashFiles/wombat.bin md5: $(md5sum < ~/wombat-os/flashFiles/wombat.bin | cut -d" " -f1)"; echo "uptime: $(uptime -p)"'
} > "$run/provenance.txt"
ssh wombat mkdir -p /tmp/rot
scp -q "$here/rawmag.py" "$here/regdump.py" wombat:/tmp/rot/
ssh wombat 'python3 /tmp/rot/rawmag.py --seconds 20 --out /tmp/rot/raw.json' | tee "$run/rawmag.txt"
scp -q wombat:/tmp/rot/raw.json "$run/"
ssh wombat rm -rf /tmp/rot
echo "saved $run"
