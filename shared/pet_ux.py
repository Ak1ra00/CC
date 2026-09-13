# pet_ux.py - screens, keys, the awake clock, and the card. The hardware-facing half.
#
# Part of the unofficial COLDCARD Tamagotchi fork. See NOTICE and LICENSE-PET.
#
# Key map on the pet screen (also on the help screen, key 8):
#   1 feed   2 snack   3 play   4 clean   5 medicine   6 scold   7 status
#   8 help   9 pet menu   0 talk   OK pat   X leave
#
import uasyncio, utime, ckcc, ngu, glob
from uasyncio import sleep_ms
from ux import (ux_show_story, ux_wait_keydown, ux_clear_keys, the_ux, ux_confirm,
                ux_input_text)
from menu import MenuSystem, MenuItem
from files import CardSlot, CardMissingError
from exceptions import AbortInteraction
import pet_model as M
import pet_draw as D
import pet_sprites as S
from pet_store import PetStore, CardFS

FRAME_MS = 400          # idle animation frame; also how often keys are polled
MSG_FRAMES = 6          # how long an action's reply stays on the text line

EVENT_LINES = {
    'poop':     "Plop.",
    'sick':     "*cough* That's not good.",
    'mistake':  "You ignored it. Noted.",
    'tantrum':  "*fake alarm* (scold it: 6)",
    'grow:child': "It grew! A child now.",
    'grow:teen':  "Teenager. Good luck.",
    'grow:adult': "All grown up. Can breed.",
    'grow:elder': "Old now. Be gentle.",
}


class PetSession:
    # Singleton. The loaded pet, its card, and the awake clock.

    def __init__(self):
        self.pet = None
        self.store = PetStore(CardFS)
        self.ram_only = False       # no card: playing in RAM, nothing saved
        self.loaded = False         # tried the card since boot?
        self.last_ms = None
        self.since_save = 0
        self.events = []
        self.ticker = None
        self.dream = None

    # ------------------------------------------------------------ hardware bits
    def rng(self, n):
        # ngu.random.uniform -> hardware TRNG, reseeded from both secure elements
        return ngu.random.uniform(n)

    def entropy(self, n=32):
        # raw bytes straight off the STM32 TRNG. This is the joke, and the point.
        buf = bytearray(n)
        ckcc.rng_bytes(buf)
        return bytes(buf)

    @property
    def active(self):
        # the pet ages only while a PetScreen is somewhere on the UX stack
        for x in the_ux.stack:
            if isinstance(x, PetScreen):
                return True
        return False

    def start_ticker(self):
        if self.ticker is None:
            # NOT an IMPT task: those wipe the device if they die.
            self.ticker = uasyncio.create_task(self._ticker())

    async def _ticker(self):
        while True:
            try:
                await sleep_ms(250)
                pet = self.pet
                if not pet or not pet.alive or not self.active:
                    self.last_ms = None
                    continue
                now = utime.ticks_ms()
                if self.last_ms is None:
                    self.last_ms = now
                    continue
                dt = utime.ticks_diff(now, self.last_ms)
                if dt < 1000:
                    continue
                n = dt // 1000
                self.last_ms = utime.ticks_add(self.last_ms, n * 1000)

                ev = pet.tick(n)
                self.events.extend(ev)
                self.since_save += n

                # the idle-logout task reboots the device after inactivity.
                # A creature on screen counts as activity.
                glob.numpad.last_event_time = now

                if not pet.alive:
                    self.bury()
                elif self.since_save >= M.AUTOSAVE_EVERY:
                    self.save()
            except Exception as e:
                # never let the ticker die; the pet just skips a beat
                try:
                    import sys
                    sys.print_exception(e)
                except: pass

    # ------------------------------------------------------------ card
    def card_present(self):
        try:
            return CardSlot.is_inserted()
        except Exception:
            return False

    def save(self):
        self.since_save = 0
        if not self.pet or not self.pet.alive:
            return False
        if not self.card_present():
            self.ram_only = True
            return False
        try:
            self.store.save(self.pet.to_dict())
            self.ram_only = False
            return True
        except (CardMissingError, OSError) as e:
            self.ram_only = True
            return False

    def bury(self):
        # pet died: tombstone first, then delete the saves. Permanent.
        self.since_save = 0
        if not self.pet or self.pet.alive:
            return
        try:
            tomb = self.pet.tombstone()
            if self.card_present():
                self.store.bury(tomb)
                self.store.set_active(None)
        except (CardMissingError, OSError):
            pass

    def load_from_card(self):
        # -> True if a live pet was loaded. Sets self.pet.
        self.loaded = True
        if not self.card_present():
            self.ram_only = True
            return False
        try:
            pets = self.store.load_all()
            active = self.store.get_active()
        except (CardMissingError, OSError):
            self.ram_only = True
            return False
        self.ram_only = False
        d = pets.get(active) if active else None
        if d is None and pets:
            # no pointer: take the oldest survivor
            d = sorted(pets.values(), key=lambda x: -x.get('age', 0))[0]
        if d is None:
            return False
        pet = M.Pet.from_dict(d, self.rng)
        if not pet.alive:
            # died with the power off between tombstone and cleanup: finish it
            self.pet = pet
            self.bury()
            self.pet = None
            return False
        self.adopt(pet, just_woke=True)
        return True

    def adopt(self, pet, just_woke=False):
        # make this the pet on screen
        self.pet = pet
        self.last_ms = None
        self.events = []
        self.dream = pet.wake() if just_woke else None
        if self.card_present():
            try:
                self.store.set_active(pet.id)
            except (CardMissingError, OSError):
                pass
        self.save()

    def other_pets(self):
        # dicts of every live pet on the card (including the current one)
        if not self.card_present():
            return {}
        try:
            return self.store.load_all()
        except (CardMissingError, OSError):
            return {}


