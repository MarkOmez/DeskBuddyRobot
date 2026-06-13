# roboeyes.py - RoboEyes-like (MicroPython) for SSD1306 (128x64)
# Capsule vertical eyes + smooth transitions + autoblink + idle gaze.
# Designed to be simple and fast on ESP32-C3.

from time import ticks_ms, ticks_diff
from math import sqrt
import urandom

def _toi(v): return int(round(v))
def _clamp(v, a, b): return a if v < a else b if v > b else v

def _urandint(a, b):
    span = b - a + 1
    r = urandom.getrandbits(16) % span
    return a + r

def _ease_in_out_cubic(t):
    if t < 0.5:
        return 4 * t * t * t
    u = 2 * t - 2
    return 0.5 * u * u * u + 1

def _lerp(a, b, t): return a + (b - a) * t

def _hspan(oled, x0, x1, y, col, W, H):
    x0 = _toi(x0); x1 = _toi(x1); y = _toi(y)
    if x1 < x0: x0, x1 = x1, x0
    if y < 0 or y >= H: return
    x0 = max(0, x0); x1 = min(W - 1, x1)
    if x0 <= x1:
        oled.hline(x0, y, x1 - x0 + 1, col)

def _fill_circle(oled, cx, cy, r, col, W, H):
    cx = _toi(cx); cy = _toi(cy); r = max(0, _toi(r))
    r2 = r * r
    y0 = max(-r, -cy)
    y1 = min(r, H - 1 - cy)
    for dy in range(y0, y1 + 1):
        dx = int(sqrt(max(0, r2 - dy * dy)))
        _hspan(oled, cx - dx, cx + dx, cy + dy, col, W, H)

def _fill_ellipse(oled, cx, cy, rx, ry, col, W, H):
    cx = _toi(cx); cy = _toi(cy)
    rx = max(0, _toi(rx)); ry = max(0, _toi(ry))
    if rx == 0 and ry == 0:
        if 0 <= cx < W and 0 <= cy < H:
            oled.pixel(cx, cy, col)
        return
    if ry == 0:
        _hspan(oled, cx - rx, cx + rx, cy, col, W, H); return
    if rx == 0:
        for y in range(cy - ry, cy + ry + 1):
            if 0 <= y < H and 0 <= cx < W:
                oled.pixel(cx, y, col)
        return

    ry2 = ry * ry
    y0 = max(-ry, -cy)
    y1 = min(ry, H - 1 - cy)
    for dy in range(y0, y1 + 1):
        t = 1.0 - (dy * dy) / float(ry2)
        dx = _toi(rx * sqrt(t if t > 0 else 0))
        _hspan(oled, cx - dx, cx + dx, cy + dy, col, W, H)

