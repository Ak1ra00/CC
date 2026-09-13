# pet_model.py - The creature. Pure Python, no hardware, no asyncio, no clock.
#
# Part of the unofficial COLDCARD Tamagotchi fork. See NOTICE and LICENSE-PET.
#
# Everything in here is driven by tick() calls from the outside. One tick is one
# second of AWAKE time: the device has no RTC, so the pet does not experience time
# while it is unplugged. Unplugging it is putting it to bed.
#
# Randomness is injected: pass rng=callable(n)->int in [0,n). On the device that is
# ngu.random.uniform (hardware TRNG underneath); in tests it is a seeded PRNG.
# Genomes are built from raw entropy bytes handed in by the caller.
#
try:
    import ujson as json
except ImportError:
    import json
try:
    from ubinascii import hexlify, unhexlify
except ImportError:
    from binascii import hexlify, unhexlify

SAVE_VERSION = 1

# ============================================================================
#  TUNING KNOBS
#  All durations are ticks == awake-seconds. Stats run 0..100.
#  Change numbers here; nothing below should need touching.
# ============================================================================

# --- stat decay, points per tick, before genome multipliers -----------------
HUNGER_DECAY  = 100.0 / (35 * 60)     # full belly to empty in ~35 min awake
HAPPY_DECAY   = 100.0 / (45 * 60)     # content to miserable in ~45 min awake
ENERGY_DECAY  = 100.0 / (100 * 60)    # ~100 min awake before it begs to be unplugged
DISC_DECAY    = 100.0 / (240 * 60)    # discipline erodes slowly

# --- action effects ---------------------------------------------------------
FEED_HUNGER     = 32      # one meal
FEED_WEIGHT     = 1
SNACK_HUNGER    = 8
SNACK_HAPPY     = 14
SNACK_WEIGHT    = 2
SNACK_SUGAR     = 3       # snacks-in-a-row before the sugar crash risk kicks in
PLAY_HAPPY_WIN  = 22
PLAY_HAPPY_LOSE = 6
PLAY_ENERGY     = 9
PLAY_WEIGHT     = -1
PLAY_MIN_ENERGY = 12      # below this it refuses to play
PET_HAPPY       = 3       # a poke / pat on the head
SCOLD_DISC      = 22
SCOLD_HAPPY     = -6
SCOLD_UNFAIR_HAPPY = -14  # scolding a pet that did nothing wrong
MED_BAD_TASTE   = -8      # medicine when not sick
MED_CURE_BASE   = 0.62    # chance one dose cures, times genome immune factor
CLEAN_HAPPY     = 5
FULL_THRESHOLD  = 92      # won't eat a meal above this hunger

# --- digestion / poop -------------------------------------------------------
DIGEST_TICKS    = 6 * 60  # a meal becomes a poop after this long
MAX_POOP        = 4

# --- sickness ---------------------------------------------------------------
SICK_BASE_P     = 1.0 / (90 * 60)  # per tick, healthy & clean pet
SICK_POOP_MULT  = 5.0     # per poop on screen
SICK_STARVE_MULT= 4.0     # hunger == 0
SICK_FAT_MULT   = 3.0     # overweight
SICK_COLD_MULT  = 2.5     # energy == 0 (exhaustion)
SICK_HAPPY_MULT = HAPPY_DECAY * 2.0   # extra happiness loss per tick while sick
SICK_FATAL      = 25 * 60 # untreated this long => death

# --- death timers (ticks spent at the bad extreme before it's fatal) --------
STARVE_FATAL    = 15 * 60 # hunger == 0 this long
SAD_FATAL       = 30 * 60 # happiness == 0 this long
FAT_FATAL       = 40 * 60 # weight >= 100 this long
LIFESPAN_BASE   = 10 * 3600   # awake-seconds; scaled by genome, shortened by mistakes
MISTAKE_LIFE_PCT= 2       # each care mistake knocks this % off lifespan

