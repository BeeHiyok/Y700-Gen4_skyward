#!/bin/bash
# Build the Skyward recovery image for the Lenovo LEGION Y700 (4th gen, TB322FC)
# from the phone's own TWRP recovery_b image.
#
#   ./scripts/make-image.sh <base recovery_b.img> <skyward binary> <out.img>
#
# The base is the recovery_b partition as the phone shipped it (TWRP).  The
# script replaces the recovery binary and the device configuration, and drops
# in the two ramdisk files this port rewrites:
#
#   init.recovery.qcom.rc        the vendor init block that starts the crypto
#                                stack (KeyMint, Gatekeeper, SPU, Weaver)
#   system/etc/vintf/manifest.xml  the framework manifest that declares them
#
# Requires: python3, lz4.  No device is touched.
set -euo pipefail

BASE=${1:?usage: make-image.sh <base recovery_b.img> <skyward binary> <out.img>}
BINARY=${2:?}
OUT=${3:?}
ROOT=$(cd "$(dirname "$0")/.." && pwd)

test -f "$BASE" || { echo "no base image $BASE" >&2; exit 1; }
test -f "$BINARY" || { echo "no skyward binary $BINARY" >&2; exit 1; }

python3 - "$BASE" "$BINARY" "$OUT" "$ROOT" <<'PY'
import hashlib, pathlib, subprocess, sys, tempfile
sys.path.insert(0, sys.argv[4] + '/scripts')
import port_tool

base, binary, out, root = sys.argv[1], sys.argv[2], sys.argv[3], pathlib.Path(sys.argv[4])

img = port_tool.BootImage.read(pathlib.Path(base))
rd = port_tool.Ramdisk.decode(img.ramdisk)

rd.replace('system/bin/recovery', pathlib.Path(binary).read_bytes())
rd.replace('skyward/device.toml', (root / 'devices/TB322FC.toml').read_bytes())
rd.replace('init.recovery.qcom.rc', (root / 'ramdisk/init.recovery.qcom.rc').read_bytes())
rd.replace('system/etc/vintf/manifest.xml', (root / 'ramdisk/system/etc/vintf/manifest.xml').read_bytes())

cpio = tempfile.NamedTemporaryFile(suffix='.cpio', delete=False)
cpio.write(port_tool.cpio_encode(rd.entries))
cpio.close()

lz4 = tempfile.NamedTemporaryFile(suffix='.lz4', delete=False)
lz4.close()
subprocess.run(['lz4', '-l', '-12', '--favor-decSpeed', '-c', cpio.name],
               stdout=open(lz4.name, 'wb'), check=True)

img.ramdisk = pathlib.Path(lz4.name).read_bytes()
image = img.to_bytes()
size = pathlib.Path(base).stat().st_size
footed = port_tool.avb_footed(image, 'recovery', size, hashlib.sha256(image).digest())
pathlib.Path(out).write_bytes(footed)
print('wrote', out, len(footed), 'bytes')
print('sha256', hashlib.sha256(footed).hexdigest())
PY
