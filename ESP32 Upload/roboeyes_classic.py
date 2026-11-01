from time import ticks_ms, ticks_diff, ticks_add
from math import sqrt, sin, pi
import urandom


def _clamp(value, low, high):
    return max(low, min(high, value))


def _ease(value):
    value = _clamp(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


def _random(low, high):
    return low + urandom.getrandbits(16) % (high - low + 1)


class ClassicEyes:
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
    POS_N, POS_NE, POS_E, POS_SE = 3, 6, 2, 8
    POS_S, POS_SW, POS_W, POS_NW = 4, 7, 1, 5

    def __init__(self, oled, width=128, height=64, max_fps=30):
        if width < 16 or height < 8 or max_fps <= 0:
            raise ValueError("Invalid eye display dimensions or frame rate")
        self.oled = oled
        self.screen_w, self.screen_h = int(width), int(height)
        self.frame_interval = max(1, int(1000 / max_fps))
        now = ticks_ms()
        self.last_frame = ticks_add(now, -self.frame_interval)
        self.bg, self.fg = 0, 1
        self._width = [34, 34]
        self._height = [34, 34]
        self._radius = [8, 8]
        self._gap = 18
        self._cyclops = False
        self._curiosity = True
        self.mood = self.DEFAULT
        # Shape: left/right width and height, top cuts, smile cuts, lid slopes.
        self._shape = [34., 34., 34., 34., 0., 0., 0., 0., 0., 0.]
        self._source = self._shape[:]
        self._target = self._shape[:]
        self._shape_at, self._shape_ms = now, 0
        self._gaze = [0., 0.]
        self._gaze_source = [0., 0.]
        self._gaze_target = [0., 0.]
        self._gaze_at, self._gaze_ms = now, 360
        self._idle = False
        self._idle_interval, self._idle_variation = 3000, 5000
        self._idle_next = ticks_add(now, 3000)
        self._autoblink = False
        self._blink_interval, self._blink_variation = 3000, 4000
        self._blink_next = ticks_add(now, 3000)
        self._blink_at = None
        self._blink_mask = [True, True]
        self._blink_hold = 35
        self._closed = [False, False]
        self._pulse_at, self._pulse_ms = None, 0
        self._shake_at, self._shake_ms = None, 0
        self._laugh_at, self._laugh_ms = None, 0

    def setDisplayColors(self, bg, fg):
        self.bg, self.fg = int(bool(bg)), int(bool(fg))

    def setWidth(self, left, right=None):
        right = left if right is None else right
        if min(left, right) < 4:
            raise ValueError("Eye width must be at least 4 pixels")
        self._width = [int(left), int(right)]
        self.setMood(self.mood, immediate=True)

    def setHeight(self, left, right=None):
        right = left if right is None else right
        if min(left, right) < 2:
            raise ValueError("Eye height must be at least 2 pixels")
        self._height = [int(left), int(right)]
        self.setMood(self.mood, immediate=True)

    def setBorderradius(self, left, right=None):
        right = left if right is None else right
        if min(left, right) < 0:
            raise ValueError("Eye radius cannot be negative")
        self._radius = [int(left), int(right)]

    def setSpacebetween(self, gap):
        self._gap = int(gap)

    def setCyclops(self, enabled):
        self._cyclops = bool(enabled)

    def setCuriosity(self, enabled):
        self._curiosity = bool(enabled)

    def setAutoblinker(self, enabled=True, interval_s=3, variation_s=4):
        self._autoblink = bool(enabled)
        self._blink_interval = max(100, int(interval_s * 1000))
        self._blink_variation = max(0, int(variation_s * 1000))
        self._schedule_blink(ticks_ms())

    def setIdleMode(self, enabled=True, interval_s=3, variation_s=5):
        self._idle = bool(enabled)
        self._idle_interval = max(200, int(interval_s * 1000))
        self._idle_variation = max(0, int(variation_s * 1000))
        self._schedule_idle(ticks_ms())

    def setPosition(self, position):
        offsets = ((0, 0), (-10, 0), (10, 0), (0, -6), (0, 6),
                   (-10, -6), (10, -6), (-10, 6), (10, 6))
        if not isinstance(position, int) or not 0 <= position < len(offsets):
            raise ValueError("Unknown eye position")
        now = ticks_ms()
        self._advance_gaze(now)
        self._gaze_source[:] = self._gaze
        self._gaze_target[:] = offsets[position]
        self._gaze_at = now

    def setMood(self, mood, transition_ms=700, immediate=False):
        if mood not in (self.DEFAULT, self.HAPPY, self.ANGRY, self.TIRED,
                        self.CURIOUS, self.SAD, self.SLEEP, self.SURPRISED,
                        self.LOVE, self.CONFUSED, self.BORED):
            raise ValueError("Unknown eye mood")
        now = ticks_ms()
        self._advance_shape(now)
        w0, w1 = self._width
        h0, h1 = self._height
        shape = [float(w0), float(h0), float(w1), float(h1),
                 0., 0., 0., 0., 0., 0.]
        if mood in (self.HAPPY, self.LOVE):
            shape[6], shape[7] = h0 * .62, h1 * .62
        elif mood == self.ANGRY:
            shape[4], shape[5] = h0 * .30, h1 * .30
            shape[8], shape[9] = h0 * .23, -h1 * .23
        elif mood == self.TIRED:
            shape[4], shape[5] = h0 * .52, h1 * .52
        elif mood == self.CURIOUS:
            shape[1], shape[3] = h0 * .72, h1 * 1.16
            shape[0], shape[2] = w0 * .88, w1 * 1.04
        elif mood == self.SAD:
            shape[4], shape[5] = h0 * .25, h1 * .25
            shape[8], shape[9] = -h0 * .20, h1 * .20
        elif mood == self.SLEEP:
            shape[1], shape[3] = 4., 4.
        elif mood == self.SURPRISED:
            shape[0], shape[2] = w0 * 1.06, w1 * 1.06
            shape[1], shape[3] = h0 * 1.22, h1 * 1.22
        elif mood == self.CONFUSED:
            shape[1], shape[3] = h0 * 1.12, h1 * .64
        elif mood == self.BORED:
            shape[4], shape[5] = h0 * .38, h1 * .38
        self.mood = mood
        self._source[:] = self._shape
        self._target[:] = shape
        self._shape_at = now
        self._shape_ms = 0 if immediate else max(0, int(transition_ms))
        if self._shape_ms == 0:
            self._shape[:] = shape

    def blink(self, left=1, right=1, hold_ms=35):
        self._blink_at = ticks_ms()
        self._blink_mask[:] = [bool(left), bool(right)]
        self._blink_hold = max(0, int(hold_ms))

    def wink(self, which="R", hold_ms=250):
        side = which.upper()
        if side not in ("L", "R"):
            raise ValueError("Wink side must be L or R")
        self.blink(left=side == "L", right=side == "R", hold_ms=hold_ms)

    def close(self, left=1, right=1):
        if left:
            self._closed[0] = True
        if right:
            self._closed[1] = True

    def open(self, left=1, right=1):
        if left:
            self._closed[0] = False
        if right:
            self._closed[1] = False

    def pulse(self, duration_ms=850):
        self._pulse_at, self._pulse_ms = ticks_ms(), max(1, int(duration_ms))

    def confused(self, duration_ms=900):
        self._shake_at, self._shake_ms = ticks_ms(), max(1, int(duration_ms))

    def laugh(self, duration_ms=900):
        self._laugh_at, self._laugh_ms = ticks_ms(), max(1, int(duration_ms))

    def anim_confused(self):
        self.confused()

    def anim_laugh(self):
        self.laugh()

    def _schedule_blink(self, now):
        self._blink_next = ticks_add(now, self._blink_interval + _random(0, self._blink_variation))

    def _schedule_idle(self, now):
        self._idle_next = ticks_add(now, self._idle_interval + _random(0, self._idle_variation))

    def _advance_shape(self, now):
        duration = self._shape_ms
        t = 1. if duration == 0 else _ease(ticks_diff(now, self._shape_at) / duration)
        for i in range(len(self._shape)):
            self._shape[i] = self._source[i] + (self._target[i] - self._source[i]) * t

    def _advance_gaze(self, now):
        t = _ease(ticks_diff(now, self._gaze_at) / self._gaze_ms)
        for i in (0, 1):
            self._gaze[i] = self._gaze_source[i] + (self._gaze_target[i] - self._gaze_source[i]) * t

    def _blink_factor(self, now):
        if self._blink_at is None:
            return 1.
        elapsed = ticks_diff(now, self._blink_at)
        if elapsed < 80:
            return 1. - _ease(elapsed / 80.)
        if elapsed < 80 + self._blink_hold:
            return 0.
        if elapsed < 230 + self._blink_hold:
            return _ease((elapsed - 80 - self._blink_hold) / 150.)
        self._blink_at = None
        self._schedule_blink(now)
        return 1.

    def update(self):
        now = ticks_ms()
        if ticks_diff(now, self.last_frame) < self.frame_interval:
            return
        self.last_frame = now
        self._render(now)

    def drawEyes(self):
        now = ticks_ms()
        self.last_frame = now
        self._render(now)

    def _render(self, now):
        self._advance_shape(now)
        self._advance_gaze(now)
        if self._idle and self.mood != self.SLEEP and ticks_diff(now, self._idle_next) >= 0:
            self.setPosition(_random(0, 8))
            self._schedule_idle(now)
        if self._autoblink and self.mood != self.SLEEP and self._blink_at is None:
            if ticks_diff(now, self._blink_next) >= 0:
                self.blink()
        blink = self._blink_factor(now)
        dx, dy = self._gaze
        pulse = 0.
        if self._pulse_at is not None:
            elapsed = ticks_diff(now, self._pulse_at)
            if elapsed >= self._pulse_ms:
                self._pulse_at = None
            else:
                pulse = 3. * sin(pi * elapsed / self._pulse_ms)
        if self._shake_at is not None:
            elapsed = ticks_diff(now, self._shake_at)
            if elapsed >= self._shake_ms:
                self._shake_at = None
            else:
                dx += 2. * sin(elapsed * .055)
        if self._laugh_at is not None:
            elapsed = ticks_diff(now, self._laugh_at)
            if elapsed >= self._laugh_ms:
                self._laugh_at = None
            else:
                dy += 2. * sin(elapsed * .055)
        w0, h0, w1, h1 = self._shape[:4]
        w0, w1 = max(4, int(w0 + pulse)), max(4, int(w1 + pulse))
        h0, h1 = h0 + pulse, h1 + pulse
        if self._curiosity and self.mood != self.SLEEP:
            if dx < -5:
                h0 += min(4., (-dx - 5.) * .7)
            elif dx > 5:
                h1 += min(4., (dx - 5.) * .7)
        # All animation effects modify only this frame, never the base geometry.
        f0 = 0. if self._closed[0] else blink if self._blink_mask[0] else 1.
        f1 = 0. if self._closed[1] else blink if self._blink_mask[1] else 1.
        h0, h1 = max(2, int(2 + (h0 - 2) * f0)), max(2, int(2 + (h1 - 2) * f1))
        cy = int(self.screen_h / 2 + dy)
        self.oled.fill(self.bg)
        if self._cyclops:
            x0 = int(_clamp(self.screen_w / 2 + dx - w0 / 2, 0, max(0, self.screen_w - w0)))
            self._eye(x0, cy, w0, h0, 0, f0)
        else:
            total = w0 + self._gap + w1
            x0 = int(_clamp((self.screen_w - total) / 2 + dx, 0, max(0, self.screen_w - total)))
            self._eye(x0, cy, w0, h0, 0, f0)
            self._eye(x0 + w0 + self._gap, cy, w1, h1, 1, f1)
        self.oled.show()

    def _eye(self, x, cy, width, height, side, opening):
        # Draw clipped scanlines; no Adafruit GFX or extra framebuffer.
        y = int(_clamp(cy - height / 2, 0, max(0, self.screen_h - height)))
        radius = min(self._radius[side], width // 2, height // 2)
        top = self._shape[4 + side] * opening
        smile = self._shape[6 + side] * opening
        slope = self._shape[8 + side] * opening
        for row in range(height):
            yy = y + row
            if yy < 0 or yy >= self.screen_h:
                continue
            inset = 0
            if radius:
                corner_y = max(radius - row - .5, row - (height - radius) + .5, 0.)
                if corner_y:
                    inset = max(0, int(radius - sqrt(max(0., radius * radius - corner_y * corner_y)) + .5))
            left = max(0, x + inset)
            right = min(self.screen_w - 1, x + width - 1 - inset)
            # Intersect the row with a sloping upper lid and curved smile cut.
            if slope:
                boundary = (row - top) / slope
                if slope > 0:
                    right = min(right, int(x + (boundary + 1.) * (width - 1) / 2))
                else:
                    left = max(left, int(x + (boundary + 1.) * (width - 1) / 2 + .999))
            elif row < top:
                continue
            if left > right:
                continue
            if smile > 0 and row > height - 1 - smile:
                # The central lower cut leaves two connected crescent-like arcs.
                vertical = (height - 1 - row) / smile
                edge = sqrt(max(0., 1. - vertical * vertical)) * (width - 1) / 2
                center = x + (width - 1) / 2
                self._span(left, min(right, int(center - edge)), yy)
                self._span(max(left, int(center + edge + .999)), right, yy)
            else:
                self._span(left, right, yy)

    def _span(self, left, right, y):
        left, right = max(0, left), min(self.screen_w - 1, right)
        if left <= right and 0 <= y < self.screen_h:
            self.oled.hline(left, y, right - left + 1, self.fg)
