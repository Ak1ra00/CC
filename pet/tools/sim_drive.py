#!/usr/bin/env python3
# sim_drive.py - drive the (headless) COLDCARD simulator through the pet, over its
# USB socket, and save real OLED frames as PNG. This is the pet running on actual
# MicroPython, frozen-module code paths and all.
#
#   python pet/tools/sim_drive.py pet/screenshots/sim     (from the repo root)
#
# Launches unix/simulator.py itself, several times: the pet has to survive a
# reboot, and the no-card / unmountable-card screens have to be the ones a
# person sees, not the ones the CPython harness imagines. Logs go to sim-N.log.
# Exits non-zero if anything doesn't happen the way the tests say it should.
import os, sys, time, json, signal, subprocess

from ckcc.client import ColdcardDevice
from ckcc.protocol import CCProtocolPacker
from PIL import Image

OUT = sys.argv[1] if len(sys.argv) > 1 else 'pet/screenshots/sim'
SOCK = sys.argv[2] if len(sys.argv) > 2 else '/tmp/ckcc-simulator.sock'
FG, BG = (204, 204, 255), (17, 17, 17)


def connect(timeout=120):
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        try:
            dev = ColdcardDevice(sn=SOCK, is_simulator=True)
            dev.send_recv(b'EXEC' + b'RV.write(b"ok")', timeout=5000, encrypt=False)
            return dev
        except Exception as e:
            last = e
            time.sleep(1)
    raise SystemExit('simulator never answered: %r' % last)


LAUNCHES = 0