# --- attention calls & discipline ------------------------------------------
CALL_GRACE      = 5 * 60  # ignore a real call this long => care mistake
CALL_MISTAKE_HAPPY = -10
FALSE_CALL_P    = 1.0 / (20 * 60)   # per tick, scaled by stubbornness
FALSE_CALL_TTL  = 3 * 60  # a fake tantrum burns out on its own after this
REFUSE_P        = 0.35    # chance a stubborn, undisciplined pet refuses a command
LOW_DISC        = 35      # below this, refusals are possible

# --- life stages: age in ticks at which each stage BEGINS -------------------
STAGES = ('egg', 'baby', 'child', 'teen', 'adult', 'elder')
STAGE_AT = {
    'baby':   90,           # hatch. button mashing warms the egg (see EGG_WARM)
    'child':  15 * 60,
    'teen':   45 * 60,
    'adult':  2 * 3600,
    'elder':  6 * 3600,
}
EGG_WARM        = 2       # extra ticks of egg-age per keypress while an egg

# --- weight -----------------------------------------------------------------
WEIGHT_START    = 5
WEIGHT_STAGE_GAIN = 6     # natural growth when a stage begins
WEIGHT_FAT_LINE = {'egg': 999, 'baby': 30, 'child': 45, 'teen': 60, 'adult': 75, 'elder': 70}

# --- autosave hint for the UX layer (ticks) ---------------------------------
AUTOSAVE_EVERY  = 30

# ============================================================================
#  end of tuning knobs
# ============================================================================

TEMPERAMENTS = ('sunny', 'grumpy', 'anxious', 'feral')

# body / eye variant counts must match pet_sprites.py
NUM_BODIES = 3
NUM_EYES = 3


def _clamp(v, lo=0.0, hi=100.0):
    return lo if v < lo else (hi if v > hi else v)

def _scale(byte, lo, hi):
    # map 0..255 onto lo..hi (floats)
    return lo + (hi - lo) * (byte / 255.0)

