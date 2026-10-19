#!/usr/bin/env python3
"""Terminal Mario - a side-scrolling platformer using only the stdlib (curses).

Run:  python3 mario.py
Keys: A / D (or arrows)  run left / right, S / DOWN  stop,
      SPACE / W / UP / K  jump,  Q  quit
Phone-friendly: a tap on A or D keeps Mario running until you tap S.
Use `python3 mario.py --hold` for keyboard-style (hold the key to run).
"""
import curses
import sys
import time

H = 18            # level height in tiles
W = 230           # level width in tiles
FPS = 30
GRAVITY = 55.0
JUMP_V = -21.0
RUN_SPEED = 11.0
ACCEL = 70.0
FRICTION = 30.0
HOLD = 0.16       # terminals send no key-up; a key counts as held this long
SOLID = set("#=?uP")


def build_level():
    g = [[" "] * W for _ in range(H)]

    def put(x, y, ch):
        if 0 <= x < W and 0 <= y < H:
            g[y][x] = ch

    pits = [(40, 43), (76, 80), (119, 123), (161, 165)]
    for x in range(W):
        if any(a <= x < b for a, b in pits):
            continue
        put(x, 16, "#")
        put(x, 17, "#")

    # question blocks / bricks at row 12
    for x in (18, 22, 24):
        put(x, 12, "?")
    for x in (21, 23, 25):
        put(x, 12, "=")
    for x in range(52, 60):
        put(x, 12, "=" if x % 3 else "?")
    for x in range(64, 69):
        put(x, 9, "=")
    put(66, 9, "?")
    for x in range(95, 102):
        put(x, 12, "=" if x != 98 else "?")
    for x in range(130, 138):
        put(x, 12, "?" if x % 2 else "=")
    for x in range(140, 146):
        put(x, 9, "=")

    # pipes (2 wide)
    for px, ph in ((32, 2), (48, 3), (88, 2), (108, 3), (150, 3), (172, 2)):
        for dy in range(ph):
            put(px, 15 - dy, "P")
            put(px + 1, 15 - dy, "P")

    # coins
    for x in range(26, 31):
        put(x, 13, "o")
    for x in range(65, 68):
        put(x, 7, "o")
    for x in range(53, 58):
        put(x, 10, "o")
    for x in range(141, 145):
        put(x, 7, "o")
    for x in (41, 42, 77, 78, 79, 120, 121, 122, 162, 163, 164):
        put(x, 12, "o")

    # staircase + flag
    for i in range(8):
        for dy in range(i + 1):
            put(190 + i, 15 - dy, "=")
    for dy in range(11):
        put(212, 15 - dy, "|")
    put(212, 4, "F")
    for x in range(216, 222):
        put(x, 15, " ")

    enemies = [34, 56, 70, 84, 98, 112, 126, 134, 148, 156, 168, 180, 184]
    return g, enemies


class Entity:
    def __init__(self, x, y, w=0.8, h=1.0):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.vx = self.vy = 0.0
        self.on_ground = False
        self.alive = True


