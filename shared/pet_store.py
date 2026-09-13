# pet_store.py - the pet lives on the microSD card. This is how.
#
# Part of the unofficial COLDCARD Tamagotchi fork. See NOTICE and LICENSE-PET.
#
# Layout on the card:
#     /pets/<id>.a  /pets/<id>.b     two alternating save slots per pet
#     /pets/active.txt               id of the pet currently being raised
#     /pets/graveyard/<id>.json      tombstones
#
# Power can go at any instant, so a save never overwrites the last good copy:
# we write the OTHER slot, with a counter and a CRC32. On load, both slots are
# parsed, corrupt ones ignored, highest counter wins. A yanked cable can cost
# you up to AUTOSAVE_EVERY seconds of the pet's life, never the pet.
#
# Filesystem access goes through a tiny adapter (open/listdir/remove/mkdir/
# exists/sync on paths relative to the card root) so the same code runs on the
# device (CardFS, wraps files.CardSlot) and under CPython tests (a directory).
#
try:
    import ujson as json
except ImportError:
    import json
try:
    from ubinascii import crc32
except ImportError:
    from binascii import crc32

MAGIC = 'CCPET1'
PETS_DIR = 'pets'
GRAVE_DIR = 'pets/graveyard'
ACTIVE_FILE = 'pets/active.txt'


class StoreError(Exception):
    pass


def _encode(n, payload):
    body = json.dumps(payload)
    return '%s\n%08x\n%d\n%s\n' % (MAGIC, crc32(body.encode()) & 0xffffffff, n, body)

def _decode(text):
    # returns (n, payload) or raises
    parts = text.split('\n', 3)
    if len(parts) < 4 or parts[0] != MAGIC:
        raise StoreError('bad magic')
    want = int(parts[1], 16)
    n = int(parts[2])
    body = parts[3].rstrip('\n')
    if (crc32(body.encode()) & 0xffffffff) != want:
        raise StoreError('bad crc')
    return n, json.loads(body)


