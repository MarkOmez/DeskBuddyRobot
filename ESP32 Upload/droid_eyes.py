"""Mechanical droid optics and original space-opera display sequences.

Requires roboeyes_classic.py and the existing SSD1306-compatible framebuffer.
"""

from time import ticks_ms, ticks_diff
from math import sin, cos, sqrt, pi
import urandom
from roboeyes_classic import ClassicEyes, _clamp

# Reuse circle vertices so blueprint frames avoid repeated trigonometry.
_ARC = tuple((cos(i * 2. * pi / 24), sin(i * 2. * pi / 24)) for i in range(1, 25))


class DroidEyes(ClassicEyes):
    def __init__(self, oled, width=128, height=64, max_fps=25):
        super().__init__(oled, width, height, max_fps=min(max_fps, 25))
        self._scene = None
        self._scene_at = 0
        self._scene_ms = 0
        # Cache direction vectors once, rather than allocating stars each frame.
        self._stars = []
        for _ in range(32):
            angle = (urandom.getrandbits(16) / 65536.) * 2. * pi
            self._stars.append((cos(angle), sin(angle), urandom.getrandbits(8)))

    def _start_scene(self, name, duration_ms):
        if duration_ms <= 0:
            raise ValueError("Scene duration must be positive")
        self._scene = name
        self._scene_at = ticks_ms()
        self._scene_ms = int(duration_ms)

    def hyperspace(self, duration_ms=3200):
        self._start_scene("HYPERSPACE", duration_ms)

    def station_plans(self, duration_ms=3800):
        self._start_scene("STATION PLANS", duration_ms)

    def trench_run(self, duration_ms=3200):
        self._start_scene("TRENCH RUN", duration_ms)

    def cancel_scene(self):
        self._scene = None

    def scene_active(self):
        return self._scene is not None

    def _render(self, now):
        if self._scene is None:
            super()._render(now)
            return
        elapsed = ticks_diff(now, self._scene_at)
        if elapsed >= self._scene_ms:
            self._scene = None
            super()._render(now)
            return
        progress = max(0., elapsed / self._scene_ms)
        self.oled.fill(self.bg)
        if self._scene == "HYPERSPACE":
            self._hyperspace(elapsed, progress)
        elif self._scene == "STATION PLANS":
            self._station_plans(elapsed, progress)
        else:
            self._trench_run(elapsed, progress)
        self.oled.show()

    def _eye(self, x, cy, width, height, side, opening):
        # A chamfered housing surrounds an aperture, concentric rings and an iris.
        # Every segment is intersected with the current expression's eyelids.
        y = int(_clamp(cy - height / 2, 0, max(0, self.screen_h - height)))
        corner = min(4, width // 3, height // 3)
        cx = x + (width - 1) / 2
        center_y = y + (height - 1) / 2
        lens = min(width, height) / 2 - 5
        top = self._shape[4 + side] * opening
        smile = self._shape[6 + side] * opening
        slope = self._shape[8 + side] * opening
        for row in range(height):
            yy = y + row
            if not 0 <= yy < self.screen_h:
                continue
            inset = max(corner - row, row - (height - 1 - corner), 0)
            left, right = x + inset, x + width - 1 - inset
            # Two-pixel frame and corner facets remain readable on a 1-bit OLED.
            if row < 2 or row >= height - 2 or height < 10:
                self._eye_segment(left, right, yy, row, x, width, height, top, smile, slope)
                continue
            self._eye_segment(left, left + 1, yy, row, x, width, height, top, smile, slope)
            self._eye_segment(right - 1, right, yy, row, x, width, height, top, smile, slope)
            if lens <= 2:
                continue
            distance = yy - center_y
            if abs(distance) <= lens:
                outer = sqrt(max(0., lens * lens - distance * distance))
                inner_radius = max(0., lens - 1.5)
                if abs(distance) < inner_radius:
                    inner = sqrt(max(0., inner_radius * inner_radius - distance * distance))
                    self._eye_segment(int(cx - outer), int(cx - inner), yy, row, x, width, height, top, smile, slope)
                    self._eye_segment(int(cx + inner), int(cx + outer), yy, row, x, width, height, top, smile, slope)
                else:
                    self._eye_segment(int(cx - outer), int(cx + outer), yy, row, x, width, height, top, smile, slope)
            # A second ring and the small solid sensor core create a lens look.
            inner_lens = lens * .50
            if abs(distance) <= inner_lens:
                edge = sqrt(max(0., inner_lens * inner_lens - distance * distance))
                for xx in (int(cx - edge), int(cx + edge)):
                    self._eye_segment(xx, xx, yy, row, x, width, height, top, smile, slope)
            if abs(distance) <= 2:
                self._eye_segment(int(cx - 2), int(cx + 2), yy, row, x, width, height, top, smile, slope)
            # Short reticle ticks on the housing's four axes.
            if abs(distance) < 1:
                self._eye_segment(x + 3, x + 5, yy, row, x, width, height, top, smile, slope)
                self._eye_segment(x + width - 6, x + width - 4, yy, row, x, width, height, top, smile, slope)
            if row in (3, height - 4):
                self._eye_segment(int(cx), int(cx), yy, row, x, width, height, top, smile, slope)

    def _eye_segment(self, left, right, yy, row, x, width, height, top, smile, slope):
        if slope:
            boundary = (row - top) / slope
            if slope > 0:
                right = min(right, int(x + (boundary + 1.) * (width - 1) / 2))
            else:
                left = max(left, int(x + (boundary + 1.) * (width - 1) / 2 + .999))
        elif row < top:
            return
        if left > right:
            return
        if smile > 0 and row > height - 1 - smile:
            vertical = (height - 1 - row) / smile
            edge = sqrt(max(0., 1. - vertical * vertical)) * (width - 1) / 2
            center = x + (width - 1) / 2
            self._span(left, min(right, int(center - edge)), yy)
            self._span(max(left, int(center + edge + .999)), right, yy)
        else:
            self._span(left, right, yy)

    def _hyperspace(self, elapsed, progress):
        cx, cy = self.screen_w / 2, self.screen_h / 2
        extent = sqrt(cx * cx + cy * cy)
        # Charge, stretch and decelerate without full-screen flashes.
        speed = min(1., progress / .25) * min(1., (1. - progress) / .16)
        for dx, dy, seed in self._stars:
            travel = ((seed / 256. + elapsed / 1100.) % 1.)
            radius = 3. + extent * travel * travel
            tail = max(0., radius - (3. + radius * .42 * speed))
            self._line(cx + dx * tail, cy + dy * tail,
                       cx + dx * radius, cy + dy * radius)
        self._circle(int(cx), int(cy), 3)
        if progress < .22:
            self._label("JUMP CHARGING", 0, self.screen_h - 8)
        elif progress > .82:
            self._label("JUMP COMPLETE", 0, self.screen_h - 8)

    def _station_plans(self, elapsed, progress):
        self._label("STATION PLANS", 0, 0)
        cx = int(self.screen_w * .35)
        cy = int(self.screen_h * .57)
        radius = max(4, int(min(self.screen_h * .36, self.screen_w * .20)))
        self._circle(cx, cy, radius)
        rotation = elapsed / 1400.
        for phase in (0., pi / 3, 2 * pi / 3):
            self._ellipse(cx, cy, max(1., abs(cos(rotation + phase)) * radius), radius)
        for fraction in (-.55, .0, .55):
            dy = fraction * radius
            rx = sqrt(max(0., radius * radius - dy * dy))
            self._ellipse(cx, cy + dy, rx, max(1., radius * .12))
        # Equatorial trench and an offset concave dish suggest a battle station.
        self._line(cx - radius, cy, cx + radius, cy)
        self._line(cx - radius, cy + 2, cx + radius, cy + 2)
        dish_x, dish_y = cx + radius // 3, cy - radius // 2
        self._circle(dish_x, dish_y, max(3, radius // 4))
        self._line(dish_x - 3, dish_y, dish_x + 3, dish_y)
        self._line(dish_x, dish_y - 3, dish_x, dish_y + 3)
        panel = int(self.screen_w * .67)
        self._label("DS-01", panel, 14)
        self._label("SCAN", panel, 26)
        self._line(panel, 38, self.screen_w - 3, 38)
        for i in range(5):
            length = 5 + int((sin(elapsed / 260. + i * 1.4) + 1.) * 11)
            self._line(panel, 43 + i * 3, min(self.screen_w - 3, panel + length), 43 + i * 3)
        scan_x = int(cx - radius + (elapsed % 1600) / 1600. * radius * 2)
        for yy in range(cy - radius, cy + radius, 4):
            self._line(scan_x, yy, scan_x, yy + 1)

    def _trench_run(self, elapsed, progress):
        self._label("TARGETING", 0, 0)
        cx, horizon = self.screen_w / 2, self.screen_h * .30
        bottom = self.screen_h - 1
        self._line(0, horizon, self.screen_w - 1, horizon)
        for fraction in (-1., -.52, -.25, .25, .52, 1.):
            self._line(cx, horizon, cx + fraction * self.screen_w, bottom)
        for i in range(7):
            distance = ((i / 7. + elapsed / 1400.) % 1.) ** 2
            yy = horizon + distance * (bottom - horizon)
            half = distance * self.screen_w
            self._line(cx - half, yy, cx + half, yy)
        target_y = horizon + 5 + progress * 15
        radius = 3 + int(progress * 6)
        self._circle(int(cx), int(target_y), radius)
        self._line(cx - radius - 4, target_y, cx + radius + 4, target_y)
        self._line(cx, target_y - radius - 4, cx, target_y + radius + 4)
        if progress > .65:
            self._label("LOCK", self.screen_w - 34, 0)

    def _label(self, text, x, y):
        # Keep text inside the screen, including on smaller supported displays.
        x, y = int(x), int(y)
        if 0 <= y <= self.screen_h - 8 and 0 <= x < self.screen_w:
            text = text[:max(0, (self.screen_w - x) // 8)]
            if text:
                self.oled.text(text, x, y, self.fg)

    def _circle(self, cx, cy, radius):
        self._ellipse(cx, cy, radius, radius)

    def _ellipse(self, cx, cy, rx, ry):
        last_x, last_y = cx + rx, cy
        for unit_x, unit_y in _ARC:
            xx, yy = cx + unit_x * rx, cy + unit_y * ry
            self._line(last_x, last_y, xx, yy)
            last_x, last_y = xx, yy

    def _line(self, x0, y0, x1, y1):
        # Cohen-Sutherland clipping keeps every framebuffer call in bounds.
        right, bottom = self.screen_w - 1, self.screen_h - 1
        for _ in range(8):
            c0 = (1 if x0 < 0 else 2 if x0 > right else 0) | (4 if y0 < 0 else 8 if y0 > bottom else 0)
            c1 = (1 if x1 < 0 else 2 if x1 > right else 0) | (4 if y1 < 0 else 8 if y1 > bottom else 0)
            if not (c0 | c1):
                self.oled.line(int(x0), int(y0), int(x1), int(y1), self.fg)
                return
            if c0 & c1:
                return
            outside = c0 or c1
            if outside & 8:
                xx, yy = x0 + (x1 - x0) * (bottom - y0) / (y1 - y0), bottom
            elif outside & 4:
                xx, yy = x0 + (x1 - x0) * (-y0) / (y1 - y0), 0
            elif outside & 2:
                xx, yy = right, y0 + (y1 - y0) * (right - x0) / (x1 - x0)
            else:
                xx, yy = 0, y0 + (y1 - y0) * (-x0) / (x1 - x0)
            if outside == c0:
                x0, y0 = xx, yy
            else:
                x1, y1 = xx, yy
