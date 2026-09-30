#!/usr/bin/env bash
# Flash an image onto the Wombat's STM32 and keep the full log.
#
#   investigation/flash.sh <image>
#
# <image> is a local file (copied over) or the name of a file already in
# ~/wombat-os/flashFiles on the Wombat (e.g. wombat.bin.pr8). The log goes to
# investigation/flashes/<UTC>-<image name>.log. Does not reboot.
set -euo pipefail

image=${1:?usage: flash.sh <image>}
here=$(cd "$(dirname "$0")" && pwd)
dir=/home/kipr/wombat-os/flashFiles
mkdir -p "$here/flashes"
log="$here/flashes/$(date -u +%Y%m%dT%H%M%SZ)-$(basename "$image").log"

if [ -f "$image" ]; then
    scp -q "$image" "wombat:$dir/wombat.bin.incoming"
    ssh wombat "mv $dir/wombat.bin.incoming $dir/wombat.bin"
    echo "source: local $image md5 $(md5sum < "$image" | cut -d' ' -f1)" | tee "$log"
else
    ssh wombat "test -f $dir/$image && cp $dir/$image $dir/wombat.bin"
    echo "source: wombat $dir/$image" | tee "$log"
fi

ssh wombat "cd $dir && md5sum wombat.bin && sudo ./wallaby_flash" 2>&1 | tee -a "$log"
# stm32flash -v verifies each block; a failed flash must not look like success.
grep -q "Flashing process completed" "$log" || { echo "FLASH DID NOT COMPLETE" >&2; exit 1; }
if grep -qiE "fail|error" "$log"; then echo "FLASH LOG CONTAINS ERRORS: $log" >&2; exit 1; fi
echo "log: $log"