session = PetSession()


# ---------------------------------------------------------------- the main screen
class PetScreen:
    # lives on the_ux stack; interact() is re-entered after an AbortInteraction

    def __init__(self):
        self.frame = 0
        self.msg = None
        self.msg_ttl = 0
        self.action = None

    def show(self):
        if session.pet:
            D.draw_main(glob.dis, session.pet, self.frame, msg=self.msg,
                        action=self.action, ram_only=session.ram_only)

    def say(self, msg, action=None, frames=MSG_FRAMES):
        self.msg = msg
        self.msg_ttl = frames if msg else 0
        self.action = action

    async def interact(self):
        dis = glob.dis
        s = session
        s.start_ticker()

        if s.dream:
            await self.wake_animation()

        while True:
            pet = s.pet
            if pet is None:
                the_ux.pop()
                return

            if not pet.alive:
                await self.death_sequence()
                the_ux.pop()
                if not isinstance(the_ux.top_of_stack(), PetMenu):
                    the_ux.push(make_pet_menu())
                return

            # things the ticker noticed
            while s.events:
                ev = s.events.pop(0)
                if ev == 'hatch':
                    self.say("It hatched! Say hi to %s." % pet.name, frames=10)
                elif ev in EVENT_LINES:
                    self.say(EVENT_LINES[ev], frames=8)

            self.show()
            self.frame += 1
            if self.msg_ttl:
                self.msg_ttl -= 1
                if not self.msg_ttl:
                    self.msg = None
                    self.action = None

            ch = await ux_wait_keydown(timeout_ms=FRAME_MS)
            if ch is None:
                continue

            if pet.is_egg() and ch not in 'x89':
                ok, msg = pet.warm_egg()
                self.say(msg, frames=2)
                if pet.stage != 'egg':
                    s.events.append('hatch')
                    s.save()
                continue

            if ch == 'x':
                s.save()
                the_ux.pop()
                return
            elif ch == '1':
                ok, msg = pet.feed()
                self.say(msg, 'eat' if ok else None)
                if ok: s.save()
            elif ch == '2':
                ok, msg = pet.snack()
                self.say(msg, 'snack' if ok else None)
                if ok: s.save()
            elif ch == '3':
                await play_menu()
            elif ch == '4':
                ok, msg = pet.clean()
                self.say(msg, 'clean' if ok else None)
                if ok: s.save()
            elif ch == '5':
                ok, msg = pet.medicine()
                self.say(msg, 'med' if ok else None)
                if ok: s.save()
            elif ch == '6':
                ok, msg = pet.scold()
                self.say(msg, 'scold' if ok else None)
                if ok: s.save()
            elif ch == '7':
                await ux_show_story(D.stats_text(pet), title=None)
            elif ch == '8':
                await ux_show_story(D.HELP_TEXT, title="Pet Help")
            elif ch == '9':
                s.save()
                the_ux.push(make_pet_menu())
                return                      # mainline runs the menu; we resume after
            elif ch == '0':
                self.say(pet.say_something_else(), frames=8)
            elif ch == 'y':
                ok, msg = pet.pat()
                self.say(msg, 'pat' if ok else None)

    async def wake_animation(self):
        dis = glob.dis
        pet = session.pet
        dream = session.dream
        session.dream = None
        for f in range(8):
            D.draw_wake(dis, pet, f, dream if f >= 4 else 'zzz...')
            ch = await ux_wait_keydown(timeout_ms=350)
            if ch:
                break
        self.say(dream, frames=10)

    async def death_sequence(self):
        dis = glob.dis
        pet = session.pet
        ux_clear_keys()
        for f in range(6):
            D.draw_death(dis, pet, f)
            await sleep_ms(400)
        while True:
            D.draw_death(dis, pet, self.frame)
            self.frame += 1
            ch = await ux_wait_keydown(timeout_ms=400)
            if ch in ('y', 'x'):
                break
        tomb = pet.tombstone()
        await ux_show_story(tomb['epitaph'] + "\n\nThe tombstone is on the card. "
                            "There is no undo.\n\nNew egg: press 9 from the pet menu.",
                            title="R.I.P.")
        session.pet = None


