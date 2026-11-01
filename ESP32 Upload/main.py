# TwoCapsules+Weather: ESP32-C3 + SSD1306 (128x64)
# Animated eyes, clock, and today/tomorrow weather.
# TTP223: OUT on GPIO20, VCC powered from GPIO21.
# Short press cycles screens: eyes -> clock -> today -> tomorrow.
# Long press toggles head servo movement.

# I2C pins
SDA_PIN = 5
SCL_PIN = 6

# TTP223 touch button
TOUCH_PIN = 20
TOUCH_PWR_PIN = 21
TOUCH_ACTIVE_LEVEL = 1
TOUCH_DEBOUNCE_MS = 250
TOUCH_LONG_PRESS_MS = 1200

# Display message duration after a long press
MOTOR_STATUS_SHOW_MS = 1400

# Wi-Fi and location
WIFI_SSID = ""  # Network name
WIFI_PSW  = ""  # Network password

LAT = 0.00  # Latitude for weather forecast
LON = 0.00  # Longitude for weather forecast
TZ  = "Europe/Rome"  # Timezone for your location

# Eye renderer: "droid" adds mechanical optics and space-themed scenes;
# "classic" uses solid RoboEyes-inspired eyes; "modern" uses cartoon eyes.
EYE_STYLE = "classic"
EYE_MAX_FPS = 30
# Disable themed scenes to keep only the droid's animated eyes.
DROID_SCENES_ENABLE = True

# Imports
from machine import Pin, I2C, PWM
from time import ticks_ms, ticks_diff, ticks_add, sleep_ms
import sys
import gc
import urandom
import time


# Startup/network delays are milliseconds; socket timeouts are seconds.
OLED_STARTUP_MS = 1200
OLED_RETRIES = 5
WIFI_TIMEOUT_MS = 8000
HTTP_TIMEOUT_S = 5
NTP_TIMEOUT_S = 2
DEBUG_HOLD_MS = 2500
BOOT_STEP_MS = 600

_active_servo = None
_active_wifi = None
_halted = False
_debug_oled = None
_debug_until = None
_stage = "IMPORT"
clock_valid = False
requests = None


def report_error(stage, error, persist=False):
    print("ERROR [{}]: {}".format(stage, error))
    sys.print_exception(error)
    if persist:
        try:
            with open("last_error.txt", "w") as f:
                f.write("Stage: {}\n".format(stage))
                sys.print_exception(error, f)
        except Exception as log_error:
            print("Cannot save last_error.txt:", log_error)


def ascii_text(value):
    # The built-in OLED font supports printable ASCII only.
    return "".join(c if 32 <= ord(c) <= 126 else " " for c in str(value))


def debug_screen(title, line1="", line2="", hold_ms=DEBUG_HOLD_MS):
    # Keep diagnostics visible until the normal screen is ready to replace them.
    global _debug_until
    if _halted:
        return
    print("[{} ms] {} | {} | {}".format(ticks_ms(), title, line1, line2))
    _debug_until = ticks_add(ticks_ms(), hold_ms)
    if _debug_oled is not None:
        _debug_oled.fill(0)
        _debug_oled.text(ascii_text(title)[:16], 0, 0, 1)
        _debug_oled.text(ascii_text(line1)[:16], 0, 20, 1)
        _debug_oled.text(ascii_text(line2)[:16], 0, 36, 1)
        _debug_oled.text("Log: USB serial", 0, 54, 1)
        _debug_oled.show()


def debug_active(now):
    return _debug_until is not None and ticks_diff(_debug_until, now) > 0


def clear_debug_screen(oled):
    # Flush a blank framebuffer before drawing eyes: no diagnostic text remains.
    global _debug_until
    oled.fill(0)
    oled.show()
    _debug_until = None


def stop_hardware():
    # Stop PWM output and Wi-Fi even if one cleanup operation fails.
    if _active_servo is not None:
        try:
            _active_servo.pwm.deinit()
        except Exception as error:
            print("Servo shutdown error:", error)
    if _active_wifi is not None:
        try:
            _active_wifi.active(False)
        except Exception as error:
            print("Wi-Fi shutdown error:", error)


