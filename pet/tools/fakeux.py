# fakeux.py - run shared/pet_ux.py under CPython asyncio with a scripted keypad
# and a fake clock, so the whole screen loop (ticker, saves, death, menus) can
# be tested without the simulator.
#
# Everything the firmware provides to pet_ux is stubbed here with the same
# shapes: uasyncio, utime, ckcc, ngu, glob, ux, menu, files, exceptions.
# Time only advances when something sleeps or waits: deterministic.
#
import os, sys, types, asyncio, random

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
from fakehw import make_display, _install_stubs, SHARED


class Clock:
    def __init__(self):
        self.ms = 1000

    def advance(self, ms):
        self.ms += ms


class AbortInteraction(Exception):
    pass


class UserInteraction:
    # copy of ux.UserInteraction
    def __init__(self):
        self.stack = []

    def top_of_stack(self):
        return self.stack[-1] if self.stack else None

    def reset(self, new_ux):
        self.stack.clear()
        self.push(new_ux)

    async def interact(self):
        try:
            await self.stack[-1].interact()
        except AbortInteraction:
            pass

    def push(self, new_ux):
        self.stack.append(new_ux)

    def replace(self, new_ux):
        self.stack.pop()
        self.stack.append(new_ux)

    def pop(self):
        if len(self.stack) < 2:
            return True
        self.stack.pop()

    def parent_of(self, child):
        for n, x in enumerate(self.stack):
            if x == child and n:
                return self.stack[n - 1]
        return None


class IdleScreen:
    # stands in for the firmware's top-level menu: sits there letting time pass
    def __init__(self, clock):
        self.clock = clock
    async def interact(self):
        self.clock.advance(400)
        await asyncio.sleep(0)