# ---------------------------------------------------------------- entry points
async def start_pet(*a):
    # menu item: "Virtual Pet"
    s = session
    dis = glob.dis

    if not s.loaded or (s.pet is None and s.card_present() and not s.ram_only):
        s.load_from_card()

    if s.pet is None and s.ram_only:
        # no card. Offer to play in RAM.
        f = 0
        while True:
            D.draw_card_pull(dis, f)
            f += 1
            ch = await ux_wait_keydown(timeout_ms=500)
            if ch == 'x':
                return
            if ch == 'y':
                break
            if s.card_present():
                s.load_from_card()
                break

    if s.pet is None:
        # nothing to raise yet
        if s.other_pets():
            the_ux.push(make_pet_menu())
        else:
            await new_egg()
            if s.pet:
                the_ux.push(PetScreen())
        return

    the_ux.push(PetScreen())


def goto_pet_screen():
    # pop pickers / the pet menu off the top, and make sure a PetScreen is up
    while isinstance(the_ux.top_of_stack(), (PetMenu, Picker)):
        the_ux.pop()
    if not session.active:
        the_ux.push(PetScreen())


async def pet_autostart():
    # called once from main.py after login: if there's a pet on the card, it
    # wakes up right on screen. This device has one job now.
    try:
        s = session
        if s.card_present() and s.load_from_card():
            the_ux.push(PetScreen())
    except Exception as e:
        try:
            import sys
            sys.print_exception(e)
        except: pass


async def new_egg(*a):
    s = session
    dis = glob.dis
    if s.pet and s.pet.alive:
        if not await ux_confirm("%s will go to sleep on the card while you raise "
                                "the new egg. Switch back any time from the pet menu."
                                % s.pet.name, title="New egg?"):
            return
        s.save()

    # the dramatic part: 256 bits off the hardware TRNG
    for i in range(21):
        D.draw_hatching(dis, S.EGGS[0], i / 20.0, i)
        await sleep_ms(70)
    raw = s.entropy(32)
    pet = M.hatch_new(raw, s.rng)
    body = S.EGGS[pet.g.body % len(S.EGGS)]
    D.draw_hatching(dis, body, 1.0, 0)
    await sleep_ms(900)
    ux_clear_keys()
    s.adopt(pet)
    await ux_show_story("An egg. Its name will be %s.\n\nGenome id %s\n\n"
                        "Keep it warm: press keys on the pet screen. It hatches "
                        "after about %d seconds of attention.\n\n%s"
                        % (pet.name, pet.id, M.STAGE_AT['baby'],
                           "NOT SAVED: no card." if s.ram_only else "Saved to the card."),
                        title="New Egg")


async def new_egg_item(*a):
    await new_egg()
    if session.pet:
        goto_pet_screen()


# ---------------------------------------------------------------- pet menu (key 9)
class PetMenu(MenuSystem):
    pass

class Picker(MenuSystem):
    pass


def make_pet_menu():
    items = [
        MenuItem('Back To Pet', f=back_to_pet, predicate=lambda: session.pet is not None),
        MenuItem('New Egg', f=new_egg_item),
        MenuItem('Switch Pet', f=switch_pet),
        MenuItem('Breed', f=breed_pets),
        MenuItem('Graveyard', f=graveyard),
        MenuItem('Rename', f=rename_pet, predicate=lambda: session.pet is not None),
        MenuItem('NFC: Beam Pet', f=nfc_beam, predicate=lambda: bool(glob.NFC) and session.pet is not None),
        MenuItem('NFC: Receive Pet', f=nfc_receive, predicate=lambda: bool(glob.NFC)),
        MenuItem('Help', f=pet_help),
    ]
    return PetMenu(items)


async def back_to_pet(*a):
    if session.pet:
        goto_pet_screen()


async def pet_help(*a):
    await ux_show_story(D.HELP_TEXT, title="Pet Help")