def fatal_halt(stage, error):
    global _halted
    _halted = True
    stop_hardware()
    report_error(stage, error, persist=True)
    print("Robot halted. Reset the board to retry.")
    # Bypass normal diagnostics so the error cannot expire or be overwritten.
    if _debug_oled is not None:
        try:
            message = ascii_text(error)
            if len(message) > 48:
                message = message[:47] + ">"
            _debug_oled.fill(0)
            _debug_oled.text("SYSTEM HALTED", 0, 0, 1)
            _debug_oled.text(ascii_text(stage)[:16], 0, 12, 1)
            for row in range(3):
                _debug_oled.text(message[row * 16:(row + 1) * 16], 0, 24 + row * 10, 1)
            _debug_oled.text("Reset to retry", 0, 56, 1)
            _debug_oled.show()
        except Exception as display_error:
            print("Cannot display error:", display_error)
    # Remain stopped without retries or resets. Ctrl+C can still recover REPL.
    while True:
        sleep_ms(100)


# Servo
SERVO_ENABLE   = True
SERVO_PIN      = 4
SERVO_FREQ_HZ  = 50
SERVO_MIN_US   = 500
SERVO_MAX_US   = 2500
SERVO_NEUTRAL  = 120
SERVO_RANGE    = (0, 180)

SERVO_JITTER_ENABLE = True
SERVO_CENTER_DEG    = SERVO_NEUTRAL
SERVO_SWING_DEG     = 30
SERVO_INTERVAL_MS   = 10_000
SERVO_MOVE_MS       = 1000

# Display
WIDTH, HEIGHT = 128, 64

# Screen modes
MODE_EYES = 0
MODE_TIME = 1
MODE_WEATHER_TODAY = 2
MODE_WEATHER_TOMORROW = 3
MODE_COUNT = 4

# Weather refresh
WEATHER_REFRESH_MS = 30 * 60 * 1000
today_code = None
tomorrow_code = None

# Utilities
def toi(v):
    return int(round(v))

def clamp(v, a, b):
    return a if v < a else b if v > b else v

def urandint(a, b):
    span = b - a + 1
    r = urandom.getrandbits(16) % span
    return a + r

# Servo easing and interpolation
def ease_in_out_cubic(t):
    if t < 0.5:
        return 4 * t * t * t
    u = 2 * t - 2
    return 0.5 * u * u * u + 1

def lerp(a, b, t):
    return a + (b - a) * t

# OLED: allow power to settle, check known addresses, use bounded retries.
def make_oled():
    from ssd1306 import SSD1306_I2C
    sleep_ms(OLED_STARTUP_MS)
    i2c = None
    last_error = None
    for attempt in range(OLED_RETRIES):
        try:
            i2c = I2C(0, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=400_000)
            addrs = i2c.scan()
            print("OLED attempt", attempt + 1, "I2C:", [hex(a) for a in addrs])
            addr = 0x3C if 0x3C in addrs else 0x3D if 0x3D in addrs else None
            if addr is None:
                raise RuntimeError("OLED not found (0x3C/0x3D)")
            return SSD1306_I2C(WIDTH, HEIGHT, i2c, addr=addr)
        except Exception as error:
            last_error = error
            print("OLED not ready:", error)
            if i2c is not None:
                try:
                    i2c.deinit()
                except Exception:
                    pass
            if attempt + 1 < OLED_RETRIES:
                sleep_ms(300)
    raise last_error


# Weather
def icon_type_from_code(code):
    if code is None:
        return "partly"

    c = int(code)

    if c == 0:
        return "sun"
    if c in (1, 2, 3):
        return "partly"
    if c in (45, 48):
        return "fog"
    if c in (51, 53, 55, 56, 57):
        return "drizzle"
    if c in (61, 63, 65, 66, 67):
        return "rain"
    if c in (71, 73, 75, 77):
        return "snow"
    if c in (80, 81, 82):
        return "shower"
    if c in (85, 86):
        return "snow"
    if c in (95, 96, 99):
        return "thunder"

    return "partly"

def weather_text_from_code(code):
    if code is None:
        return "N/A"

    c = int(code)

    if c == 0:
        return "SUNNY"
    if c == 1:
        return "MOSTLY CLR"
    if c == 2:
        return "PARTLY CLD"
    if c == 3:
        return "CLOUDY"
    if c in (45, 48):
        return "FOG"
    if c in (51, 53, 55, 56, 57):
        return "DRIZZLE"
    if c in (61, 63, 65, 66, 67):
        return "RAIN"
    if c in (71, 73, 75, 77):
        return "SNOW"
    if c in (80, 81, 82):
        return "SHOWERS"
    if c in (85, 86):
        return "SNOW"
    if c in (95, 96, 99):
        return "THUNDER"

    return "WEATHER"

