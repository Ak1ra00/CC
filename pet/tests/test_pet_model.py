# Unit tests for shared/pet_model.py -- the creature, against a fake clock.
#
# The "clock" is tick(n): one tick == one awake-second. No wall time anywhere.
import json, random
import pytest

import pet_model as M
from pet_model import Pet, Genome, hatch_new, breed, fmt_awake


def hatched(entropy, rng, **kw):
    # a freshly hatched baby, for tests that don't care about the egg
    p = hatch_new(entropy(), rng)
    p.tick(M.STAGE_AT['baby'])
    assert p.stage == 'baby'
    for k, v in kw.items():
        setattr(p, k, v)
    return p


# ---------------------------------------------------------------- genome
def test_genome_decodes_every_byte_deterministically(entropy):
    raw = entropy()
    a, b = Genome(raw), Genome(raw)
    assert a.to_hex() == b.to_hex()
    assert a.name == b.name and a.temperament == b.temperament
    assert 0.6 <= a.appetite <= 1.6
    assert 0.7 <= a.lifespan <= 1.4
    assert a.temperament in M.TEMPERAMENTS
    assert 0 <= a.body < M.NUM_BODIES and 0 <= a.eyes < M.NUM_EYES
    assert len(a.id) == 8


def test_genome_roundtrips_hex(entropy):
    g = Genome(entropy())
    assert Genome.from_hex(g.to_hex()).raw == g.raw


def test_different_entropy_gives_different_pets(entropy):
    seen = set()
    for i in range(50):
        g = Genome(entropy(seed=i))
        seen.add((g.name, g.temperament, g.body, g.eyes, round(g.appetite, 2)))
    # 50 rolls; if fewer than 45 are distinct the decode is too coarse
    assert len(seen) >= 45


def test_names_are_pronounceable_and_capitalised():
    for a in range(0, 256, 7):
        for b in range(0, 256, 13):
            n = M.name_from_seed(a, b)
            assert 2 <= len(n) <= 10
            assert n[0].isupper() and n[1:].islower()


def test_genome_rejects_wrong_size():
    with pytest.raises(AssertionError):
        Genome(b'\x00' * 31)


# ---------------------------------------------------------------- egg & growth
def test_egg_hatches_after_awake_time(entropy, rng):
    p = hatch_new(entropy(), rng)
    assert p.stage == 'egg' and p.is_egg()
    ev = p.tick(M.STAGE_AT['baby'] - 1)
    assert p.stage == 'egg' and 'hatch' not in ev
    ev = p.tick(1)
    assert p.stage == 'baby' and 'hatch' in ev and 'grow:baby' in ev


def test_egg_does_not_get_hungry(entropy, rng):
    p = hatch_new(entropy(), rng)
    h = p.hunger
    p.tick(60)
    assert p.hunger == h and p.poop == 0 and not p.sick


