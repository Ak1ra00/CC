# pet_draw.py - all the pet's screens, as plain drawing functions.
#
# Part of the unofficial COLDCARD Tamagotchi fork. See NOTICE and LICENSE-PET.
#
# Nothing async in here and no key handling: every function takes the Display
# and draws one frame. pet_ux.py drives these; pet/tools/render.py renders them
# to PNG on a desktop for the README. Same code both places.
#
from zevvpeep import FontTiny, FontSmall, FontLarge
import pet_sprites as S
from pet_model import fmt_awake, STAGE_AT

W, H = 128, 64
FLOOR_Y = 48            # creature stands on this line
TEXT_Y = 58             # utterance line (FontTiny is 6 tall)


def _tiny(dis, x, y, s, invert=0):
    return dis.text(x, y, s, font=FontTiny, invert=invert)


# ---------------------------------------------------------------- the creature
def draw_creature(dis, pet, cx, base_y, frame, action=None, eyes_override=None):
    # Draw the pet centred on cx with its feet on base_y. frame: 0/1 idle bob.
    # action: None or one of 'eat','snack','play','clean','med','scold','pat','talk'
    # Returns (x, y, w, h) of where the body landed.
    g = pet.g
    if not pet.alive:
        w, h = S.TOMBSTONE[0], S.TOMBSTONE[1]
        x, y = cx - w // 2, base_y - h
        dis.icon(x, y, S.TOMBSTONE)
        return x, y, w, h

    body = S.BODIES[pet.stage][g.body % len(S.BODIES[pet.stage])]
    bob = frame & 1
    x = cx - body.w // 2
    y = base_y - body.h + bob

    if pet.is_egg():
        # wobble instead of bob; crack appears when it's nearly done
        x += (1 if frame & 1 else -1) if (pet.age % 7 < 3) else 0
        y = base_y - body.h
        dis.icon(x, y, body.spr)
        if pet.age > STAGE_AT['baby'] * 0.7:
            dis.icon(x + body.w // 2 - 2, y + 3, S.CRACK)
        return x, y, body.w, body.h

    mood = pet.mood()
    if action in ('play', 'pat') or mood == 'happy':
        y -= 2 if (frame & 1) else 0           # little hop
    if mood == 'sick':
        x += (frame & 1)                        # shiver

    dis.icon(x, y, body.spr)

    # eyes
    if eyes_override:
        est = eyes_override
    elif mood in ('sick',):
        est = 'sick'
    elif mood in ('sad', 'tired'):
        est = 'sad'
    elif mood == 'happy' or action in ('play', 'pat', 'snack'):
        est = 'happy'
    elif (pet.age % 23) == 0 and frame & 1:
        est = 'closed'                          # blink
    else:
        est = 'open'
    # face is carved INTO the body: invert=1 draws '#' as dark pixels
    dis.icon(x + body.fx, y + body.fy, S.EYES[g.eyes % len(S.EYES)][est], invert=1)

    # mouth
    if action in ('eat', 'snack'):
        m = 'eat' if frame & 1 else 'happy'
    elif mood == 'sick':
        m = 'sick'
    elif mood in ('sad', 'tired'):
        m = 'sad'
    elif mood == 'happy' or action in ('play', 'pat'):
        m = 'happy'
    else:
        m = 'idle'
    dis.icon(x + body.mx, y + body.my, S.MOUTHS[m], invert=1)

    # decorations
    if mood == 'sad' and frame & 1:
        dis.icon(x + body.fx + 1, y + body.fy + 4, S.TEAR, invert=1)
    if mood == 'tired':
        dis.icon(x + body.w - 4, y - 8 - (frame & 1), S.ZZZ)
    if action in ('pat',) or (mood == 'happy' and frame & 1 and action is None and pet.age % 4 == 0):
        dis.icon(x + body.w - 2, y - 6, S.HEART)
    if action == 'play':
        dis.icon(x - 7, y - 4 + (frame & 1), S.NOTE)

    # props for actions, drawn to the left of the face
    px = x - 13
    py = y + body.fy - 2
    if action == 'eat':
        dis.icon(px, py, S.MEAL)
    elif action == 'snack':
        dis.icon(px + 2, py, S.SNACK)
    elif action == 'med':
        dis.icon(px + 2, py + 1, S.PILL)
    elif action == 'clean':
        dis.icon(x + body.w + 2, base_y - 9, S.BROOM)
    elif action == 'scold':
        dis.icon(px + 2, py - 2 - (frame & 1) * 2, S.HAND)

    return x, y, body.w, body.h


def draw_gauge(dis, x, y, h, value, label):
    # vertical 4px gauge with outline; value 0..100
    fb = dis.dis
    fb.rect(x, y, 5, h, 1)
    fill = int((h - 2) * max(0, min(100, value)) / 100.0 + 0.5)
    if fill:
        fb.fill_rect(x + 1, y + h - 1 - fill, 3, fill, 1)
    _tiny(dis, x, y + h + 1, label)


def draw_main(dis, pet, frame, msg=None, action=None, ram_only=False, flash=False):
    # The screen you'll be staring at.
    dis.clear()
    fb = dis.dis

    # header: name / stage + awake age
    _tiny(dis, 0, 0, pet.name.upper())
    if ram_only and frame & 1:
        _tiny(dis, -1, 0, 'NOT SAVING!')
    else:
        _tiny(dis, -1, 0, '%s %s' % (pet.stage, fmt_awake(pet.age)))
    fb.hline(0, 7, W, 1)

    if not pet.is_egg() and pet.alive:
        # gauges on the left
        draw_gauge(dis, 2, 10, 30, pet.hunger, 'F')
        draw_gauge(dis, 9, 10, 30, pet.happy, 'J')
        draw_gauge(dis, 16, 10, 30, pet.energy, 'Z')

    # creature
    draw_creature(dis, pet, 64, FLOOR_Y, frame, action=action)

    # floor
    for x in range(24, 106, 2):
        fb.pixel(x, FLOOR_Y, 1)

    # right column: alerts
    ry = 10
    if pet.call and (frame & 1 or pet.call == 'real'):
        dis.icon(121, ry, S.ALERT); ry += 9
    if pet.sick:
        dis.icon(120, ry, S.SKULL); ry += 9
    if pet.refusing:
        _tiny(dis, 118, ry, 'NO'); ry += 7

    # poop on the floor, to the right of the pet
    for i in range(pet.poop):
        dis.icon(94 + (i % 2) * 9, FLOOR_Y - 8 - (i // 2) * 7, S.POOP)

    # utterance
    line = msg if msg else pet.says()
    _tiny(dis, 0, TEXT_Y, line[:32])
    dis.show()


# ---------------------------------------------------------------- text screens
def bar(v, n=8):
    f = int(round(v / 100.0 * n))
    return '#' * f + '-' * (n - f)

def stats_text(pet):
    # for ux_show_story (FontSmall, ~17 chars/line, scrolls with 5/8)
    ln = []
    ln.append('%s, %s' % (pet.name, pet.stage))
    ln.append('Awake: %s' % fmt_awake(pet.age))
    ln.append('Generation: %d' % pet.generation)
    ln.append('')
    ln.append('Food  %s' % bar(pet.hunger))
    ln.append('Joy   %s' % bar(pet.happy))
    ln.append('Sleep %s' % bar(pet.energy))
    ln.append('Order %s' % bar(pet.discipline))
    ln.append('Weight %dg%s' % (int(pet.weight), ' (fat)' if pet.overweight() else ''))
    ln.append('Poop: %d  Sick: %s' % (pet.poop, 'YES' if pet.sick else 'no'))
    ln.append('')
    ln.append('Meals %d Snacks %d' % (pet.stats['meals'], pet.stats['snacks']))
    ln.append('Games %d Wins %d' % (pet.stats['games'], pet.stats['wins']))
    ln.append('Naps %d Scolds %d' % (pet.stats['naps'], pet.stats['scolds']))
    ln.append('Mistakes %d' % pet.stats['mistakes'])
    ln.append('')
    ln.append('-- Genome --')
    ln.extend(pet.g.describe())
    ln.append('id ' + pet.id)
    if pet.parents:
        ln.append('parents:')
        ln.extend(pet.parents)
    ln.append('')
    ln.append('32 bytes of TRNG:')
    hx = pet.g.to_hex()
    for i in range(0, 64, 16):
        ln.append(hx[i:i + 16])
    return '\n'.join(ln)


HELP_TEXT = '''\
1 = Feed (meal)
2 = Snack
3 = Play (games)
4 = Clean poop
5 = Medicine
6 = Scold
7 = Status
8 = This help
9 = Pet menu
0 = Make it talk
OK = Pat it
X = Leave (it keeps
    living while the
    device is on and
    you are here)

Unplug = bedtime.
Time only passes
while powered.

It can die. That is
permanent. No undo.

The pet IS the
microSD card. Pull
the card, take the
pet. Two adults on
one card can breed.

Press 5/8 to scroll.'''


def death_lines(pet):
    t = pet.tombstone()
    return t['epitaph']


# ---------------------------------------------------------------- special screens
def draw_death(dis, pet, frame):
    dis.clear()
    dis.text(None, 0, 'R.I.P.', font=FontLarge)
    dis.icon(8, 24, S.TOMBSTONE)
    _tiny(dis, 34, 26, pet.name.upper())
    _tiny(dis, 34, 34, 'awake ' + fmt_awake(pet.age))
    _tiny(dis, 34, 42, 'cause: ' + (pet.cause or '?'))
    if frame & 1:
        _tiny(dis, 0, TEXT_Y, 'Press OK. It is permanent.')
    dis.show()


def draw_hatching(dis, egg_body, pct, frame):
    # rolling entropy for a new egg
    dis.clear()
    dis.text(None, 0, 'New Egg', font=FontLarge)
    _tiny(dis, 0, 24, 'Rolling 256 bits from the')
    _tiny(dis, 0, 31, 'hardware TRNG. Not 2021 fw.')
    dis.icon(56, 38, egg_body.spr) if pct >= 1 else None
    if pct < 1:
        _tiny(dis, 0, 45, '%3d%% ' % int(pct * 100) + ('#' * int(pct * 20)))
    dis.progress_bar(pct)
    dis.show()


def draw_wake(dis, pet, frame, dream):
    # just booted: it was asleep
    dis.clear()
    _tiny(dis, 0, 0, pet.name.upper() + ' WAKES UP')
    dis.dis.hline(0, 7, W, 1)
    draw_creature(dis, pet, 64, FLOOR_Y, frame, eyes_override=('closed' if frame < 4 else None))
    if frame < 4:
        dis.icon(84, 12, S.ZZZ)
    _tiny(dis, 0, TEXT_Y, (dream or '')[:32])
    dis.show()


def draw_card_pull(dis, frame):
    dis.clear()
    dis.text(None, 2, 'Card?', font=FontLarge)
    dis.icon(58, 26, S.CARD)
    _tiny(dis, 0, 44, 'The pet lives on microSD.')
    _tiny(dis, 0, 51, 'No card = nothing is saved.')
    _tiny(dis, 0, TEXT_Y, 'OK: play in RAM anyway  X: back')
    dis.show()


# ---------------------------------------------------------------- minigames
def draw_pin_drill(dis, pet, shown, entered, round_no, frame, phase):
    # phase: 'show' (pet says digits), 'input' (you type), 'win', 'lose'
    dis.clear()
    _tiny(dis, 0, 0, 'PIN DRILL  round %d' % round_no)
    dis.dis.hline(0, 7, W, 1)
    draw_creature(dis, pet, 26, FLOOR_Y, frame,
                  action=('play' if phase in ('show', 'win') else None),
                  eyes_override=('happy' if phase == 'win' else 'sad' if phase == 'lose' else None))
    if phase == 'show':
        _tiny(dis, 50, 12, 'Remember this PIN:')
        dis.text(50, 20, shown, font=FontLarge)
        _tiny(dis, 50, 44, '(new PIN each round)')
    elif phase == 'input':
        _tiny(dis, 50, 12, 'Type it back:')
        dis.text(50, 20, entered + ('_' if frame & 1 else ' '), font=FontLarge)
        _tiny(dis, 50, 44, 'X = give up')
    elif phase == 'win':
        dis.text(50, 16, 'CORRECT', font=FontSmall)
        _tiny(dis, 50, 34, 'Better than you did')
        _tiny(dis, 50, 41, 'with the real one.')
    else:
        dis.text(50, 16, 'WRONG', font=FontSmall)
        _tiny(dis, 50, 34, 'It was ' + shown)
        _tiny(dis, 50, 41, 'Brick Me is next.')
    _tiny(dis, 0, TEXT_Y, 'OK continue   X quit')
    dis.show()


def draw_which_way(dis, pet, facing, guess, score, round_no, frame, reveal):
    # facing: 'L'/'R' where the pet will look. guess: 'L'/'R'/None
    dis.clear()
    _tiny(dis, 0, 0, 'WHICH WAY?  %d/5  score %d' % (round_no, score))
    dis.dis.hline(0, 7, W, 1)
    x, y, w, h = draw_creature(dis, pet, 64, FLOOR_Y, frame,
                               eyes_override=('happy' if (reveal and guess == facing) else None))
    if reveal:
        # arrow showing where it looked
        ax = x - 10 if facing == 'L' else x + w + 3
        _tiny(dis, ax, y + 4, '<' if facing == 'L' else '>')
        _tiny(dis, 0, 12, 'YES' if guess == facing else 'nope')
    else:
        _tiny(dis, 0, 12, '4 = left')
        _tiny(dis, -1, 12, 'right = 6')
    _tiny(dis, 0, TEXT_Y, 'Guess where it looks. X quits')
    dis.show()

# EOF
