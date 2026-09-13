# Test harness for the pet: runs the firmware's pure-Python pet modules under CPython.
# Nothing here needs the simulator, the toolchain, or a device.
import os, sys, random
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'pet', 'tools'))
# shared/ goes LAST: it has a random.py that must not shadow the stdlib one
sys.path.append(os.path.join(ROOT, 'shared'))


@pytest.fixture
def rng():
    # deterministic stand-in for ngu.random.uniform
    r = random.Random(1234)
    return lambda n: r.randrange(n)


@pytest.fixture
def entropy():
    # deterministic stand-in for ckcc.rng_bytes(); 64 bytes so breeding works too
    r = random.Random(99)
    def make(n=32, seed=None):
        rr = random.Random(seed) if seed is not None else r
        return bytes(rr.randrange(256) for _ in range(n))
    return make