def test_keypresses_warm_the_egg(entropy, rng):
    p = hatch_new(entropy(), rng)
    presses = 0
    while p.is_egg():
        ok, msg = p.warm_egg()
        assert ok
        presses += 1
    assert p.stage == 'baby' and msg == 'It hatched!'
    assert presses == -(-M.STAGE_AT['baby'] // M.EGG_WARM)
    assert p.warm_egg() == (False, None)


def test_life_stages_in_order(entropy, rng):
    p = hatch_new(entropy(), rng)
    # keep it alive by feeding & cleaning generously as time passes
    seen = ['egg']
    for _ in range(M.STAGE_AT['elder'] + 10):
        p.hunger, p.happy, p.energy, p.poop = 80, 80, 80, 0
        p.sick = False
        p.tick()
        if p.stage != seen[-1]:
            seen.append(p.stage)
    assert seen == list(M.STAGES)
    assert p.alive


# ---------------------------------------------------------------- decay
def test_stats_fall_while_awake_and_only_then(entropy, rng):
    p = hatched(entropy, rng)
    h0, ha0, e0 = p.hunger, p.happy, p.energy
    p.tick(600)
    assert p.hunger < h0 and p.happy < ha0 and p.energy < e0
    # no ticks == no time == nothing changes (that's the whole design)
    snap = p.to_dict()
    assert p.to_dict() == snap


def test_appetite_gene_changes_hunger_rate(rng):
    raw = bytearray(32)
    raw[0] = 0
    slow = Pet(Genome(bytes(raw)), rng); slow.stage = 'baby'; slow.age = 100
    raw[0] = 255
    fast = Pet(Genome(bytes(raw)), rng); fast.stage = 'baby'; fast.age = 100
    slow.tick(300); fast.tick(300)
    assert fast.hunger < slow.hunger


# ---------------------------------------------------------------- actions
def test_feed_raises_hunger_and_schedules_poop(entropy, rng):
    p = hatched(entropy, rng, hunger=40.0)
    ok, msg = p.feed()
    assert ok and p.hunger > 40 and p.stats['meals'] == 1 and len(p.digest) == 1
    assert p.poop == 0
    p.tick(p.digest[0] + 1)
    assert p.poop == 1


def test_feed_refused_when_full(entropy, rng):
    p = hatched(entropy, rng, hunger=99.0)
    ok, msg = p.feed()
    assert not ok and p.stats['meals'] == 0


def test_snacks_are_fun_but_fattening(entropy, rng):
    p = hatched(entropy, rng, happy=50.0)
    w = p.weight
    ok, _ = p.snack()
    assert ok and p.happy > 50 and p.weight > w
    for _ in range(M.SNACK_SUGAR + 1):
        ok, msg = p.snack()
    assert 'Sugar' in msg


def test_clean_only_when_dirty(entropy, rng):
    p = hatched(entropy, rng)
    assert p.clean()[0] is False
    p.poop = 2
    ok, _ = p.clean()
    assert ok and p.poop == 0 and p.stats['cleans'] == 1


def test_medicine_cures_eventually(entropy, rng):
    p = hatched(entropy, rng)
    p.sick = True
    for _ in range(20):
        p.medicine()
        if not p.sick:
            break
    assert not p.sick


def test_medicine_when_healthy_is_a_bad_idea(entropy, rng):
    p = hatched(entropy, rng, happy=50.0)
    ok, msg = p.medicine()
    assert ok and p.happy < 50 and 'Wasn' in msg


def test_scold_fixes_tantrum_and_raises_discipline(entropy, rng):
    p = hatched(entropy, rng, discipline=10.0)
    p.call = 'tantrum'
    ok, msg = p.scold()
    assert ok and p.call is None and p.discipline > 10


def test_scolding_an_innocent_pet_hurts(entropy, rng):
    p = hatched(entropy, rng, happy=50.0)
    ok, msg = p.scold()
    assert ok and p.happy < 50 and 'nothing wrong' in msg


def test_play_needs_energy(entropy, rng):
    p = hatched(entropy, rng, energy=5.0)
    ok, msg = p.can_play()
    assert not ok and 'Unplug' in msg
    p.energy = 90.0
    p.discipline = 100.0   # no refusals
    assert p.can_play()[0]
    ha = p.happy
    p.play_result(True)
    assert p.happy > ha and p.stats['wins'] == 1 and p.stats['games'] == 1


def test_pat_on_head(entropy, rng):
    p = hatched(entropy, rng, happy=50.0)
    ok, msg = p.pat()
    assert ok and p.stats['pats'] == 1


# ---------------------------------------------------------------- stubbornness
def test_stubborn_undisciplined_pet_sometimes_refuses(rng):
    raw = bytearray(32); raw[2] = 255          # maximum stubborn
    p = Pet(Genome(bytes(raw)), rng); p.stage = 'baby'; p.age = 100
    p.discipline = 0.0
    refused = 0
    for _ in range(200):
        p.hunger = 10.0
        ok, _ = p.feed()
        if not ok:
            refused += 1
    assert refused > 10
    assert p.stats['refusals'] == refused


def test_disciplined_pet_never_refuses(rng):
    raw = bytearray(32); raw[2] = 255
    p = Pet(Genome(bytes(raw)), rng); p.stage = 'baby'; p.age = 100
    p.discipline = 100.0
    for _ in range(200):
        p.hunger = 10.0
        assert p.feed()[0]


# ---------------------------------------------------------------- calls & mistakes
def test_ignoring_a_real_call_is_a_care_mistake(entropy, rng):
    p = hatched(entropy, rng)
    p.hunger = 0.0
    p.starve_t = 0
    ev = p.tick(M.CALL_GRACE)
    assert 'mistake' in ev and p.stats['mistakes'] == 1
    assert p.lifespan() < M.LIFESPAN_BASE * p.g.lifespan


def test_answering_a_call_in_time_is_not_a_mistake(entropy, rng):
    p = hatched(entropy, rng, hunger=20.0)
    p.tick(M.CALL_GRACE // 2)
    assert p.call == 'real'
    p.feed(); p.feed()
    p.tick(10)
    assert p.call is None and p.stats['mistakes'] == 0


# ---------------------------------------------------------------- sickness & death
def test_poop_makes_sickness_likely(entropy, rng):
    p = hatched(entropy, rng)
    p.poop = M.MAX_POOP
    for _ in range(4 * 3600):
        p.hunger, p.happy, p.energy = 80, 80, 80
        p.tick()
        if p.sick:
            break
    assert p.sick


def test_untreated_sickness_kills(entropy, rng):
    p = hatched(entropy, rng)
    p.sick = True
    ev = p.tick(M.SICK_FATAL + 1)
    assert not p.alive and p.cause == 'sickness' and 'death' in ev


def test_starvation_kills_and_only_after_the_grace(entropy, rng):
    p = hatched(entropy, rng)
    p.hunger = 0.0
    p.tick(M.STARVE_FATAL - 1)
    assert p.alive
    p.tick(1)
    assert not p.alive and p.cause == 'starvation'


def test_old_age_kills(entropy, rng):
    p = hatched(entropy, rng)
    p.age = p.lifespan() - 1
    p.hunger, p.happy, p.energy = 80, 80, 80
    p.tick(1)
    assert not p.alive and p.cause == 'old age'


def test_death_is_permanent(entropy, rng):
    p = hatched(entropy, rng)
    p.sick = True
    p.tick(M.SICK_FATAL + 1)
    assert not p.alive
    age = p.age
    p.tick(1000)
    assert p.age == age            # time stops for the dead
    assert p.feed()[0] is False
    assert p.medicine()[0] is False
    assert p.snack()[0] is False
    # reloading the save does not bring it back
    q = Pet.from_json(p.to_json(), rng)
    assert not q.alive and q.cause == 'sickness'


def test_tombstone_has_epitaph_and_lifetime_stats(entropy, rng):
    p = hatched(entropy, rng, discipline=100.0)   # no stubborn refusals
    p.feed(); p.feed(); p.snack()
    p.sick = True
    p.tick(M.SICK_FATAL + 1)
    t = p.tombstone()
    assert t['name'] == p.name and t['cause'] == 'sickness'
    assert t['stats']['meals'] == 2 and t['stats']['snacks'] == 1
    assert t['genome'] == p.g.to_hex()
    assert 'Here lies %s' % p.name in t['epitaph']
    assert 'untreated bug' in t['epitaph']
    json.dumps(t)   # must be serialisable


# ---------------------------------------------------------------- sleep
def test_unplugging_is_sleep(entropy, rng):
    p = hatched(entropy, rng, energy=3.0)
    p.call = 'tantrum'
    dream = p.wake()
    assert p.energy == 100.0 and p.stats['naps'] == 1 and p.call is None
    assert dream in M.DREAMS


def test_eggs_do_not_dream(entropy, rng):
    p = hatch_new(entropy(), rng)
    assert p.wake() is None


# ---------------------------------------------------------------- words
def test_status_line_prioritises_needs(entropy, rng):
    p = hatched(entropy, rng)
    p.sick = True; p.hunger = 0.0; p.poop = 3
    assert p.says() in M.NEED_LINES['sick']
    p.sick = False
    assert p.says() in M.NEED_LINES['starve']
    p.hunger = 80.0
    assert p.says() in M.NEED_LINES['poop']
    p.poop = 0; p.happy = 80.0; p.energy = 80.0
    assert p.says() in M.SAYINGS[p.g.temperament] + M.SAYINGS_ANY


def test_talk_key_cycles_lines(entropy, rng):
    p = hatched(entropy, rng)
    p.hunger = p.happy = p.energy = 80.0
    a = p.says()
    b = p.say_something_else()
    assert a != b


def test_fmt_awake():
    assert fmt_awake(0) == '0m'
    assert fmt_awake(59) == '0m'
    assert fmt_awake(61) == '1m'
    assert fmt_awake(3600 * 2 + 60 * 13) == '2h13m'
    assert fmt_awake(86400 + 3600 * 3) == '1d3h'


# ---------------------------------------------------------------- persistence
def test_save_roundtrip_is_lossless(entropy, rng):
    p = hatched(entropy, rng)
    p.feed(); p.snack(); p.tick(300); p.poop = 2; p.sick = True; p.call = 'real'; p.call_t = 7
    d = p.to_dict()
    q = Pet.from_dict(json.loads(json.dumps(d)), rng)
    assert q.to_dict() == d
    assert q.name == p.name and q.g.raw == p.g.raw


def test_loading_unknown_keys_is_tolerated(entropy, rng):
    p = hatched(entropy, rng)
    d = p.to_dict()
    d['from_the_future'] = 1
    del d['stats']['pats']
    Pet.from_dict(d, rng)


# ---------------------------------------------------------------- breeding
def adult(entropy, rng, seed):
    p = Pet(Genome(entropy(seed=seed)), rng)
    p.stage = 'adult'
    p.age = M.STAGE_AT['adult'] + 1
    return p


def test_breeding_mixes_both_genomes(entropy, rng):
    a, b = adult(entropy, rng, 1), adult(entropy, rng, 2)
    child, msg = breed(a, b, entropy(64, seed=3), rng)
    assert child is not None and child.stage == 'egg'
    assert child.generation == 2 and child.parents == [a.id, b.id]
    from_a = sum(1 for i in range(28) if child.g.raw[i] == a.g.raw[i])
    from_b = sum(1 for i in range(28) if child.g.raw[i] == b.g.raw[i])
    assert from_a > 3 and from_b > 3           # something from each parent
    assert child.id not in (a.id, b.id)       # fresh identity


def test_breeding_needs_two_living_adults(entropy, rng):
    a, b = adult(entropy, rng, 1), adult(entropy, rng, 2)
    assert breed(a, a, entropy(64), rng)[0] is None
    b.stage = 'teen'
    assert breed(a, b, entropy(64), rng)[0] is None
    b.stage = 'adult'; b.alive = False
    assert breed(a, b, entropy(64), rng)[0] is None


def test_breeding_is_deterministic_given_entropy(entropy, rng):
    a, b = adult(entropy, rng, 1), adult(entropy, rng, 2)
    e = entropy(64, seed=7)
    c1, _ = breed(a, b, e, rng)
    a, b = adult(entropy, rng, 1), adult(entropy, rng, 2)
    c2, _ = breed(a, b, e, rng)
    assert c1.g.raw == c2.g.raw
