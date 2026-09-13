# fakehw.py - run the firmware's real display.py + fonts under CPython.
#
# Gives you a Display object whose drawing code is the actual firmware code
# (shared/display.py, shared/zevvpeep.py fonts), on top of a small pure-Python
# clone of MicroPython's framebuf. Enough to render pet screens to PNG for
# eyeballing and for the README, without the SDL simulator.
#
# Usage:
#   from fakehw import make_display, to_image
#   dis = make_display()
#   ... draw with dis.text()/dis.icon()/dis.dis.fill_rect() ...
#   to_image(dis, scale=4).save('screen.png')
#
import os, sys, types, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
SHARED = os.path.join(ROOT, 'shared')

MONO_VLSB = 0
MONO_HLSB = 3
MONO_HMSB = 4


class FrameBuffer:
    # Pure-Python subset of micropython framebuf, mono formats only.

    def __init__(self, buf, w, h, fmt, stride=None):
        self.buf = buf
        self.w = w
        self.h = h
        self.fmt = fmt
        self.stride = stride if stride is not None else w
        if fmt in (MONO_HLSB, MONO_HMSB):
            # micropython rounds horizontal strides up to whole bytes
            self.stride = (self.stride + 7) & ~7

    # -- pixel level --------------------------------------------------------
    def _get(self, x, y):
        if self.fmt == MONO_VLSB:
            i = (y >> 3) * self.stride + x
            return (self.buf[i] >> (y & 7)) & 1
        elif self.fmt == MONO_HLSB:
            i = (y * self.stride + x) >> 3
            return (self.buf[i] >> (7 - (x & 7))) & 1
        else:
            i = (y * self.stride + x) >> 3
            return (self.buf[i] >> (x & 7)) & 1

    def _set(self, x, y, c):
        if not (0 <= x < self.w and 0 <= y < self.h):
            return
        if self.fmt == MONO_VLSB:
            i = (y >> 3) * self.stride + x
            m = 1 << (y & 7)
        elif self.fmt == MONO_HLSB:
            i = (y * self.stride + x) >> 3
            m = 1 << (7 - (x & 7))
        else:
            i = (y * self.stride + x) >> 3
            m = 1 << (x & 7)
        if c:
            self.buf[i] |= m
        else:
            self.buf[i] &= ~m & 0xff

    def pixel(self, x, y, c=None):
        if c is None:
            if 0 <= x < self.w and 0 <= y < self.h:
                return self._get(x, y)
            return None
        self._set(x, y, c)

    # -- primitives -----------------------------------------------------------
    def fill(self, c):
        for i in range(len(self.buf)):
            self.buf[i] = 0xff if c else 0

    def fill_rect(self, x, y, w, h, c):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self._set(xx, yy, c)

    def rect(self, x, y, w, h, c, f=False):
        if f:
            return self.fill_rect(x, y, w, h, c)
        self.hline(x, y, w, c); self.hline(x, y + h - 1, w, c)
        self.vline(x, y, h, c); self.vline(x + w - 1, y, h, c)

    def hline(self, x, y, w, c):
        for xx in range(x, x + w):
            self._set(xx, y, c)

    def vline(self, x, y, h, c):
        for yy in range(y, y + h):
            self._set(x, yy, c)

    def line(self, x0, y0, x1, y1, c):
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self._set(x0, y0, c)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy; x0 += sx
            if e2 <= dx:
                err += dx; y0 += sy

    def blit(self, fb, x, y, key=-1):
        for yy in range(fb.h):
            for xx in range(fb.w):
                c = fb._get(xx, yy)
                if c == key:
                    continue
                self._set(x + xx, y + yy, c)

    def text(self, s, x, y, c=1):
        # 8x8 built-in font: not used by the pet. Draw boxes so it's obvious.
        for i, ch in enumerate(s):
            self.rect(x + i * 8, y, 7, 7, c)

    def scroll(self, dx, dy):
        raise NotImplementedError