def launch(*args):
    # start unix/simulator.py headless (it spawns the MicroPython child); the
    # whole process group gets killed by stop(), so the socket frees up.
    global LAUNCHES
    LAUNCHES += 1
    try:
        os.remove(SOCK)
    except OSError:
        pass
    log = open('sim-%d.log' % LAUNCHES, 'w')
    print('launch #%d: simulator.py --headless %s' % (LAUNCHES, ' '.join(args)))
    proc = subprocess.Popen([sys.executable, './simulator.py', '--headless'] + list(args),
                            cwd='unix', stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    return proc

def stop(proc):
    # SIGKILL the group: simulator.py ignores SIGINT and would leave its child
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except OSError:
        pass
    proc.wait()
    time.sleep(0.5)


SHOTS = 0       # frame numbering runs across simulator relaunches

class Sim:
    def __init__(self, dev):
        self.dev = dev
        os.makedirs(OUT, exist_ok=True)

    @property
    def n(self):
        return SHOTS

    def exec(self, code, timeout=10000):
        return self.dev.send_recv(b'EXEC' + code.encode(), timeout=timeout, encrypt=False)

    def ev(self, expr):
        # repr() of an expression evaluated inside the simulator
        return self.exec('RV.write(repr(%s).encode())' % expr).decode()

    def key(self, *keys, gap=0.05):
        for k in keys:
            self.dev.send_recv(CCProtocolPacker.sim_keypress(k.encode('ascii')), timeout=5000)
            time.sleep(gap)

    def frame(self):
        raw = self.exec('RV.write(bytes(glob.dis.dis.buffer))')
        assert len(raw) == 1024, len(raw)
        return raw

    def shot(self, name, scale=4):
        buf = self.frame()
        img = Image.new('RGB', (128, 64), BG)
        px = img.load()
        for x in range(128):
            for page in range(8):
                v = buf[page * 128 + x]
                for bit in range(8):
                    if v & (1 << bit):
                        px[x, page * 8 + bit] = FG
        img = img.resize((128 * scale, 64 * scale), Image.NEAREST)
        global SHOTS
        fn = os.path.join(OUT, '%02d_%s.png' % (SHOTS, name))
        img.save(fn)
        SHOTS += 1
        print('shot', fn, '| screen text:', self.ev('sim_display.full_contents')[:70])
        return img

    def wait(self, expr, want=None, timeout=20, msg=''):
        t0 = time.time()
        while time.time() - t0 < timeout:
            v = self.ev(expr)
            if (want is None and v not in ('None', 'False', '')) or (want is not None and v == want):
                return v
            time.sleep(0.25)
        raise SystemExit('timeout waiting for %s == %r (last %r) %s' % (expr, want, v, msg))

    def pet(self, attr):
        return self.ev("__import__('pet_ux').session.pet.%s" % attr)


def main():
    proc = launch('--pet')
    sim = Sim(connect())
    print('connected; version', sim.ev('version.get_mpy_version()'))

    # --pet pressed OK on "Virtual Pet"; no card pets => New Egg story is up
    sim.wait('sim_display.story', msg='(New Egg story)')
    story = sim.ev('sim_display.story')
    assert 'New Egg' in story, story
    sim.shot('new_egg_story')
    sim.key('y')
    sim.wait("__import__('pet_ux').session.pet is not None", want='True')
    sim.wait("__import__('pet_ux').session.active", want='True')
    time.sleep(0.6)
    sim.shot('egg')
    name = sim.pet('name').strip("'")
    print('pet name:', name, 'genome', sim.pet('g.to_hex()'))

    # warm it: exactly enough presses to hatch (see pet_model.EGG_WARM)
    need = int(sim.ev("-(-__import__('pet_model').STAGE_AT['baby'] // __import__('pet_model').EGG_WARM)"))
    for i in range(need):
        if sim.pet('is_egg()') != 'True':
            break                       # real ticks warmed it too; don't over-press
        sim.key('5', gap=0.02)
        if i % 10 == 9:
            time.sleep(0.3)
    sim.wait("__import__('pet_ux').session.pet.stage", want="'baby'", msg='(hatch)')
    time.sleep(0.5)
    sim.shot('hatched')

    # it must be aging on real ticks now: wait for ~3 awake seconds
    a0 = int(sim.pet('age'))
    sim.wait("__import__('pet_ux').session.pet.age >= %d" % (a0 + 3), want='True', timeout=15,
             msg='(ticker)')
    # and the idle-logout clock was bumped by the ticker (no keys pressed meanwhile)
    print('numpad.last_event_time', sim.ev('glob.numpad.last_event_time'))

    # actions
    sim.exec("p=__import__('pet_ux').session.pet; p.hunger=40.0; p.discipline=100.0")
    sim.key('1'); time.sleep(0.5); sim.shot('feed')
    assert sim.pet("stats['meals']") == '1'
    sim.key('2'); time.sleep(0.5); sim.shot('snack')
    sim.exec("p=__import__('pet_ux').session.pet; p.poop=2; p.hunger=15.0")
    time.sleep(1.2); sim.shot('hungry_poop')
    sim.key('4'); time.sleep(0.5); sim.shot('clean')
    assert sim.pet('poop') == '0'
    sim.key('y'); time.sleep(0.5); sim.shot('pat')
    sim.key('0'); time.sleep(0.5); sim.shot('talk')

    # the card: saves should exist in the simulated MicroSD
    pid = sim.pet('id').strip("'")
    files = sim.ev("__import__('os').listdir(__import__('ckcc').get_sim_root_dirs()[1] + '/pets')")
    print('card files:', files)
    assert pid + '.a' in files, files

    # stats + help stories
    sim.key('7'); sim.wait('sim_display.story'); sim.shot('stats'); sim.key('x'); time.sleep(0.3)
    sim.key('8'); sim.wait('sim_display.story'); sim.shot('help'); sim.key('x'); time.sleep(0.3)

    # minigame: PIN drill, quit out with X after the show phase
    sim.exec("p=__import__('pet_ux').session.pet; p.energy=90.0")
    sim.key('3'); sim.wait('sim_display.story'); sim.shot('play_menu')
    sim.key('1'); time.sleep(0.8); sim.shot('pin_drill')
    sim.key('x'); time.sleep(0.5)
    sim.wait("__import__('pet_ux').session.active", want='True')

    # pet menu
    sim.key('9'); time.sleep(0.6); sim.shot('pet_menu')
    sim.key('x'); time.sleep(0.5)

    # sickness, then death, witnessed
    sim.exec("p=__import__('pet_ux').session.pet; p.sick=True; p.sick_t=1")
    time.sleep(1.2); sim.shot('sick')
    sim.exec("import pet_model; p=__import__('pet_ux').session.pet; p.sick_t=pet_model.SICK_FATAL-2")
    sim.wait("__import__('pet_ux').session.pet.alive", want='False', timeout=15, msg='(death)')
    time.sleep(3.0)
    sim.shot('rip')
    sim.key('y')
    sim.wait('sim_display.story'); sim.shot('epitaph')
    epitaph = sim.ev('sim_display.story')
    assert 'Here lies' in epitaph, epitaph
    sim.key('y'); time.sleep(0.5)
    sim.wait("__import__('pet_ux').session.pet is None", want='True')
    graves = sim.ev("__import__('os').listdir(__import__('ckcc').get_sim_root_dirs()[1] + '/pets/graveyard')")
    print('graveyard:', graves)
    assert pid + '.json' in graves, graves
    files = sim.ev("__import__('os').listdir(__import__('ckcc').get_sim_root_dirs()[1] + '/pets')")
    assert pid + '.a' not in files and pid + '.b' not in files, files
    sim.shot('after_death_menu')

    # ------------------------------------------------------------ a second pet,
    # raised a little, then the power goes: it must come back on reboot.
    # (pet menu is up; with no pet, "New Egg" is its first item)
    sim.key('y')
    sim.wait('sim_display.story', msg='(New Egg story #2)')
    sim.key('y')
    sim.wait("__import__('pet_ux').session.pet is not None", want='True')
    sim.wait("__import__('pet_ux').session.active", want='True')
    for i in range(need):
        if sim.pet('is_egg()') != 'True':
            break
        sim.key('5', gap=0.02)
        if i % 10 == 9:
            time.sleep(0.3)
    sim.wait("__import__('pet_ux').session.pet.stage", want="'baby'", msg='(hatch #2)')
    sim.exec("p=__import__('pet_ux').session.pet; p.hunger=40.0")
    sim.key('1'); time.sleep(0.4)
    assert sim.pet("stats['meals']") == '1'
    sim.key('x'); time.sleep(0.6)               # X leaves the pet screen: saves
    pid2 = sim.pet('id').strip("'")
    age2 = int(sim.pet('age'))
    assert sim.ev("__import__('pet_ux').session.ram_only") == 'False'
    files = sim.ev("__import__('os').listdir(__import__('ckcc').get_sim_root_dirs()[1] + '/pets')")
    print('card files before power cut:', files)
    assert pid2 + '.a' in files or pid2 + '.b' in files, files
    stop(proc)
    print('--- power cut ---')

    # ------------------------------------------------------------ reboot, card in.
    # No --pet: nobody presses anything. main.py's pet_autostart has to find it.
    proc = launch()
    sim = Sim(connect())
    sim.wait("__import__('pet_ux').session.pet is not None", want='True', timeout=60,
             msg='(autostart after reboot)')
    assert sim.pet('id').strip("'") == pid2, (sim.pet('id'), pid2)
    assert int(sim.pet('age')) >= age2
    assert sim.pet("stats['meals']") == '1'
    assert sim.pet("stats['naps']") == '1'
    assert sim.ev("__import__('pet_ux').session.ram_only") == 'False'
    sim.wait("__import__('pet_ux').session.active", want='True', msg='(pet screen after reboot)')
    time.sleep(2.0)
    sim.shot('woke_up')
    # it keeps aging after the reboot
    a1 = int(sim.pet('age'))
    sim.wait("__import__('pet_ux').session.pet.age >= %d" % (a1 + 2), want='True', timeout=15,
             msg='(ticker after reboot)')
    # the Card Check screen, on MicroPython, with a real listing
    txt = sim.ev("__import__('pet_ux').session.card_check_text()")
    print('card check:', txt)
    assert 'Card OK' in txt and pid2 in txt and 'Active: ' + pid2 in txt, txt
    stop(proc)
    print('--- power cut ---')

    # ------------------------------------------------------------ reboot, no card.
    # Must not touch the card's pet, must not hand out a silent egg.
    proc = launch('--eject', '--pet')
    sim = Sim(connect())
    sim.wait("'Card?' in sim_display.full_contents", want='True', timeout=60, msg='(card? screen)')
    assert sim.ev("__import__('pet_ux').session.pet") == 'None'
    sim.shot('no_card')
    sim.key('y')                                # play in RAM anyway?
    sim.wait('sim_display.story', msg='(RAM only? confirm)')
    assert 'RAM only' in sim.ev('sim_display.story'), sim.ev('sim_display.story')
    sim.shot('ram_confirm')
    sim.key('y')
    time.sleep(0.5)
    sim.wait("__import__('pet_ux').session.pet is not None", want='True', timeout=30)
    sim.wait('sim_display.story', msg='(New Egg story, RAM)')
    story = sim.ev('sim_display.story')
    assert 'NOT SAVED' in story, story
    sim.key('y')
    sim.wait("__import__('pet_ux').session.active", want='True')
    assert sim.ev("__import__('pet_ux').session.ram_only") == 'True'
    sim.wait("'NOT SAVING' in sim_display.full_contents", want='True', timeout=10,
             msg='(RAM banner)')
    sim.shot('ram_banner')
    stop(proc)
    print('--- power cut ---')

    # ------------------------------------------------------------ reboot, card in,
    # then the card goes bad mid-life (mount fails, as with exFAT): loud, and it
    # recovers by itself when the card is usable again.
    proc = launch()
    sim = Sim(connect())
    sim.wait("__import__('pet_ux').session.pet is not None", want='True', timeout=60,
             msg='(autostart #2)')
    assert sim.pet('id').strip("'") == pid2
    assert sim.pet("stats['naps']") == '2'
    sim.wait("__import__('pet_ux').session.active", want='True')
    # the wake-up animation eats the first keypress; let it finish
    sim.wait("'WAKES UP' in sim_display.full_contents", want='True', timeout=10, msg='(waking)')
    sim.wait("'WAKES UP' not in sim_display.full_contents", want='True', timeout=10, msg='(awake)')
    time.sleep(0.5)
    sim.exec("import files; files._good_try = files._try_microsd; files._try_microsd = lambda: False")
    # discipline 100: a stubborn pet may refuse a meal, and a refusal doesn't save
    sim.exec("p=__import__('pet_ux').session.pet; p.hunger=40.0; p.discipline=100.0")
    sim.key('1')                                # feed: the save fails
    sim.wait('sim_display.story', timeout=15, msg='(Not Saving story)')
    story = sim.ev('sim_display.story')
    assert 'Not Saving' in story and 'will not mount' in story, story
    assert sim.ev("__import__('pet_ux').session.ram_only") == 'True'
    sim.shot('save_failed')
    sim.key('y')
    time.sleep(0.5)
    txt = sim.ev("__import__('pet_ux').session.card_check_text()")
    assert 'unusable' in txt and 'FAT32' in txt, txt
    sim.exec("import files; files._try_microsd = files._good_try")
    sim.exec("p=__import__('pet_ux').session.pet; p.hunger=40.0; p.discipline=100.0")
    meals = int(sim.pet("stats['meals']"))
    sim.key('1')                                # feed: the save works again
    sim.wait("__import__('pet_ux').session.pet.stats['meals']", want=str(meals + 1), timeout=10,
             msg='(fed after card fixed)')
    sim.wait("__import__('pet_ux').session.ram_only", want='False', timeout=15, msg='(recovered)')
    time.sleep(0.6)
    sim.shot('card_back')
    stop(proc)

    print('\nALL GOOD: %d frames in %s, %d simulator launches' % (sim.n, OUT, LAUNCHES))


if __name__ == '__main__':
    main()
