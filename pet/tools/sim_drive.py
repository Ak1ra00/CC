#!/usr/bin/env python3
# sim_drive.py - drive the (headless) COLDCARD simulator through the pet, over its
# USB socket, and save real OLED frames as PNG. This is the pet running on actual
# MicroPython, frozen-module code paths and all.
#
#   cd unix && ./simulator.py --headless --pet > sim.log 2>&1 &
#   python pet/tools/sim_drive.py pet/screenshots/sim [/tmp/ckcc-simulator.sock]
#
# Exits non-zero if anything doesn't happen the way the tests say it should.
import os, sys, time, json

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


class Sim:
    def __init__(self, dev):
        self.dev = dev
        self.n = 0
        os.makedirs(OUT, exist_ok=True)

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
        fn = os.path.join(OUT, '%02d_%s.png' % (self.n, name))
        img.save(fn)
        self.n += 1
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
    for i in range(0, need, 5):
        if sim.pet('is_egg()') != 'True':
            break                       # real ticks warmed it too; don't over-press
        sim.key(*(['5'] * min(5, need - i)), gap=0.03)
        time.sleep(0.4)
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

    print('\nALL GOOD: %d frames in %s' % (sim.n, OUT))


if __name__ == '__main__':
    main()