def _toi(v):
    return int(round(v))

def _fc(oled, cx, cy, r, col=1):
    cx = _toi(cx)
    cy = _toi(cy)
    r = max(0, _toi(r))
    r2 = r * r

    for yy in range(cy - r, cy + r + 1):
        dy = yy - cy
        dx = int((r2 - dy * dy) ** 0.5)
        oled.hline(cx - dx, yy, 2 * dx + 1, col)

def _ring_rays(oled, cx, cy, r1, r2, step_deg):
    import math

    for a in range(0, 360, step_deg):
        rad = math.radians(a)
        x1 = _toi(cx + r1 * math.cos(rad))
        y1 = _toi(cy + r1 * math.sin(rad))
        x2 = _toi(cx + r2 * math.cos(rad))
        y2 = _toi(cy + r2 * math.sin(rad))
        oled.line(x1, y1, x2, y2, 1)

def _cloud32(oled, x, y):
    oled.fill_rect(x + 4, y + 18, 24, 8, 1)
    _fc(oled, x + 10, y + 20, 8, 1)
    _fc(oled, x + 20, y + 18, 7, 1)
    _fc(oled, x + 26, y + 21, 6, 1)

def _drop(oled, x, y):
    oled.pixel(x + 1, y, 1)
    oled.hline(x, y + 1, 3, 1)
    oled.hline(x, y + 2, 3, 1)
    oled.hline(x + 1, y + 3, 1, 1)
    oled.pixel(x + 1, y + 4, 1)

def _flake(oled, x, y):
    oled.pixel(x + 2, y + 0, 1)
    oled.vline(x + 2, y + 0, 5, 1)
    oled.hline(x + 0, y + 2, 5, 1)
    oled.pixel(x + 0, y + 0, 1)
    oled.pixel(x + 4, y + 0, 1)
    oled.pixel(x + 0, y + 4, 1)
    oled.pixel(x + 4, y + 4, 1)

def _bolt(oled, x, y):
    oled.line(x + 6, y, x + 2, y + 8, 1)
    oled.line(x + 2, y + 8, x + 8, y + 8, 1)
    oled.line(x + 8, y + 8, x + 3, y + 16, 1)

def draw_weather_icon(oled, kind, x, y):
    if kind == "sun":
        cx, cy = x + 16, y + 16
        _fc(oled, cx, cy, 8, 1)
        _ring_rays(oled, cx, cy, 11, 14, 22)
        return

    if kind == "partly":
        _fc(oled, x + 10, y + 10, 7, 1)
        _ring_rays(oled, x + 10, y + 10, 10, 13, 45)
        _cloud32(oled, x, y)
        return

    if kind == "cloud":
        _cloud32(oled, x, y)
        return

    if kind in ("drizzle", "rain", "shower"):
        _cloud32(oled, x, y)

        cols = (x + 8, x + 16, x + 24)
        ys = (y + 24, y + 26, y + 24)

        for i, (xx, yy) in enumerate(zip(cols, ys)):
            if kind == "drizzle" and i == 1:
                continue

            _drop(oled, xx, yy)

            if kind == "shower":
                _drop(oled, xx - 3, yy + 5)

        return

    if kind == "snow":
        _cloud32(oled, x, y)
        _flake(oled, x + 10, y + 25)
        _flake(oled, x + 20, y + 27)
        return

    if kind == "thunder":
        _cloud32(oled, x, y)
        _bolt(oled, x + 14, y + 18)
        return

    if kind == "fog":
        _cloud32(oled, x, y - 4)

        for yy in (y + 18, y + 22, y + 26, y + 30):
            oled.hline(x + 2, yy, 28, 1)

        return

    _cloud32(oled, x, y)

