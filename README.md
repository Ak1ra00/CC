# COLDCARD Tamagotchi

> **This is an unofficial fork. It is not made, endorsed, or supported by Coinkite.**
> It is firmware for a COLDCARD Mk4 that you have *retired from Bitcoin forever*.
> It is signed with the public developer key, which every COLDCARD bootloader
> treats as "somebody random built this" and warns you about at every boot.
> **Do not put a seed on a device running this. Do not sign anything with it.**
> See [NOTICE](NOTICE). Coinkite's original README is [README-coldcard.md](README-coldcard.md).

A $200 steel-clad, dual-secure-element, air-gapped, paranoid Bitcoin signing device
whose remaining purpose is keeping a small creature alive.

| | |
|---|---|
| ![egg](pet/screenshots/sim/01_egg.png) | ![hatched](pet/screenshots/sim/03_feed.png) |
| ![poop](pet/screenshots/sim/05_hungry_poop.png) | ![clean](pet/screenshots/sim/06_clean.png) |
| ![PIN drill](pet/screenshots/sim/12_pin_drill.png) | ![sick](pet/screenshots/sim/14_sick.png) |
| ![R.I.P.](pet/screenshots/sim/15_rip.png) | ![epitaph](pet/screenshots/sim/16_epitaph.png) |

*Real frames from Coinkite's desktop simulator running this firmware's MicroPython code,
captured headlessly in CI by [`pet/tools/sim_drive.py`](pet/tools/sim_drive.py) (all 18
are in [`pet/screenshots/sim/`](pet/screenshots/sim/)). More creatures, rendered through
the same `display.py` and fonts by `pet/tools/render.py`:*

| | | |
|---|---|---|
| ![](pet/screenshots/stage_1_baby.png) | ![](pet/screenshots/stage_2_child.png) | ![](pet/screenshots/stage_3_teen.png) |
| ![](pet/screenshots/adult_body0_eyes0.png) | ![](pet/screenshots/adult_body1_eyes1.png) | ![](pet/screenshots/adult_body2_eyes2.png) |
| ![](pet/screenshots/stage_5_elder.png) | ![](pet/screenshots/situation_tired.png) | ![](pet/screenshots/situation_pat.png) |

## What it does

- **Time only passes while the device is powered.** There is no battery-backed clock
  in a COLDCARD, so the pet does not experience time while unplugged. Unplugging it
  is putting it to bed; it wakes up rested, having dreamed something.
- **It can only die on your watch.** It ages only while the pet screen is up. Neglect
  has to be witnessed. Death is permanent: a tombstone is written to the card *before*
  the save files are deleted, and there is no undo, resurrect, or reset.