def _install_stubs():
    if 'framebuf' in sys.modules and getattr(sys.modules['framebuf'], '_fake', False):
        return

    fb = types.ModuleType('framebuf'); fb._fake = True
    fb.FrameBuffer = FrameBuffer
    fb.MONO_VLSB, fb.MONO_HLSB, fb.MONO_HMSB = MONO_VLSB, MONO_HLSB, MONO_HMSB
    sys.modules['framebuf'] = fb

    uc = types.ModuleType('ucollections'); uc.namedtuple = collections.namedtuple
    sys.modules['ucollections'] = uc

    machine = types.ModuleType('machine')
    class Pin:
        OUT = 1; IN = 0; PULL_UP = 1
        def __init__(self, *a, **k): pass
        def __call__(self, *a): return 0
        def value(self, *a): return 0
    machine.Pin = Pin
    machine.SPI = lambda *a, **k: None
    sys.modules['machine'] = machine

    uzlib = types.ModuleType('uzlib')
    import zlib
    uzlib.decompress = lambda d, wbits=0: zlib.decompress(d, wbits)
    sys.modules['uzlib'] = uzlib

    ckcc = types.ModuleType('ckcc')
    ckcc.is_simulator = lambda: True
    ckcc.rng = lambda: 12345
    def rng_bytes(buf):
        import os as _os
        buf[:] = _os.urandom(len(buf))
    ckcc.rng_bytes = rng_bytes
    sys.modules['ckcc'] = ckcc

    utime = types.ModuleType('utime')
    import time
    utime.ticks_ms = lambda: int(time.time() * 1000) & 0x3fffffff
    utime.ticks_diff = lambda a, b: a - b
    utime.sleep_ms = lambda ms: None
    sys.modules['utime'] = utime

    version = types.ModuleType('version')
    version.mk_num = 4
    version.is_devmode = False
    version.has_qwerty = False
    version.hw_label = 'mk4'
    version.num_sd_slots = 1
    version.has_qr = False
    version.has_nfc = True
    version.get_mpy_version = lambda: ('2026-01-01', 'PET', '')
    sys.modules['version'] = version

    # real graphics table lives behind a symlink that Windows checkouts can't follow
    import importlib.util
    gpath = os.path.join(ROOT, 'graphics', 'graphics_mk4.py')
    spec = importlib.util.spec_from_file_location('graphics_mk4', gpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules['graphics_mk4'] = mod

    ssd = types.ModuleType('ssd1306')
    class SSD1306_SPI(FrameBuffer):
        def __init__(self, width, height, spi, dc, res, cs, is_mk5=False):
            self.width, self.height = width, height
            self.pages = height // 8
            self.buffer = bytearray(self.pages * width)
            super().__init__(self.buffer, width, height, MONO_VLSB)
            self.frames = 0
        def show(self):
            self.frames += 1
        def contrast(self, v): pass
        def busy_bar(self, enable, pattern): pass
    ssd.SSD1306_SPI = SSD1306_SPI
    sys.modules['ssd1306'] = ssd

    # shared/ goes LAST: it has a random.py that must not shadow the stdlib one
    if SHARED not in sys.path:
        sys.path.append(SHARED)


def make_display():
    _install_stubs()
    import display
    return display.Display()


def to_image(dis, scale=4, fg=(204, 204, 255), bg=(17, 17, 17)):
    # PIL image of the OLED, same colours as the SDL simulator
    from PIL import Image
    fb = dis.dis
    img = Image.new('RGB', (fb.width, fb.height), bg)
    px = img.load()
    for y in range(fb.height):
        for x in range(fb.width):
            if fb._get(x, y):
                px[x, y] = fg
    if scale != 1:
        img = img.resize((fb.width * scale, fb.height * scale), Image.NEAREST)
    return img


def to_text(dis):
    # ASCII dump, handy in test failures
    fb = dis.dis
    rows = []
    for y in range(fb.height):
        rows.append(''.join('#' if fb._get(x, y) else '.' for x in range(fb.width)))
    return '\n'.join(rows)

# EOF