def fetch_weather_today_tomorrow(lat, lon, tz):
    global requests
    if requests is None:
        try:
            import requests as http_module
        except ImportError:
            import urequests as http_module
        requests = http_module
    url = (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude={}&longitude={}&daily=weathercode&timezone={}"
    ).format(lat, lon, tz)
    response = None
    try:
        # Never retry without a timeout if an old requests library rejects it.
        response = requests.get(url, timeout=HTTP_TIMEOUT_S)
        if response.status_code != 200:
            raise RuntimeError("HTTP {}".format(response.status_code))
        codes = response.json().get("daily", {}).get("weathercode", [])
        if len(codes) < 2 or codes[0] is None or codes[1] is None:
            raise ValueError("Missing weather data")
        return int(codes[0]), int(codes[1])
    finally:
        if response is not None:
            response.close()


def show_weather_screen(oled, code, title):
    oled.fill(0)

    kind = icon_type_from_code(code)
    text = weather_text_from_code(code)

    oled.text(title, 0, 0, 1)

    # Icon on the left
    draw_weather_icon(oled, kind, 4, 18)

    # Forecast text on the right
    oled.text(text, 48, 28, 1)

    oled.show()

# Time: NTP + Europe/Rome DST
def ntp_sync_once():
    import ntptime
    ntptime.host = "time.google.com"
    ntptime.timeout = NTP_TIMEOUT_S
    ntptime.settime()


class NetworkService:
    """Show boot diagnostics before eyes; propagate every network error."""

    def __init__(self):
        global _stage
        _stage = "WIFI CONFIG"
        if not WIFI_SSID:
            raise ValueError("WIFI_SSID is empty")
        self.sta = None
        self.connecting = False
        self.online = False
        self.deadline = None
        self.next_poll = ticks_ms()
        self.next_ntp = ticks_ms()
        self.next_weather = ticks_ms()
        self.ntp_done = False
        self.weather_done = False

    def ready(self):
        return self.online and self.ntp_done and self.weather_done

    def poll(self, now, allow_io=True):
        global today_code, tomorrow_code, clock_valid, _active_wifi, _stage
        if ticks_diff(now, self.next_poll) < 0:
            return
        self.next_poll = ticks_add(now, 200)
        _stage = "WIFI"
        if self.sta is None:
            import network
            self.network = network
            interface = getattr(network, "STA_IF", None)
            if interface is None:
                interface = network.WLAN.IF_STA
            self.sta = network.WLAN(interface)
            _active_wifi = self.sta

        if not self.online:
            if not self.connecting:
                debug_screen("WIFI", "Connecting...", "Timeout: 8s")
                self.sta.active(True)
                if not self.sta.isconnected():
                    self.sta.connect(WIFI_SSID, WIFI_PSW)
                self.connecting = True
                self.deadline = ticks_add(ticks_ms(), WIFI_TIMEOUT_MS)

            if self.sta.isconnected():
                self.online = True
                self.connecting = False
                self.next_ntp = ticks_add(ticks_ms(), DEBUG_HOLD_MS)
                self.next_weather = self.next_ntp
                debug_screen("WIFI OK", self.sta.ifconfig()[0])
            else:
                status = self.sta.status()
                if status == getattr(self.network, "STAT_WRONG_PASSWORD", -3):
                    raise RuntimeError("Wrong Wi-Fi password")
                if status == getattr(self.network, "STAT_NO_AP_FOUND", -2):
                    raise RuntimeError("Wi-Fi network not found")
                if status == getattr(self.network, "STAT_CONNECT_FAIL", -1):
                    raise RuntimeError("Wi-Fi connection failed")
                if ticks_diff(ticks_ms(), self.deadline) >= 0:
                    raise RuntimeError("Wi-Fi timeout (8s)")
            return

        if not self.sta.isconnected():
            raise RuntimeError("Wi-Fi connection lost")

        # Let each diagnostic finish; defer synchronous work while touch/servo
        # are busy. During boot there are no animations to interrupt.
        if not allow_io or debug_active(ticks_ms()):
            return
        if ticks_diff(now, self.next_ntp) >= 0:
            _stage = "NTP"
            debug_screen("TIME / NTP", "Synchronizing...")
            if not self.ntp_done:
                sleep_ms(BOOT_STEP_MS)
            ntp_sync_once()
            clock_valid = True
            self.ntp_done = True
            self.next_ntp = ticks_add(ticks_ms(), 6 * 60 * 60_000)
            debug_screen("TIME OK", hhmm_local())
            return

        if ticks_diff(now, self.next_weather) >= 0:
            _stage = "WEATHER"
            debug_screen("WEATHER", "Downloading...")
            if not self.weather_done:
                sleep_ms(BOOT_STEP_MS)
            gc.collect()
            try:
                today_code, tomorrow_code = fetch_weather_today_tomorrow(LAT, LON, TZ)
            finally:
                gc.collect()
            self.weather_done = True
            self.next_weather = ticks_add(ticks_ms(), WEATHER_REFRESH_MS)
            debug_screen("WEATHER OK", "Data updated")


