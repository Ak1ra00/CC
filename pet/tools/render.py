#!/usr/bin/env python3
# render.py - draw every pet screen to PNG using the firmware's own drawing code.
#
#   python pet/tools/render.py [outdir]
#
# Output is pixel-for-pixel what the firmware puts on the OLED (same display.py,
# same fonts, same sprite code), scaled 4x with the simulator's colours.
import os, sys, random

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from fakehw import make_display, to_image

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', 'screenshots')


def main():
    os.makedirs(OUT, exist_ok=True)
    dis = make_display()
    import pet_model as M
    import pet_draw as D
    import pet_sprites as S

    rr = random.Random(7)
    rng = lambda n: rr.randrange(n)

    def save(name):
        to_image(dis).save(os.path.join(OUT, name + '.png'))
        print('wrote', name)

    def pet_with(seed, stage, **kw):
        raw = bytes(random.Random(seed).randrange(256) for _ in range(32))
        p = M.Pet(M.Genome(raw), rng)
        p.stage = stage
        p.age = M.STAGE_AT.get(stage, 0) + 300
        p.hunger = p.happy = p.energy = 80.0
        for k, v in kw.items():
            setattr(p, k, v)
        return p

    # one of each stage, each with a different body/eyes
    for i, st in enumerate(M.STAGES):
        p = pet_with(10 + i, st)
        D.draw_main(dis, p, 0)
        save('stage_%d_%s' % (i, st))

    # the three body variants x three eye variants, adult
    for b in range(S.NUM_BODIES if hasattr(S, 'NUM_BODIES') else 3):
        for e in range(3):
            raw = bytearray(random.Random(100 + b * 3 + e).randrange(256) for _ in range(32))
            raw[4] = b; raw[5] = e
            p = M.Pet(M.Genome(bytes(raw)), rng)
            p.stage = 'adult'; p.age = M.STAGE_AT['adult'] + 60
            p.hunger = p.happy = p.energy = 85.0
            D.draw_main(dis, p, 0)
            save('adult_body%d_eyes%d' % (b, e))

    # moods and situations
    p = pet_with(21, 'child', hunger=10.0, happy=20.0, poop=3, call='real')
    D.draw_main(dis, p, 1); save('situation_hungry_poop')

    p = pet_with(22, 'teen', sick=True, poop=1)
    D.draw_main(dis, p, 0); save('situation_sick')

    p = pet_with(23, 'adult', energy=5.0)
    D.draw_main(dis, p, 1); save('situation_tired')

    p = pet_with(24, 'adult', happy=95.0, hunger=90.0)
    D.draw_main(dis, p, 1, msg='*purrs in 120 MHz*', action='pat'); save('situation_pat')

    p = pet_with(25, 'child', hunger=40.0)
    D.draw_main(dis, p, 1, msg='Chomp chomp.', action='eat'); save('action_feed')
    D.draw_main(dis, p, 0, msg='Sweet!', action='snack'); save('action_snack')
    D.draw_main(dis, p, 0, msg='Wasn\'t sick. Tastes awful.', action='med'); save('action_medicine')
    p.poop = 2
    D.draw_main(dis, p, 0, msg='Much better.', action='clean'); save('action_clean')
    p.poop = 0; p.call = 'tantrum'
    D.draw_main(dis, p, 1, msg='Sulks. Lesson learned.', action='scold'); save('action_scold')

    p = pet_with(26, 'elder', weight=90.0)
    D.draw_main(dis, p, 0, ram_only=True); save('situation_ram_only_elder')

    # egg
    p = M.Pet(M.Genome(bytes(random.Random(30).randrange(256) for _ in range(32))), rng)
    D.draw_main(dis, p, 0); save('egg_fresh')
    p.age = int(M.STAGE_AT['baby'] * 0.9)
    D.draw_main(dis, p, 1); save('egg_cracking')

    # death
    p = pet_with(31, 'adult')
    p.alive = False; p.cause = 'starvation'
    D.draw_death(dis, p, 1); save('death')
    D.draw_main(dis, p, 0); save('death_main')

    # hatching / wake / card
    D.draw_hatching(dis, S.EGGS[1], 0.4, 0); save('hatching_rolling')
    D.draw_hatching(dis, S.EGGS[1], 1.0, 0); save('hatching_done')
    p = pet_with(32, 'teen')
    D.draw_wake(dis, p, 1, 'I dreamed of a 25th word.'); save('wake_up')
    D.draw_card_pull(dis, 0); save('no_card')

    # games
    p = pet_with(33, 'adult')
    D.draw_pin_drill(dis, p, '4812', '', 1, 0, 'show'); save('game_pin_show')
    D.draw_pin_drill(dis, p, '4812', '48', 1, 1, 'input'); save('game_pin_input')
    D.draw_pin_drill(dis, p, '4812', '4812', 1, 1, 'win'); save('game_pin_win')
    D.draw_pin_drill(dis, p, '4812', '4821', 1, 1, 'lose'); save('game_pin_lose')
    D.draw_which_way(dis, p, 'L', None, 2, 3, 0, False); save('game_way_guess')
    D.draw_which_way(dis, p, 'L', 'L', 3, 3, 1, True); save('game_way_reveal')

    # text screens rendered like ux_show_story would (first 5 lines)
    from charcodes import OUT_CTRL_TITLE
    lines = D.stats_text(p).split('\n')
    dis.draw_story(lines[:5] + ['EOT'], 0, len(lines), False)
    save('stats_story_page1')
    lines = D.HELP_TEXT.split('\n')
    dis.draw_story(lines[:5], 0, len(lines), False)
    save('help_story_page1')


if __name__ == '__main__':
    main()