class Harness:
    def reset_to_top(self):
        self.the_ux.reset(IdleScreen(self.clock))

    def __init__(self, card_dir=None, card_inserted=True, seed=5):
        self.clock = Clock()
        self.keys = []            # scripted keydowns
        self.stories = []         # (title, msg) shown via ux_show_story
        self.story_answers = []   # scripted returns for ux_show_story
        self.confirm_answers = []
        self.text_answers = []
        self.menu_script = []     # labels to pick when a MenuSystem interacts, or 'x'
        self.card_dir = card_dir
        self.card_inserted = card_inserted
        self.rand = random.Random(seed)
        self.the_ux = UserInteraction()
        self.last_event_time = 0
        self._install()

    # ------------------------------------------------------------ scripting
    def press(self, *keys):
        for k in keys:
            self.keys.extend(list(k) if len(k) > 1 and k not in ('x', 'y') else [k])

    # ------------------------------------------------------------ stubs
    def _install(self):
        _install_stubs()
        H = self
        ms = sys.modules

        # -- uasyncio: real asyncio, but sleeping advances the fake clock
        ua = types.ModuleType('uasyncio')
        async def sleep_ms(n):
            H.clock.advance(n)
            await asyncio.sleep(0)
        ua.sleep_ms = sleep_ms
        ua.create_task = asyncio.create_task
        ua.sleep = asyncio.sleep
        ms['uasyncio'] = ua

        # -- utime on the fake clock
        ut = types.ModuleType('utime')
        ut.ticks_ms = lambda: H.clock.ms
        ut.ticks_diff = lambda a, b: a - b
        ut.ticks_add = lambda a, b: a + b
        ut.ticks_us = lambda: H.clock.ms * 1000
        ut.sleep_ms = lambda n: H.clock.advance(n)
        ms['utime'] = ut

        # -- entropy
        ck = ms['ckcc']
        def rng_bytes(buf):
            for i in range(len(buf)):
                buf[i] = H.rand.randrange(256)
        ck.rng_bytes = rng_bytes
        ck.is_simulator = lambda: True

        ngu = types.ModuleType('ngu')
        ngu.random = types.SimpleNamespace(uniform=lambda n: H.rand.randrange(n))
        ms['ngu'] = ngu

        # -- glob
        g = types.ModuleType('glob')
        g.dis = make_display()
        class Numpad:
            ABORT_KEY = '\xff'
            key_pressed = ''
            def __init__(s2): s2.last_event_time = H.clock.ms
            def clear_pressed(s2): pass
            def empty(s2): return not H.keys
        g.numpad = Numpad()
        g.NFC = None
        g.settings = None
        g.hsm_active = None
        ms['glob'] = g
        self.glob = g

        # -- exceptions
        ex = types.ModuleType('exceptions')
        ex.AbortInteraction = AbortInteraction
        ms['exceptions'] = ex

        # -- ux
        ux = types.ModuleType('ux')
        ux.the_ux = self.the_ux
        async def ux_wait_keydown(allowed=None, timeout_ms=None):
            while H.keys:
                k = H.keys.pop(0)
                if allowed and k not in allowed:
                    continue
                H.glob.numpad.last_event_time = H.clock.ms
                return k
            if timeout_ms:
                H.clock.advance(timeout_ms)
            await asyncio.sleep(0)
            return None
        ux.ux_wait_keydown = ux_wait_keydown
        async def ux_show_story(msg, title=None, escape=None, **kw):
            H.stories.append((title, msg))
            await asyncio.sleep(0)
            return H.story_answers.pop(0) if H.story_answers else 'y'
        ux.ux_show_story = ux_show_story
        async def ux_confirm(msg, title=None, **kw):
            H.stories.append((title, msg))
            await asyncio.sleep(0)
            return H.confirm_answers.pop(0) if H.confirm_answers else True
        ux.ux_confirm = ux_confirm
        async def ux_input_text(pw, **kw):
            await asyncio.sleep(0)
            return H.text_answers.pop(0) if H.text_answers else None
        ux.ux_input_text = ux_input_text
        ux.ux_clear_keys = lambda *a, **k: None
        ms['ux'] = ux

        # -- menu
        mn = types.ModuleType('menu')
        class MenuItem:
            def __init__(self, label, menu=None, f=None, chooser=None, arg=None,
                         predicate=None, shortcut=None):
                self.label = label; self.arg = arg
                self.next_menu = menu; self.next_function = f
                self._predicate = predicate
            def predicate(self):
                if self._predicate is None: return True
                return self._predicate() if callable(self._predicate) else self._predicate
            async def activate(self, menu, idx):
                if self.next_function:
                    rv = await self.next_function(menu, idx, self)
                    if isinstance(rv, MenuSystem):
                        H.the_ux.replace(rv)
                m = self.next_menu
                if callable(m):
                    m = await m(menu, idx, self)
                if isinstance(m, list):
                    m = MenuSystem(m)
                if m:
                    H.the_ux.push(m)
        class MenuSystem:
            def __init__(self, items, chosen=None, should_cont=None, **kw):
                self.items = [i for i in items if i.predicate()]
                self.cursor = 0
                self.labels = [i.label for i in self.items]
                H.menus_seen.append(self.labels)
            def show(self): pass
            def update_contents(self): pass
            async def interact(self):
                while H.the_ux.top_of_stack() is self:
                    await asyncio.sleep(0)
                    if not H.menu_script:
                        # nothing scripted: idle, let time pass
                        H.clock.advance(400)
                        continue
                    want = H.menu_script.pop(0)
                    if want == 'x':
                        H.the_ux.pop()
                        return
                    for idx, it in enumerate(self.items):
                        if it.label == want:
                            self.cursor = idx
                            await it.activate(self, idx)
                            break
                    else:
                        raise AssertionError('menu has no item %r; has %r' % (want, self.labels))
        mn.MenuItem = MenuItem
        mn.MenuSystem = MenuSystem
        ms['menu'] = mn
        self.menus_seen = []

        # -- files: CardSlot over a directory
        fl = types.ModuleType('files')
        class CardMissingError(RuntimeError):
            pass
        class CardSlot:
            @classmethod
            def is_inserted(cls):
                return H.card_inserted
            def __init__(self, **kw):
                self.mountpt = None
            def __enter__(self):
                if not H.card_inserted:
                    raise CardMissingError
                self.mountpt = H.card_dir
                return self
            def __exit__(self, *a):
                return False
            def open(self, fname, mode='r', **kw):
                return open(fname, mode, **kw)
        fl.CardSlot = CardSlot
        fl.CardMissingError = CardMissingError
        ms['files'] = fl

        # fresh pet modules every harness (module-level session singleton)
        for m in ('pet_ux', 'pet_store', 'pet_model', 'pet_draw', 'pet_sprites'):
            ms.pop(m, None)
        if SHARED not in sys.path:
            sys.path.append(SHARED)
        import pet_ux
        self.pet_ux = pet_ux
        self.session = pet_ux.session

    # ------------------------------------------------------------ running
    async def _mainline(self):
        # same shape as main.py's mainline(): forever interact with top of stack
        while True:
            if self.the_ux.stack:
                await self.the_ux.interact()
            else:
                self.clock.advance(100)
                await asyncio.sleep(0)

    async def run_until(self, cond, max_ms=600000):
        # step the event loop (mainline + ticker) until cond() or the fake clock
        # has advanced max_ms. Returns True if cond became true.
        if getattr(self, '_main_task', None) is None or self._main_task.done():
            self._main_task = asyncio.ensure_future(self._mainline())
        deadline = self.clock.ms + max_ms
        while self.clock.ms < deadline:
            if cond():
                return True
            if self._main_task.done() and self._main_task.exception():
                raise self._main_task.exception()
            await asyncio.sleep(0)
        return cond()

    def run(self, coro):
        # sync helper for tests: one asyncio loop per test
        return asyncio.run(coro)

# EOF