- **The microSD card *is* the pet.** Saves live on the card, atomically (two alternating
  slots, counter + CRC32). Pull the card and you've taken the creature. Insert it into
  another COLDCARD running this firmware and it wakes up there. No card, or a card it
  can't use: it says so on a full screen, and only plays in RAM if you explicitly agree,
  with the header blinking `NOT SAVING! RAM ONLY` the whole time. The card must be
  **FAT32** — see [The card](#the-card).
- **Genetics from the real hardware TRNG.** Each egg's genome is 32 bytes straight off
  the STM32 true-random generator (`ckcc.rng_bytes`), the path Coinkite fixed after the
  [2021–2026 entropy bug](README-coldcard.md#security-advisory). Appetite, temperament
  (sunny / grumpy / anxious / feral), stubbornness, immune system, lifespan, body shape,
  eye style and name all come from it. Two pets do not feel the same.
- **Sneakernet breeding.** Two living adults on one card can be bred into an egg whose
  genome is a per-byte mix of both parents plus fresh TRNG mutations. Generation and
  parentage go in the save. Pets travel between devices by handing someone a card.
- **NFC, via a phone.** Mk4's NFC is a passive tag, so two COLDCARDs can't tap each
  other. A phone can read the pet off one device (*NFC: Beam Pet*) and write it into
  another (*NFC: Receive Pet*). SD stays the real transport.
- **Graveyard.** Every death leaves a tombstone: name, lifetime stats, genome, cause,
  and a generated epitaph. *Pet menu → Graveyard* reads them back.
- **It has opinions.** The status line is the creature talking. Grumpy ones say things
  like "Your PIN was better." Anxious ones keep asking whether the card is still in.

## Controls

The pet screen maps actions straight onto the keypad. Key **8** shows this on-device.

```
 1  Feed (meal)      2  Snack           3  Play (minigames)
 4  Clean poop       5  Medicine        6  Scold
 7  Status/stats     8  Help            9  Pet menu
 0  Make it talk    OK  Pat it          X  Leave the pet screen
```

- **Egg:** any key warms it. It hatches after ~90 seconds of attention.
- **Minigames** (key 3): *PIN Drill* — it shows you a PIN, you type it back, rounds get
  longer; *Which Way?* — guess which way it looks with 4/6. Winning raises happiness
  and burns weight.
- **Pet menu** (key 9): Back To Pet, New Egg, Switch Pet, Breed, Graveyard, Rename,
  NFC Beam/Receive, Card Check, Help.
- After login, if a live pet is on the card it wakes up on screen automatically.
  `Virtual Pet` is also the first item of every top-level menu.

## The card

The pet is saved to the microSD card on every action, every 30 seconds while on screen,
and when you leave the pet screen. On the card it looks like this:

```
pets/<id>.a  pets/<id>.b     two alternating save slots (counter + CRC32; a yanked
                             cable corrupts at most the slot being written)
pets/active.txt              which pet is on screen
pets/graveyard/<id>.json     tombstones
```

- The card has to be **FAT32**, which is what the COLDCARD firmware can mount. Cards over
  32 GB usually ship formatted as exFAT and *will not mount*; the device still detects
  them, so the pet screen reports `card detected but it will not mount` and offers a
  retry. **Advanced/Tools → File Management → Format SD Card** on the device makes it
  FAT32 (and erases it).
- If the pet screen ever shows a new egg when you expected your pet, open the pet menu
  (**9**) → **Card Check**. It mounts the card and lists exactly what it finds: every
  save slot with its counter and the pet's name, the active pointer, tombstones, free
  space, and any file it could not parse. Press **1** there to force a save and see the
  result.
- A save that fails mid-life is never silent: a `Not Saving!` screen names the error,
  the header blinks, and the pet keeps living in RAM. Fix or re-insert the card and the
  next save just works ("Card is back. Saved.").
- Up to 30 seconds of the pet's life can be lost to a power cut. Never the pet.

## Caring for it

Three gauges on the left: **F**ood, **J**oy, **Z**zz (energy). Poop appears on the floor
some minutes after meals; leave it and the pet gets sick (skull icon). Sick pets need
medicine (5), sometimes twice. A `!` means it wants something; ignore a real call for
five minutes and that's a *care mistake*, which shortens its life. Stubborn, undisciplined
pets throw fake tantrums and refuse food — scold them (6) when they do, and only then.
Snacks are fun and fattening. Energy only comes back from sleep, and sleep only comes
from unplugging it.

It dies of: starvation, untreated sickness, a broken heart, too many snacks, or old age.

All decay rates, thresholds, stage timings and lifespan are in **one labelled block** at
the top of [`shared/pet_model.py`](shared/pet_model.py) (`TUNING KNOBS`).

## Get the firmware

The current build is committed in [`releases/`](releases/) next to its SHA-256
(`tamagotchi-sha256.txt`), and published on the
[Releases page](https://github.com/Ak1ra00/CC/releases) together with the simulator
screenshots from the same CI run.

## Building

The `.dfu` is built by GitHub Actions on every push
([`.github/workflows/pet-firmware.yml`](.github/workflows/pet-firmware.yml)) inside
Coinkite's own build container, and attached as a workflow artifact
(`tamagotchi-mk4-dfu`). The same workflow builds the desktop simulator, runs the pet in
it headlessly on real MicroPython, and fails if anything deviates from the scripted
life story or the simulator prints a traceback. Tags named `pet-v*` publish a GitHub
Release with the `.dfu`, its SHA-256 and the simulator frames.

Locally (Linux/macOS/WSL with Docker):

```bash
git clone --branch tamagotchi https://github.com/Ak1ra00/CC.git && cd CC
git submodule update --init external/micropython external/libngu external/mpy-qr external/ckcc-protocol
git -C external/micropython submodule update --init lib/stm32lib
git -C external/libngu/libs submodule update --init bech32 cifra secp256k1
sed 's/musl-dev make/musl-dev gcc make/' stm32/dockerfile.build | docker build -t coldcard-build -
docker run --rm -v "$PWD:/work/src" -w /work/src -e HOME=/tmp -u "$(id -u):$(id -g)" coldcard-build sh stm32/pet-build.sh
ls stm32/*.dfu
```

Version string is `5.6.2p` (upstream 5.6.2 + pet). Never sign with `signit --high_water`.

### Tests (no toolchain needed)

```bash
pip install pytest pillow
cd pet && python -m pytest
python pet/tools/render.py          # re-render the screenshots
```

`pet/tests/` runs the pet model against a fake clock (one tick = one awake-second), the
card store against a temp directory, and the whole UX loop — ticker, autosave, death,
menus, minigames, breeding, card yank — under CPython asyncio with a scripted keypad.

### Desktop simulator

Coinkite's simulator (`unix/`) needs Linux/macOS (WSL on Windows): follow
[unix/README.md](unix/README.md) for `make setup && make`, then

```bash
cd unix && ./simulator.py --pet            # boots straight into the pet
./simulator.py --pet --eject               # no card: the Card? screen, RAM mode
./simulator.py                             # a pet already on the card wakes up by itself
```

The simulated card is `unix/work/MicroSD/`; the pet's files appear under `pets/` there
and survive restarts, which is how the reboot path gets tested. `^Z` snapshots the
screen, `^S`/`^E` records a GIF. What CI runs against this, headless, on every push
(`pet/tools/sim_drive.py`): one full life from egg to tombstone; a second pet raised,
the simulator killed, relaunched, and the pet found again with its age and meals; a boot
with no card; and a card that stops mounting mid-life, then recovers.

## Flashing

Prerequisites: a Mk4 (or Mk5) with a **main PIN set** — the firmware upgrade path is
only available after login. Nothing here touches the bootloader; it cannot be replaced
and always runs first.

1. Take `*-mk-tamagotchi.dfu` from [`releases/`](releases/) or the
   [Releases page](https://github.com/Ak1ra00/CC/releases). Check its SHA-256 against
   `tamagotchi-sha256.txt` / `built-sha256.txt` from the same build.
2. Copy it to a microSD card. On the device: **Advanced/Tools → Upgrade Firmware →
   From MicroSD**, pick the file, confirm. (Or over USB: `pip install ckcc-protocol` then
   `ckcc upgrade file.dfu`.)
3. On reboot the bootloader shows a large warning that the firmware is signed with a
   dev key, plus a forced delay. **This is expected and normal**, every single boot.
4. Log in with your PIN. A `Virtual Pet` item is at the top of the menu. Put a card in.

The Mk4 has one microSD slot; the pet and any firmware `.dfu` can share the card.

## Back to official firmware

The path back is the same path in: download the official `.dfu` from
[coldcard.com/downloads](https://coldcard.com/downloads), verify it against Coinkite's
signed `signatures.txt`, put it on a card, **Advanced/Tools → Upgrade Firmware → From
MicroSD** (or `ckcc upgrade`). The bootloader verifies Coinkite's signature and the
warning goes away.

Two things could break that path, and this fork guards against both:

- The bootloader has one-way *downgrade protection*: an OTP "high-water" timestamp
  that, once raised, refuses any firmware with an older build date. It is raised **only**
  by *Danger Zone → Set High-Water* (which this fork disables) or by a firmware header
  flag (`signit --high_water`, which the build never sets). Installing this fork does
  not raise it. **Never** re-enable or use either on a build newer than the official
  release you want to return to.
- Nothing in *Brick Me*, trick PINs, PIN/secure-element handling, or the bootloader is
  modified by this fork. `git diff upstream/master..tamagotchi -- shared/` shows exactly
  what changed: five new `pet_*.py` modules, their entries in `manifest.py`, menu
  wiring in `flow.py`, one hook in `main.py`, the splash text, and the disabled
  Set High-Water item.

If your COLDCARD ever refuses an official image as a "downgrade", pick a newer official
release than this build's timestamp; that will always be accepted.

## Layout

```
shared/pet_model.py    the creature: stats, stages, genome, breeding, death, words  (pure Python)
shared/pet_sprites.py  ASCII-art bodies, eyes, mouths, props -> Display.icon() tuples
shared/pet_draw.py     every screen as a plain function of (display, pet, frame)
shared/pet_store.py    atomic two-slot saves, tombstones, active pointer, card adapter
shared/pet_ux.py       async UX: PetScreen, ticker, menus, minigames, NFC relay
pet/tests/             pytest: model, store, UX under a fake clock
pet/tools/             fakehw.py (pure-Python framebuf + real display.py), fakeux.py, render.py
stm32/pet-build.sh     container build + key-zero signing
```

## Licence

Coinkite's firmware is MIT + Commons Clause ([COPYING-CC](COPYING-CC), via `LICENSE`)
and that continues to cover this fork as a whole. The new pet files are additionally
offered under plain MIT ([LICENSE-PET](LICENSE-PET)). See [NOTICE](NOTICE).
