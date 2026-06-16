# droid_led_eyes.py
# Sci-fi LED-matrix robot eyes for SSD1306 128x64 in MicroPython.
# Compatible with the ModernEyes API used by DeskBuddyRobot:
# setMood(), setPosition(), wink(), pulse(), confused(), update(),
# setAutoblinker(), setIdleMode(), setDisplayColors(), setWidth(), setHeight(), setSpacebetween().
#
# The style is inspired by classic sci-fi droid LED displays, using generic
# space-themed micro animations: crossing energy blades, hyperspace,
# schematic battle-station flythrough, and small generic robot silhouettes.
# This variant uses cute vertical rounded-rectangle LED panels with no moving pupils.

from time import ticks_ms, ticks_diff
import urandom
import math


class DroidLedEyes:
    DEFAULT = 0
    HAPPY = 1
    ANGRY = 2
    TIRED = 3
    CURIOUS = 4
    SAD = 5
    SLEEP = 6
    SURPRISED = 7
    LOVE = 8
    CONFUSED = 9
    BORED = 10

    POS_DEFAULT = 0
    POS_LEFT = 1
    POS_RIGHT = 2
    POS_UP = 3
    POS_DOWN = 4
    POS_UP_LEFT = 5
    POS_UP_RIGHT = 6
    POS_DOWN_LEFT = 7
    POS_DOWN_RIGHT = 8

    ANIM_SABERS = 100
    ANIM_HYPERSPACE = 101
    ANIM_X_FIGHTER = 102
    ANIM_Y_FIGHTER = 103
    ANIM_DROID_ROW = 104
    ANIM_RADAR = 105
    ANIM_BATTLE_PLANS = 106

    def __init__(self, oled, width=128, height=64, max_fps=35):
        self.oled = oled
        self.screen_w = width
        self.screen_h = height
        self.frame_interval = int(1000 / max_fps)
        self.last_frame = ticks_ms()

        self.bg = 0
        self.fg = 1

        # Matrix geometry. Each lit LED is a small square.
        # Cute compact eyes: vertical rounded rectangles that leave more room on screen.
        self.dot = 2
        self.pitch = 4
        self.eye_cols = 6
        self.eye_rows = 10
        self.base_gap = 18
        self.center_y = 34

        self.mood = self.DEFAULT
        self.position = self.POS_DEFAULT

        # Blink / idle
        self.blink_enabled = True
        self.blinking = False
        self.blink_start = 0
        self.blink_next = ticks_ms() + self._rand(1800, 5200)
        self.blink_close_ms = 90
        self.blink_hold_ms = 40
        self.blink_open_ms = 150

        self.idle_enabled = True
        self.idle_next = ticks_ms() + self._rand(1700, 3800)
        self.idle_return_at = 0

        self.micro_phase = self._rand(0, 628) / 100.0
        self.micro_x = 0
        self.micro_y = 0

        # Reactions
        self.wink_active = False
        self.wink_side = "R"
        self.wink_start = 0
        self.wink_duration = 650

        self.pulse_active = False
        self.pulse_start = 0
        self.pulse_duration = 850

        self.confused_active = False
        self.confused_start = 0
        self.confused_duration = 900

        # Mini screen animations that occasionally replace the eyes.
        self.anim_enabled = True
        self.anim_active = False
        self.anim_type = self.ANIM_SABERS
        self.anim_start = 0
        self.anim_duration = 2900
        self.anim_next = ticks_ms() + self._rand(9000, 16000)
        self.anim_list = [
            self.ANIM_SABERS,
            self.ANIM_HYPERSPACE,
            self.ANIM_BATTLE_PLANS,
            self.ANIM_DROID_ROW,
            self.ANIM_RADAR,
        ]

    # ---------- API compatibility ----------
    def setDisplayColors(self, bg, fg):
        self.bg = bg
        self.fg = fg

    def setWidth(self, left, right):
        # Kept for compatibility. Geometry is LED-grid based.
        pass

    def setHeight(self, left, right):
        # Kept for compatibility. Geometry is LED-grid based.
        pass

    def setSpacebetween(self, gap):
        self.base_gap = gap

    def setAutoblinker(self, enabled=True, interval_s=3, variation_s=4):
        self.blink_enabled = enabled
        self.blink_next = ticks_ms() + self._rand(
            int(interval_s * 1000),
            int((interval_s + variation_s) * 1000)
        )

    def setIdleMode(self, enabled=True, interval_s=3, variation_s=5):
        self.idle_enabled = enabled
        self.idle_next = ticks_ms() + self._rand(
            int(interval_s * 1000),
            int((interval_s + variation_s) * 1000)
        )

    def setMood(self, mood, transition_ms=850, immediate=False):
        self.mood = mood

    def setPosition(self, position):
        self.position = position

    def wink(self, side="R", hold_ms=650):
        self.wink_active = True
        self.wink_side = side
        self.wink_start = ticks_ms()
        self.wink_duration = hold_ms

    def pulse(self, duration_ms=850):
        self.pulse_active = True
        self.pulse_start = ticks_ms()
        self.pulse_duration = duration_ms

    def confused(self, duration_ms=900):
        self.confused_active = True
        self.confused_start = ticks_ms()
        self.confused_duration = duration_ms

    def setMiniAnimations(self, enabled=True, interval_ms_min=9000, interval_ms_max=16000):
        self.anim_enabled = enabled
        self.anim_next = ticks_ms() + self._rand(interval_ms_min, interval_ms_max)

    def playMiniAnimation(self, anim_type=None, duration_ms=2900):
        if anim_type is None:
            anim_type = self.anim_list[self._rand(0, len(self.anim_list) - 1)]
        self.anim_type = anim_type
        self.anim_duration = duration_ms
        self.anim_start = ticks_ms()
        self.anim_active = True

    # ---------- Utilities ----------
    def _rand(self, a, b):
        if b <= a:
            return a
        return a + (urandom.getrandbits(16) % (b - a + 1))

    def _clamp(self, v, a, b):
        if v < a:
            return a
        if v > b:
            return b
        return v

    def _ease(self, t):
        t = self._clamp(t, 0.0, 1.0)
        return t * t * (3.0 - 2.0 * t)

    def _led(self, x, y, size=None):
        if size is None:
            size = self.dot
        if x < -size or y < -size or x >= self.screen_w or y >= self.screen_h:
            return
        self.oled.fill_rect(int(x), int(y), int(size), int(size), self.fg)

    def _line_led(self, x1, y1, x2, y2, step=5, size=None):
        dx = x2 - x1
        dy = y2 - y1
        dist = int(max(abs(dx), abs(dy)))
        if dist <= 0:
            self._led(x1, y1, size)
            return
        n = max(1, dist // step)
        for i in range(n + 1):
            t = i / float(n)
            self._led(x1 + dx * t, y1 + dy * t, size)

    def _circle_led(self, cx, cy, r, dots=24, size=2):
        for i in range(dots):
            a = 2.0 * math.pi * i / dots
            self._led(cx + math.cos(a) * r, cy + math.sin(a) * r, size)

    def _text_center(self, text, y):
        x = (self.screen_w - len(text) * 8) // 2
        self.oled.text(text, x, y, self.fg)

    # ---------- Eyes ----------
    def _gaze_offset(self):
        # Intentionally fixed. This style has no moving pupils and the
        # LED panels stay centered for a calmer, cuter expression.
        return 0, 0

    def _blink_level(self, now):
        if not self.blink_enabled:
            return 0.0

        if (not self.blinking) and ticks_diff(now, self.blink_next) >= 0:
            self.blinking = True
            self.blink_start = now

        if not self.blinking:
            return 0.0

        dt = ticks_diff(now, self.blink_start)
        total = self.blink_close_ms + self.blink_hold_ms + self.blink_open_ms

        if dt < self.blink_close_ms:
            return self._ease(dt / float(self.blink_close_ms))
        if dt < self.blink_close_ms + self.blink_hold_ms:
            return 1.0
        if dt < total:
            t = (dt - self.blink_close_ms - self.blink_hold_ms) / float(self.blink_open_ms)
            return 1.0 - self._ease(t)

        self.blinking = False
        self.blink_next = now + self._rand(1800, 5200)
        return 0.0

    def _mood_shape(self, col, row, side, blink_rows):
        # side: -1 left, +1 right. The function returns True for active LEDs.
        # The base eye is a compact vertical rounded rectangle, with no moving pupil.
        c = col
        r = row
        rows = self.eye_rows
        cols = self.eye_cols
        mood = self.mood

        # Blink closes from top and bottom.
        if r < blink_rows or r >= rows - blink_rows:
            return False

        # Rounded rectangle mask: softly remove the four extreme corners.
        if (r == 0 or r == rows - 1) and (c == 0 or c == cols - 1):
            return False

        # Default vertical panel.
        active = True

        if mood == self.SLEEP:
            return r == rows // 2 and 1 <= c <= cols - 2

        if mood == self.TIRED:
            return r >= 2 and not ((r == 2 or r == rows - 1) and (c == 0 or c == cols - 1))

        if mood == self.BORED:
            return 2 <= r <= rows - 3 and not ((r == 2 or r == rows - 3) and (c == 0 or c == cols - 1))

        if mood == self.HAPPY:
            # A cute vertical capsule with a softer top and fuller lower half.
            if r == 1 and c in (0, cols - 1):
                return False
            if r == 2 and c in (0, cols - 1):
                return False
            if r >= rows - 3:
                return 1 <= c <= cols - 2
            return True

        if mood == self.SAD:
            # Slight inward droop near the top, fuller at the bottom.
            if side < 0:
                if (r <= 2 and c == cols - 1) or (r == 0 and c >= cols - 2):
                    return False
            else:
                if (r <= 2 and c == 0) or (r == 0 and c <= 1):
                    return False
            return r >= 1 or 1 <= c <= cols - 2

        if mood == self.ANGRY:
            # Inward slant toward the center.
            if side < 0:
                if (r == 0 and c >= 2) or (r == 1 and c >= 4) or (r == 2 and c == cols - 1):
                    return False
            else:
                if (r == 0 and c <= cols - 3) or (r == 1 and c <= 1) or (r == 2 and c == 0):
                    return False
            return True

        if mood == self.SURPRISED:
            # Hollow tall rounded rectangle.
            return c in (1, cols - 2) or r in (1, rows - 2)

        if mood == self.CONFUSED:
            # Zig-zag internal fill, but panel stays fixed.
            if side < 0:
                return (r in (1, 2, 4, 6, 8) and 1 <= c <= cols - 2) or (c == 2 and r in (3, 5, 7))
            return (r in (1, 3, 5, 7, 8) and 1 <= c <= cols - 2) or (c == 3 and r in (2, 4, 6))

        if mood == self.CURIOUS:
            # One eye a bit more open, the other slightly narrowed.
            if side < 0:
                return not ((r == 1 or r == rows - 2) and c in (0, cols - 1))
            return 1 <= r <= rows - 2 and not ((r == 1 or r == rows - 2) and c in (0, cols - 1))

        if mood == self.LOVE:
            # Small heart-like fill inside a tall panel.
            return (
                (r == 1 and c in (1, 2, 3, 4)) or
                (r == 2 and c in (0, 1, 2, 3, 4, 5)) or
                (r == 3 and c in (1, 2, 3, 4)) or
                (r == 4 and c in (2, 3)) or
                (r == 5 and c in (1, 2, 3, 4)) or
                (r == 6 and c in (1, 2, 3, 4)) or
                (r == 7 and c in (2, 3))
            )

        return active

    def _draw_eye(self, cx, cy, side, closed=False, pulse=0):
        gx, gy = self._gaze_offset()
        panel_w = (self.eye_cols - 1) * self.pitch + self.dot
        panel_h = (self.eye_rows - 1) * self.pitch + self.dot
        x0 = int(cx - panel_w // 2 + gx)
        y0 = int(cy - panel_h // 2 + gy)

        blink_rows = 4 if closed else 0
        now = ticks_ms()
        blink_rows = max(blink_rows, int(self._blink_level(now) * 4.2))

        dot_size = self.dot + pulse

        # Soft rounded outline made of sparse LEDs. It makes the panels read as
        # small vertical rounded rectangles while keeping the LED-matrix look.
        outline_x = x0 - 3
        outline_y = y0 - 3
        outline_w = panel_w + 6
        outline_h = panel_h + 6
        self.oled.hline(outline_x + 4, outline_y, outline_w - 8, self.fg)
        self.oled.hline(outline_x + 4, outline_y + outline_h, outline_w - 8, self.fg)
        self.oled.vline(outline_x, outline_y + 4, outline_h - 8, self.fg)
        self.oled.vline(outline_x + outline_w, outline_y + 4, outline_h - 8, self.fg)
        self.oled.pixel(outline_x + 2, outline_y + 2, self.fg)
        self.oled.pixel(outline_x + outline_w - 2, outline_y + 2, self.fg)
        self.oled.pixel(outline_x + 2, outline_y + outline_h - 2, self.fg)
        self.oled.pixel(outline_x + outline_w - 2, outline_y + outline_h - 2, self.fg)

        for r in range(self.eye_rows):
            for c in range(self.eye_cols):
                if self._mood_shape(c, r, side, blink_rows):
                    # Gentle LED sparkle: very rare skipped pixels, no moving pupil.
                    if self.mood not in (self.SLEEP, self.LOVE) and ((c * 7 + r * 11 + now // 420) % 67 == 0):
                        continue
                    self._led(x0 + c * self.pitch, y0 + r * self.pitch, dot_size)

        # Tiny cute cheek LEDs for happy/love moods.
        if self.mood in (self.HAPPY, self.LOVE):
            cheek_y = y0 + panel_h + 7
            cheek_x = x0 + (1 if side < 0 else panel_w - 3)
            self._led(cheek_x, cheek_y, 2)

    def _draw_eyes(self):
        now = ticks_ms()

        if self.idle_enabled and ticks_diff(now, self.idle_next) >= 0:
            self.position = self._rand(0, 8)
            self.idle_return_at = now + self._rand(500, 1100)
            self.idle_next = now + self._rand(1700, 4200)

        if self.idle_return_at and ticks_diff(now, self.idle_return_at) >= 0:
            self.position = self.POS_DEFAULT
            self.idle_return_at = 0

        pulse = 0
        if self.pulse_active:
            dt = ticks_diff(now, self.pulse_start)
            if dt >= self.pulse_duration:
                self.pulse_active = False
            else:
                t = dt / float(self.pulse_duration)
                pulse = 1 if math.sin(t * math.pi) > 0.35 else 0

        left_closed = False
        right_closed = False
        if self.wink_active:
            dt = ticks_diff(now, self.wink_start)
            if dt >= self.wink_duration:
                self.wink_active = False
            else:
                phase = math.sin((dt / float(self.wink_duration)) * math.pi)
                if phase > 0.25:
                    if self.wink_side == "L":
                        left_closed = True
                    else:
                        right_closed = True

        if self.confused_active:
            dt = ticks_diff(now, self.confused_start)
            if dt >= self.confused_duration:
                self.confused_active = False
            else:
                # Keep panels fixed; the CONFUSED mood shape creates the animation.
                pass

        self.oled.fill(self.bg)
        panel_w = (self.eye_cols - 1) * self.pitch + self.dot
        left_cx = self.screen_w // 2 - panel_w // 2 - self.base_gap // 2
        right_cx = self.screen_w // 2 + panel_w // 2 + self.base_gap // 2
        self._draw_eye(left_cx, self.center_y, -1, left_closed, pulse)
        self._draw_eye(right_cx, self.center_y, 1, right_closed, pulse)
        self.oled.show()

    # ---------- Mini animations ----------
    def _draw_starfield(self, t_ms):
        for i in range(18):
            x = (i * 23 + t_ms // 22) % self.screen_w
            y = (i * 17 + 11) % self.screen_h
            self.oled.pixel(x, y, self.fg)

    def _anim_sabers(self, t):
        cx = 64
        cy = 34
        swing = math.sin(t * math.pi * 2.0)
        a1 = -0.85 + swing * 0.25
        a2 = -2.25 - swing * 0.25
        l = 42
        self._line_led(cx, cy, cx + math.cos(a1) * l, cy + math.sin(a1) * l, step=4, size=2)
        self._line_led(cx, cy, cx + math.cos(a2) * l, cy + math.sin(a2) * l, step=4, size=2)
        self._line_led(cx, cy, cx - math.cos(a1) * 14, cy - math.sin(a1) * 14, step=4, size=2)
        self._line_led(cx, cy, cx - math.cos(a2) * 14, cy - math.sin(a2) * 14, step=4, size=2)
        self._led(cx - 2, cy - 2, 5)
        if int(t * 12) % 2 == 0:
            self._circle_led(cx, cy, 9, dots=12, size=1)

    def _anim_hyperspace(self, t):
        # Hyperspace-style LED tunnel: stars accelerate from the center outward.
        cx = self.screen_w // 2
        cy = self.screen_h // 2
        phase = t * 2.0

        # A tiny central glow, then many streaking stars radiate outward.
        self._led(cx - 1, cy - 1, 3)
        if int(t * 18) % 2 == 0:
            self.oled.pixel(cx, cy, self.fg)

        for i in range(34):
            angle = (i * 2.399963 + 0.13)  # golden-angle spread
            lane = (i % 7) * 0.13
            p = (phase + lane + (i * 0.037)) % 1.0

            # Ease outward so motion feels like acceleration.
            dist = 2 + (p * p) * 78
            tail = 4 + int(p * 16)

            x = cx + math.cos(angle) * dist
            y = cy + math.sin(angle) * dist * 0.58

            x0 = cx + math.cos(angle) * max(1, dist - tail)
            y0 = cy + math.sin(angle) * max(1, dist - tail) * 0.58

            if 0 <= x < self.screen_w and 0 <= y < self.screen_h:
                self._line_led(x0, y0, x, y, step=5, size=1 if p < 0.72 else 2)

        # A few longer foreground streaks for speed.
        for i in range(10):
            angle = (i * 0.628) + math.sin(t * math.pi * 2) * 0.05
            p = (phase * 1.35 + i * 0.17) % 1.0
            dist = 8 + (p * p) * 88
            x = cx + math.cos(angle) * dist
            y = cy + math.sin(angle) * dist * 0.55
            x0 = cx + math.cos(angle) * max(1, dist - 24)
            y0 = cy + math.sin(angle) * max(1, dist - 24) * 0.55
            self._line_led(x0, y0, x, y, step=4, size=1)

    def _draw_twin_ion(self, x, y, scale=1):
        s = scale
        self.oled.rect(int(x - 15*s), int(y - 10*s), int(7*s), int(20*s), self.fg)
        self.oled.rect(int(x + 8*s), int(y - 10*s), int(7*s), int(20*s), self.fg)
        self.oled.rect(int(x - 4*s), int(y - 4*s), int(8*s), int(8*s), self.fg)
        self.oled.hline(int(x - 8*s), int(y), int(16*s), self.fg)
        self.oled.vline(int(x), int(y - 5*s), int(10*s), self.fg)

    def _anim_twin_ion(self, t):
        self._draw_starfield(int(t * 3000))
        x = -20 + int(t * 168)
        y = 35 + int(math.sin(t * math.pi * 2) * 9)
        self._draw_twin_ion(x, y, 1)
        self._line_led(x - 28, y - 2, x - 50, y - 8, step=8, size=1)
        self._line_led(x - 28, y + 2, x - 50, y + 8, step=8, size=1)

    def _draw_x_fighter(self, x, y, scale=1):
        s = scale
        self.oled.hline(int(x - 15*s), int(y), int(30*s), self.fg)
        self.oled.vline(int(x + 2*s), int(y - 4*s), int(8*s), self.fg)
        self.oled.line(int(x - 8*s), int(y), int(x - 23*s), int(y - 12*s), self.fg)
        self.oled.line(int(x - 8*s), int(y), int(x - 23*s), int(y + 12*s), self.fg)
        self.oled.line(int(x + 8*s), int(y), int(x + 23*s), int(y - 12*s), self.fg)
        self.oled.line(int(x + 8*s), int(y), int(x + 23*s), int(y + 12*s), self.fg)
        self.oled.pixel(int(x + 16*s), int(y), self.fg)

    def _anim_x_fighter(self, t):
        self._draw_starfield(int(t * 2600))
        x = 145 - int(t * 175)
        y = 42 - int(t * 18)
        self._draw_x_fighter(x, y, 1)
        if int(t * 15) % 2 == 0:
            self.oled.pixel(x - 18, y - 9, self.fg)
            self.oled.pixel(x - 18, y + 9, self.fg)

    def _draw_y_fighter(self, x, y, scale=1):
        s = scale
        self.oled.hline(int(x - 17*s), int(y), int(34*s), self.fg)
        self.oled.rect(int(x + 8*s), int(y - 3*s), int(8*s), int(6*s), self.fg)
        self.oled.vline(int(x - 9*s), int(y - 10*s), int(21*s), self.fg)
        self.oled.vline(int(x - 15*s), int(y - 8*s), int(17*s), self.fg)
        self.oled.line(int(x + 16*s), int(y), int(x + 24*s), int(y - 4*s), self.fg)
        self.oled.line(int(x + 16*s), int(y), int(x + 24*s), int(y + 4*s), self.fg)

    def _anim_y_fighter(self, t):
        self._draw_starfield(int(t * 2200))
        x = -20 + int(t * 170)
        y = 45 - int(math.sin(t * math.pi) * 22)
        self._draw_y_fighter(x, y, 1)

    def _draw_small_droid(self, x, y, kind=0):
        if kind == 0:
            # dome droid
            self.oled.rect(x + 2, y + 9, 14, 13, self.fg)
            self.oled.hline(x + 4, y + 7, 10, self.fg)
            self.oled.hline(x + 6, y + 5, 6, self.fg)
            self.oled.pixel(x + 11, y + 11, self.fg)
            self.oled.vline(x + 4, y + 22, 5, self.fg)
            self.oled.vline(x + 14, y + 22, 5, self.fg)
        elif kind == 1:
            # tall protocol-style silhouette, generic
            self.oled.rect(x + 5, y + 4, 8, 9, self.fg)
            self.oled.rect(x + 3, y + 14, 12, 15, self.fg)
            self.oled.line(x + 3, y + 17, x - 1, y + 26, self.fg)
            self.oled.line(x + 15, y + 17, x + 19, y + 26, self.fg)
            self.oled.vline(x + 6, y + 29, 7, self.fg)
            self.oled.vline(x + 12, y + 29, 7, self.fg)
            self.oled.pixel(x + 7, y + 8, self.fg)
            self.oled.pixel(x + 11, y + 8, self.fg)
        else:
            # rolling sphere droid, generic
            self._circle_led(x + 10, y + 21, 9, dots=18, size=1)
            self.oled.rect(x + 6, y + 7, 8, 6, self.fg)
            self.oled.hline(x + 4, y + 14, 13, self.fg)
            self.oled.pixel(x + 11, y + 9, self.fg)

    def _anim_battle_plans(self, t):
        # Cinematic wireframe battle-station plans with a pseudo-3D flythrough.
        # It is inspired by classic film schematics, but rendered as an original
        # monochrome vector animation suitable for the SSD1306 display.
        cx = self.screen_w // 2
        cy = self.screen_h // 2 + 1

        if t < 0.33:
            # Phase 1: reveal a detailed schematic globe with trench and dish.
            p = t / 0.33
            r = 11 + int(17 * self._ease(p))

            self._circle_led(cx, cy, r, dots=34, size=1)
            self._circle_led(cx, cy, max(6, r - 6), dots=24, size=1)

            # Equatorial trench.
            self.oled.hline(cx - int(r * 0.92), cy, int(r * 1.84), self.fg)
            self.oled.hline(cx - int(r * 0.78), cy + 2, int(r * 1.56), self.fg)

            # Latitude hints.
            for frac in (-0.52, -0.22, 0.24, 0.56):
                yy = cy + int(frac * r * 0.78)
                half = int((1.0 - abs(frac) * 0.55) * r * 0.90)
                self.oled.hline(cx - half, yy, half * 2, self.fg)

            # Longitudinal / meridian hints.
            for frac in (-0.55, -0.18, 0.18, 0.55):
                xx = cx + int(frac * r * 0.70)
                top = cy - int(r * 0.80)
                self.oled.vline(xx, top, int(r * 1.60), self.fg)

            # Dish / concavity.
            dx = cx + int(r * 0.38)
            dy = cy - int(r * 0.38)
            self._circle_led(dx, dy, max(3, int(r * 0.17)), dots=12, size=1)
            self.oled.pixel(dx, dy, self.fg)

            # Surface panel grid segments.
            for i in range(6):
                yy = cy - int(r * 0.70) + i * max(3, r // 5)
                span = int(r * (0.58 + ((i + 1) % 2) * 0.15))
                self.oled.hline(cx - span // 2, yy, span, self.fg)

            # Diagonal scan sweep.
            sweep = int((p * 2.0) * r) - r
            self.oled.line(cx - r, cy + sweep // 2, cx + r, cy - sweep // 2, self.fg)
            if int(p * 10) % 2 == 0:
                self.oled.rect(cx - r - 2, cy - r - 2, 2 * r + 4, 2 * r + 4, self.fg)

        elif t < 0.80:
            # Phase 2: pseudo-3D visit through a trench / technical corridor.
            p = (t - 0.33) / 0.47
            vx = cx + int(math.sin(p * math.pi * 1.8) * 6)
            vy = cy - 4

            # Receding wireframe frames for tunnel depth.
            for i in range(10):
                q = (i / 10.0 + p * 1.45) % 1.0
                q2 = q * q
                w = 8 + int(q2 * 116)
                h = 4 + int(q2 * 50)
                x0 = vx - w // 2
                y0 = vy - h // 2
                self.oled.rect(x0, y0, w, h, self.fg)

                # Internal deck / service lines.
                if w > 18:
                    self.oled.hline(x0 + 2, vy, w - 4, self.fg)
                if i % 2 == 0 and h > 10:
                    self.oled.vline(vx, y0 + 2, h - 4, self.fg)

            # Converging guide rails.
            self.oled.line(vx - 3, vy - 2, 4, 8, self.fg)
            self.oled.line(vx + 3, vy - 2, self.screen_w - 5, 8, self.fg)
            self.oled.line(vx - 3, vy + 2, 12, self.screen_h - 9, self.fg)
            self.oled.line(vx + 3, vy + 2, self.screen_w - 13, self.screen_h - 9, self.fg)

            # Side greebles / towers along the trench edges.
            for side in (-1, 1):
                for i in range(7):
                    q = (i / 7.0 + p * 1.8 + (0.11 if side > 0 else 0.0)) % 1.0
                    q2 = q * q
                    x = cx + side * (8 + int(q2 * 48))
                    y = cy + 3 + int(q2 * 20)
                    h = 2 + int(q * 9)
                    self.oled.vline(x, y - h, h, self.fg)
                    if i % 2 == 0:
                        self.oled.pixel(x + side, y - h, self.fg)

            # Racing particles to reinforce forward motion.
            for i in range(14):
                q = (p * 2.1 + i * 0.071) % 1.0
                x = vx + int((q - 0.5) * 110)
                y = vy + int((q * q) * 34)
                self.oled.vline(x, y, 2 + int(q * 5), self.fg)

            # A small highlighted target port appears near the end of the flythrough.
            if p > 0.60:
                s = (p - 0.60) / 0.40
                tw = 4 + int(s * 8)
                th = 2 + int(s * 4)
                ty = cy + 13 + int((1.0 - s) * 6)
                self.oled.rect(cx - tw // 2, ty - th // 2, tw, th, self.fg)
                self.oled.hline(cx - 14, ty, 10, self.fg)
                self.oled.hline(cx + 5, ty, 10, self.fg)

        else:
            # Phase 3: final blueprint lock-on / zoom-out.
            p = (t - 0.80) / 0.20
            s = 1.0 - p
            r = 24 - int(10 * p)

            self._circle_led(cx, cy - 2, r, dots=30, size=1)
            self._circle_led(cx, cy - 2, max(8, r - 8), dots=20, size=1)
            self.oled.hline(cx - int(r * 0.9), cy - 2, int(r * 1.8), self.fg)

            # Layered targeting frames.
            for i in range(4):
                w = 18 + i * 18 + int(8 * s)
                h = 10 + i * 9 + int(5 * s)
                self.oled.rect(cx - w // 2, cy - h // 2, w, h, self.fg)

            # Center lock-on crosshair.
            self.oled.hline(cx - 8, cy - 2, 17, self.fg)
            self.oled.vline(cx, cy - 10, 17, self.fg)
            self._led(cx - 1, cy - 3, 3)

            # Scan / data line.
            scan = int(p * (self.screen_h - 10))
            self.oled.hline(8, 8 + scan, self.screen_w - 16, self.fg)

            # Highlighted port / entry corridor.
            port_y = cy + 15
            self.oled.rect(cx - 7, port_y - 3, 14, 6, self.fg)
            self.oled.rect(cx - 3, port_y - 1, 6, 2, self.fg)
            self.oled.line(cx - 20, cy + 3, cx - 7, port_y, self.fg)
            self.oled.line(cx + 20, cy + 3, cx + 7, port_y, self.fg)

    def _anim_droid_row(self, t):
        bob = int(math.sin(t * math.pi * 4) * 2)
        self._draw_small_droid(18, 22 + bob, 0)
        self._draw_small_droid(54, 16 - bob, 1)
        self._draw_small_droid(94, 22 + bob, 2)
        scan_x = int(t * 128)
        self.oled.vline(scan_x, 12, 48, self.fg)

    def _anim_radar(self, t):
        cx = 64
        cy = 34
        self._circle_led(cx, cy, 10, dots=20, size=1)
        self._circle_led(cx, cy, 20, dots=32, size=1)
        self._circle_led(cx, cy, 29, dots=44, size=1)
        a = t * math.pi * 2.0
        self.oled.line(cx, cy, int(cx + math.cos(a) * 30), int(cy + math.sin(a) * 30), self.fg)
        for px, py in ((38, 26), (76, 18), (89, 46), (51, 51)):
            if int(t * 8 + px) % 3 != 0:
                self._led(px, py, 2)

    def _draw_animation(self, now):
        dt = ticks_diff(now, self.anim_start)
        if dt >= self.anim_duration:
            self.anim_active = False
            self.anim_next = now + self._rand(9000, 17000)
            return False

        t = dt / float(self.anim_duration)
        self.oled.fill(self.bg)

        if self.anim_type == self.ANIM_SABERS:
            self._anim_sabers(t)
        elif self.anim_type == self.ANIM_HYPERSPACE:
            self._anim_hyperspace(t)
        elif self.anim_type == self.ANIM_X_FIGHTER:
            self._anim_hyperspace(t)
        elif self.anim_type == self.ANIM_Y_FIGHTER:
            self._anim_hyperspace(t)
        elif self.anim_type == self.ANIM_BATTLE_PLANS:
            self._anim_battle_plans(t)
        elif self.anim_type == self.ANIM_DROID_ROW:
            self._anim_droid_row(t)
        else:
            self._anim_radar(t)

        self.oled.show()
        return True

    # ---------- Main frame update ----------
    def update(self):
        now = ticks_ms()
        if ticks_diff(now, self.last_frame) < self.frame_interval:
            return
        self.last_frame = now

        if self.anim_active:
            if self._draw_animation(now):
                return

        if self.anim_enabled and ticks_diff(now, self.anim_next) >= 0:
            self.playMiniAnimation()
            self._draw_animation(now)
            return

        self._draw_eyes()
