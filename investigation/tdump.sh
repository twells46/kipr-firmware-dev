#!/usr/bin/env bash
# Read the T1 loop-timing stats (builds/t1-timing-*) into runs/<UTC>-<label>/.
#
#   investigation/tdump.sh <label> [windows=5]
#
# A T1 image must already be flashed. Does not flash, reboot, or write
# outside /tmp on the Wombat.
set -euo pipefail
label=${1:?usage: tdump.sh <label> [windows]}
windows=${2:-5}
here=$(cd "$(dirname "$0")" && pwd)
run="$here/runs/$(date -u +%Y%m%dT%H%M%SZ)-$label"
remote=/tmp/imu-tdump
mkdir -p "$run"
{
    echo "label: $label"
    echo "utc: $(date -u +%FT%TZ)"
    echo "tool: tdump.py md5 $(md5sum < "$here/tdump.py" | cut -d' ' -f1)"
    ssh wombat 'cd ~/wombat-os/flashFiles
        echo "flashFiles/wombat.bin md5 (last flashed): $(md5sum < wombat.bin | cut -d" " -f1)"
        echo "botui running: $(pgrep -x botui >/dev/null && echo yes || echo no)"
        echo "uptime: $(uptime -p)"'
} > "$run/provenance.txt"
cat "$run/provenance.txt"; echo
ssh wombat "mkdir -p $remote"
scp -q "$here/regdump.py" "$here/tdump.py" "wombat:$remote/"
ssh wombat "python3 $remote/tdump.py --windows $windows --out $remote/tdump.json" | tee "$run/tdump.txt"
scp -q "wombat:$remote/tdump.json" "$run/"
ssh wombat "rm -rf $remote"
echo "saved $run"
