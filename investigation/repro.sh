#!/usr/bin/env bash
# Measure at-rest gyro/accel on the Wombat and pull the results back.
#
#   [LIBKIPR=<local libkipr.so>] investigation/repro.sh <label> [samples] [interval_ms]
#
# Results land in investigation/runs/<UTC timestamp>-<label>/: the sample CSV,
# its summary, and provenance.txt describing exactly what was deployed.
# Does not flash, reboot, or change anything on the Wombat besides /tmp.
# LIBKIPR tests a locally built library: it is copied to /tmp on the Wombat and
# loaded instead of /usr/lib/libkipr.so, which stays untouched.
set -euo pipefail

label=${1:?usage: repro.sh <label> [samples] [interval_ms]}
samples=${2:-2000}
interval=${3:-10}

here=$(cd "$(dirname "$0")" && pwd)
root=$(dirname "$here")
run="$here/runs/$(date -u +%Y%m%dT%H%M%SZ)-$label"
remote=/tmp/imu-run
library=/usr/lib/libkipr.so
[ -n "${LIBKIPR:-}" ] && library=$remote/libkipr.so
mkdir -p "$run"

git_state() {
    local sha dirty
    sha=$(git -C "$1" rev-parse HEAD)
    dirty=$(git -C "$1" status --porcelain --untracked-files=no | wc -l)
    echo "$sha ($(git -C "$1" rev-parse --abbrev-ref HEAD), $dirty modified files)"
}

{
    echo "label: $label"
    echo "utc: $(date -u +%FT%TZ)"
    echo "samples: $samples  interval_ms: $interval"
    echo "Wombat-Firmware: $(git_state "$root/Wombat-Firmware")"
    echo "libwallaby: $(git_state "$root/libwallaby")"
    echo "local build/Firmware/wombat.bin md5: $(md5sum < "$root/Wombat-Firmware/build/Firmware/wombat.bin" 2>/dev/null | cut -d' ' -f1)"
    ssh wombat 'cd ~/wombat-os/flashFiles
        echo "wombat kernel: $(uname -r)  debian: $(cat /etc/debian_version)"
        echo "wombat libkipr: $(dpkg-query -W -f="\${Version}" kipr) sha256 $(sha256sum /usr/lib/libkipr.so | cut -c1-16)"
        echo "flashFiles md5 (last flashed, not verified on STM32):"
        md5sum wombat.bin* | sed "s/^/  /"
        echo "botui running: $(pgrep -x botui >/dev/null && echo yes || echo no)"
        echo "uptime: $(uptime -p)"'
    if [ -n "${LIBKIPR:-}" ]; then
        echo "library under test: $LIBKIPR sha256 $(sha256sum < "$LIBKIPR" | cut -c1-16) (loaded from $library)"
    else
        echo "library under test: $library (installed)"
    fi
} > "$run/provenance.txt"
cat "$run/provenance.txt"
echo

ssh wombat "mkdir -p $remote"
scp -q "$here/wombat_sample.py" "wombat:$remote/"
[ -n "${LIBKIPR:-}" ] && scp -q "$LIBKIPR" "wombat:$library"
ssh wombat "python3 $remote/wombat_sample.py --samples $samples --interval-ms $interval --library $library --out $remote/imu" \
    | tee "$run/summary.txt"
scp -q "wombat:$remote/imu.*" "$run/"
ssh wombat "rm -rf $remote"
echo "saved $run"
