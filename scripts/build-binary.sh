#!/bin/bash
# Build the arm64 recovery binary from this source tree.
#
#   ./scripts/build-binary.sh [out-binary]
#
# Requires: Rust (stable, via rustup), Android NDK r29, cargo-ndk.
# The Android standard library is installed by rustup on the first run.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=${1:-$ROOT/skyward-tb322fc-recovery}

export ANDROID_NDK_HOME=${ANDROID_NDK_HOME:-/opt/android-ndk-r29}
export PATH="$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/bin:$HOME/.cargo/bin:$PATH"

cd "$ROOT"

# cargo-ndk is what turns the NDK into the linker and sysroot cargo needs.
command -v cargo-ndk >/dev/null 2>&1 || cargo install cargo-ndk
rustup target add aarch64-linux-android

cargo ndk -t arm64-v8a --platform 30 build --locked --release -p skyward

cp target/aarch64-linux-android/release/skyward "$OUT"
chmod 755 "$OUT"
ls -l "$OUT"
sha256sum "$OUT"
