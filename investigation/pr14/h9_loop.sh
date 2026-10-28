#!/usr/bin/env bash
# H9 (pr14.md): alternate master and PR 14 diag2, one pr14_uv.py run each,
# while the pack drains towards the Pi's undervoltage threshold.
#
#   investigation/pr14/h9_loop.sh <first-index> <max-runs> [powers] [cells]
#
# Runs are tagged m<i> (master) or p<i> (PR 14), starting with master.
# Stops before a run if the Pi reports undervoltage while idle (pack too
# weak to compare anything), and after <max-runs>.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
i=${1:?first index}; max=${2:?max runs}
powers=${3:-400,400}; cells=${4:-A0,D50,D100,D150,D200,D300,AM}
img_m=$here/../builds/pr14-master-b2ff45e/wombat.bin
img_p=$here/../builds/pr14-merge-master+diag2/wombat.bin
for ((n = 0; n < max; n++, i++)); do
    if ((n % 2 == 0)); then tag=m$i; img=$img_m; else tag=p$i; img=$img_p; fi
    idle=$(ssh wombat 'sleep 4; vcgencmd get_throttled' | cut -d= -f2)
    if (( idle & 1 )); then echo "STOP before $tag: undervoltage while idle ($idle)"; exit 1; fi
    "$here/../flash.sh" "$img" > /dev/null 2>&1 || { echo "STOP: flash of $img failed"; exit 1; }
    sleep 2
    echo "RUN $tag $(date -u +%FT%TZ) idle throttled $idle"
    ssh -o ServerAliveInterval=5 -o ServerAliveCountMax=3 wombat \
        "sudo python3 /tmp/pr14_uv.py run $tag 6 $powers cells=$cells" > "$here/run-h9-$tag.txt" 2>&1
    echo "exit $?" >> "$here/run-h9-$tag.txt"
    scp -q "wombat:/tmp/uv-$tag.jsonl" "$here/"
    grep -E "^P=|onsets|SATURATED|RESET|rebooted=True" "$here/run-h9-$tag.txt" | sed "s/^/$tag /"
done
echo "LOOP DONE"