class World:
    def __init__(self):
        self.grid, self.enemy_x = build_level()
        self.hi = 0
        self.view_w, self.view_h = 60, H
        self.latch = True      # tap-to-run (no key-up events on phones)
        self.lives = 3
        self.score = 0
        self.coins = 0
        self.state = "title"   # title | play | dead | over | won
        self.msg_until = 0.0
        self.reset_level(keep_score=False)

    # -- helpers ---------------------------------------------------------
    def reset_level(self, keep_score=True):
        self.grid, self.enemy_x = build_level()
        self.player = Entity(3.0, 14.0)
        self.facing = 1
        self.enemies = []
        for ex in self.enemy_x:
            e = Entity(float(ex), 15.0)
            e.vx = -3.0
            self.enemies.append(e)
        self.cam = 0.0
        self.time_left = 300.0
        self.left_t = self.right_t = self.jump_t = 0.0
        self.run_dir = 0
        self.camy = 0.0
        if not keep_score:
            self.score = 0
            self.coins = 0
            self.lives = 3

    def solid(self, c, r):
        if c < 0 or c >= W:
            return True
        if r < 0 or r >= H:
            return False
        return self.grid[r][c] in SOLID

    def move(self, e, dt, is_player=False):
        # horizontal
        e.x += e.vx * dt
        top, bot = int(e.y + 0.05), int(e.y + e.h - 0.05)
        if e.vx > 0:
            c = int(e.x + e.w)
            if any(self.solid(c, r) for r in range(top, bot + 1)):
                e.x = c - e.w - 0.001
                e.vx = -e.vx if not is_player else 0.0
        elif e.vx < 0:
            c = int(e.x)
            if e.x < 0 or any(self.solid(c, r) for r in range(top, bot + 1)):
                e.x = c + 1.001 if e.x >= 0 else 0.0
                e.vx = -e.vx if not is_player else 0.0
        # vertical
        e.vy = min(e.vy + GRAVITY * dt, 40.0)
        e.y += e.vy * dt
        e.on_ground = False
        lc, rc = int(e.x + 0.05), int(e.x + e.w - 0.05)
        if e.vy > 0:
            r = int(e.y + e.h)
            if any(self.solid(c, r) for c in range(lc, rc + 1)):
                e.y = r - e.h
                e.vy = 0.0
                e.on_ground = True
        elif e.vy < 0:
            r = int(e.y)
            if any(self.solid(c, r) for c in range(lc, rc + 1)):
                if is_player:
                    self.bump(int(e.x + e.w / 2), r)
                e.y = r + 1.0
                e.vy = 0.0

    def bump(self, c, r):
        if not (0 <= c < W and 0 <= r < H):
            return
        if self.grid[r][c] == "?":
            self.grid[r][c] = "u"
            self.coins += 1
            self.score += 200
        # coins resting directly above a bumped block pop too
        if r > 0 and self.grid[r - 1][c] == "o":
            self.grid[r - 1][c] = " "
            self.coins += 1
            self.score += 100

    def lose_life(self, now):
        self.lives -= 1
        self.state = "over" if self.lives <= 0 else "dead"
        self.msg_until = now + 1.5

    # -- per-frame update ------------------------------------------------
    def update(self, dt, now):
        if self.state != "play":
            if self.state == "dead" and now >= self.msg_until:
                self.reset_level()
                self.state = "play"
            return
        p = self.player
        self.time_left -= dt
        if self.time_left <= 0:
            self.lose_life(now)
            return

        want = 0
        if self.latch:
            want = self.run_dir
        else:
            if now < self.left_t:
                want -= 1
            if now < self.right_t:
                want += 1
        if want:
            self.facing = want
            target = want * RUN_SPEED
            step = ACCEL * dt
            p.vx += max(-step, min(step, target - p.vx))
        else:
            step = FRICTION * dt
            p.vx = 0.0 if abs(p.vx) <= step else p.vx - step * (1 if p.vx > 0 else -1)
        if now < self.jump_t and p.on_ground:
            p.vy = JUMP_V
            self.jump_t = 0.0
        self.move(p, dt, is_player=True)

        # coins
        for r in range(int(p.y), int(p.y + p.h) + 1):
            for c in range(int(p.x), int(p.x + p.w) + 1):
                if 0 <= r < H and 0 <= c < W and self.grid[r][c] == "o":
                    self.grid[r][c] = " "
                    self.coins += 1
                    self.score += 100

        # enemies
        for e in self.enemies:
            if not e.alive:
                continue
            if abs(e.x - p.x) > 40:
                continue
            self.move(e, dt)
            if e.y > H + 2:
                e.alive = False
                continue
            if abs(e.x - p.x) < 0.85 and abs(e.y - p.y) < 0.9:
                if p.vy > 0 and p.y + p.h < e.y + 0.75:
                    e.alive = False
                    p.vy = JUMP_V * 0.6
                    self.score += 300
                else:
                    self.lose_life(now)
                    return

        # fell in a pit
        if p.y > H + 2:
            self.lose_life(now)
            return
        # flag
        if p.x >= 211.5:
            self.score += int(self.time_left) * 10
            self.hi = max(self.hi, self.score)
            self.state = "won"
            return
        self.hi = max(self.hi, self.score)
        self.cam = max(0.0, p.x - self.view_w // 3)
        vh = self.view_h
        self.camy = max(0.0, min(H - vh, p.y - vh * 0.6))


# -- rendering -----------------------------------------------------------
def init_colors():
    if not curses.has_colors():
        return {}
    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error:
        bg = curses.COLOR_BLACK
    pairs = {
        "sky": (curses.COLOR_CYAN, bg), "ground": (curses.COLOR_YELLOW, bg),
        "brick": (curses.COLOR_RED, bg), "q": (curses.COLOR_YELLOW, bg),
        "pipe": (curses.COLOR_GREEN, bg), "coin": (curses.COLOR_YELLOW, bg),
        "mario": (curses.COLOR_RED, bg), "goomba": (curses.COLOR_MAGENTA, bg),
        "flag": (curses.COLOR_GREEN, bg), "hud": (curses.COLOR_WHITE, bg),
    }
    out = {}
    for i, (name, (fg, b)) in enumerate(pairs.items(), start=1):
        curses.init_pair(i, fg, b)
        out[name] = curses.color_pair(i)
    return out


TILE = {
    "#": ("ground", "▒"), "=": ("brick", "▤"), "?": ("q", "?"), "u": ("brick", "■"),
    "P": ("pipe", "█"), "o": ("coin", "●"), "|": ("flag", "║"), "F": ("flag", "▶"),
}


def put(scr, y, x, s, attr=0):
    try:
        scr.addstr(y, x, s, attr)
    except curses.error:
        pass


def draw(scr, w, col, ascii_mode):
    scr.erase()
    sh, sw = scr.getmaxyx()
    if sh < 8 or sw < 24:
        put(scr, 0, 0, "Terminal too small")
        scr.refresh()
        return
    view = min(sw - 1, 100)
    vh = min(H, sh - 1)
    w.view_w, w.view_h = view, vh
    cam = int(w.cam)
    camy = int(w.camy)
    for r in range(camy, camy + vh):
        for sx in range(view):
            ch = w.grid[r][cam + sx] if cam + sx < W else " "
            if ch == " ":
                continue
            name, glyph = TILE[ch]
            if ascii_mode:
                glyph = {"▒": "#", "▤": "=", "■": "X", "█": "H", "●": "o", "║": "|", "▶": ">"}.get(glyph, glyph)
            put(scr, r - camy + 1, sx, glyph, col.get(name, 0))
    for e in w.enemies:
        if e.alive:
            sx = int(e.x + 0.4) - cam
            ey = int(e.y + 0.5) - camy + 1
            if 0 <= sx < view and 1 <= ey <= vh:
                put(scr, ey, sx, "G", col.get("goomba", 0) | curses.A_BOLD)
    p = w.player
    sx = int(p.x + 0.4) - cam
    py = int(p.y + 0.5) - camy + 1
    if 0 <= sx < view and 1 <= py <= vh:
        put(scr, py, sx, "M", col.get("mario", 0) | curses.A_BOLD)
    if sw < 60:
        hud = f"{w.score:05d} x{w.coins:02d} L{w.lives} T{max(0, int(w.time_left)):03d}"
    else:
        hud = (f" MARIO {w.score:06d}   COINS x{w.coins:02d}   LIVES {w.lives}"
               f"   TIME {max(0, int(w.time_left)):03d}   HI {w.hi:06d}")
    put(scr, 0, 0, hud, col.get("hud", 0) | curses.A_BOLD)

    def center(y, s, attr=curses.A_BOLD):
        put(scr, y, max(0, (view - len(s)) // 2), s, attr)

    if w.state == "title":
        t = max(1, vh // 2 - 3)
        center(t, "TERMINAL MARIO", col.get("mario", 0) | curses.A_BOLD)
        center(t + 2, "A / D  run (tap once)")
        center(t + 3, "S  stop   SPACE  jump")
        center(t + 4, "Stomp the G's. Reach the flag!")
        center(t + 6, "Tap any key to start")
    elif w.state == "dead":
        center(vh // 2, "Ouch!  Lives left: %d" % w.lives)
    elif w.state == "over":
        center(max(1, vh // 2 - 1), "GAME OVER")
        center(vh // 2 + 1, "R = retry   Q = quit")
    elif w.state == "won":
        center(max(1, vh // 2 - 2), "COURSE CLEAR!")
        center(vh // 2, f"Score {w.score}")
        center(vh // 2 + 2, "R = again   Q = quit")
    scr.refresh()


def main(scr):
    curses.curs_set(0)
    scr.nodelay(True)
    scr.keypad(True)
    col = init_colors()
    import locale
    ascii_mode = "UTF" not in (locale.getpreferredencoding() or "").upper()
    w = World()
    w.latch = "--hold" not in sys.argv
    dt = 1.0 / FPS
    nxt = time.monotonic()
    while True:
        now = time.monotonic()
        while True:
            k = scr.getch()
            if k == -1:
                break
            if k in (ord("q"), ord("Q")):
                return
            if w.state == "title":
                w.state = "play"
                continue
            if w.state in ("over", "won"):
                if k in (ord("r"), ord("R")):
                    w.reset_level(keep_score=False)
                    w.state = "play"
                continue
            if k in (curses.KEY_LEFT, ord("a"), ord("A")):
                w.left_t, w.right_t, w.run_dir = now + HOLD, 0.0, -1
            elif k in (curses.KEY_RIGHT, ord("d"), ord("D")):
                w.right_t, w.left_t, w.run_dir = now + HOLD, 0.0, 1
            elif k in (curses.KEY_DOWN, ord("s"), ord("S")):
                w.run_dir = 0
            elif k in (curses.KEY_UP, ord(" "), ord("w"), ord("W"), ord("k"), ord("K")):
                w.jump_t = now + 0.12
        w.update(dt, now)
        draw(scr, w, col, ascii_mode)
        nxt += dt
        delay = nxt - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:
            nxt = time.monotonic()


if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
