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

# Imports
from machine import Pin, I2C, PWM
from time import ticks_ms, ticks_diff, sleep_ms
import network
import urequests as requests
import urandom
from ssd1306 import SSD1306_I2C
import ntptime
import time

from modern_eyes import ModernEyes

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

screen_mode = MODE_EYES

# Weather refresh
WEATHER_REFRESH_MS = 30 * 60 * 1000
weather_last_fetch = -WEATHER_REFRESH_MS
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

# OLED and Wi-Fi
def make_oled():
    i2c = I2C(0, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=400_000)
    addrs = i2c.scan()

    if not addrs:
        raise RuntimeError("Nessun dispositivo I2C trovato.")

    addr = 0x3C if 0x3C in addrs else (0x3D if 0x3D in addrs else addrs[0])
    print("I2C ok:", [hex(a) for a in addrs], "uso", hex(addr))

    return SSD1306_I2C(WIDTH, HEIGHT, i2c, addr=addr)

def wifi_connect():
    sta = network.WLAN(network.STA_IF)
    sta.active(True)

    if not sta.isconnected():
        print("Wi-Fi: connessione a", WIFI_SSID)
        sta.connect(WIFI_SSID, WIFI_PSW)

        for _ in range(60):
            if sta.isconnected():
                break
            sleep_ms(100)

    print("Wi-Fi:", "ok" if sta.isconnected() else "fallito")
    print(sta.ifconfig())

    try:
        mac = sta.config("mac")
        print("Wi-Fi: MAC attuale", ":".join("{:02X}".format(b) for b in mac))
    except:
        pass

    return sta.isconnected()

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
        return "N/D"

    c = int(code)

    if c == 0:
        return "SERENO"
    if c == 1:
        return "QUASI SER."
    if c == 2:
        return "VARIABILE"
    if c == 3:
        return "NUVOLOSO"
    if c in (45, 48):
        return "NEBBIA"
    if c in (51, 53, 55, 56, 57):
        return "PIOVIGGINE"
    if c in (61, 63, 65, 66, 67):
        return "PIOGGIA"
    if c in (71, 73, 75, 77):
        return "NEVE"
    if c in (80, 81, 82):
        return "ROVESCI"
    if c in (85, 86):
        return "NEVE"
    if c in (95, 96, 99):
        return "TEMPORALE"

    return "METEO"

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
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            "?latitude={}&longitude={}"
            "&daily=weathercode"
            "&timezone={}"
        ).format(lat, lon, tz)

        r = requests.get(url)

        if r.status_code != 200:
            print("Meteo HTTP:", r.status_code)
            r.close()
            return None, None

        daily = r.json().get("daily", {})
        codes = daily.get("weathercode", [])

        r.close()

        today = codes[0] if len(codes) > 0 else None
        tomorrow = codes[1] if len(codes) > 1 else None

        return today, tomorrow

    except Exception as e:
        print("Errore fetch_weather_today_tomorrow:", e)
        return None, None

def update_weather_if_needed(force=False):
    global weather_last_fetch, today_code, tomorrow_code

    now = ticks_ms()

    if force or ticks_diff(now, weather_last_fetch) >= WEATHER_REFRESH_MS:
        if wifi_connect():
            t, tm = fetch_weather_today_tomorrow(LAT, LON, TZ)

            if t is not None:
                today_code = t

            if tm is not None:
                tomorrow_code = tm

            weather_last_fetch = now

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
    try:
        ntptime.host = "time.google.com"

        try:
            ntptime.timeout = 2
        except:
            pass

        ntptime.settime()
        print("NTP ok")

    except Exception as e:
        print("NTP errore:", e)

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
        title = "MOTORE"
        status = "OFF"
    else:
        title = "MOTORE"
        status = "ON"

    oled.text(title, 38, 12, 1)
    text_big(oled, status, 38 if status == "OFF" else 48, 32, 2)

    oled.show()

# Minimal servo driver
class Servo:
    def __init__(self, pin, freq_hz=50, min_us=500, max_us=2500, deg_min=0, deg_max=180):
        self.pwm = PWM(Pin(pin), freq=freq_hz)
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

# Eye mood sequence
sequence = [
    ModernEyes.DEFAULT,
    ModernEyes.CURIOUS,
    ModernEyes.DEFAULT,
    "WINK",
    ModernEyes.HAPPY,
    ModernEyes.DEFAULT,
    ModernEyes.SURPRISED,
    ModernEyes.DEFAULT,
    ModernEyes.ANGRY,
    ModernEyes.DEFAULT,
    ModernEyes.CONFUSED,
    ModernEyes.SAD,
    ModernEyes.TIRED,
    ModernEyes.SLEEP,
    ModernEyes.DEFAULT,
]

MOOD_HOLD_MS = 4500
mood_idx = 0
mood_next_at = ticks_ms() + MOOD_HOLD_MS

# Hardware initialization
oled = make_oled()

# Power the TTP223 from GPIO21
touch_power = Pin(TOUCH_PWR_PIN, Pin.OUT)
touch_power.value(1)
sleep_ms(100)

# Read the TTP223 input from GPIO20
touch = Pin(TOUCH_PIN, Pin.IN)

wifi_connect()
ntp_sync_once()

# Initial weather fetch
update_weather_if_needed(force=True)

# Eyes
eyes = ModernEyes(oled, WIDTH, HEIGHT, max_fps=45)
eyes.setDisplayColors(0, 1)
eyes.setWidth(34, 34)
eyes.setHeight(34, 34)
eyes.setSpacebetween(18)
eyes.setAutoblinker(True, interval_s=3, variation_s=4)
eyes.setIdleMode(True, interval_s=3, variation_s=5)
eyes.setMood(sequence[mood_idx], immediate=True)

