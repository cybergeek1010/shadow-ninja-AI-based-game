#!/usr/bin/env python3
"""
SHADOW NINJA - a stealth game driven by guard AI  (single file, needs pygame)

    pip install pygame
    python ninja_stealth.py

AI techniques implemented
  1. Finite State Machine : PATROL -> SUSPICIOUS -> ALERT -> CHASE -> SEARCH -> PATROL
  2. A* pathfinding       : guards route around walls (patrol, chase, search, investigate)
  3. Field-of-view vision : distance + angle + wall-blocked line of sight, awareness meter
  4. Noise detection      : walking / running / thrown stone / breaking a door
  5. Multi-agent comms    : an alerted guard tells nearby guards (Medium = radius, Hard = all)

Controls
  WASD / arrows  move            SHIFT  run (loud)
  E              steal artifact / hide in bush / leave bush
  Left click     throw a stone at the mouse   (SPACE = throw in facing direction)
  TAB            debug view (A* paths, state names)
  R restart      ESC menu/quit
"""
import heapq
import math
import random
import sys

import pygame

# ----------------------------------------------------------------------------
# Constants / configuration
# ----------------------------------------------------------------------------
TILE = 32
COLS, ROWS = 30, 20
MAP_W, MAP_H = COLS * TILE, ROWS * TILE
HUD_H = 70
WIN_W, WIN_H = MAP_W, MAP_H + HUD_H

NOISE_SCALE = 5            # noise level * 5 px = hearing radius (before difficulty multiplier)
WALK_NOISE, RUN_NOISE, STONE_NOISE, DOOR_NOISE = 5, 20, 50, 80
STONE_RANGE = 280
WALK_SPEED, RUN_SPEED = 100, 170

# '#' wall  '.' floor  'H' hiding spot  'R' locked door (breaks loudly)
# 'P' ninja start  'G' artifact  'X' exit door (in the wall)
MAP_RAW = [
    "##############################",
    "#............#...............#",
    "#............#...............#",
    "#..HH........#....######.....#",
    "#............R....#....#..H..#",
    "#######.######....#.G..#.....#",
    "#............#....#....#.....#",
    "#............#....###R###....#",
    "#..H.........#...............#",
    "#............#...............#",
    "#####R########.######..#######",
    "#............................#",
    "#............................#",
    "#..######....H....######.....#",
    "#..#....#.........#....#.....#",
    "#..#....R.........R....#..H..#",
    "#..######.........######.....#",
    "#............................#",
    "#.P..........................#",
    "#X############################",
]

# Patrol routes (tile coordinates). Guards ping-pong A->B->C->D->C->B->A
GUARD_ROUTES = [
    [(2, 2), (11, 3), (7, 7), (11, 8), (2, 8)],
    [(15, 2), (27, 2), (27, 5), (15, 5)],
    [(2, 12), (14, 12), (27, 12), (27, 17), (14, 17), (11, 17)],
    [(15, 9), (27, 9), (27, 7), (15, 7)],
    [(19, 4), (22, 4), (22, 6), (19, 6)],       # inside the artifact room (Hard only)
]

DIFFS = {
    "EASY":   dict(guards=3, vision=130, fov=70,  patrol=55, chase=90,  detect=1.3, search=6,
                   npts=2, lose=2.0, repath=0.9,  hear=0.7, comm=0,    react=0.6),
    "MEDIUM": dict(guards=4, vision=170, fov=90,  patrol=65, chase=125, detect=0.9, search=10,
                   npts=4, lose=3.5, repath=0.4,  hear=1.0, comm=220,  react=0.4),
    "HARD":   dict(guards=5, vision=210, fov=110, patrol=75, chase=150, detect=0.55, search=15,
                   npts=6, lose=5.5, repath=0.15, hear=1.3, comm=9999, react=0.2),
}