def fmt_awake(ticks):
    # "2h13m", "48m", "0m", "3d2h" -- awake time, never wall time
    ticks = int(ticks)
    d, r = divmod(ticks, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    if d:
        return '%dd%dh' % (d, h)
    if h:
        return '%dh%02dm' % (h, m)
    return '%dm' % m


# ----------------------------------------------------------------------------
#  Names. Rolled from the genome so every creature arrives pre-named.
# ----------------------------------------------------------------------------
_ONSETS = ['b', 'bl', 'br', 'd', 'dr', 'f', 'fl', 'g', 'gl', 'gr', 'k', 'kr', 'm', 'n',
           'p', 'pl', 'pr', 's', 'sk', 'sn', 'sp', 't', 'tr', 'v', 'w', 'z', 'zl', 'skr',
           'thr', 'wh', 'j', 'sq', 'gn', 'pf']
_NUCLEI = ['a', 'e', 'i', 'o', 'u', 'oo', 'ee', 'ai', 'or', 'ub', 'ib', 'og', 'ep']
_CODAS = ['', 'b', 'bble', 'g', 'k', 'm', 'n', 'p', 'rt', 'sh', 'x', 'zz', 'mp', 'nk',
          't', 'ff', 'lt', 'nch', 'bs']

def name_from_seed(a, b):
    # a, b: two bytes
    n = _ONSETS[a % len(_ONSETS)] + _NUCLEI[(a >> 3) % len(_NUCLEI)] + _CODAS[b % len(_CODAS)]
    if b & 0x80:
        n += _NUCLEI[(b >> 2) % len(_NUCLEI)] + _CODAS[(a ^ b) % len(_CODAS)]
    n = n[:10]
    return n[0].upper() + n[1:]


# ----------------------------------------------------------------------------
#  Genome: 32 bytes of hardware entropy, decoded into a personality.
# ----------------------------------------------------------------------------
class Genome:
    SIZE = 32

    def __init__(self, raw):
        assert len(raw) == self.SIZE, 'genome must be %d bytes' % self.SIZE
        self.raw = bytes(raw)
        b = self.raw
        self.appetite    = _scale(b[0], 0.6, 1.6)     # hunger decay multiplier
        self.temperament = TEMPERAMENTS[b[1] % len(TEMPERAMENTS)]
        self.stubborn    = b[2] / 255.0               # 0 = pushover, 1 = mule
        self.lifespan    = _scale(b[3], 0.7, 1.4)     # lifespan multiplier
        self.body        = b[4] % NUM_BODIES
        self.eyes        = b[5] % NUM_EYES
        self.metabolism  = _scale(b[6], 0.6, 1.6)     # weight gain multiplier
        self.immune      = _scale(b[7], 0.5, 1.8)     # >1 = resists sickness
        self.name        = name_from_seed(b[8], b[9])
        self.energy_need = _scale(b[11], 0.7, 1.4)    # energy decay multiplier
        self.id          = hexlify(b[28:32]).decode()

    @classmethod
    def from_entropy(cls, raw):
        return cls(raw)

    @classmethod
    def breed(cls, mother, father, entropy):
        # Each byte comes from one parent, chosen by an entropy bit. Then a few
        # bytes mutate outright so lineages drift. Needs >= 40 bytes of entropy.
        assert len(entropy) >= 40
        out = bytearray(cls.SIZE)
        for i in range(cls.SIZE):
            bit = (entropy[i // 8] >> (i % 8)) & 1
            out[i] = mother.raw[i] if bit else father.raw[i]
        # mutation: 2..4 bytes get fresh entropy; id bytes (28..31) always fresh
        n_mut = 2 + (entropy[4] % 3)
        for k in range(n_mut):
            idx = entropy[5 + k] % 28
            out[idx] = entropy[8 + k]
        out[28:32] = entropy[32:36]
        return cls(bytes(out))

    def to_hex(self):
        return hexlify(self.raw).decode()

    @classmethod
    def from_hex(cls, h):
        return cls(unhexlify(h))

    def describe(self):
        # short human-readable trait list for the stats screen
        lines = []
        lines.append('Temper: ' + self.temperament)
        lines.append('Appetite: ' + ('huge' if self.appetite > 1.3 else
                                     'big' if self.appetite > 1.05 else
                                     'small' if self.appetite < 0.8 else 'normal'))
        lines.append('Stubborn: ' + ('mule' if self.stubborn > 0.75 else
                                     'yes' if self.stubborn > 0.45 else
                                     'a bit' if self.stubborn > 0.2 else 'no'))
        lines.append('Immune: ' + ('iron' if self.immune > 1.4 else
                                   'ok' if self.immune > 0.9 else 'weak'))
        lines.append('Lifespan: ' + ('long' if self.lifespan > 1.2 else
                                     'short' if self.lifespan < 0.85 else 'average'))
        return lines


# ----------------------------------------------------------------------------
#  Words. The creature has opinions.
# ----------------------------------------------------------------------------
SAYINGS = {
    'sunny': [
        "I love this steel box.",
        "Best day to be powered!",
        "You came back! Again!",
        "Entropy? I'm full of it.",
        "Verify me. I dare you.",
        "Cold storage, warm heart.",
        "Air-gapped and adorable.",
    ],
    'grumpy': [
        "Feed me or unplug me.",
        "Your PIN was better.",
        "This screen is 128 pixels.",
        "I've seen the seed. Meh.",
        "You call this a keypad?",
        "Not my keys, not my problem.",
        "Sign nothing. Ever again.",
    ],
    'anxious': [
        "Is the card still in?",
        "Check the card. Check again.",
        "What if the RNG is bad?",
        "Did you verify the hash?",
        "I hear USB. Is that USB?",
        "Don't brick me. Please.",
        "12 words or 24? I forget.",
    ],
    'feral': [
        "I bit the SD card.",
        "Show me the seed words.",
        "I want to see Brick Me.",
        "I ate a PSBT. It was fine.",
        "Let me out of the case.",
        "Where is the 25th word?",
        "Trick PIN? I AM the trick.",
    ],
}

SAYINGS_ANY = [
    "Trust, but verify my hunger.",
    "More entropy than 2021 fw.",
    "Unplug me = bedtime.",
    "I only die on your watch.",
    "The card is me. Be careful.",
    "This is my whole life now.",
    "$200 of pet. Worth it.",
    "Two secure elements, one me.",
]

# situational, in priority order (first match wins)
NEED_LINES = {
    'dead':   ["..."],
    'sick':   ["I feel like bad firmware.", "Something is wrong. Pill?", "Not... verified..."],
    'starve': ["FEED ME. Press 1.", "Empty. Like a fresh unit.", "I'd eat a seed phrase."],
    'hungry': ["Hungry. Press 1.", "Belly empty. 1 please.", "A meal would be nice. (1)"],
    'poop':   ["Clean that up. Press 4.", "There is poop. It's mine.", "Ugh. Press 4."],
    'tired':  ["Unplug me. I need sleep.", "So tired. Pull the cable.", "Bedtime = power off."],
    'sad':    ["Nobody plays with me. (3)", "Bored. Press 3.", "Entertain me. Press 3."],
    'fat':    ["Too many snacks.", "I can't see my keypad.", "Exercise? Press 3."],
    'tantrum':["ATTENTION. (fake)", "Beep beep beep. (why?)", "Pay attention to meee"],
    'full':   ["Stuffed. No more.", "Couldn't eat another bit.", "Burp."],
}

DREAMS = [
    "I dreamed of a 25th word.",
    "I dreamed I was a Ledger.",
    "I dreamed the RNG was good.",
    "I dreamed of mainnet.",
    "I dreamed you unplugged me.",
    "Dreamt of two SD slots.",
    "I dreamed I had a clock.",
]

EPITAPH_CAUSE = {
    'starvation':  "Starved while you watched.",
    'sickness':    "Died of an untreated bug.",
    'old age':     "Died of old age. Rare.",
    'neglect':     "Died of a broken heart.",
    'snacks':      "Died of snacks.",
    'unknown':     "Died. Cause: unverified.",
}

EPITAPH_FLAIR = {
    'sunny':   ["Loved everyone. Even you.", "Never stopped smiling.", "Would have forgiven you."],
    'grumpy':  ["Hated it here. Fair.", "Complained to the end.", "Told you so."],
    'anxious': ["Was right to worry.", "Never found the 25th word.", "Checked the card 9000 times."],
    'feral':   ["Went down biting.", "Was never really tame.", "Ate three PSBTs."],
}


# ----------------------------------------------------------------------------
#  The pet.
# ----------------------------------------------------------------------------
class Pet:

    def __init__(self, genome, rng, name=None, generation=1, parents=None):
        self.g = genome
        self.rng = rng
        self.id = genome.id
        self.name = name or genome.name
        self.generation = generation
        self.parents = list(parents or [])

        # vital stats 0..100
        self.hunger = 80.0
        self.happy = 70.0
        self.energy = 100.0
        self.discipline = 30.0
        self.weight = WEIGHT_START

        self.age = 0              # ticks of awake time, total
        self.stage = 'egg'
        self.poop = 0
        self.sick = False
        self.sick_t = 0
        self.alive = True
        self.cause = None

        # timers
        self.digest = []          # list of countdowns to next poop
        self.starve_t = 0
        self.sad_t = 0
        self.fat_t = 0
        self.sugar = 0            # snacks in a row
        self.call = None          # what it is yelling about, or None
        self.call_t = 0           # how long it's been yelling
        self.refusing = False     # currently being stubborn

        # lifetime counters (go on the tombstone)
        self.stats = dict(meals=0, snacks=0, games=0, wins=0, cleans=0, meds=0,
                          scolds=0, pats=0, naps=0, mistakes=0, refusals=0, tantrums=0)

        # transient (not saved): last thing that happened, for the UX to show
        self.last_event = None
        self._say_idx = 0

    # ------------------------------------------------------------------ helpers
    def _chance(self, p):
        # true with probability p (0..1)
        if p <= 0:
            return False
        if p >= 1:
            return True
        return self.rng(1000000) < int(p * 1000000)

    def _pick(self, lst):
        return lst[self.rng(len(lst))]

    def lifespan(self):
        life = LIFESPAN_BASE * self.g.lifespan
        life *= max(0.2, 1.0 - (self.stats['mistakes'] * MISTAKE_LIFE_PCT / 100.0))
        return int(life)

    def is_egg(self):
        return self.stage == 'egg'

    def overweight(self):
        return self.weight >= WEIGHT_FAT_LINE[self.stage]

    def mood(self):
        # coarse mood for sprite selection
        if not self.alive:
            return 'dead'
        if self.is_egg():
            return 'egg'
        if self.sick:
            return 'sick'
        if self.energy < 15:
            return 'tired'
        if self.hunger < 25 or self.happy < 25:
            return 'sad'
        if self.happy > 75 and self.hunger > 50:
            return 'happy'
        return 'idle'

    def need(self):
        # the most urgent thing, for the status line; None if content
        if not self.alive: return 'dead'
        if self.is_egg(): return None
        if self.sick: return 'sick'
        if self.hunger <= 0: return 'starve'
        if self.poop: return 'poop'
        if self.hunger < 30: return 'hungry'
        if self.energy < 15: return 'tired'
        if self.happy < 30: return 'sad'
        if self.overweight(): return 'fat'
        if self.call == 'tantrum': return 'tantrum'
        return None

    def says(self):
        # one line of text for the screen. Needs first, then personality.
        n = self.need()
        if n:
            lines = NEED_LINES[n]
            return lines[(self.age // 7) % len(lines)]
        if self.is_egg():
            return ['...', '(wobble)', 'Keep it warm: press keys.'][(self.age // 5) % 3]
        pool = SAYINGS[self.g.temperament] + SAYINGS_ANY
        return pool[(self.age // 11 + self._say_idx) % len(pool)]

    def say_something_else(self):
        # user pressed the "talk" key
        self._say_idx += 1
        return self.says()

    def hearts(self, v):
        # 0..4 for display bars
        return min(4, int(v / 25.0 + 0.5))

    # ------------------------------------------------------------------ time
    def tick(self, n=1):
        # advance n awake-seconds. Returns list of notable events that happened.
        events = []
        for _ in range(n):
            if not self.alive:
                break
            self.age += 1
            self._tick_once(events)
        return events

    def _tick_once(self, ev):
        g = self.g
        if self.is_egg():
            self._maybe_grow(ev)
            return

        self.hunger = _clamp(self.hunger - HUNGER_DECAY * g.appetite)
        self.happy = _clamp(self.happy - HAPPY_DECAY * (2.0 if self.poop else 1.0)
                            - (SICK_HAPPY_MULT if self.sick else 0.0))
        self.energy = _clamp(self.energy - ENERGY_DECAY * g.energy_need)
        self.discipline = _clamp(self.discipline - DISC_DECAY)

        # digestion
        if self.digest:
            self.digest = [d - 1 for d in self.digest]
            while self.digest and self.digest[0] <= 0:
                self.digest.pop(0)
                if self.poop < MAX_POOP:
                    self.poop += 1
                    ev.append('poop')

        # sickness roll
        if not self.sick:
            p = SICK_BASE_P / g.immune
            if self.poop: p *= SICK_POOP_MULT * self.poop
            if self.hunger <= 0: p *= SICK_STARVE_MULT
            if self.overweight(): p *= SICK_FAT_MULT
            if self.energy <= 0: p *= SICK_COLD_MULT
            if self.sugar > SNACK_SUGAR: p *= 2.0
            if self._chance(p):
                self.sick = True
                self.sick_t = 0
                ev.append('sick')
        else:
            self.sick_t += 1
            if self.sick_t >= SICK_FATAL:
                self._die('sickness', ev)
                return

        # fatal timers
        self.starve_t = self.starve_t + 1 if self.hunger <= 0 else 0
        self.sad_t = self.sad_t + 1 if self.happy <= 0 else 0
        self.fat_t = self.fat_t + 1 if self.weight >= 100 else 0
        if self.starve_t >= STARVE_FATAL:
            self._die('starvation', ev); return
        if self.sad_t >= SAD_FATAL:
            self._die('neglect', ev); return
        if self.fat_t >= FAT_FATAL:
            self._die('snacks', ev); return
        if self.age >= self.lifespan():
            self._die('old age', ev); return

        # attention calls
        real = self.need() not in (None, 'tantrum', 'full', 'fat')
        if real:
            if self.call != 'real':
                self.call = 'real'
                self.call_t = 0
            self.call_t += 1
            if self.call_t == CALL_GRACE:
                self.stats['mistakes'] += 1
                self.happy = _clamp(self.happy + CALL_MISTAKE_HAPPY)
                ev.append('mistake')
        elif self.call == 'real':
            self.call = None
            self.call_t = 0
        elif self.call == 'tantrum':
            self.call_t += 1
            if self.call_t >= FALSE_CALL_TTL:
                self.call = None
                self.call_t = 0
        elif self._chance(FALSE_CALL_P * g.stubborn * (2.0 if self.discipline < LOW_DISC else 0.5)):
            self.call = 'tantrum'
            self.call_t = 0
            self.stats['tantrums'] += 1
            ev.append('tantrum')

        self._maybe_grow(ev)

    def _maybe_grow(self, ev):
        cur = STAGES.index(self.stage)
        for st in STAGES[cur + 1:]:
            if self.age >= STAGE_AT[st]:
                self.stage = st
                self.weight += WEIGHT_STAGE_GAIN
                ev.append('grow:' + st)
                if st == 'baby':
                    # fresh out of the shell: hungry, happy, awake
                    self.hunger, self.happy, self.energy = 60.0, 80.0, 100.0
                    ev.append('hatch')

    def _die(self, cause, ev):
        self.alive = False
        self.cause = cause
        self.call = None
        ev.append('death')

    # ------------------------------------------------------------------ sleep
    def wake(self):
        # Called when the device boots with this pet loaded: it just slept.
        if not self.alive or self.is_egg():
            return None
        self.stats['naps'] += 1
        self.energy = 100.0
        self.sugar = 0
        self.refusing = False
        if self.call == 'tantrum':
            self.call = None
        return self._pick(DREAMS)

    # ------------------------------------------------------------------ stubborn
    def _refuses(self):
        # stubborn + undisciplined pets sometimes ignore you
        if self.discipline >= LOW_DISC or self.g.stubborn < 0.2:
            return False
        if self._chance(REFUSE_P * self.g.stubborn):
            self.refusing = True
            self.stats['refusals'] += 1
            return True
        return False

    # ------------------------------------------------------------------ actions
    # Each returns (ok, message). ok=False means nothing happened.
    def warm_egg(self):
        if not self.is_egg():
            return False, None
        self.age += EGG_WARM
        ev = []
        self._maybe_grow(ev)
        return True, ('It hatched!' if 'hatch' in ev else '(wobble)')

    def feed(self):
        if not self.alive: return False, "It's dead. Feed the grief."
        if self.is_egg(): return False, "Eggs don't eat. Warm it."
        if self.hunger > FULL_THRESHOLD:
            return False, self._pick(NEED_LINES['full'])
        if self._refuses():
            return False, "Refuses to eat. Scold? (6)"
        self.hunger = _clamp(self.hunger + FEED_HUNGER)
        self.weight = _clamp(self.weight + FEED_WEIGHT * self.g.metabolism)
        self.digest.append(int(DIGEST_TICKS / self.g.metabolism))
        self.sugar = 0
        self.stats['meals'] += 1
        self.refusing = False
        return True, self._pick(["Nom.", "Chomp chomp.", "Delicious bits.", "*eats the whole thing*"])

    def snack(self):
        if not self.alive: return False, "..."
        if self.is_egg(): return False, "Eggs don't snack."
        self.hunger = _clamp(self.hunger + SNACK_HUNGER)
        self.happy = _clamp(self.happy + SNACK_HAPPY)
        self.weight = _clamp(self.weight + SNACK_WEIGHT * self.g.metabolism)
        self.sugar += 1
        self.stats['snacks'] += 1
        self.digest.append(int(DIGEST_TICKS * 1.5))
        if self.sugar > SNACK_SUGAR:
            return True, "Sugar rush. Uh oh."
        return True, self._pick(["Ooh! Snack!", "Sweet!", "Crunch.", "More. Now."])

    def can_play(self):
        if not self.alive or self.is_egg():
            return False, "No."
        if self.energy < PLAY_MIN_ENERGY:
            return False, "Too tired. Unplug me."
        if self.sick:
            return False, "Too sick to play."
        if self._refuses():
            return False, "Won't play. Stubborn."
        return True, None

    def play_result(self, won, score=0):
        # call after a minigame finishes
        self.stats['games'] += 1
        if won:
            self.stats['wins'] += 1
            self.happy = _clamp(self.happy + PLAY_HAPPY_WIN)
        else:
            self.happy = _clamp(self.happy + PLAY_HAPPY_LOSE)
        self.energy = _clamp(self.energy - PLAY_ENERGY)
        self.weight = _clamp(self.weight + PLAY_WEIGHT, 1)
        self.refusing = False
        return True, ("Yes! Again!" if won else "Hmph. Again.")

    def clean(self):
        if not self.alive: return False, "..."
        if not self.poop:
            return False, "Nothing to clean. Suspicious."
        self.poop = 0
        self.happy = _clamp(self.happy + CLEAN_HAPPY)
        self.stats['cleans'] += 1
        return True, "Much better."

    def medicine(self):
        if not self.alive: return False, "Too late for that."
        if self.is_egg(): return False, "Eggs can't swallow."
        self.stats['meds'] += 1
        if not self.sick:
            self.happy = _clamp(self.happy + MED_BAD_TASTE)
            return True, "Wasn't sick. Tastes awful."
        if self._chance(min(0.95, MED_CURE_BASE * self.g.immune)):
            self.sick = False
            self.sick_t = 0
            return True, "Cured! (probably)"
        return True, "Still sick. One more?"

    def scold(self):
        if not self.alive: return False, "..."
        if self.is_egg(): return False, "You scolded an egg."
        self.stats['scolds'] += 1
        if self.call == 'tantrum' or self.refusing:
            self.call = None
            self.call_t = 0
            self.refusing = False
            self.discipline = _clamp(self.discipline + SCOLD_DISC)
            self.happy = _clamp(self.happy + SCOLD_HAPPY)
            return True, "Sulks. Lesson learned."
        self.discipline = _clamp(self.discipline + SCOLD_DISC / 4)
        self.happy = _clamp(self.happy + SCOLD_UNFAIR_HAPPY)
        return True, "It did nothing wrong!"

    def pat(self):
        if not self.alive: return False, "Cold."
        if self.is_egg(): return self.warm_egg()
        self.stats['pats'] += 1
        if self.g.temperament == 'grumpy' and self._chance(0.4):
            return True, "Don't touch me."
        if self.g.temperament == 'feral' and self._chance(0.25):
            self.happy = _clamp(self.happy + 1)
            return True, "*bites you* (affection)"
        self.happy = _clamp(self.happy + PET_HAPPY)
        return True, self._pick(["*purrs in 120 MHz*", "*happy beep*", "*leans in*"])

    # ------------------------------------------------------------------ death
    def tombstone(self):
        # dict written to the graveyard. Includes a generated epitaph.
        assert not self.alive
        cause = self.cause or 'unknown'
        flair = EPITAPH_FLAIR[self.g.temperament]
        flair = flair[self.g.raw[13] % len(flair)]
        epitaph = "Here lies %s. %s Awake %s. %s" % (
            self.name, EPITAPH_CAUSE.get(cause, EPITAPH_CAUSE['unknown']),
            fmt_awake(self.age), flair)
        return dict(v=SAVE_VERSION, id=self.id, name=self.name, genome=self.g.to_hex(),
                    generation=self.generation, parents=self.parents, cause=cause,
                    age=self.age, stage=self.stage, weight=int(self.weight),
                    stats=dict(self.stats), epitaph=epitaph,
                    temperament=self.g.temperament)

    # ------------------------------------------------------------------ persistence
    def to_dict(self):
        return dict(
            v=SAVE_VERSION, id=self.id, name=self.name, genome=self.g.to_hex(),
            generation=self.generation, parents=self.parents,
            hunger=round(self.hunger, 2), happy=round(self.happy, 2),
            energy=round(self.energy, 2), discipline=round(self.discipline, 2),
            weight=round(self.weight, 2), age=self.age, stage=self.stage,
            poop=self.poop, sick=self.sick, sick_t=self.sick_t,
            alive=self.alive, cause=self.cause,
            digest=self.digest, starve_t=self.starve_t, sad_t=self.sad_t,
            fat_t=self.fat_t, sugar=self.sugar, call=self.call, call_t=self.call_t,
            refusing=self.refusing, stats=dict(self.stats),
        )

    @classmethod
    def from_dict(cls, d, rng):
        g = Genome.from_hex(d['genome'])
        p = cls(g, rng, name=d.get('name'), generation=d.get('generation', 1),
                parents=d.get('parents'))
        for k in ('hunger', 'happy', 'energy', 'discipline', 'weight'):
            setattr(p, k, float(d.get(k, getattr(p, k))))
        for k in ('age', 'stage', 'poop', 'sick', 'sick_t', 'alive', 'cause',
                  'digest', 'starve_t', 'sad_t', 'fat_t', 'sugar', 'call', 'call_t',
                  'refusing'):
            if k in d:
                setattr(p, k, d[k])
        st = d.get('stats') or {}
        for k in p.stats:
            p.stats[k] = int(st.get(k, 0))
        return p

    def to_json(self):
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, s, rng):
        return cls.from_dict(json.loads(s), rng)


def hatch_new(entropy, rng):
    # brand-new egg from raw hardware entropy (32 bytes)
    return Pet(Genome.from_entropy(entropy), rng)

def breed(mother, father, entropy, rng):
    # both must be alive adults (or elders), and different pets
    if mother.id == father.id:
        return None, "Needs two different pets."
    for p in (mother, father):
        if not p.alive:
            return None, "%s is dead. No." % p.name
        if p.stage not in ('adult', 'elder'):
            return None, "%s is too young." % p.name
    g = Genome.breed(mother.g, father.g, entropy)
    child = Pet(g, rng, generation=max(mother.generation, father.generation) + 1,
                parents=[mother.id, father.id])
    for p in (mother, father):
        p.energy = _clamp(p.energy - 20)
    return child, "An egg! %s x %s = %s" % (mother.name, father.name, child.name)

# EOF
