# Tests for shared/pet_store.py -- atomic saves on a directory standing in for the card.
import os, json
import pytest

import pet_model as M
from pet_store import PetStore, DirFS, PETS_DIR, GRAVE_DIR, _encode, _decode, StoreError


@pytest.fixture
def card(tmp_path):
    root = str(tmp_path)
    return root, PetStore(lambda: DirFS(root))


def make_pet(entropy, rng, seed=1):
    return M.Pet(M.Genome(entropy(seed=seed)), rng)


def test_encode_decode_roundtrip():
    n, d = _decode(_encode(7, {'a': 1, 'b': [1, 2]}))
    assert n == 7 and d == {'a': 1, 'b': [1, 2]}


def test_decode_rejects_garbage_and_bad_crc():
    with pytest.raises(StoreError):
        _decode('nope')
    good = _encode(1, {'x': 1})
    bad = good.replace('"x": 1', '"x": 2')
    with pytest.raises(StoreError):
        _decode(bad)


def test_save_and_load(card, entropy, rng):
    root, store = card
    p = make_pet(entropy, rng)
    assert store.save(p.to_dict())
    assert os.path.exists(os.path.join(root, PETS_DIR, p.id + '.a'))
    got = store.load_all()
    assert list(got) == [p.id]
    q = M.Pet.from_dict(got[p.id], rng)
    assert q.to_dict() == p.to_dict()


def test_saves_alternate_slots_and_never_touch_last_good_copy(card, entropy, rng):
    root, store = card
    p = make_pet(entropy, rng)
    store.save(p.to_dict())
    a = open(os.path.join(root, PETS_DIR, p.id + '.a')).read()
    p.tick(10)
    store.save(p.to_dict())
    # second save went to .b; .a is byte-identical to before
    assert open(os.path.join(root, PETS_DIR, p.id + '.a')).read() == a
    assert os.path.exists(os.path.join(root, PETS_DIR, p.id + '.b'))
    p.tick(10)
    store.save(p.to_dict())
    # third save back to .a, and it now differs
    assert open(os.path.join(root, PETS_DIR, p.id + '.a')).read() != a


def test_yanked_cable_mid_write_falls_back_to_other_slot(card, entropy, rng):
    root, store = card
    p = make_pet(entropy, rng)
    store.save(p.to_dict())                       # -> .a, n=1
    p.tick(100)
    store.save(p.to_dict())                       # -> .b, n=2
    # simulate power loss while writing .b: truncate it
    pb = os.path.join(root, PETS_DIR, p.id + '.b')
    data = open(pb).read()
    open(pb, 'w').write(data[:len(data) // 2])
    fresh = PetStore(lambda: DirFS(root))
    got = fresh.load_all()
    assert got[p.id]['age'] == 0                  # the older, intact copy
    # and the next save goes to .b again (overwriting the junk), leaving .a alone
    p.tick(5)
    fresh.save(p.to_dict())
    n_b, _ = _decode(open(pb).read())
    assert n_b == 2


def test_highest_counter_wins_even_if_slot_a_is_newer(card, entropy, rng):
    root, store = card
    p = make_pet(entropy, rng)
    for i in range(5):
        p.tick(1)
        store.save(p.to_dict())
    fresh = PetStore(lambda: DirFS(root))
    assert fresh.load_all()[p.id]['age'] == 5


def test_id_mismatch_is_ignored(card, entropy, rng):
    root, store = card
    p = make_pet(entropy, rng)
    d = p.to_dict()
    d['id'] = 'deadbeef'
    os.makedirs(os.path.join(root, PETS_DIR))
    open(os.path.join(root, PETS_DIR, p.id + '.a'), 'w').write(_encode(1, d))
    assert store.load_all() == {}


def test_multiple_pets_on_one_card(card, entropy, rng):
    root, store = card
    a, b = make_pet(entropy, rng, 1), make_pet(entropy, rng, 2)
    store.save(a.to_dict()); store.save(b.to_dict())
    got = store.load_all()
    assert set(got) == {a.id, b.id}


def test_active_pointer(card, entropy, rng):
    root, store = card
    assert store.get_active() is None
    p = make_pet(entropy, rng)
    store.set_active(p.id)
    assert store.get_active() == p.id
    store.set_active(None)
    assert store.get_active() is None


def test_bury_writes_tombstone_then_removes_saves(card, entropy, rng):
    root, store = card
    p = make_pet(entropy, rng)
    p.tick(M.STAGE_AT['baby'])
    store.save(p.to_dict()); p.tick(1); store.save(p.to_dict())
    p.sick = True
    p.tick(M.SICK_FATAL + 1)
    assert not p.alive
    store.bury(p.tombstone())
    assert not os.path.exists(os.path.join(root, PETS_DIR, p.id + '.a'))
    assert not os.path.exists(os.path.join(root, PETS_DIR, p.id + '.b'))
    graves = store.graveyard()
    assert len(graves) == 1 and graves[0]['name'] == p.name
    assert 'Here lies' in graves[0]['epitaph']
    assert store.load_all() == {}


def test_delete(card, entropy, rng):
    root, store = card
    p = make_pet(entropy, rng)
    store.save(p.to_dict())
    store.delete(p.id)
    assert store.load_all() == {}


def test_empty_card_is_fine(card):
    root, store = card
    assert store.load_all() == {}
    assert store.graveyard() == []
