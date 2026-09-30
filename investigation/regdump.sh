#!/usr/bin/env bash
# Read the MPU9250 registers published by the E1 regdump firmware.
#
#   investigation/regdump.sh <label>
#
# The regdump firmware (builds/e1-regdump) must already be flashed. Results go
# to investigation/runs/<UTC>-<label>/ (regdump.txt, regdump.json,
# provenance.txt). Does not flash, reboot, or write outside /tmp on the Wombat.
set -euo pipefail

label=${1:?usage: regdump.sh <label>}
here=$(cd "$(dirname "$0")" && pwd)
run="$here/runs/$(date -u +%Y%m%dT%H%M%SZ)-$label"
remote=/tmp/imu-regdump
mkdir -p "$run"

{
    echo "label: $label"
    echo "utc: $(date -u +%FT%TZ)"
    echo "tool: regdump.py md5 $(md5sum < "$here/regdump.py" | cut -d' ' -f1)"
    ssh wombat 'cd ~/wombat-os/flashFiles
        echo "flashFiles/wombat.bin md5 (last flashed): $(md5sum < wombat.bin | cut -d" " -f1)"
        echo "botui running: $(pgrep -x botui >/dev/null && echo yes || echo no)"
        echo "uptime: $(uptime -p)"'
} > "$run/provenance.txt"
cat "$run/provenance.txt"
echo

ssh wombat "mkdir -p $remote"
scp -q "$here/regdump.py" "wombat:$remote/"
ssh wombat "python3 $remote/regdump.py --out $remote/regdump.json" | tee "$run/regdump.txt"
scp -q "wombat:$remote/regdump.json" "$run/"
ssh wombat "rm -rf $remote"
echo "saved $run"
