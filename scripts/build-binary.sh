#!/bin/bash
# Apply this port's patch to a clean Skyward v0.2.0 checkout and build the
# arm64 recovery binary.
#
#   SKYWARD_SRC=~/skyward ./scripts/build-binary.sh [out-binary]
#
# Requires: a Skyward v0.2.0 source tree, Rust stable, Android NDK r29,
# cargo-ndk, and the aarch64-linux-android standard library for the active
# toolchain (rustup target add aarch64-linux-android).
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SRC=${SKYWARD_SRC:?set SKYWARD_SRC to a Skyward v0.2.0 checkout}
OUT=${1:-$ROOT/skyward-tb322fc-recovery}

cd "$SRC"
git rev-parse --verify HEAD >/dev/null
# v0.2.0 is commit 22528ba ("chore: release 0.2.0").
if ! git apply --check "$ROOT/patches/skyward-tb322fc.patch" 2>/dev/null; then
  echo "the patch does not apply cleanly; is this a clean v0.2.0 tree?" >&2
  exit 1
fi
git apply "$ROOT/patches/skyward-tb322fc.patch"

export ANDROID_NDK_HOME=${ANDROID_NDK_HOME:-/opt/android-ndk-r29}
export PATH="$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/bin:$HOME/.cargo/bin:$PATH"

cargo ndk -t arm64-v8a --platform 30 build --locked --release -p skyward
cp target/aarch64-linux-android/release/skyward "$OUT"
chmod 755 "$OUT"
sha256sum "$OUT"