def _fill_vcapsule(oled, cx, cy, w, h, col, W, H):
    cx = _toi(cx); cy = _toi(cy)
    w = max(1, _toi(w)); h = max(1, _toi(h))
    r = w // 2
    if h <= w:
        _fill_ellipse(oled, cx, cy, r, h // 2, col, W, H)
        return
    body_h = h - 2 * r
    y_top = cy - body_h // 2
    # body
    x0 = cx - r
    y0 = y_top
    ww = 2 * r + 1
    hh = body_h
    if hh > 0:
        # clip manually (SSD1306 fill_rect does no clipping)
        if x0 < W and x0 + ww > 0 and y0 < H and y0 + hh > 0:
            x1 = max(0, x0); y1 = max(0, y0)
            x2 = min(W, x0 + ww); y2 = min(H, y0 + hh)
            if x2 > x1 and y2 > y1:
                oled.fill_rect(x1, y1, x2 - x1, y2 - y1, col)

    _fill_circle(oled, cx, y_top, r, col, W, H)
    _fill_circle(oled, cx, y_top + body_h, r, col, W, H)

# --------------------------------------------------------------------

class RoboEyes:
    # moods (RoboEyes-like)
    DEFAULT = "DEFAULT"
    HAPPY   = "HAPPY"
    TIRED   = "TIRED"
    ANGRY   = "ANGRY"
    CONFUSED= "CONFUSED"
    SLEEP   = "SLEEP"
    WINK    = "WINK"

    # positions
    POS_DEFAULT = "DEFAULT"
    POS_N  = "N";  POS_NE="NE"; POS_E="E"; POS_SE="SE"
    POS_S  = "S";  POS_SW="SW"; POS_W="W"; POS_NW="NW"

    def __init__(self, oled, screen_w, screen_h, max_fps=60):
        self.oled = oled
        self.W = screen_w
        self.H = screen_h

        self.max_fps = max_fps
        self._min_frame_ms = int(1000 / max_fps) if max_fps else 0
        self._next_frame_at = ticks_ms()

        # base geometry
        self._base_wL = 26; self._base_hL = 38
        self._base_wR = 26; self._base_hR = 38
        self._space = 16
        self._cyclops = False

        # state / target (tween)
        self._cur = {"wL": self._base_wL, "hL": self._base_hL, "wR": self._base_wR, "hR": self._base_hR}
        self._src = self._cur.copy()
        self._dst = self._cur.copy()
        self._t0 = ticks_ms()
        self._trans_ms = 300

        # mood / position
        self._mood = self.DEFAULT
        self._pos  = self.POS_DEFAULT
        self._pos_dx = 0
        self._pos_dy = 0

        # eye offset (gaze)
        self._gaze_x = 0
        self._gaze_y = 0

        # curiosity (optional): increase outer eye height when looking far left/right
        self._curiosity = False

        # autoblink
        self._autoblink = False
        self._blink_interval_s = 2
        self._blink_var_s = 2
        self._next_blink_at = ticks_ms() + 1500
        self._blinking = False
        self._blink_phase = 0
        self._blink_t0 = 0

        # idle mode (random gaze reposition)
        self._idle = False
        self._idle_interval_s = 3
        self._idle_var_s = 3
        self._next_idle_at = ticks_ms() + 1200

        # drawing colors for mono OLED
        self.bg = 0
        self.fg = 1

        # sleep decoration
        self._sleep_zzz = True
        self._zzz_phase = 0

    # --- API similar to RoboEyes ---
    def begin(self, screen_w=None, screen_h=None, max_fps=None):
        if screen_w: self.W = screen_w
        if screen_h: self.H = screen_h
        if max_fps is not None:
            self.max_fps = max_fps
            self._min_frame_ms = int(1000 / max_fps) if max_fps else 0

    def setDisplayColors(self, background, main):
        self.bg = background
        self.fg = main

    def setWidth(self, leftEye, rightEye=None):
        if rightEye is None: rightEye = leftEye
        self._base_wL = int(leftEye); self._base_wR = int(rightEye)
        self._apply_mood(self._mood, transition_ms=0)

    def setHeight(self, leftEye, rightEye=None):
        if rightEye is None: rightEye = leftEye
        self._base_hL = int(leftEye); self._base_hR = int(rightEye)
        self._apply_mood(self._mood, transition_ms=0)

    def setSpacebetween(self, space):
        self._space = int(space)

    def setCyclops(self, onoff):
        self._cyclops = bool(onoff)

    def setCuriosity(self, onoff):
        self._curiosity = bool(onoff)

    def setMood(self, mood, transition_ms=280):
        self._apply_mood(mood, transition_ms=transition_ms)

    def setPosition(self, pos):
        self._pos = pos
        # dx/dy in pixels
        dx = dy = 0
        if pos in (self.POS_N, self.POS_NE, self.POS_NW): dy = -6
        if pos in (self.POS_S, self.POS_SE, self.POS_SW): dy = +6
        if pos in (self.POS_E, self.POS_NE, self.POS_SE): dx = +10
        if pos in (self.POS_W, self.POS_NW, self.POS_SW): dx = -10
        self._pos_dx = dx
        self._pos_dy = dy

    def setAutoblinker(self, onoff, interval_s=2, variation_s=2):
        self._autoblink = bool(onoff)
        self._blink_interval_s = int(interval_s)
        self._blink_var_s = int(variation_s)
        self._schedule_next_blink()

    def setIdleMode(self, onoff, interval_s=3, variation_s=3):
        self._idle = bool(onoff)
        self._idle_interval_s = int(interval_s)
        self._idle_var_s = int(variation_s)
        self._schedule_next_idle()

    def open(self, left=1, right=1, transition_ms=180):
        # open = restore current mood target, but allow one eye closed-ish
        self._apply_mood(self._mood, transition_ms=transition_ms)
        if not left:
            self._dst["hL"] = max(4, int(self._dst["hL"] * 0.10))
        if not right:
            self._dst["hR"] = max(4, int(self._dst["hR"] * 0.10))
        self._start_tween(transition_ms)

    # convenience
    def wink(self, which="R", hold_ms=250):
        # sets a wink and schedules automatic return via internal blink anim
        self.setMood(self.WINK, transition_ms=120)
        # store which side: R closes right eye, L closes left eye
        self._wink_side = which
        self._wink_until = ticks_ms() + int(hold_ms)

    def setSleepDecoration(self, zzz_on=True):
        self._sleep_zzz = bool(zzz_on)

    def update(self):
        # framerate cap
        now = ticks_ms()
        if self._min_frame_ms:
            if ticks_diff(now, self._next_frame_at) < 0:
                return
            self._next_frame_at = now + self._min_frame_ms

        # handle wink auto-return
        if getattr(self, "_wink_until", 0) and ticks_diff(now, self._wink_until) >= 0 and self._mood == self.WINK:
            self._wink_until = 0
            self.setMood(self.DEFAULT, transition_ms=180)

        # idle gaze
        if self._idle and ticks_diff(now, self._next_idle_at) >= 0:
            # small random offsets
            self._gaze_x = _urandint(-12, 12)
            self._gaze_y = _urandint(-4, 4)
            self._schedule_next_idle()

        # autoblink
        if self._autoblink and not self._blinking and ticks_diff(now, self._next_blink_at) >= 0:
            self._blinking = True
            self._blink_phase = 0
            self._blink_t0 = now

        # update tween
        self._step_tween(now)

        # blink animation (overrides height temporarily)
        draw_params = self._cur.copy()
        if self._blinking:
            # 7-step curve, ~140ms total
            steps = (1.0, 0.55, 0.25, 0.10, 0.25, 0.55, 1.0)
            # progress by time slice
            dt = ticks_diff(now, self._blink_t0)
            idx = dt // 20
            if idx >= len(steps):
                self._blinking = False
                self._schedule_next_blink()
            else:
                f = steps[int(idx)]
                draw_params["hL"] = max(4, _toi(draw_params["hL"] * f))
                draw_params["hR"] = max(4, _toi(draw_params["hR"] * f))

        # wink mood: close one eye hard
        if self._mood == self.WINK:
            side = getattr(self, "_wink_side", "R")
            if side.upper() == "L":
                draw_params["hL"] = 6
            else:
                draw_params["hR"] = 6

        # curiosity: if looking far left/right, stretch outer eye a bit
        if self._curiosity:
            if self._gaze_x <= -10:
                draw_params["hL"] = min(58, draw_params["hL"] + 6)
            elif self._gaze_x >= 10:
                draw_params["hR"] = min(58, draw_params["hR"] + 6)

        self.drawEyes(draw_params)

    def drawEyes(self, params=None):
        if params is None:
            params = self._cur

        self.oled.fill(self.bg)

        # compute centers
        cy = (self.H // 2) + self._pos_dy + self._gaze_y
        if self._cyclops:
            cx = (self.W // 2) + self._pos_dx + self._gaze_x
            _fill_vcapsule(self.oled, cx, cy, params["wL"], params["hL"], self.fg, self.W, self.H)
        else:
            cxL = (self.W // 2) - (self._space // 2) - (params["wL"] // 2) + self._pos_dx + self._gaze_x
            cxR = (self.W // 2) + (self._space // 2) + (params["wR"] // 2) + self._pos_dx + self._gaze_x

            # clamp to screen
            # keep some margin so capsules don't clip too often
            margin = 6
            cxL = _clamp(cxL, margin, self.W//2 - margin)
            cxR = _clamp(cxR, self.W//2 + margin, self.W - margin)

            _fill_vcapsule(self.oled, cxL, cy, params["wL"], params["hL"], self.fg, self.W, self.H)
            _fill_vcapsule(self.oled, cxR, cy, params["wR"], params["hR"], self.fg, self.W, self.H)

        # sleep decoration
        if self._mood == self.SLEEP and self._sleep_zzz:
            self._draw_zzz()

        self.oled.show()

    # --- internal helpers ---
    def _start_tween(self, transition_ms):
        self._trans_ms = max(0, int(transition_ms))
        self._src = self._cur.copy()
        self._t0 = ticks_ms()

    def _step_tween(self, now):
        if self._trans_ms <= 0:
            self._cur = self._dst.copy()
            return
        dt = ticks_diff(now, self._t0)
        if dt <= 0:
            self._cur = self._src.copy()
            return
        t = dt / float(self._trans_ms)
        if t >= 1.0:
            self._cur = self._dst.copy()
            return
        tt = _ease_in_out_cubic(t)
        out = {}
        for k in self._dst:
            out[k] = _lerp(self._src.get(k, 0), self._dst.get(k, 0), tt)
        # store as ints where needed
        self._cur = {k: _toi(v) for k, v in out.items()}

    def _apply_mood(self, mood, transition_ms=280):
        self._mood = mood

        # base
        wL, hL = self._base_wL, self._base_hL
        wR, hR = self._base_wR, self._base_hR

        if mood == self.DEFAULT:
            pass
        elif mood == self.HAPPY:
            hL = max(10, hL - 10); hR = max(10, hR - 10)
        elif mood == self.TIRED:
            hL = max(8, hL - 18); hR = max(8, hR - 18)
        elif mood == self.ANGRY:
            wL = max(10, wL - 4); wR = max(10, wR - 4)
            hL = max(8, hL - 12); hR = max(8, hR - 12)
        elif mood == self.CONFUSED:
            hL = min(58, hL + 6)
            hR = max(8, hR - 12)
        elif mood == self.SLEEP:
            hL = 10; hR = 10
        elif mood == self.WINK:
            # keep base; wink is applied in update() per-eye
            pass
        else:
            # unknown mood -> default
            self._mood = self.DEFAULT

        self._dst = {"wL": int(wL), "hL": int(hL), "wR": int(wR), "hR": int(hR)}
        self._start_tween(transition_ms)

    def _schedule_next_blink(self):
        base = max(1, self._blink_interval_s)
        var  = max(0, self._blink_var_s)
        add = _urandint(0, var) if var else 0
        self._next_blink_at = ticks_ms() + (base + add) * 1000

    def _schedule_next_idle(self):
        base = max(1, self._idle_interval_s)
        var  = max(0, self._idle_var_s)
        add = _urandint(0, var) if var else 0
        self._next_idle_at = ticks_ms() + (base + add) * 1000

    def _draw_zzz(self):
        # simple drifting ZZZ in top-right
        # moves slowly upward
        self._zzz_phase = (self._zzz_phase + 1) % 10000
        y = 46 - ((self._zzz_phase // 2) % 56)
        x0 = self.W - 32
        # wrap
        if y < -8:
            y += 64 + 24
        # three Z
        self.oled.text("Z", x0 + 0, y, self.fg)
        self.oled.text("Z", x0 + 6, y - 10, self.fg)
        self.oled.text("Z", x0 + 12, y - 20, self.fg)
