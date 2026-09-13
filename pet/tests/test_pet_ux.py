# End-to-end tests of shared/pet_ux.py: the screen loop, ticker, saves, death,
# menus -- under CPython asyncio with a scripted keypad and a fake clock.
import os, json, asyncio
import pytest

from fakeux import Harness


@pytest.fixture
def card(tmp_path):
    d = str(tmp_path / 'MicroSD')
    os.makedirs(d)
    return d


def pets_on(card):
    p = os.path.join(card, 'pets')
    return sorted(f for f in os.listdir(p)) if os.path.isdir(p) else []


def graves_on(card):
    p = os.path.join(card, 'pets', 'graveyard')
    return sorted(os.listdir(p)) if os.path.isdir(p) else []


async def start(h):
    # like picking "Virtual Pet" from the top menu
    h.reset_to_top()
    await h.pet_ux.start_pet(None, 0, None)


async def hatched(h):
    # start on an empty card, mash keys until the egg hatches
    await start(h)
    s = h.session
    assert s.pet is not None and s.pet.is_egg()
    assert isinstance(h.the_ux.top_of_stack(), h.pet_ux.PetScreen)
    import pet_model as M
    need = -(-M.STAGE_AT['baby'] // M.EGG_WARM)     # exactly enough; extras would be medicine
    h.press(*(['5'] * need))
    ok = await h.run_until(lambda: s.pet.stage == 'baby', max_ms=60000)
    assert ok
    return s.pet


# ---------------------------------------------------------------- start & hatch
def test_first_run_makes_an_egg_and_saves_it(card):
    h = Harness(card_dir=card)

    async def go():
        await start(h)
        s = h.session
        assert s.pet and s.pet.is_egg() and not s.ram_only
        assert isinstance(h.the_ux.top_of_stack(), h.pet_ux.PetScreen)
        assert any(t == 'New Egg' for t, m in h.stories)
        files = pets_on(card)
        assert s.pet.id + '.a' in files and 'active.txt' in files
        assert open(os.path.join(card, 'pets', 'active.txt')).read().strip() == s.pet.id
    h.run(go())


def test_keys_warm_the_egg_until_it_hatches(card):
    h = Harness(card_dir=card)

    async def go():
        pet = await hatched(h)
        assert pet.stage == 'baby'
        assert 'hatch' in h.session.events or h.the_ux.top_of_stack().msg
    h.run(go())


# ---------------------------------------------------------------- time
def test_pet_ages_only_while_its_screen_is_up(card):
    h = Harness(card_dir=card)

    async def go():
        pet = await hatched(h)
        a0 = pet.age
        assert await h.run_until(lambda: pet.age >= a0 + 30, max_ms=120000)
        # leave the screen
        h.press('x')
        assert await h.run_until(lambda: not h.session.active, max_ms=5000)
        a1 = pet.age
        await h.run_until(lambda: False, max_ms=30000)   # time passes, nothing on screen
        assert pet.age == a1
    h.run(go())


def test_autosave_happens_while_watching(card):
    h = Harness(card_dir=card)

    async def go():
        pet = await hatched(h)
        import pet_model as M
        target = pet.age + M.AUTOSAVE_EVERY * 2 + 5
        assert await h.run_until(lambda: pet.age >= target, max_ms=300000)
        from pet_store import _decode
        best = 0
        for fn in pets_on(card):
            if fn.endswith('.a') or fn.endswith('.b'):
                try:
                    n, d = _decode(open(os.path.join(card, 'pets', fn)).read())
                    best = max(best, d['age'])
                except Exception:
                    pass
        assert best >= target - M.AUTOSAVE_EVERY
    h.run(go())


def test_ticker_counts_as_activity_for_idle_logout(card):
    h = Harness(card_dir=card)

    async def go():
        pet = await hatched(h)
        h.keys.clear()
        t0 = h.glob.numpad.last_event_time
        assert await h.run_until(lambda: pet.age >= pet.age + 1 or True, max_ms=100)
        a0 = pet.age
        assert await h.run_until(lambda: pet.age >= a0 + 10, max_ms=60000)
        assert h.glob.numpad.last_event_time > t0
    h.run(go())


# ---------------------------------------------------------------- keys
def test_action_keys(card):
    h = Harness(card_dir=card)

    async def go():
        pet = await hatched(h)
        pet.discipline = 100.0
        pet.hunger = 40.0
        h.press('1')
        assert await h.run_until(lambda: pet.stats['meals'] == 1, max_ms=5000)
        h.press('2')
        assert await h.run_until(lambda: pet.stats['snacks'] == 1, max_ms=5000)
        pet.poop = 2
        h.press('4')
        assert await h.run_until(lambda: pet.stats['cleans'] == 1, max_ms=5000)
        h.press('5')
        assert await h.run_until(lambda: pet.stats['meds'] == 1, max_ms=5000)
        h.press('6')
        assert await h.run_until(lambda: pet.stats['scolds'] == 1, max_ms=5000)
        h.press('y')
        assert await h.run_until(lambda: pet.stats['pats'] == 1, max_ms=5000)
        h.press('7')
        assert await h.run_until(lambda: any('TRNG' in m for t, m in h.stories), max_ms=5000)
        h.press('8')
        assert await h.run_until(lambda: any(t == 'Pet Help' for t, m in h.stories), max_ms=5000)
        h.press('0')
        scr = h.the_ux.top_of_stack()
        assert await h.run_until(lambda: scr.msg is not None, max_ms=5000)
    h.run(go())


def test_pin_drill_minigame_affects_happiness(card):
    h = Harness(card_dir=card)

    async def go():
        pet = await hatched(h)
        pet.discipline = 100.0
        pet.energy = 90.0
        pet.happy = 40.0
        # capture the PIN it shows by peeking at the rng: easier to just lose on purpose
        h.story_answers.append('1')            # choose PIN Drill
        h.press('3')
        # any key skips the "remember this" phase; then type junk and continue
        h.press('5', '0', '0', '0', '0', 'y')
        assert await h.run_until(lambda: pet.stats['games'] == 1, max_ms=60000)
        assert pet.happy > 40.0                 # even losing is a little fun
    h.run(go())


def test_which_way_minigame(card):
    h = Harness(card_dir=card)

    async def go():
        pet = await hatched(h)
        pet.discipline = 100.0
        pet.energy = 90.0
        h.story_answers.append('2')
        h.press('3')
        h.press('4', '4', '4', '4', '4', 'y')
        assert await h.run_until(lambda: pet.stats['games'] == 1, max_ms=60000)
    h.run(go())


# ---------------------------------------------------------------- death
def test_death_on_screen_is_permanent_and_witnessed(card):
    h = Harness(card_dir=card)

    async def go():
        pet = await hatched(h)
        import pet_model as M
        pet.sick = True
        pet.sick_t = M.SICK_FATAL - 5
        assert await h.run_until(lambda: not pet.alive, max_ms=60000)
        h.press('y')                             # dismiss the R.I.P. screen
        assert await h.run_until(lambda: h.session.pet is None, max_ms=60000)
        # tombstone on the card, saves gone, pointer cleared
        assert graves_on(card) == [pet.id + '.json']
        assert not any(f.startswith(pet.id) for f in pets_on(card))
        assert open(os.path.join(card, 'pets', 'active.txt')).read().strip() == ''
        tomb = json.load(open(os.path.join(card, 'pets', 'graveyard', pet.id + '.json')))
        assert tomb['cause'] == 'sickness' and 'Here lies' in tomb['epitaph']
        assert any(t == 'R.I.P.' for t, m in h.stories)
        # and we land on the pet menu, where New Egg is
        assert isinstance(h.the_ux.top_of_stack(), h.pet_ux.PetMenu)
    h.run(go())


def test_reboot_loads_pet_from_card_and_it_wakes(card):
    h = Harness(card_dir=card)

    async def go():
        pet = await hatched(h)
        pet.energy = 12.0
        h.session.save()
        return pet.id, pet.age
    pid, age = h.run(go())

    # "reboot": brand new harness on the same card
    h2 = Harness(card_dir=card)

    async def go2():
        await h2.pet_ux.pet_autostart()
        s = h2.session
        assert s.pet and s.pet.id == pid and s.pet.age == age
        assert s.pet.energy == 100.0 and s.pet.stats['naps'] == 1
        assert isinstance(h2.the_ux.top_of_stack(), h2.pet_ux.PetScreen)
    h2.run(go2())


def test_reboot_with_no_card_does_nothing(card):
    h = Harness(card_dir=card, card_inserted=False)

    async def go():
        await h.pet_ux.pet_autostart()
        assert h.session.pet is None and not h.the_ux.stack
    h.run(go())


# ---------------------------------------------------------------- no card
def test_no_card_offers_ram_mode_and_saves_nothing(card):
    h = Harness(card_dir=card, card_inserted=False)

    async def go():
        h.press('y')                            # "play in RAM anyway"
        await start(h)
        s = h.session
        assert s.pet and s.ram_only
        assert pets_on(card) == []
        h.press(*(['1'] * 45))
        await h.run_until(lambda: s.pet.stage == 'baby', max_ms=60000)
        h.press('1')
        await h.run_until(lambda: s.pet.stats['meals'] >= 1, max_ms=5000)
        assert pets_on(card) == []
    h.run(go())


def test_no_card_x_backs_out(card):
    h = Harness(card_dir=card, card_inserted=False)

    async def go():
        h.press('x')
        await start(h)
        assert h.session.pet is None
    h.run(go())


# ---------------------------------------------------------------- pet menu
def test_pet_menu_new_egg_and_switch_back(card):
    h = Harness(card_dir=card)

    async def go():
        first = await hatched(h)
        # open the pet menu with 9, make a new egg, then switch back to the first
        h.menu_script.extend(['New Egg'])
        h.press('9')
        s = h.session
        on_screen = lambda: isinstance(h.the_ux.top_of_stack(), h.pet_ux.PetScreen)
        assert await h.run_until(lambda: s.pet is not None and s.pet.id != first.id and on_screen(),
                                 max_ms=30000)
        assert s.pet.is_egg()
        # both pets are on the card
        ids = {f[:8] for f in pets_on(card) if f.endswith('.a')}
        assert ids == {first.id, s.pet.id}
        # switch back
        h.menu_script.extend(['Switch Pet', '%s (baby)' % first.name])
        h.press('9')
        assert await h.run_until(lambda: s.pet.id == first.id and on_screen(), max_ms=30000)
        assert s.pet.stats['naps'] == 1      # it slept on the card meanwhile
    h.run(go())


def test_graveyard_lists_the_dead(card):
    h = Harness(card_dir=card)

    async def go():
        pet = await hatched(h)
        import pet_model as M
        pet.sick = True
        pet.sick_t = M.SICK_FATAL - 2
        assert await h.run_until(lambda: not pet.alive, max_ms=60000)
        h.press('y')
        assert await h.run_until(lambda: h.session.pet is None, max_ms=60000)
        h.menu_script.extend(['Graveyard', '%s, %s' % (pet.name, M.fmt_awake(pet.age)), 'x', 'x'])
        assert await h.run_until(lambda: any(t == pet.name for t, m in h.stories), max_ms=30000)
    h.run(go())


def test_breed_two_adults_from_menu(card):
    h = Harness(card_dir=card)

    async def go():
        import pet_model as M
        s = h.session
        a = await hatched(h)
        a.stage = 'adult'; a.age = M.STAGE_AT['adult'] + 10
        s.save()
        # second adult straight onto the card
        raw = bytes(h.rand.randrange(256) for _ in range(32))
        b = M.Pet(M.Genome(raw), s.rng)
        b.stage = 'adult'; b.age = M.STAGE_AT['adult'] + 10
        s.store.save(b.to_dict())

        h.menu_script.extend(['Breed', '%s (adult)' % a.name, '%s (adult)' % b.name])
        h.press('9')
        assert await h.run_until(lambda: s.pet is not None and s.pet.generation == 2, max_ms=60000)
        child = s.pet
        assert child.is_egg() and set(child.parents) == {a.id, b.id}
        assert any(t == 'Bred' for t, m in h.stories)
        ids = {f[:8] for f in pets_on(card) if f.endswith('.a')}
        assert ids == {a.id, b.id, child.id}
    h.run(go())


def test_breed_refuses_with_one_adult(card):
    h = Harness(card_dir=card)

    async def go():
        s = h.session
        await hatched(h)
        h.menu_script.extend(['Breed', 'x'])
        h.press('9')
        assert await h.run_until(lambda: any(t == 'Breed' for t, m in h.stories), max_ms=30000)
        assert s.pet.generation == 1
    h.run(go())


def test_rename(card):
    h = Harness(card_dir=card)

    async def go():
        s = h.session
        await hatched(h)
        h.text_answers.append('Gary')
        h.menu_script.extend(['Rename', 'Back To Pet'])
        h.press('9')
        assert await h.run_until(lambda: s.pet.name == 'Gary', max_ms=30000)
        assert await h.run_until(lambda: isinstance(h.the_ux.top_of_stack(), h.pet_ux.PetScreen), max_ms=30000)
        from pet_store import _decode
        names = set()
        for fn in pets_on(card):
            if fn[-2:] in ('.a', '.b'):
                names.add(_decode(open(os.path.join(card, 'pets', fn)).read())[1]['name'])
        assert 'Gary' in names
    h.run(go())


# ---------------------------------------------------------------- card yanked
def test_card_pulled_mid_life_switches_to_ram_and_back(card):
    h = Harness(card_dir=card)

    async def go():
        s = h.session
        pet = await hatched(h)
        h.card_inserted = False
        h.press('1')
        assert await h.run_until(lambda: pet.stats['meals'] == 1, max_ms=5000)
        assert s.ram_only
        h.card_inserted = True
        pet.hunger = 30.0
        h.press('1')
        assert await h.run_until(lambda: pet.stats['meals'] == 2 and not s.ram_only, max_ms=5000)
    h.run(go())
