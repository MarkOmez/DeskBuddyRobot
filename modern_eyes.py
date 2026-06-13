# modern_eyes.py
# Cartoon/RoboEyes-style robot eyes for SSD1306 128x64 in MicroPython.
# Compatible API: setMood(), setPosition(), wink(), pulse(), update(),
# setAutoblinker(), and setIdleMode().

from time import ticks_ms, ticks_diff
import urandom
import math


class ModernEyes:
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

    def __init__(self, oled, width=128, height=64, max_fps=45):
        self.oled = oled
        self.screen_w = width
        self.screen_h = height

        self.frame_interval = int(1000 / max_fps)
        self.last_frame = ticks_ms()

        self.bg = 0
        self.fg = 1

        # Cartoon/RoboEyes-like geometry
        self.base_eye_w = 34
        self.base_eye_h = 34
        self.base_gap = 14
        self.base_radius = 10
        self.center_y = 34

        # Current state
        self.cur_w_l = self.base_eye_w
        self.cur_w_r = self.base_eye_w
        self.cur_h_l = self.base_eye_h
        self.cur_h_r = self.base_eye_h

        self.cur_lid_top_l = 0
        self.cur_lid_top_r = 0
        self.cur_lid_bottom_l = 0
        self.cur_lid_bottom_r = 0

        self.cur_slant_l = 0
        self.cur_slant_r = 0

        self.cur_eye_offset_x = 0
        self.cur_eye_offset_y = 0
        self.cur_pupil_x = 0
        self.cur_pupil_y = 0

        # Target
        self.tgt_w_l = self.base_eye_w
        self.tgt_w_r = self.base_eye_w
        self.tgt_h_l = self.base_eye_h
        self.tgt_h_r = self.base_eye_h

        self.tgt_lid_top_l = 0
        self.tgt_lid_top_r = 0
        self.tgt_lid_bottom_l = 0
        self.tgt_lid_bottom_r = 0

        self.tgt_slant_l = 0
        self.tgt_slant_r = 0

        self.tgt_eye_offset_x = 0
        self.tgt_eye_offset_y = 0
        self.tgt_pupil_x = 0
        self.tgt_pupil_y = 0

        # Global transition speed. Lower values are smoother/slower.
        self.motion_speed = 0.075

        self.mood = self.DEFAULT
        self.position = self.POS_DEFAULT

        # Natural blinking
        self.blink_enabled = True
        self.blinking = False
        self.blink_next = ticks_ms() + self._rand(1800, 5200)
        self.blink_start = 0
        self.blink_close_ms = 95
        self.blink_hold_ms = 35
        self.blink_open_ms = 130

        # Curious idle behavior
        self.idle_enabled = True
        self.idle_next = ticks_ms() + self._rand(1800, 4200)
        self.idle_return_at = 0

        # Organic micro movement
        self.micro_enabled = True
        self.micro_phase_x = self._rand(0, 628) / 100.0
        self.micro_phase_y = self._rand(0, 628) / 100.0

        # Saccades: small gaze jumps
        self.saccade_next = ticks_ms() + self._rand(900, 2600)
        self.saccade_until = 0
        self.saccade_x = 0
        self.saccade_y = 0

        # Reactions
        self.wink_active = False
        self.wink_side = "R"
        self.wink_start = 0
        self.wink_duration = 650

        self.pulse_active = False
        self.pulse_start = 0
        self.pulse_duration = 900

        self.confused_active = False
        self.confused_start = 0
        self.confused_duration = 900

        self.laugh_active = False
        self.laugh_start = 0
        self.laugh_duration = 900

        self.setMood(self.DEFAULT, immediate=True)

    # Utilities
    def _rand(self, a, b):
        return a + (urandom.getrandbits(16) % (b - a + 1))

    def _ease(self, t):
        if t < 0:
            t = 0
        if t > 1:
            t = 1
        return t * t * (3 - 2 * t)

    def _approach(self, cur, tgt, speed):
        return cur + (tgt - cur) * speed

    def _clamp(self, v, a, b):
        if v < a:
            return a
        if v > b:
            return b
        return v

    # Compatible API
    def setDisplayColors(self, bg, fg):
        self.bg = bg
        self.fg = fg

    def setWidth(self, left, right):
        self.base_eye_w = left
        self.tgt_w_l = left
        self.tgt_w_r = right

    def setHeight(self, left, right):
        self.base_eye_h = left
        self.tgt_h_l = left
        self.tgt_h_r = right

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

        # transition_ms is converted into a smooth speed. Higher values are slower.
        if transition_ms <= 0:
            self.motion_speed = 1.0
        else:
            self.motion_speed = self._clamp(70.0 / transition_ms, 0.045, 0.16)

        # Reset base target
        self.tgt_w_l = self.base_eye_w
        self.tgt_w_r = self.base_eye_w
        self.tgt_h_l = self.base_eye_h
        self.tgt_h_r = self.base_eye_h

        self.tgt_lid_top_l = 0
        self.tgt_lid_top_r = 0
        self.tgt_lid_bottom_l = 0
        self.tgt_lid_bottom_r = 0

        self.tgt_slant_l = 0
        self.tgt_slant_r = 0

        # Cartoon expressions
        if mood == self.DEFAULT:
            pass

        elif mood == self.HAPPY:
            self.tgt_h_l = self.base_eye_h - 5
            self.tgt_h_r = self.base_eye_h - 5
            self.tgt_lid_bottom_l = 12
            self.tgt_lid_bottom_r = 12
            self.tgt_slant_l = 2
            self.tgt_slant_r = -2

        elif mood == self.ANGRY:
            self.tgt_lid_top_l = 10
            self.tgt_lid_top_r = 10
            self.tgt_slant_l = -11
            self.tgt_slant_r = 11
            self.tgt_h_l = self.base_eye_h - 2
            self.tgt_h_r = self.base_eye_h - 2

        elif mood == self.TIRED:
            self.tgt_h_l = self.base_eye_h - 9
            self.tgt_h_r = self.base_eye_h - 9
            self.tgt_lid_top_l = 14
            self.tgt_lid_top_r = 14
            self.tgt_lid_bottom_l = 2
            self.tgt_lid_bottom_r = 2

        elif mood == self.CURIOUS:
            # One eye wider and the other narrower, o_O style
            self.tgt_w_l = self.base_eye_w + 5
            self.tgt_h_l = self.base_eye_h + 4
            self.tgt_w_r = self.base_eye_w - 6
            self.tgt_h_r = self.base_eye_h - 6
            self.tgt_lid_top_r = 5

        elif mood == self.SAD:
            self.tgt_lid_top_l = 7
            self.tgt_lid_top_r = 7
            self.tgt_slant_l = 9
            self.tgt_slant_r = -9
            self.tgt_h_l = self.base_eye_h - 3
            self.tgt_h_r = self.base_eye_h - 3

        elif mood == self.SLEEP:
            self.tgt_h_l = 8
            self.tgt_h_r = 8
            self.tgt_lid_top_l = 18
            self.tgt_lid_top_r = 18
            self.tgt_lid_bottom_l = 7
            self.tgt_lid_bottom_r = 7

        elif mood == self.SURPRISED:
            self.tgt_w_l = self.base_eye_w + 8
            self.tgt_w_r = self.base_eye_w + 8
            self.tgt_h_l = self.base_eye_h + 10
            self.tgt_h_r = self.base_eye_h + 10

        elif mood == self.LOVE:
            self.tgt_h_l = self.base_eye_h - 2
            self.tgt_h_r = self.base_eye_h - 2
            self.tgt_lid_bottom_l = 5
            self.tgt_lid_bottom_r = 5

        elif mood == self.CONFUSED:
            self.tgt_w_l = self.base_eye_w - 4
            self.tgt_w_r = self.base_eye_w + 6
            self.tgt_h_l = self.base_eye_h + 3
            self.tgt_h_r = self.base_eye_h - 4
            self.tgt_slant_l = 6
            self.tgt_slant_r = 6
            self.confused()

        elif mood == self.BORED:
            self.tgt_h_l = self.base_eye_h - 12
            self.tgt_h_r = self.base_eye_h - 12
            self.tgt_lid_top_l = 16
            self.tgt_lid_top_r = 16

        if immediate:
            self.cur_w_l = self.tgt_w_l
            self.cur_w_r = self.tgt_w_r
            self.cur_h_l = self.tgt_h_l
            self.cur_h_r = self.tgt_h_r

            self.cur_lid_top_l = self.tgt_lid_top_l
            self.cur_lid_top_r = self.tgt_lid_top_r
            self.cur_lid_bottom_l = self.tgt_lid_bottom_l
            self.cur_lid_bottom_r = self.tgt_lid_bottom_r

            self.cur_slant_l = self.tgt_slant_l
            self.cur_slant_r = self.tgt_slant_r

    def setPosition(self, pos):
        self.position = pos

        x = 0
        y = 0

        if pos == self.POS_LEFT:
            x = -8
        elif pos == self.POS_RIGHT:
            x = 8
        elif pos == self.POS_UP:
            y = -5
        elif pos == self.POS_DOWN:
            y = 5
        elif pos == self.POS_UP_LEFT:
            x = -7
            y = -4
        elif pos == self.POS_UP_RIGHT:
            x = 7
            y = -4
        elif pos == self.POS_DOWN_LEFT:
            x = -7
            y = 4
        elif pos == self.POS_DOWN_RIGHT:
            x = 7
            y = 4

        self.tgt_pupil_x = x
        self.tgt_pupil_y = y

        # Slightly move the whole eye group for a less static cartoon effect.
        self.tgt_eye_offset_x = int(x * 0.35)
        self.tgt_eye_offset_y = int(y * 0.35)

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

    def laugh(self, duration_ms=900):
        self.laugh_active = True
        self.laugh_start = ticks_ms()
        self.laugh_duration = duration_ms

    # Drawing primitives
    def _rounded_rect(self, x, y, w, h, r, col):
        x = int(x)
        y = int(y)
        w = int(w)
        h = int(h)

        if w <= 0 or h <= 0:
            return

        r = int(min(r, w // 2, h // 2))
        if r < 1:
            self.oled.fill_rect(x, y, w, h, col)
            return

        self.oled.fill_rect(x + r, y, w - 2 * r, h, col)
        self.oled.fill_rect(x, y + r, w, h - 2 * r, col)

        rr = r * r

        for yy in range(-r, r + 1):
            dx = int((rr - yy * yy) ** 0.5)

            # left top/bottom
            self.oled.hline(x + r - dx, y + r + yy, dx + 1, col)
            self.oled.hline(x + r - dx, y + h - r + yy, dx + 1, col)

            # right top/bottom
            self.oled.hline(x + w - r, y + r + yy, dx + 1, col)
            self.oled.hline(x + w - r, y + h - r + yy, dx + 1, col)

    def _fill_circle(self, cx, cy, r, col):
        cx = int(cx)
        cy = int(cy)
        r = int(r)

        if r <= 0:
            return

        rr = r * r

        for yy in range(-r, r + 1):
            dx = int((rr - yy * yy) ** 0.5)
            self.oled.hline(cx - dx, cy + yy, dx * 2 + 1, col)

    def _erase_top_lid(self, x, y, w, lid, slant, is_left):
        if lid <= 0 and slant == 0:
            return

        top = int(y)
        max_h = int(abs(slant) + lid + 4)

        for i in range(max_h):
            t = i / max(1, max_h)

            if is_left:
                left_y = lid + max(0, -slant)
                right_y = lid + max(0, slant)
            else:
                left_y = lid + max(0, slant)
                right_y = lid + max(0, -slant)

            cut_left = int(y + left_y * t)
            cut_right = int(y + right_y * t)

            yy = y + i

            # Approximate upper eyelid fill; works well on small OLEDs.
            if yy <= max(cut_left, cut_right):
                self.oled.hline(int(x), int(yy), int(w), self.bg)

        # Diagonal white eyebrow/eyelid line
        if lid > 2 or slant != 0:
            if is_left:
                x1 = int(x + 2)
                y1 = int(y + lid + max(0, -slant))
                x2 = int(x + w - 2)
                y2 = int(y + lid + max(0, slant))
            else:
                x1 = int(x + 2)
                y1 = int(y + lid + max(0, slant))
                x2 = int(x + w - 2)
                y2 = int(y + lid + max(0, -slant))

            self.oled.line(x1, y1, x2, y2, self.fg)

    def _erase_bottom_lid(self, x, y, w, h, lid):
        if lid <= 0:
            return

        yy = int(y + h - lid)
        self.oled.fill_rect(int(x), yy, int(w), int(lid) + 2, self.bg)

        # Simplified curved white line
        self.oled.hline(int(x + 4), yy, int(w - 8), self.fg)

    def _draw_pupil_cutout(self, cx, cy, px, py, mood):
        # Negative pupil, comic style on a white eye.
        if mood == self.SLEEP:
            return

        if mood == self.LOVE:
            self._draw_heart_cutout(cx + px, cy + py)
            return

        if mood == self.SURPRISED:
            self._fill_circle(cx + px, cy + py, 5, self.bg)
            self.oled.pixel(int(cx + px - 2), int(cy + py - 2), self.fg)
            return

        self._rounded_rect(cx + px - 4, cy + py - 6, 8, 12, 3, self.bg)

        # Small internal highlight
        self.oled.pixel(int(cx + px - 1), int(cy + py - 3), self.fg)
        self.oled.pixel(int(cx + px), int(cy + py - 3), self.fg)

    def _draw_heart_cutout(self, cx, cy):
        cx = int(cx)
        cy = int(cy)

        # Small black heart inside the white eye.
        pts = [
            (0, -3),
            (-3, -6),
            (-6, -3),
            (-5, 1),
            (0, 6),
            (5, 1),
            (6, -3),
            (3, -6),
        ]

        # Simplified filled pixel/line version
        self.oled.hline(cx - 3, cy - 4, 3, self.bg)
        self.oled.hline(cx + 1, cy - 4, 3, self.bg)
        self.oled.hline(cx - 5, cy - 3, 11, self.bg)
        self.oled.hline(cx - 6, cy - 2, 13, self.bg)
        self.oled.hline(cx - 5, cy - 1, 11, self.bg)
        self.oled.hline(cx - 4, cy, 9, self.bg)
        self.oled.hline(cx - 3, cy + 1, 7, self.bg)
        self.oled.hline(cx - 2, cy + 2, 5, self.bg)
        self.oled.hline(cx - 1, cy + 3, 3, self.bg)
        self.oled.pixel(cx, cy + 4, self.bg)

    def _draw_brow(self, cx, cy, w, mood, is_left):
        # Cartoon eyebrows make expressions easier to read.
        y = int(cy - 27)
        half = int(w / 2)

        if mood == self.ANGRY:
            if is_left:
                self.oled.line(cx - half + 2, y + 2, cx + half - 2, y - 5, self.fg)
                self.oled.line(cx - half + 2, y + 3, cx + half - 2, y - 4, self.fg)
            else:
                self.oled.line(cx - half + 2, y - 5, cx + half - 2, y + 2, self.fg)
                self.oled.line(cx - half + 2, y - 4, cx + half - 2, y + 3, self.fg)

        elif mood == self.SAD:
            if is_left:
                self.oled.line(cx - half + 2, y - 4, cx + half - 2, y + 2, self.fg)
            else:
                self.oled.line(cx - half + 2, y + 2, cx + half - 2, y - 4, self.fg)

        elif mood == self.CURIOUS:
            if is_left:
                self.oled.line(cx - half + 4, y - 3, cx + half - 4, y - 7, self.fg)
            else:
                self.oled.line(cx - half + 4, y + 2, cx + half - 4, y + 1, self.fg)

        elif mood == self.TIRED or mood == self.BORED:
            self.oled.line(cx - half + 2, y + 2, cx + half - 2, y + 1, self.fg)

        elif mood == self.SURPRISED:
            self.oled.line(cx - half + 5, y - 6, cx + half - 5, y - 6, self.fg)

    def _draw_eye(self, cx, cy, w, h, lid_top, lid_bottom, slant, px, py, is_left):
        x = int(cx - w / 2)
        y = int(cy - h / 2)

        # Eye body: filled capsule
        r = min(self.base_radius, int(w / 3), int(h / 2))
        self._rounded_rect(x, y, int(w), int(h), r, self.fg)

        # Black eyelids cut into the shape
        self._erase_top_lid(x, y, int(w), int(lid_top), int(slant), is_left)
        self._erase_bottom_lid(x, y, int(w), int(h), int(lid_bottom))

        # Pupil / cutout
        self._draw_pupil_cutout(int(cx), int(cy), int(px), int(py), self.mood)

        # Lower edge / comic-style shine
        if self.mood not in (self.SLEEP,):
            self.oled.pixel(x + int(w * 0.22), y + int(h * 0.78), self.bg)
            self.oled.pixel(x + int(w * 0.22) + 1, y + int(h * 0.78), self.bg)

    def _draw_sleep_marks(self):
        self.oled.text("z", 93, 11, self.fg)
        self.oled.text("Z", 104, 3, self.fg)

    def _draw_sweat_drop(self):
        # Cartoon drop for confused/tired expressions
        x = 103
        y = 19
        self.oled.pixel(x + 2, y, self.fg)
        self.oled.hline(x + 1, y + 1, 3, self.fg)
        self.oled.hline(x, y + 2, 5, self.fg)
        self.oled.hline(x, y + 3, 5, self.fg)
        self.oled.hline(x + 1, y + 4, 3, self.fg)
        self.oled.pixel(x + 2, y + 5, self.fg)

    # Animation updates
    def _update_blink(self, now):
        if not self.blink_enabled:
            return 0

        if not self.blinking and ticks_diff(now, self.blink_next) >= 0:
            self.blinking = True
            self.blink_start = now

        if not self.blinking:
            return 0

        elapsed = ticks_diff(now, self.blink_start)
        close_ms = self.blink_close_ms
        hold_ms = self.blink_hold_ms
        open_ms = self.blink_open_ms
        total = close_ms + hold_ms + open_ms

        if elapsed < close_ms:
            f = elapsed / close_ms
        elif elapsed < close_ms + hold_ms:
            f = 1
        elif elapsed < total:
            f = 1 - ((elapsed - close_ms - hold_ms) / open_ms)
        else:
            self.blinking = False
            self.blink_next = now + self._rand(2300, 6500)
            f = 0

        return self._ease(f)

    def _update_idle(self, now):
        if not self.idle_enabled:
            return

        if ticks_diff(now, self.idle_next) >= 0:
            positions = [
                self.POS_LEFT,
                self.POS_RIGHT,
                self.POS_UP_LEFT,
                self.POS_UP_RIGHT,
                self.POS_DOWN_LEFT,
                self.POS_DOWN_RIGHT,
                self.POS_DEFAULT,
            ]

            self.setPosition(positions[self._rand(0, len(positions) - 1)])

            self.idle_return_at = now + self._rand(850, 1800)
            self.idle_next = now + self._rand(2600, 6500)

        if self.idle_return_at and ticks_diff(now, self.idle_return_at) >= 0:
            self.setPosition(self.POS_DEFAULT)
            self.idle_return_at = 0

    def _update_saccade(self, now):
        if ticks_diff(now, self.saccade_next) >= 0:
            self.saccade_x = self._rand(-2, 2)
            self.saccade_y = self._rand(-1, 1)
            self.saccade_until = now + self._rand(80, 170)
            self.saccade_next = now + self._rand(1000, 3000)

        if ticks_diff(now, self.saccade_until) > 0:
            return self.saccade_x, self.saccade_y

        return 0, 0

    def _reaction_offsets(self, now):
        ox = 0
        oy = 0

        if self.confused_active:
            elapsed = ticks_diff(now, self.confused_start)

            if elapsed >= self.confused_duration:
                self.confused_active = False
            else:
                ox += int(math.sin(elapsed / 38.0) * 4)

        if self.laugh_active:
            elapsed = ticks_diff(now, self.laugh_start)

            if elapsed >= self.laugh_duration:
                self.laugh_active = False
            else:
                oy += int(math.sin(elapsed / 45.0) * 3)

        return ox, oy

    # Main update
    def update(self):
        now = ticks_ms()

        if ticks_diff(now, self.last_frame) < self.frame_interval:
            return

        self.last_frame = now

        self._update_idle(now)
        blink = self._update_blink(now)
        sx, sy = self._update_saccade(now)
        rx, ry = self._reaction_offsets(now)

        # Smooth micro movement
        t = now / 1000.0
        mx = math.sin(t * 1.55 + self.micro_phase_x) * 1.1 if self.micro_enabled else 0
        my = math.sin(t * 1.05 + self.micro_phase_y) * 0.7 if self.micro_enabled else 0

        sp = self.motion_speed

        self.cur_w_l = self._approach(self.cur_w_l, self.tgt_w_l, sp)
        self.cur_w_r = self._approach(self.cur_w_r, self.tgt_w_r, sp)
        self.cur_h_l = self._approach(self.cur_h_l, self.tgt_h_l, sp)
        self.cur_h_r = self._approach(self.cur_h_r, self.tgt_h_r, sp)

        self.cur_lid_top_l = self._approach(self.cur_lid_top_l, self.tgt_lid_top_l, sp)
        self.cur_lid_top_r = self._approach(self.cur_lid_top_r, self.tgt_lid_top_r, sp)
        self.cur_lid_bottom_l = self._approach(self.cur_lid_bottom_l, self.tgt_lid_bottom_l, sp)
        self.cur_lid_bottom_r = self._approach(self.cur_lid_bottom_r, self.tgt_lid_bottom_r, sp)

        self.cur_slant_l = self._approach(self.cur_slant_l, self.tgt_slant_l, sp)
        self.cur_slant_r = self._approach(self.cur_slant_r, self.tgt_slant_r, sp)

        self.cur_eye_offset_x = self._approach(self.cur_eye_offset_x, self.tgt_eye_offset_x, sp)
        self.cur_eye_offset_y = self._approach(self.cur_eye_offset_y, self.tgt_eye_offset_y, sp)

        self.cur_pupil_x = self._approach(self.cur_pupil_x, self.tgt_pupil_x, sp)
        self.cur_pupil_y = self._approach(self.cur_pupil_y, self.tgt_pupil_y, sp)

        # Wink
        wink_l = 0
        wink_r = 0

        if self.wink_active:
            elapsed = ticks_diff(now, self.wink_start)

            if elapsed >= self.wink_duration:
                self.wink_active = False
            else:
                phase = elapsed / self.wink_duration

                if phase < 0.5:
                    wf = self._ease(phase * 2)
                else:
                    wf = self._ease((1 - phase) * 2)

                if self.wink_side == "L":
                    wink_l = wf
                else:
                    wink_r = wf

        # Pulse
        pulse = 0

        if self.pulse_active:
            elapsed = ticks_diff(now, self.pulse_start)

            if elapsed >= self.pulse_duration:
                self.pulse_active = False
            else:
                phase = elapsed / self.pulse_duration
                pulse = math.sin(phase * math.pi) * 4

        # Final dimensions
        w_l = self.cur_w_l + pulse
        w_r = self.cur_w_r + pulse
        h_l = self.cur_h_l + pulse
        h_r = self.cur_h_r + pulse

        # Blink closes both eyes
        h_l = max(5, h_l * (1 - blink * 0.84))
        h_r = max(5, h_r * (1 - blink * 0.84))

        # Wink closes one eye
        h_l = max(5, h_l * (1 - wink_l * 0.9))
        h_r = max(5, h_r * (1 - wink_r * 0.9))

        total_w = w_l + w_r + self.base_gap
        base_lx = int((self.screen_w - total_w) / 2 + w_l / 2)
        base_rx = int(base_lx + w_l / 2 + self.base_gap + w_r / 2)

        ox = int(self.cur_eye_offset_x + rx)
        oy = int(self.cur_eye_offset_y + ry)

        lx = base_lx + ox
        rx_c = base_rx + ox
        cy = self.center_y + oy + my

        px = self.cur_pupil_x + mx + sx
        py = self.cur_pupil_y + sy

        self.oled.fill(self.bg)

        # Draw eyebrows before eyes
        self._draw_brow(lx, int(cy), int(w_l), self.mood, True)
        self._draw_brow(rx_c, int(cy), int(w_r), self.mood, False)

        self._draw_eye(
            lx,
            cy,
            int(w_l),
            int(h_l),
            int(self.cur_lid_top_l),
            int(self.cur_lid_bottom_l),
            int(self.cur_slant_l),
            int(px),
            int(py),
            True
        )

        self._draw_eye(
            rx_c,
            cy,
            int(w_r),
            int(h_r),
            int(self.cur_lid_top_r),
            int(self.cur_lid_bottom_r),
            int(self.cur_slant_r),
            int(px),
            int(py),
            False
        )

        if self.mood == self.SLEEP:
            self._draw_sleep_marks()

        if self.mood in (self.CONFUSED, self.TIRED, self.BORED):
            self._draw_sweat_drop()

        self.oled.show()