# Servo
servo = None

if SERVO_ENABLE:
    try:
        servo = Servo(
            SERVO_PIN,
            freq_hz=SERVO_FREQ_HZ,
            min_us=SERVO_MIN_US,
            max_us=SERVO_MAX_US,
            deg_min=SERVO_RANGE[0],
            deg_max=SERVO_RANGE[1],
        )

        print("Servo OK su GPIO", SERVO_PIN, "- porto a posizione neutra")
        servo.write_deg_immediate(SERVO_NEUTRAL)

    except Exception as e:
        print("Servo init fallita:", e)
        SERVO_ENABLE = False

servo_cur_deg        = SERVO_NEUTRAL
servo_target_deg     = SERVO_NEUTRAL
servo_from_deg       = SERVO_NEUTRAL
servo_move_start_ms  = 0
servo_moving         = False
servo_next_move_at   = ticks_ms() + SERVO_INTERVAL_MS

SERVO_MIN_SAFE = max(SERVO_RANGE[0], SERVO_CENTER_DEG - SERVO_SWING_DEG)
SERVO_MAX_SAFE = min(SERVO_RANGE[1], SERVO_CENTER_DEG + SERVO_SWING_DEG)

# Button state
last_touch_value = touch.value()
last_touch_ms = 0
touch_press_start_ms = 0
touch_long_press_done = False

# Manual servo lock toggled by long press
head_motor_locked = False

# Temporary display message after a long press
motor_status_until = 0
motor_status_drawn = False

# Redraw static screens only when needed
last_drawn_mode = -1
last_drawn_minute = -1
last_drawn_today_code = None
last_drawn_tomorrow_code = None

# Main loop
while True:
    now = ticks_ms()

    # TTP223 handling: short press changes screen, long press toggles servo lock.
    touch_value = touch.value()

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
    if touch_value == TOUCH_ACTIVE_LEVEL and not touch_long_press_done:
        if ticks_diff(now, touch_press_start_ms) >= TOUCH_LONG_PRESS_MS:
            head_motor_locked = not head_motor_locked
            touch_long_press_done = True
            last_touch_ms = now

            # When locking the servo, stop any movement immediately.
            # When unlocking it, movement resumes normally.
            servo_moving = False
            servo_next_move_at = now + 300

            # Show a temporary status message on the display
            motor_status_until = now + MOTOR_STATUS_SHOW_MS
            motor_status_drawn = False
            last_drawn_mode = -1

            print(
                "Motore testa:",
                "BLOCCATO" if head_motor_locked else "SBLOCCATO"
            )

    # Press released
    if (
        touch_value != TOUCH_ACTIVE_LEVEL
        and last_touch_value == TOUCH_ACTIVE_LEVEL
        and ticks_diff(now, last_touch_ms) > TOUCH_DEBOUNCE_MS
    ):
        # If it was not a long press, treat it as a short press
        if not touch_long_press_done:
            screen_mode = (screen_mode + 1) % MODE_COUNT

            # Force a screen redraw
            last_drawn_mode = -1

            # Refresh stale weather data when entering a weather screen
            if screen_mode in (MODE_WEATHER_TODAY, MODE_WEATHER_TOMORROW):
                update_weather_if_needed(force=False)

        last_touch_ms = now

    last_touch_value = touch_value

    # Lightweight periodic weather refresh
    update_weather_if_needed(force=False)

    # Screens
    if ticks_diff(motor_status_until, now) > 0:
        if not motor_status_drawn:
            show_motor_status(oled, head_motor_locked)
            motor_status_drawn = True

    else:
        motor_status_drawn = False

        if screen_mode == MODE_EYES:
          if ticks_diff(now, mood_next_at) >= 0:
              mood_idx = (mood_idx + 1) % len(sequence)
              m = sequence[mood_idx]
      
              if m == "WINK":
                  eyes.wink("R", hold_ms=750)
              else:
                  eyes.setMood(m, transition_ms=950)
      
                  if m in (ModernEyes.SURPRISED, ModernEyes.HAPPY):
                      eyes.pulse(850)
      
                  if m == ModernEyes.CONFUSED:
                      eyes.confused(900)
      
              mood_next_at = now + MOOD_HOLD_MS
      
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
                show_weather_screen(oled, today_code, "OGGI")
                last_drawn_mode = screen_mode
                last_drawn_today_code = today_code

        elif screen_mode == MODE_WEATHER_TOMORROW:
            if (
                last_drawn_mode != screen_mode
                or last_drawn_tomorrow_code != tomorrow_code
            ):
                show_weather_screen(oled, tomorrow_code, "DOMANI")
                last_drawn_mode = screen_mode
                last_drawn_tomorrow_code = tomorrow_code

    # Servo jitter
    if SERVO_ENABLE and SERVO_JITTER_ENABLE and servo is not None and not head_motor_locked:
        if (not servo_moving) and ticks_diff(now, servo_next_move_at) >= 0:
            rnd = urandint(-SERVO_SWING_DEG, SERVO_SWING_DEG)
            tgt = clamp(SERVO_CENTER_DEG + rnd, SERVO_MIN_SAFE, SERVO_MAX_SAFE)

            servo_from_deg      = servo_cur_deg
            servo_target_deg    = tgt
            servo_move_start_ms = now
            servo_moving        = True
            servo_next_move_at  = now + SERVO_INTERVAL_MS

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
        if SERVO_ENABLE and servo is not None:
            servo_moving = False

    sleep_ms(16)