async def rename_pet(*a):
    pet = session.pet
    if not pet: return
    nm = await ux_input_text(pet.name, max_len=10, min_len=1)
    if nm:
        pet.name = nm.strip()[:10] or pet.name
        session.save()


def _pet_label(d):
    return '%s (%s)' % (d.get('name', '?'), d.get('stage', '?'))


async def switch_pet(*a):
    s = session
    pets = s.other_pets()
    if not pets:
        await ux_show_story("No other pets on this card." if s.card_present()
                            else "No card, no pets.")
        return
    items = []
    for pid, d in sorted(pets.items(), key=lambda kv: kv[1].get('name', '')):
        if s.pet and pid == s.pet.id:
            continue
        items.append(MenuItem(_pet_label(d), f=_pick_pet, arg=d))
    if not items:
        await ux_show_story("Only %s is on this card." % s.pet.name)
        return
    the_ux.push(Picker(items))


async def _pick_pet(menu, idx, item):
    s = session
    d = item.arg
    if s.pet and s.pet.alive:
        s.save()
    pet = M.Pet.from_dict(d, s.rng)
    s.adopt(pet, just_woke=True)
    goto_pet_screen()


async def breed_pets(*a):
    s = session
    pets = s.other_pets()
    adults = {k: v for k, v in pets.items()
              if v.get('alive', True) and v.get('stage') in ('adult', 'elder')}
    if s.pet and s.pet.alive and s.pet.stage in ('adult', 'elder'):
        adults[s.pet.id] = s.pet.to_dict()
    if len(adults) < 2:
        await ux_show_story("Breeding needs two living adults on this card. "
                            "You have %d.\n\nRaise another one (New Egg), or "
                            "borrow a card." % len(adults), title="Breed")
        return

    picked = []

    async def pick(menu, idx, item):
        picked.append(item.arg)
        the_ux.pop()

    for which in ('mother', 'father'):
        items = [MenuItem(_pet_label(d), f=pick, arg=d) for pid, d in adults.items()
                 if not picked or pid != picked[0]['id']]
        m = Picker(items)
        the_ux.push(m)
        # run the picker inline until it pops itself
        while the_ux.top_of_stack() is m:
            await m.interact()
        if len(picked) < (1 if which == 'mother' else 2):
            return

    mother = M.Pet.from_dict(picked[0], s.rng)
    father = M.Pet.from_dict(picked[1], s.rng)
    if s.pet and s.pet.id == mother.id: mother = s.pet
    if s.pet and s.pet.id == father.id: father = s.pet

    dis = glob.dis
    for i in range(21):
        D.draw_hatching(dis, S.EGGS[0], i / 20.0, i)
        await sleep_ms(60)
    child, msg = M.breed(mother, father, s.entropy(64), s.rng)
    if not child:
        await ux_show_story(msg, title="No egg")
        return
    # parents spent some energy; persist whichever is not the current pet
    for p in (mother, father):
        if p is not s.pet and s.card_present():
            try: s.store.save(p.to_dict())
            except (CardMissingError, OSError): pass
    if s.pet and s.pet.alive:
        s.save()
    D.draw_hatching(dis, S.EGGS[child.g.body % len(S.EGGS)], 1.0, 0)
    await sleep_ms(900)
    s.adopt(child)
    await ux_show_story(msg + "\n\nGeneration %d. Genome mixed from both parents "
                        "with fresh TRNG mutations. The egg is now the active pet."
                        % child.generation, title="Bred")
    goto_pet_screen()


async def graveyard(*a):
    s = session
    if not s.card_present():
        await ux_show_story("No card, no graveyard.")
        return
    try:
        graves = s.store.graveyard()
    except (CardMissingError, OSError):
        graves = []
    if not graves:
        await ux_show_story("Nobody has died yet.\n\nGive it time.", title="Graveyard")
        return
    items = [MenuItem('%s, %s' % (t.get('name', '?'), M.fmt_awake(t.get('age', 0))),
                      f=_show_grave, arg=t) for t in graves]
    the_ux.push(Picker(items))


async def _show_grave(menu, idx, item):
    t = item.arg
    st = t.get('stats', {})
    msg = t.get('epitaph', '') + '\n\n'
    msg += 'Stage: %s\nGen: %d\nWeight: %dg\n' % (t.get('stage'), t.get('generation', 1), t.get('weight', 0))
    msg += 'Meals %d Snacks %d\nGames %d Naps %d\nMistakes %d\n' % (
        st.get('meals', 0), st.get('snacks', 0), st.get('games', 0), st.get('naps', 0), st.get('mistakes', 0))
    msg += 'Temper: %s\nid %s\n' % (t.get('temperament', '?'), t.get('id', '?'))
    await ux_show_story(msg, title=t.get('name', 'R.I.P.'))