class PetStore:
    # fs_factory: callable returning a context manager that yields an fs adapter
    def __init__(self, fs_factory):
        self.fs_factory = fs_factory
        self._slot = {}       # id -> (last counter, last slot letter) once seen

    # ------------------------------------------------------------ internals
    def _prep(self, fs):
        for d in (PETS_DIR, GRAVE_DIR):
            if not fs.exists(d):
                fs.mkdir(d)

    def _read_slot(self, fs, path):
        try:
            with fs.open(path, 'r') as f:
                return _decode(f.read())
        except (OSError, ValueError, StoreError):
            return None

    # ------------------------------------------------------------ pets
    def load_all(self):
        # -> dict id -> pet dict (best valid copy). Also learns slot counters.
        found = {}
        self._slot = {}       # the card is the truth; rebuild from scratch
        with self.fs_factory() as fs:
            if not fs.exists(PETS_DIR):
                return found
            for fn in fs.listdir(PETS_DIR):
                if len(fn) != 10 or fn[8] != '.' or fn[9] not in 'ab':
                    continue
                pid, slot = fn[:8], fn[9]
                got = self._read_slot(fs, PETS_DIR + '/' + fn)
                if not got:
                    continue
                n, d = got
                if d.get('id') != pid:
                    continue
                prev = self._slot.get(pid)
                if prev is None or n > prev[0]:
                    self._slot[pid] = (n, slot)
                    found[pid] = d
        return found

    def save(self, d):
        # d: pet.to_dict(). Writes the slot NOT holding the newest copy.
        pid = d['id']
        n, slot = self._slot.get(pid, (0, 'b'))
        n += 1
        slot = 'a' if slot == 'b' else 'b'
        with self.fs_factory() as fs:
            self._prep(fs)
            with fs.open('%s/%s.%s' % (PETS_DIR, pid, slot), 'w') as f:
                f.write(_encode(n, d))
            fs.sync()
        self._slot[pid] = (n, slot)
        return True

    def delete(self, pid):
        with self.fs_factory() as fs:
            for slot in 'ab':
                p = '%s/%s.%s' % (PETS_DIR, pid, slot)
                if fs.exists(p):
                    fs.remove(p)
            fs.sync()
        self._slot.pop(pid, None)

    # ------------------------------------------------------------ active pointer
    def get_active(self):
        with self.fs_factory() as fs:
            if not fs.exists(ACTIVE_FILE):
                return None
            try:
                with fs.open(ACTIVE_FILE, 'r') as f:
                    v = f.read().strip()
                return v if len(v) == 8 else None
            except OSError:
                return None

    def set_active(self, pid):
        with self.fs_factory() as fs:
            self._prep(fs)
            with fs.open(ACTIVE_FILE, 'w') as f:
                f.write((pid or '') + '\n')
            fs.sync()

    # ------------------------------------------------------------ graveyard
    def bury(self, tomb):
        # write tombstone FIRST, then remove the saves: a power cut between the
        # two leaves a dead pet on the card, which load() treats as buried.
        pid = tomb['id']
        with self.fs_factory() as fs:
            self._prep(fs)
            with fs.open('%s/%s.json' % (GRAVE_DIR, pid), 'w') as f:
                f.write(json.dumps(tomb))
            fs.sync()
            for slot in 'ab':
                p = '%s/%s.%s' % (PETS_DIR, pid, slot)
                if fs.exists(p):
                    fs.remove(p)
            fs.sync()
        self._slot.pop(pid, None)

    def graveyard(self):
        # list of tombstone dicts, oldest death first (by awake age is meaningless;
        # use file order, which FAT keeps as creation order most of the time)
        out = []
        with self.fs_factory() as fs:
            if not fs.exists(GRAVE_DIR):
                return out
            for fn in fs.listdir(GRAVE_DIR):
                if not fn.endswith('.json'):
                    continue
                try:
                    with fs.open(GRAVE_DIR + '/' + fn, 'r') as f:
                        out.append(json.loads(f.read()))
                except (OSError, ValueError):
                    continue
        return out


# ---------------------------------------------------------------- adapters
class DirFS:
    # plain directory; used by tests and could be used for the sim's MicroSD dir
    def __init__(self, root):
        import os
        self.os = os
        self.root = root

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def _p(self, rel):
        return self.root + '/' + rel if rel else self.root

    def open(self, rel, mode):
        return open(self._p(rel), mode)

    def listdir(self, rel):
        return self.os.listdir(self._p(rel))

    def remove(self, rel):
        self.os.remove(self._p(rel))

    def mkdir(self, rel):
        try:
            self.os.mkdir(self._p(rel))
        except OSError:
            pass

    def exists(self, rel):
        try:
            self.os.stat(self._p(rel))
            return True
        except OSError:
            return False

    def sync(self):
        try:
            self.os.sync()
        except AttributeError:
            pass


class CardFS:
    # the real thing: powers up the slot, mounts the card, and unmounts on exit.
    # Raises files.CardMissingError from __enter__ if there is no card.
    def __init__(self):
        from files import CardSlot
        self.card = CardSlot()
        self.root = None

    def __enter__(self):
        self.card.__enter__()
        self.root = self.card.mountpt
        return self

    def __exit__(self, *a):
        self.card.__exit__(*a)
        return False

    def _p(self, rel):
        return self.root + '/' + rel if rel else self.root

    def open(self, rel, mode):
        return self.card.open(self._p(rel), mode)

    def listdir(self, rel):
        import os
        return os.listdir(self._p(rel))

    def remove(self, rel):
        import os
        os.remove(self._p(rel))

    def mkdir(self, rel):
        import os
        try:
            os.mkdir(self._p(rel))
        except OSError:
            pass

    def exists(self, rel):
        import os
        try:
            os.stat(self._p(rel))
            return True
        except OSError:
            return False

    def sync(self):
        import os
        try:
            os.sync()
        except AttributeError:
            pass

# EOF
