#!/bin/sh
#
# pet-build.sh - build the Mk4 Tamagotchi firmware and sign it with dev key zero.
#
# Runs inside the Coinkite build container (stm32/dockerfile.build, plus a host
# gcc for mpy-cross); see .github/workflows/pet-firmware.yml. Mirrors the steps
# of repro-build.sh without the published-binary comparison, because there is
# no published binary to compare against: this is not Coinkite firmware.
#
# Output: stm32/firmware-signed.dfu  (+ .bin, .elf, .lss) and a copy named
#         stm32/<timestamp>-v<version>-mk-tamagotchi.dfu
#
set -ex

cd "$(dirname "$0")"
STM32=$PWD
export HOME=${HOME:-/tmp}

# signit (key zero lives in stm32/keys/00.pem, committed upstream on purpose)
cd ../cli
python3 -m venv /tmp/ENV
. /tmp/ENV/bin/activate
python -m pip install -q -r requirements.txt
python -m pip install -q --editable .
cd "$STM32"

# one-time: stm32lib, libngu's cifra/secp256k1, mpy-cross, board symlinks
make -f MK-Makefile setup

# the firmware itself, release flavour (DEBUG_BUILD=0), then sign with key 0
make -f MK-Makefile DEBUG_BUILD=0 all
make -f MK-Makefile firmware-signed.bin firmware-signed.dfu firmware.elf firmware.lss

# never, ever: signit ... --high_water   (see NOTICE / README, "path back to stock")

NAME="$(signit version firmware-signed.bin)-mk-tamagotchi.dfu"
cp firmware-signed.dfu "$NAME"
sha256sum firmware-signed.dfu "$NAME" firmware-signed.bin | tee built-sha256.txt
ls -la ./*.dfu