def _is_leap(y):
    return (y % 4 == 0 and y % 100 != 0) or (y % 400 == 0)

def _weekday(y, m, d):
    t = [0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4]

    if m < 3:
        y -= 1

    return (y + y // 4 - y // 100 + y // 400 + t[m - 1] + d) % 7

def _days_in_month(y, m):
    dim = [
        31,
        29 if _is_leap(y) else 28,
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ]

    return dim[m - 1]

def _last_sunday(y, m):
    d = _days_in_month(y, m)

    while _weekday(y, m, d) != 0:
        d -= 1

    return d

def is_dst_europe_rome(y, mon, day, hour_utc):
    start_day = _last_sunday(y, 3)
    end_day = _last_sunday(y, 10)

    if 4 <= mon <= 9:
        return True

    if mon == 3:
        return day > start_day or (day == start_day and hour_utc >= 1)

    if mon == 10:
        return day < end_day or (day == end_day and hour_utc < 1)

    return False

def local_tuple():
    now_utc = time.time()
    y, mon, day, hr, mi, se, wd, yd = time.gmtime(now_utc)
    offset_hours = 2 if is_dst_europe_rome(y, mon, day, hr) else 1

    return time.localtime(now_utc + offset_hours * 3600)

def hhmm_local():
    if not clock_valid:
        return "--:--"
    t = local_tuple()
    return "{:02d}:{:02d}".format(t[3], t[4])

# Large font
def text_big(oled, s, x, y, scale=2):
    from framebuf import FrameBuffer, MONO_HLSB

    fb = FrameBuffer(bytearray(8 * 8), 8, 8, MONO_HLSB)

    for i, c in enumerate(s):
        fb.fill(0)
        fb.text(c, 0, 0, 1)

        for px in range(8):
            for py in range(8):
                if fb.pixel(px, py):
                    for dx in range(scale):
                        for dy in range(scale):
                            oled.pixel(
                                x + i * 8 * scale + px * scale + dx,
                                y + py * scale + dy,
                                1,
                            )

def show_time(oled, timestr):
    oled.fill(0)

    s = timestr or "--:--"
    scale = 3
    text_width = 8 * scale * len(s)
    x = (oled.width - text_width) // 2
    y = (oled.height - 8 * scale) // 2

    text_big(oled, s, x, y, scale)
    oled.show()

def show_motor_status(oled, motor_locked):
    oled.fill(0)

    if motor_locked:
        title = "MOTOR"
        status = "OFF"
    else:
        title = "MOTOR"
        status = "ON"

    oled.text(title, 38, 12, 1)
    text_big(oled, status, 38 if status == "OFF" else 48, 32, 2)

    oled.show()

# Minimal servo driver
class Servo:
    def __init__(self, pin, freq_hz=50, min_us=500, max_us=2500, deg_min=0, deg_max=180):
        global _active_servo
        self.pwm = PWM(Pin(pin), freq=freq_hz)
        _active_servo = self
        self.min_us = min_us
        self.max_us = max_us
        self.deg_min = deg_min
        self.deg_max = deg_max

    def _deg_to_us(self, deg):
        d = max(self.deg_min, min(self.deg_max, deg))
        t = (d - self.deg_min) / float(self.deg_max - self.deg_min)
        return int(self.min_us + t * (self.max_us - self.min_us))

    def write_deg_immediate(self, deg):
        us = self._deg_to_us(deg)
        self.pwm.duty_ns(us * 1000)

def run_robot():
    global _debug_oled, _debug_until, _stage, clock_valid
    # Initialize the display and local hardware before importing network modules.
    _stage = "OLED"
    oled = make_oled()
    _debug_oled = oled
    debug_screen("DISPLAY OK", "Starting local...")
    sleep_ms(BOOT_STEP_MS)
    _stage = "EYE MODULE"
    if EYE_STYLE == "classic":
        from roboeyes_classic import ClassicEyes as EyeRenderer
    elif EYE_STYLE == "modern":
        from modern_eyes import ModernEyes as EyeRenderer
    elif EYE_STYLE == "droid":
        from droid_eyes import DroidEyes as EyeRenderer
    else:
        raise ValueError("EYE_STYLE must be droid, classic or modern")
    # The RTC may already contain synchronized time after a soft reset.
    clock_valid = time.gmtime()[0] >= 2024
    servo_enabled = SERVO_ENABLE
    screen_mode = MODE_EYES
    # Eye mood sequence
    sequence = [
        EyeRenderer.DEFAULT,
        EyeRenderer.CURIOUS,
        EyeRenderer.DEFAULT,
        "WINK",
        EyeRenderer.HAPPY,
        EyeRenderer.DEFAULT,
        EyeRenderer.SURPRISED,
        EyeRenderer.DEFAULT,
        EyeRenderer.ANGRY,
        EyeRenderer.DEFAULT,
        EyeRenderer.CONFUSED,
        EyeRenderer.SAD,
        EyeRenderer.TIRED,
        EyeRenderer.SLEEP,
        EyeRenderer.DEFAULT,
    ]
    if EYE_STYLE == "droid" and DROID_SCENES_ENABLE:
        sequence = [
            EyeRenderer.DEFAULT, EyeRenderer.CURIOUS, "HYPERSPACE",
            EyeRenderer.DEFAULT, EyeRenderer.HAPPY, "STATION PLANS",
            EyeRenderer.DEFAULT, EyeRenderer.ANGRY, "TRENCH RUN",
            EyeRenderer.DEFAULT, EyeRenderer.CONFUSED, EyeRenderer.TIRED,
        ]

    MOOD_HOLD_MS = 4500
    mood_idx = 0
    mood_next_at = ticks_add(ticks_ms(), MOOD_HOLD_MS)

    # Configure the touch input; any failure stops startup.
    _stage = "TOUCH"
    debug_screen("STARTING TOUCH", "GPIO20 / GPIO21")
    touch_power = Pin(TOUCH_PWR_PIN, Pin.OUT)
    touch_power.value(1)
    sleep_ms(BOOT_STEP_MS)
    touch = Pin(TOUCH_PIN, Pin.IN)

    _stage = "EYES"
    debug_screen("STARTING EYES", EYE_STYLE.upper())
    sleep_ms(BOOT_STEP_MS)
    # Eyes
    eyes = EyeRenderer(oled, WIDTH, HEIGHT, max_fps=EYE_MAX_FPS)
    eyes.setDisplayColors(0, 1)
    eyes.setWidth(34, 34)
    eyes.setHeight(34, 34)
    eyes.setSpacebetween(18)
    if EYE_STYLE == "classic":
        eyes.setBorderradius(8, 8)
        eyes.setCuriosity(True)
    eyes.setAutoblinker(True, interval_s=3, variation_s=4)
    eyes.setIdleMode(True, interval_s=3, variation_s=5)
    eyes.setMood(sequence[mood_idx], immediate=True)

    # Servo
    _stage = "SERVO"
    debug_screen("STARTING SERVO", "GPIO4")
    servo = None

    if servo_enabled:
        servo = Servo(
            SERVO_PIN,
            freq_hz=SERVO_FREQ_HZ,
            min_us=SERVO_MIN_US,
            max_us=SERVO_MAX_US,
            deg_min=SERVO_RANGE[0],
            deg_max=SERVO_RANGE[1],
        )
        print("Servo ready on GPIO", SERVO_PIN, "- moving to neutral")
        servo.write_deg_immediate(SERVO_NEUTRAL)
    sleep_ms(BOOT_STEP_MS)

    servo_cur_deg        = SERVO_NEUTRAL
    servo_target_deg     = SERVO_NEUTRAL
    servo_from_deg       = SERVO_NEUTRAL
    servo_move_start_ms  = 0
    servo_moving         = False
    servo_next_move_at   = ticks_add(ticks_ms(), SERVO_INTERVAL_MS)

    SERVO_MIN_SAFE = max(SERVO_RANGE[0], SERVO_CENTER_DEG - SERVO_SWING_DEG)
    SERVO_MAX_SAFE = min(SERVO_RANGE[1], SERVO_CENTER_DEG + SERVO_SWING_DEG)

    # Button state
    last_touch_value = touch.value() if touch is not None else 1 - TOUCH_ACTIVE_LEVEL
    touch_ready_at = ticks_add(ticks_ms(), 1000)
    last_touch_ms = 0
    touch_press_start_ms = None
    touch_long_press_done = False

    # Manual servo lock toggled by long press
    head_motor_locked = False

    # Temporary display message after a long press
    motor_status_until = ticks_ms()
    motor_status_drawn = False

    # Redraw static screens only when needed
    last_drawn_mode = -1
    last_drawn_minute = -1
    last_drawn_today_code = None
    last_drawn_tomorrow_code = None

    # Keep all current startup diagnostics visible before showing any eyes.
    debug_screen("LOCAL ROBOT OK", "Starting network", "Local setup done")
    sleep_ms(BOOT_STEP_MS)
    net = NetworkService()
    while not net.ready():
        net.poll(ticks_ms())
        sleep_ms(20)
    while debug_active(ticks_ms()):
        sleep_ms(20)

    # Diagnostics are complete. Clear both framebuffer and OLED before eyes.
    _stage = "EYES"
    clear_debug_screen(oled)
    eyes.update()
    mood_next_at = ticks_add(ticks_ms(), MOOD_HOLD_MS)
    servo_next_move_at = ticks_add(ticks_ms(), SERVO_INTERVAL_MS)
    last_touch_value = touch.value()
    last_touch_ms = ticks_ms()
    touch_ready_at = ticks_add(ticks_ms(), 300)
    motor_status_until = ticks_ms()
    debug_was_active = False

    # Main loop
    while True:
        now = ticks_ms()
        _stage = "TOUCH"

        # TTP223 handling: short press changes screen, long press toggles servo lock.
        touch_value = touch.value() if touch is not None else 1 - TOUCH_ACTIVE_LEVEL
        # Ignore initial touch calibration and require an actual press edge
        # before recognizing a long press.
        if ticks_diff(now, touch_ready_at) < 0:
            touch_value = 1 - TOUCH_ACTIVE_LEVEL
            last_touch_value = touch_value

        # Press started
        if (
            touch_value == TOUCH_ACTIVE_LEVEL
            and last_touch_value != TOUCH_ACTIVE_LEVEL
            and ticks_diff(now, last_touch_ms) > TOUCH_DEBOUNCE_MS
        ):
            touch_press_start_ms = now
            touch_long_press_done = False
            last_touch_ms = now

        # Held press: check for long press
        if touch_value == TOUCH_ACTIVE_LEVEL and touch_press_start_ms is not None and not touch_long_press_done:
            if ticks_diff(now, touch_press_start_ms) >= TOUCH_LONG_PRESS_MS:
                head_motor_locked = not head_motor_locked
                touch_long_press_done = True
                last_touch_ms = now

                # When locking the servo, stop any movement immediately.
                # When unlocking it, movement resumes normally.
                servo_moving = False
                servo_next_move_at = ticks_add(now, 300)

                # Show a temporary status message on the display
                motor_status_until = ticks_add(now, MOTOR_STATUS_SHOW_MS)
                motor_status_drawn = False
                last_drawn_mode = -1

                print(
                    "Head motor:",
                    "LOCKED" if head_motor_locked else "UNLOCKED"
                )

        # Press released
        if (
            touch_value != TOUCH_ACTIVE_LEVEL
            and last_touch_value == TOUCH_ACTIVE_LEVEL
            and ticks_diff(now, last_touch_ms) > TOUCH_DEBOUNCE_MS
        ):
            # If it was not a long press, treat it as a short press
            if touch_press_start_ms is not None and not touch_long_press_done:
                screen_mode = (screen_mode + 1) % MODE_COUNT

                # Force a screen redraw
                last_drawn_mode = -1

            last_touch_ms = now
            touch_press_start_ms = None

        last_touch_value = touch_value

        # Redraw static screens when a diagnostic message expires.
        showing_debug = debug_active(now)
        if debug_was_active and not showing_debug:
            last_drawn_mode = -1
            motor_status_drawn = False
        debug_was_active = showing_debug

        # Screens
        _stage = "DISPLAY"
        if showing_debug:
            pass
        elif ticks_diff(motor_status_until, now) > 0:
            if not motor_status_drawn:
                show_motor_status(oled, head_motor_locked)
                motor_status_drawn = True

        else:
            motor_status_drawn = False

            if screen_mode == MODE_EYES:
                _stage = "EYES"
                if last_drawn_mode != MODE_EYES:
                    clear_debug_screen(oled)
                    last_drawn_mode = MODE_EYES
                if ticks_diff(now, mood_next_at) >= 0:
                    mood_idx = (mood_idx + 1) % len(sequence)
                    m = sequence[mood_idx]

                    if m == "WINK":
                        eyes.wink("R", hold_ms=750)
                    elif EYE_STYLE == "droid" and m == "HYPERSPACE":
                        eyes.hyperspace(3200)
                    elif EYE_STYLE == "droid" and m == "STATION PLANS":
                        eyes.station_plans(3800)
                    elif EYE_STYLE == "droid" and m == "TRENCH RUN":
                        eyes.trench_run(3200)
                    else:
                        eyes.setMood(m, transition_ms=950)

                        if m in (EyeRenderer.SURPRISED, EyeRenderer.HAPPY):
                            eyes.pulse(850)

                        if EYE_STYLE == "classic" and m == EyeRenderer.HAPPY:
                            eyes.laugh(900)

                        if m == EyeRenderer.CONFUSED:
                            eyes.confused(900)

                    mood_next_at = ticks_add(now, MOOD_HOLD_MS)

                eyes.update()

            elif screen_mode == MODE_TIME:
                current_time = hhmm_local()
                current_minute = current_time

                if last_drawn_mode != screen_mode or last_drawn_minute != current_minute:
                    show_time(oled, current_time)
                    last_drawn_mode = screen_mode
                    last_drawn_minute = current_minute

            elif screen_mode == MODE_WEATHER_TODAY:
                if (
                    last_drawn_mode != screen_mode
                    or last_drawn_today_code != today_code
                ):
                    show_weather_screen(oled, today_code, "TODAY")
                    last_drawn_mode = screen_mode
                    last_drawn_today_code = today_code

            elif screen_mode == MODE_WEATHER_TOMORROW:
                if (
                    last_drawn_mode != screen_mode
                    or last_drawn_tomorrow_code != tomorrow_code
                ):
                    show_weather_screen(oled, tomorrow_code, "TOMORROW")
                    last_drawn_mode = screen_mode
                    last_drawn_tomorrow_code = tomorrow_code

        # Servo jitter
        _stage = "SERVO"
        if servo_enabled and SERVO_JITTER_ENABLE and servo is not None and not head_motor_locked:
            if (not servo_moving) and ticks_diff(now, servo_next_move_at) >= 0:
                rnd = urandint(-SERVO_SWING_DEG, SERVO_SWING_DEG)
                tgt = clamp(SERVO_CENTER_DEG + rnd, SERVO_MIN_SAFE, SERVO_MAX_SAFE)

                servo_from_deg      = servo_cur_deg
                servo_target_deg    = tgt
                servo_move_start_ms = now
                servo_moving        = True
                servo_next_move_at  = ticks_add(now, SERVO_INTERVAL_MS)

            if servo_moving:
                dt = ticks_diff(now, servo_move_start_ms)
                t = clamp(dt / float(SERVO_MOVE_MS), 0.0, 1.0)
                tt = ease_in_out_cubic(t)

                cur = lerp(servo_from_deg, servo_target_deg, tt)
                servo.write_deg_immediate(cur)
                servo_cur_deg = cur

                if t >= 1.0:
                    servo_moving = False

        else:
            # Manual lock: keep the servo at its current position.
            if servo_enabled and servo is not None:
                servo_moving = False

        # Poll Wi-Fi without sleeping in the animation loop.
        net.poll(ticks_ms(), allow_io=(
            not servo_moving
            and touch_value != TOUCH_ACTIVE_LEVEL
            and ticks_diff(motor_status_until, ticks_ms()) <= 0
        ))
        # A periodic network update may have shown a diagnostic after rendering.
        # Invalidate the normal screen after that message expires.
        if debug_active(ticks_ms()):
            debug_was_active = True
        sleep_ms(16)


def main():
    try:
        run_robot()
    except KeyboardInterrupt:
        stop_hardware()
        print("Program stopped from the console.")
    except Exception as error:
        fatal_halt(_stage, error)


if __name__ == "__main__":
    main()