# ---------------------------------------------------------------- NFC (phone relay)
# Mk4 NFC is a passive tag: two Coldcards cannot tap each other. A phone can
# read the pet off one device and write it into another. SD card stays primary.
async def nfc_beam(*a):
    s = session
    if not glob.NFC or not s.pet:
        return
    s.save()
    await glob.NFC.share_text(s.pet.to_json())


async def nfc_receive(*a):
    import ndef
    s = session
    if not glob.NFC:
        return
    data = await glob.NFC.start_nfc_rx()
    if not data:
        return
    got = None
    try:
        for urn, msg, meta in ndef.record_parser(data):
            if urn == 'urn:nfc:wkt:T' or (msg and msg[:1] == b'{'):
                try:
                    d = M.json.loads(bytes(msg).decode())
                    if d.get('genome') and d.get('id'):
                        got = d
                        break
                except Exception:
                    continue
    except Exception:
        got = None
    if not got:
        await ux_show_story("That wasn't a pet.", title="Sorry!")
        return
    pet = M.Pet.from_dict(got, s.rng)
    if not pet.alive:
        await ux_show_story("Someone beamed you a dead pet. Rude.", title="Sorry!")
        return
    if s.pet and s.pet.alive:
        s.save()
    s.adopt(pet, just_woke=True)
    await ux_show_story("%s arrived over NFC.\n\nDon't keep the other copy alive "
                        "too; that's cloning, and it knows." % pet.name, title="Received")
    goto_pet_screen()


# ---------------------------------------------------------------- minigames
async def play_menu():
    s = session
    pet = s.pet
    ok, why = pet.can_play()
    if not ok:
        await ux_show_story(why, title="Nope")
        return
    ch = await ux_show_story("1: PIN Drill\n   (memory game)\n\n2: Which Way?\n   (guess left/right)\n\n"
                             "Winning makes it happy and thinner.", title="Play", escape='12')
    if ch == '1':
        await game_pin_drill()
    elif ch == '2':
        await game_which_way()
    s.save()


async def game_pin_drill():
    # It shows you a PIN. You type it back. Rounds get longer. Sound familiar?
    s = session
    dis = glob.dis
    pet = s.pet
    won_rounds = 0
    for rnd in range(1, 4):
        length = 3 + rnd
        pin = ''.join(str(s.rng(10)) for _ in range(length))
        frames = (1000 + 450 * length) // 250
        for f in range(frames):
            D.draw_pin_drill(dis, pet, pin, '', rnd, f, 'show')
            ch = await ux_wait_keydown(timeout_ms=250)
            if ch == 'x':
                return
            if ch:
                break                       # impatient: straight to typing
        entered = ''
        f = 0
        gave_up = False
        while len(entered) < length:
            D.draw_pin_drill(dis, pet, pin, entered, rnd, f, 'input')
            f += 1
            ch = await ux_wait_keydown(allowed='0123456789x', timeout_ms=300)
            if ch == 'x':
                gave_up = True
                break
            if ch:
                entered += ch
        if gave_up:
            entered = entered or '?'
        phase = 'win' if entered == pin else 'lose'
        if phase == 'win':
            won_rounds += 1
        f = 0
        while True:
            D.draw_pin_drill(dis, pet, pin, entered, rnd, f, phase)
            f += 1
            ch = await ux_wait_keydown(timeout_ms=400)
            if ch in ('y', 'x'):
                break
        if phase == 'lose' or ch == 'x':
            break
    ok, msg = pet.play_result(won_rounds >= 2, won_rounds)
    await ux_show_story("%d of 3 rounds.\n\n%s" % (won_rounds, msg), title="PIN Drill")


async def game_which_way():
    s = session
    dis = glob.dis
    pet = s.pet
    score = 0
    for rnd in range(1, 6):
        facing = 'L' if s.rng(2) else 'R'
        guess = None
        f = 0
        while guess is None:
            D.draw_which_way(dis, pet, facing, None, score, rnd, f, False)
            f += 1
            ch = await ux_wait_keydown(allowed='46x', timeout_ms=300)
            if ch == 'x':
                return
            if ch == '4': guess = 'L'
            if ch == '6': guess = 'R'
        if guess == facing:
            score += 1
        for f in range(4):
            D.draw_which_way(dis, pet, facing, guess, score, rnd, f, True)
            await sleep_ms(220)
    ok, msg = pet.play_result(score >= 3, score)
    await ux_show_story("%d of 5.\n\n%s" % (score, msg), title="Which Way?")

# EOF