STATE_COL = {
    "PATROL": (80, 200, 120), "SUSPICIOUS": (240, 210, 60), "ALERT": (255, 140, 30),
    "CHASE": (235, 60, 60), "SEARCH": (70, 140, 255),
}
SYMBOL = {"PATROL": "", "SUSPICIOUS": "?", "ALERT": "!", "CHASE": "!!", "SEARCH": "..."}


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------
def tile_of(x, y):
    return int(x // TILE), int(y // TILE)


def center(t):
    return t[0] * TILE + TILE / 2, t[1] * TILE + TILE / 2


def adiff(a, b):
    """signed smallest difference a-b in radians"""
    return (a - b + math.pi) % (2 * math.pi) - math.pi


def approach(a, b, step):
    d = adiff(b, a)
    return a + max(-step, min(step, d))


# ----------------------------------------------------------------------------
# Guard: FSM brain + A* movement
# ----------------------------------------------------------------------------
class Guard:
    def __init__(self, route):
        self.wp = list(route)
        self.x, self.y = center(self.wp[0])
        nx, ny = center(self.wp[1])
        self.angle = self.want = math.atan2(ny - self.y, nx - self.x)
        self.state = "PATROL"
        self.path = []
        self.wp_i, self.wp_dir = 0, 1
        self.timer = self.wait = 0.0
        self.aware = 0.0
        self.last_known = None
        self.noise = None
        self.repath_t = self.lost_t = 0.0
        self.search_pts = []
        self.sees = False
        self.scan_t = random.random() * 6
        self.scan_base = self.angle

    def tile(self):
        return tile_of(self.x, self.y)

    # ---- perception ------------------------------------------------------
    def can_see(self, g):
        p = g.player
        dx, dy = p.x - self.x, p.y - self.y
        d = math.hypot(dx, dy)
        if d > g.vision_range():
            return False
        if p.hidden and d > 32:
            return False
        if d < 1:
            return True
        off = abs(adiff(math.atan2(dy, dx), self.angle))
        if off > math.radians(g.cfg["fov"]) / 2 and d > 28:   # can't see behind (except very close)
            return False
        return g.los(self.x, self.y, p.x, p.y)

    def hear(self, g, pos):
        if self.state in ("ALERT", "CHASE"):
            return
        if self.state == "SUSPICIOUS" and self.noise and \
                math.hypot(pos[0] - self.noise[0], pos[1] - self.noise[1]) < 48:
            return
        self.state = "SUSPICIOUS"
        self.noise = pos
        self.wait = 0
        self.timer = 2.0
        self.path = g.astar(self.tile(), tile_of(*pos)) or []

    # ---- state transitions -----------------------------------------------
    def enter_alert(self, g):
        self.state = "ALERT"
        self.timer = g.cfg["react"]
        self.path = []
        g.alert_others(self)

    def start_search(self, g):
        self.state = "SEARCH"
        self.timer = g.cfg["search"]
        self.wait = 0
        lk = self.last_known or (self.x, self.y)
        self.path = g.astar(self.tile(), tile_of(*lk)) or []
        self.search_pts = g.search_points(tile_of(*lk), g.cfg["npts"])

    def to_patrol(self):
        self.state = "PATROL"
        self.path = []
        tx, ty = self.tile()
        self.wp_i = min(range(len(self.wp)),
                        key=lambda i: abs(self.wp[i][0] - tx) + abs(self.wp[i][1] - ty))

    def begin_wait(self, t):
        self.wait = t
        self.scan_base = self.angle
        self.scan_t = 0

    def advance(self):
        n = len(self.wp)
        if not 0 <= self.wp_i + self.wp_dir < n:
            self.wp_dir *= -1
        self.wp_i += self.wp_dir

    # ---- movement ---------------------------------------------------------
    def scan(self, dt):
        self.scan_t += dt
        self.want = self.scan_base + math.sin(self.scan_t * 2.0) * 1.0

    def follow(self, dt, speed, g):
        """Walk along the A* path. Returns True when the path is finished."""
        if not self.path:
            return True
        tx, ty = center(self.path[0])
        dx, dy = tx - self.x, ty - self.y
        d = math.hypot(dx, dy)
        step = speed * dt
        if d > 1e-6:
            self.want = math.atan2(dy, dx)
        if d <= step:
            self.x, self.y = tx, ty
            t = self.path.pop(0)
            if g.grid[t[1]][t[0]] == "R":
                g.grid[t[1]][t[0]] = "r"          # guards open doors quietly
        else:
            self.x += dx / d * step
            self.y += dy / d * step
        return not self.path

    # ---- FSM update -------------------------------------------------------
    def update(self, dt, g):
        cfg, p = g.cfg, g.player
        mult = g.speed_mult()
        self.sees = self.can_see(g)
        dist = math.hypot(p.x - self.x, p.y - self.y)

        if self.sees:
            if self.state in ("ALERT", "CHASE"):
                self.aware = 1.0
            else:
                rate = (1.0 / cfg["detect"]) * max(0.4, 1.6 - dist / g.vision_range())
                if self.state in ("SUSPICIOUS", "SEARCH"):
                    rate *= 2
                self.aware = min(1.0, self.aware + rate * dt)
        else:
            self.aware = max(0.0, self.aware - 0.35 * dt)

        if self.sees and self.aware >= 1.0:
            self.last_known = (p.x, p.y)
            self.lost_t = 0
            if self.state not in ("ALERT", "CHASE"):
                self.enter_alert(g)

        staring = (self.sees and self.aware > 0.25 and
                   self.state in ("PATROL", "SUSPICIOUS", "SEARCH"))
        if staring:                                    # guard notices something: stop and stare
            self.want = math.atan2(p.y - self.y, p.x - self.x)
        elif self.state == "PATROL":
            self.do_patrol(dt, g, cfg["patrol"] * mult)
        elif self.state == "SUSPICIOUS":
            self.do_suspicious(dt, g, cfg["patrol"] * 1.2 * mult)
        elif self.state == "ALERT":
            self.do_alert(dt)
        elif self.state == "CHASE":
            self.do_chase(dt, g, cfg["chase"] * mult, dist)
        elif self.state == "SEARCH":
            self.do_search(dt, g, cfg["patrol"] * 1.25 * mult)

        self.angle = approach(self.angle, self.want, 6.0 * dt)

    def do_patrol(self, dt, g, speed):
        if self.wait > 0:
            self.scan(dt)
            self.wait -= dt
            return
        tgt = self.wp[self.wp_i]
        if self.path:
            self.follow(dt, speed, g)
        elif self.tile() == tgt:
            self.advance()
            self.begin_wait(0.5)
        else:
            path = g.astar(self.tile(), tgt)
            if path is None:
                self.advance()
            else:
                self.path = path

    def do_suspicious(self, dt, g, speed):
        if self.path:
            self.follow(dt, speed, g)
            self.scan_base, self.scan_t = self.angle, 0
        else:
            self.scan(dt)
            self.timer -= dt
            if self.timer <= 0:
                self.to_patrol()

    def do_alert(self, dt):
        lk = self.last_known
        if lk:
            self.want = math.atan2(lk[1] - self.y, lk[0] - self.x)
        self.timer -= dt
        if self.timer <= 0:
            self.state = "CHASE"
            self.repath_t = 0

    def do_chase(self, dt, g, speed, dist):
        p = g.player
        if self.sees:
            self.lost_t = 0
            self.last_known = (p.x, p.y)
        else:
            self.lost_t += dt
            if self.lost_t > g.cfg["lose"]:
                self.start_search(g)
                return
        if self.sees and dist < 52:                    # close & visible: run straight at player
            self.path = []
            dx, dy = p.x - self.x, p.y - self.y
            self.want = math.atan2(dy, dx)
            step = min(speed * dt, dist)
            self.x += dx / max(dist, 1e-6) * step
            self.y += dy / max(dist, 1e-6) * step
            return
        self.repath_t -= dt
        if self.repath_t <= 0 or not self.path:
            self.path = g.astar(self.tile(), tile_of(*self.last_known)) or []
            self.repath_t = g.cfg["repath"]
        if self.follow(dt, speed, g) and not self.sees:
            self.start_search(g)

    def do_search(self, dt, g, speed):
        self.timer -= dt
        if self.timer <= 0:
            self.to_patrol()
            return
        if self.wait > 0:
            self.scan(dt)
            self.wait -= dt
        elif self.path:
            if self.follow(dt, speed, g):
                self.begin_wait(1.3)
        elif self.search_pts:
            self.path = g.astar(self.tile(), self.search_pts.pop()) or []
            if not self.path:
                self.begin_wait(1.0)
        else:
            self.to_patrol()


# ----------------------------------------------------------------------------
# Player
# ----------------------------------------------------------------------------
class Player:
    def __init__(self, tile):
        self.x, self.y = center(tile)
        self.hidden = False
        self.face = 0.0
        self.stones = 5
        self.has_art = False
        self.running = False
        self.noise_t = 0.0


# ----------------------------------------------------------------------------
# Game
# ----------------------------------------------------------------------------
class Game:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((WIN_W, WIN_H))
        pygame.display.set_caption("Shadow Ninja - Stealth AI")
        self.clock = pygame.time.Clock()
        self.f_big = pygame.font.Font(None, 64)
        self.f_med = pygame.font.Font(None, 32)
        self.f_sm = pygame.font.Font(None, 22)
        self.overlay = pygame.Surface((MAP_W, MAP_H), pygame.SRCALPHA)
        self.mode = "MENU"
        self.diff = "MEDIUM"
        self.debug = False
        self.cfg = DIFFS[self.diff]
        self.time = 0.0

    # ---- setup -------------------------------------------------------------
    def start(self, diff):
        self.diff, self.cfg = diff, DIFFS[diff]
        self.grid = [list(r) for r in MAP_RAW]
        start = art = None
        for y, row in enumerate(self.grid):
            for x, c in enumerate(row):
                if c == "P":
                    start, self.grid[y][x] = (x, y), "."
                elif c == "G":
                    art, self.grid[y][x] = (x, y), "."
                elif c == "X":
                    self.exit_pos = center((x, y))
        self.player = Player(start)
        self.art_pos = center(art)
        self.guards = [Guard(r) for r in GUARD_ROUTES[: self.cfg["guards"]]]
        self.rocks, self.ripples, self.comm_lines = [], [], []
        self.alarm, self.alarm_on, self.alarm_t, self.ping_t = 0.0, False, 0.0, 0.0
        self.msg, self.msg_t = "", 0.0
        self.time = 0.0
        self.astar_calls = 0
        self.mode = "PLAY"
        self.say("Steal the artifact, then escape through the EXIT.", 5)

    def say(self, s, t=3.0):
        self.msg, self.msg_t = s, t

    # ---- world queries -------------------------------------------------------
    def tile_at(self, x, y):
        tx, ty = int(x // TILE), int(y // TILE)
        if 0 <= tx < COLS and 0 <= ty < ROWS:
            return self.grid[ty][tx]
        return "#"

    def los(self, x1, y1, x2, y2):
        n = int(math.hypot(x2 - x1, y2 - y1) // 6) + 1
        for i in range(1, n):
            t = i / n
            if self.tile_at(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t) in "#XR":
                return False
        return True

    def vision_range(self):
        return self.cfg["vision"] * (1.3 if self.alarm_on else 1.0)

    def speed_mult(self):
        return 1.2 if self.alarm_on else 1.0

    def astar(self, start, goal):
        """4-connected A* on the tile grid. Returns list of tiles (excluding start) or None."""
        self.astar_calls += 1
        if start == goal:
            return []
        grid = self.grid

        def ok(x, y):
            return 0 <= x < COLS and 0 <= y < ROWS and grid[y][x] not in "#X"

        if not ok(*goal):
            return None
        h = lambda t: abs(t[0] - goal[0]) + abs(t[1] - goal[1])
        openq = [(h(start), 0, start)]
        came, best = {}, {start: 0}
        while openq:
            _, gc, cur = heapq.heappop(openq)
            if cur == goal:
                path = []
                while cur != start:
                    path.append(cur)
                    cur = came[cur]
                return path[::-1]
            if gc > best.get(cur, 1e9):
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nb = (cur[0] + dx, cur[1] + dy)
                if ok(*nb) and gc + 1 < best.get(nb, 1e9):
                    best[nb] = gc + 1
                    came[nb] = cur
                    heapq.heappush(openq, (gc + 1 + h(nb), gc + 1, nb))
        return None

    def search_points(self, c, n):
        """Spots near the last known position to check - hiding spots are preferred."""
        cands = [(x, y)
                 for y in range(max(0, c[1] - 6), min(ROWS, c[1] + 7))
                 for x in range(max(0, c[0] - 6), min(COLS, c[0] + 7))
                 if self.grid[y][x] not in "#X" and abs(x - c[0]) + abs(y - c[1]) <= 7]
        random.shuffle(cands)
        bushes = [t for t in cands if self.grid[t[1]][t[0]] == "H"]
        rest = [t for t in cands if self.grid[t[1]][t[0]] != "H"]
        return (bushes[: max(1, n // 2)] + rest)[:n]

    # ---- sound & communication ---------------------------------------------
    def make_noise(self, x, y, level, ripple=True):
        rng = level * NOISE_SCALE * self.cfg["hear"]
        for gd in self.guards:
            if math.hypot(gd.x - x, gd.y - y) <= rng:
                gd.hear(self, (x, y))
        if ripple:
            self.ripples.append([x, y, rng, 0.0])

    def alert_others(self, src):
        rng = self.cfg["comm"]
        if rng <= 0:
            return
        for o in self.guards:
            if o is src or o.state in ("ALERT", "CHASE"):
                continue
            if math.hypot(o.x - src.x, o.y - src.y) <= rng:
                o.last_known = src.last_known
                o.start_search(self)
                self.comm_lines.append([src.x, src.y, o.x, o.y, 0.8])

    def trigger_alarm(self):
        self.alarm_on, self.alarm_t, self.ping_t = True, 18.0, 4.0
        self.say("ALARM! All guards are hunting you!", 4)
        p = self.player
        for gd in self.guards:
            if gd.state not in ("CHASE", "ALERT"):
                gd.last_known = (p.x, p.y)
                gd.start_search(self)

    # ---- player actions ------------------------------------------------------
    def blocked(self, x, y, r=9):
        return any(self.tile_at(cx, cy) in "#X"
                   for cx, cy in ((x - r, y - r), (x + r, y - r), (x - r, y + r), (x + r, y + r)))

    def update_player(self, dt):
        p = self.player
        k = pygame.key.get_pressed()
        dx = int(bool(k[pygame.K_RIGHT] or k[pygame.K_d])) - int(bool(k[pygame.K_LEFT] or k[pygame.K_a]))
        dy = int(bool(k[pygame.K_DOWN] or k[pygame.K_s])) - int(bool(k[pygame.K_UP] or k[pygame.K_w]))
        p.running = False
        if p.hidden or not (dx or dy):
            return
        l = math.hypot(dx, dy)
        dx, dy = dx / l, dy / l
        p.running = bool(k[pygame.K_LSHIFT] or k[pygame.K_RSHIFT])
        sp = RUN_SPEED if p.running else WALK_SPEED
        if not self.blocked(p.x + dx * sp * dt, p.y):
            p.x += dx * sp * dt
        if not self.blocked(p.x, p.y + dy * sp * dt):
            p.y += dy * sp * dt
        p.face = math.atan2(dy, dx)

        p.noise_t -= dt                                  # footstep noise
        if p.noise_t <= 0:
            p.noise_t = 0.3
            self.make_noise(p.x, p.y, RUN_NOISE if p.running else WALK_NOISE, ripple=p.running)

        tx, ty = tile_of(p.x, p.y)
        if self.grid[ty][tx] == "R":                     # breaking a locked door
            self.grid[ty][tx] = "r"
            self.make_noise(p.x, p.y, DOOR_NOISE)
            self.alarm = min(100, self.alarm + 12)
            self.say("You broke a door - very loud!", 2.5)

    def interact(self):
        p = self.player
        if p.hidden:
            p.hidden = False
            self.say("You leave the bush.", 1.5)
        elif not p.has_art and math.hypot(p.x - self.art_pos[0], p.y - self.art_pos[1]) < 40:
            p.has_art = True
            self.say("ARTIFACT STOLEN! Now escape through the EXIT!", 4)
        elif self.tile_at(p.x, p.y) == "H":
            if any(g.sees and g.state in ("ALERT", "CHASE") for g in self.guards):
                self.say("Can't hide - a guard is watching you!", 2)
            else:
                p.hidden = True
                p.x, p.y = center(tile_of(p.x, p.y))
                self.say("Hidden. Press E to come out.", 2)

    def throw(self, tx, ty):
        p = self.player
        if self.mode != "PLAY" or p.hidden or p.stones <= 0:
            return
        dx, dy = tx - p.x, ty - p.y
        d = math.hypot(dx, dy)
        if d < 8:
            return
        ux, uy = dx / d, dy / d
        d = min(d, STONE_RANGE)
        lx, ly, r = p.x, p.y, 0.0
        while r < d:
            r = min(d, r + 6)
            nx, ny = p.x + ux * r, p.y + uy * r
            if self.tile_at(nx, ny) in "#XR":
                break
            lx, ly = nx, ny
        p.stones -= 1
        self.rocks.append([p.x, p.y, lx, ly])

    # ---- main update ------------------------------------------------------------
    def update(self, dt):
        self.time += dt
        p = self.player
        self.update_player(dt)

        for r in self.rocks[:]:                           # stones in flight
            dx, dy = r[2] - r[0], r[3] - r[1]
            d = math.hypot(dx, dy)
            if d <= 420 * dt:
                self.make_noise(r[2], r[3], STONE_NOISE)
                self.rocks.remove(r)
            else:
                r[0] += dx / d * 420 * dt
                r[1] += dy / d * 420 * dt

        for gd in self.guards:
            gd.update(dt, self)

        gain = 0.0                                        # alarm meter
        for gd in self.guards:
            if gd.sees:
                gain += 12 if gd.state in ("ALERT", "CHASE") else 8 * gd.aware
            if p.running and not p.hidden and math.hypot(gd.x - p.x, gd.y - p.y) < 130:
                gain += 6
        if self.alarm_on:
            self.alarm_t -= dt
            self.ping_t -= dt
            if self.ping_t <= 0:                          # alarm keeps guards roughly informed
                self.ping_t = 4.0
                for gd in self.guards:
                    if gd.state not in ("CHASE", "ALERT"):
                        gd.last_known = (p.x + random.uniform(-64, 64), p.y + random.uniform(-64, 64))
                        if self.tile_at(*gd.last_known) in "#X":
                            gd.last_known = (p.x, p.y)
                        gd.start_search(self)
            if self.alarm_t <= 0:
                self.alarm_on, self.alarm = False, 40.0
                self.say("The alarm stops - guards are still edgy.", 3)
        else:
            self.alarm = min(100.0, self.alarm + gain * dt) if gain > 0 else max(0.0, self.alarm - 4 * dt)
            if self.alarm >= 100:
                self.trigger_alarm()

        for gd in self.guards:                            # caught?
            if math.hypot(gd.x - p.x, gd.y - p.y) < 18:
                self.mode = "LOSE"
                return

        if math.hypot(p.x - self.exit_pos[0], p.y - self.exit_pos[1]) < 48:
            if p.has_art:
                self.mode = "WIN"
                return
            if self.msg_t <= 0:
                self.say("You need the artifact before leaving!", 2)

        for rp in self.ripples[:]:
            rp[3] += dt
            if rp[3] > 0.8:
                self.ripples.remove(rp)
        for cl in self.comm_lines[:]:
            cl[4] -= dt
            if cl[4] <= 0:
                self.comm_lines.remove(cl)
        self.msg_t = max(0.0, self.msg_t - dt)

    # ---- drawing --------------------------------------------------------------------
    def text(self, s, pos, font=None, col=(230, 230, 240), ctr=False):
        surf = (font or self.f_sm).render(s, True, col)
        r = surf.get_rect(center=pos) if ctr else surf.get_rect(topleft=pos)
        self.screen.blit(surf, r)

    def draw_map(self):
        scr = self.screen
        for y in range(ROWS):
            for x in range(COLS):
                c = self.grid[y][x]
                rect = pygame.Rect(x * TILE, y * TILE, TILE, TILE)
                if c in "#X":
                    pygame.draw.rect(scr, (58, 62, 80), rect)
                    pygame.draw.rect(scr, (40, 43, 58), rect, 1)
                    pygame.draw.line(scr, (80, 85, 108), rect.topleft, rect.topright)
                    continue
                pygame.draw.rect(scr, (30, 32, 42) if (x + y) % 2 else (34, 36, 47), rect)
                if c == "H":
                    for ox, oy in ((9, 10), (22, 12), (15, 22)):
                        pygame.draw.circle(scr, (40, 130, 60), (rect.x + ox, rect.y + oy), 9)
                    pygame.draw.circle(scr, (60, 170, 80), (rect.x + 16, rect.y + 14), 8)
                elif c == "R":
                    pygame.draw.rect(scr, (130, 85, 45), rect.inflate(-4, -4))
                    pygame.draw.rect(scr, (80, 50, 25), rect.inflate(-4, -4), 2)
                    pygame.draw.circle(scr, (230, 190, 70), (rect.centerx + 6, rect.centery), 3)
                elif c == "r":
                    pygame.draw.rect(scr, (90, 60, 35), (rect.x + 2, rect.y + 2, 5, TILE - 4))
        ex, ey = self.exit_pos
        er = pygame.Rect(0, 0, TILE, TILE)
        er.center = (ex, ey)
        pygame.draw.rect(scr, (60, 200, 90) if self.player.has_art else (200, 160, 40), er)
        self.text("EXIT", (ex, ey), self.f_sm, (20, 20, 20), True)

        if not self.player.has_art:                        # artifact
            ax, ay = self.art_pos
            s = 9 + 2 * math.sin(self.time * 4)
            pygame.draw.polygon(scr, (90, 240, 255), [(ax, ay - s), (ax + s, ay), (ax, ay + s), (ax - s, ay)])
            pygame.draw.polygon(scr, (255, 255, 255), [(ax, ay - s), (ax + s, ay), (ax, ay + s), (ax - s, ay)], 2)

    def draw_cones(self):
        ov = self.overlay
        ov.fill((0, 0, 0, 0))
        fov = math.radians(self.cfg["fov"])
        vr = self.vision_range()
        for gd in self.guards:
            pts = [(gd.x, gd.y)]
            n = 26
            for i in range(n + 1):
                a = gd.angle - fov / 2 + fov * i / n
                ca, sa = math.cos(a), math.sin(a)
                r = 0
                while r < vr and self.tile_at(gd.x + ca * (r + 6), gd.y + sa * (r + 6)) not in "#XR":
                    r += 6
                pts.append((gd.x + ca * r, gd.y + sa * r))
            pygame.draw.polygon(ov, (*STATE_COL[gd.state], 55), pts)
        self.screen.blit(ov, (0, 0))

    def draw_entities(self):
        scr, p = self.screen, self.player
        for rp in self.ripples:                            # noise ripples
            k = rp[3] / 0.8
            pygame.draw.circle(scr, (255, 255, 255), (int(rp[0]), int(rp[1])), max(2, int(rp[2] * k)), 1)
        for cl in self.comm_lines:
            pygame.draw.line(scr, (255, 90, 255), (cl[0], cl[1]), (cl[2], cl[3]), 2)
        for r in self.rocks:
            pygame.draw.circle(scr, (170, 170, 170), (int(r[0]), int(r[1])), 4)

        for gd in self.guards:
            col = STATE_COL[gd.state]
            if self.debug:
                if gd.path:
                    pygame.draw.lines(scr, col, False, [(gd.x, gd.y)] + [center(t) for t in gd.path], 2)
                if gd.last_known and gd.state in ("CHASE", "SEARCH", "ALERT"):
                    lx, ly = gd.last_known
                    pygame.draw.line(scr, col, (lx - 6, ly - 6), (lx + 6, ly + 6), 2)
                    pygame.draw.line(scr, col, (lx - 6, ly + 6), (lx + 6, ly - 6), 2)
            pygame.draw.circle(scr, (40, 40, 60), (int(gd.x), int(gd.y)), 12)
            pygame.draw.circle(scr, col, (int(gd.x), int(gd.y)), 12, 3)
            pygame.draw.line(scr, (255, 255, 255), (gd.x, gd.y),
                             (gd.x + math.cos(gd.angle) * 14, gd.y + math.sin(gd.angle) * 14), 2)
            sym = SYMBOL[gd.state]
            if sym:
                self.text(sym, (gd.x, gd.y - 24), self.f_med, col, True)
            if gd.aware > 0.02 and gd.state in ("PATROL", "SUSPICIOUS", "SEARCH"):
                pygame.draw.rect(scr, (60, 60, 60), (gd.x - 12, gd.y - 20, 24, 4))
                pygame.draw.rect(scr, (255, 220, 60), (gd.x - 12, gd.y - 20, 24 * gd.aware, 4))
            if self.debug:
                self.text(gd.state, (gd.x, gd.y + 22), self.f_sm, col, True)

        if p.hidden:
            pygame.draw.circle(scr, (110, 240, 130), (int(p.x), int(p.y)), 13, 2)
            self.text("hidden", (p.x, p.y - 22), self.f_sm, (110, 240, 130), True)
        else:
            pygame.draw.circle(scr, (25, 25, 35), (int(p.x), int(p.y)), 10)
            pygame.draw.circle(scr, (190, 190, 215), (int(p.x), int(p.y)), 10, 2)
            px, py = -math.sin(p.face), math.cos(p.face)     # red headband
            pygame.draw.line(scr, (220, 40, 40), (p.x - px * 9 + math.cos(p.face) * 3, p.y - py * 9 + math.sin(p.face) * 3),
                             (p.x + px * 9 + math.cos(p.face) * 3, p.y + py * 9 + math.sin(p.face) * 3), 3)
        if self.alarm_on and int(self.time * 4) % 2:
            pygame.draw.rect(scr, (255, 30, 30), (0, 0, MAP_W, MAP_H), 6)

    def draw_hud(self):
        scr, p = self.screen, self.player
        pygame.draw.rect(scr, (12, 12, 18), (0, MAP_H, WIN_W, HUD_H))
        self.text("ALARM %d%%" % self.alarm, (20, MAP_H + 8), self.f_sm, (255, 120, 120) if self.alarm_on else (230, 230, 240))
        pygame.draw.rect(scr, (50, 50, 60), (20, MAP_H + 28, 280, 16))
        pygame.draw.rect(scr, (230, 50, 50) if self.alarm > 66 else (240, 170, 40), (20, MAP_H + 28, 280 * self.alarm / 100, 16))
        pygame.draw.rect(scr, (140, 140, 150), (20, MAP_H + 28, 280, 16), 1)
        self.text("Stones: %d" % p.stones, (330, MAP_H + 8))
        self.text("Artifact: " + ("STOLEN - reach the EXIT" if p.has_art else "not yet"), (330, MAP_H + 28),
                  col=(120, 240, 130) if p.has_art else (230, 230, 240))
        self.text("Difficulty: %s   Time: %ds" % (self.diff, self.time), (650, MAP_H + 8))
        self.text("A* calls: %d   (TAB debug)" % self.astar_calls, (650, MAP_H + 28), col=(150, 150, 165))
        x = 20
        for name, col in STATE_COL.items():                # legend
            pygame.draw.circle(scr, col, (x + 5, MAP_H + 57), 5)
            self.text(name, (x + 14, MAP_H + 51), col=col)
            x += 130
        if self.msg_t > 0:
            s = self.f_med.render(self.msg, True, (255, 255, 255))
            r = s.get_rect(center=(MAP_W // 2, 22))
            pygame.draw.rect(scr, (0, 0, 0), r.inflate(24, 12))
            scr.blit(s, r)

    def draw_menu(self):
        scr = self.screen
        scr.fill((12, 12, 20))
        self.text("SHADOW NINJA", (WIN_W // 2, 70), self.f_big, (230, 60, 60), True)
        lines = [
            "Infiltrate the compound, steal the artifact, escape through the EXIT.",
            "",
            "Guards run a Finite State Machine (PATROL / SUSPICIOUS / ALERT / CHASE / SEARCH)",
            "and use A* to walk around walls. They see through a vision cone (walls block it),",
            "hear noise, search bushes near your last position, and warn each other.",
            "",
            "WASD / arrows: move      SHIFT: run (loud!)      E: steal artifact / hide in bush",
            "Left click: throw stone to lure guards      SPACE: throw forward      TAB: debug view",
            "Breaking a locked door (brown) is very loud.   Don't let the ALARM reach 100%.",
        ]
        for i, l in enumerate(lines):
            self.text(l, (WIN_W // 2, 140 + i * 28), self.f_sm, ctr=True)
        self.text("Choose difficulty:", (WIN_W // 2, 440), self.f_med, ctr=True)
        for i, (k, c) in enumerate((("1  EASY", (90, 220, 120)), ("2  MEDIUM", (240, 210, 60)), ("3  HARD", (240, 70, 70)))):
            self.text(k, (WIN_W // 2, 490 + i * 40), self.f_med, c, True)

    def draw_end(self):
        s = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
        s.fill((0, 0, 0, 170))
        self.screen.blit(s, (0, 0))
        if self.mode == "WIN":
            self.text("MISSION COMPLETE", (WIN_W // 2, 270), self.f_big, (120, 240, 140), True)
            self.text("Escaped in %d seconds." % self.time, (WIN_W // 2, 330), self.f_med, ctr=True)
        else:
            self.text("CAUGHT!", (WIN_W // 2, 270), self.f_big, (240, 70, 70), True)
        self.text("R: retry    M: menu    ESC: quit", (WIN_W // 2, 390), self.f_med, ctr=True)

    def draw(self):
        if self.mode == "MENU":
            self.draw_menu()
            return
        self.screen.fill((14, 15, 20))
        self.draw_map()
        self.draw_cones()
        self.draw_entities()
        self.draw_hud()
        if self.mode in ("WIN", "LOSE"):
            self.draw_end()

    # ---- loop -----------------------------------------------------------------------------
    def run(self):
        keymap = {pygame.K_1: "EASY", pygame.K_2: "MEDIUM", pygame.K_3: "HARD"}
        while True:
            dt = min(self.clock.tick(60) / 1000.0, 0.05)
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()
                if e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_ESCAPE:
                        if self.mode == "PLAY":
                            self.mode = "MENU"
                        else:
                            pygame.quit()
                            sys.exit()
                    elif self.mode == "MENU":
                        if e.key in keymap:
                            self.start(keymap[e.key])
                        elif e.key == pygame.K_RETURN:
                            self.start("MEDIUM")
                    elif e.key == pygame.K_r:
                        self.start(self.diff)
                    elif e.key == pygame.K_m:
                        self.mode = "MENU"
                    elif self.mode == "PLAY":
                        if e.key == pygame.K_e:
                            self.interact()
                        elif e.key == pygame.K_SPACE:
                            p = self.player
                            self.throw(p.x + math.cos(p.face) * 200, p.y + math.sin(p.face) * 200)
                        elif e.key == pygame.K_TAB:
                            self.debug = not self.debug
                if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and self.mode == "PLAY":
                    if e.pos[1] < MAP_H:
                        self.throw(*e.pos)
            if self.mode == "PLAY":
                self.update(dt)
            self.draw()
            pygame.display.flip()


if __name__ == "__main__":
    Game().run()
