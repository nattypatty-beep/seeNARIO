#!/usr/bin/env python3
"""
SeeNARIO
Webcam -> Gemini vision -> spoken guidance (ElevenLabs or computer voice) -> live website.

Works on a Raspberry Pi, Windows and Mac.

COMMANDS (use python3 on Pi/Mac, python on Windows):
    python3 seenario_pi.py --check   # test everything: keys, camera, Gemini, voice, website
    python3 seenario_pi.py --voice   # test ElevenLabs ONLY (no fallback) and show your credits
    python3 seenario_pi.py --test    # speaker test only
    python3 seenario_pi.py           # run the assistant (Ctrl+C to stop)

KEYS: environment variables, or a keys.txt file (lines like GEMINI_API_KEY=...) in this
folder, the folder above it, or your home folder.

OPTIONAL SETTINGS (environment variables):
    GEMINI_MODEL, THINKING_LEVEL, INTERVAL_SECONDS, REPEAT_COOLDOWN, CAMERA_INDEX, LOG_FILE,
    DEBUG, CAMERA_HEIGHT_M, CAMERA_PITCH_DEG, VFOV_DEG, DIST_SCALE, UPLOAD_TO_SITE,
    UPLOAD_EVERY, SKIP_UNCHANGED, MIN_GAP, ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL,
    ELEVEN_ONLY (set to 1 to NEVER use the computer voice, so you can hear if ElevenLabs fails)
    (set DEBUG=1 to print Gemini's raw hazard list)
"""
import base64
import hashlib
import io
import json
import math
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from datetime import datetime

import cv2
import requests

HERE = os.path.dirname(os.path.abspath(__file__))


def load_keys() -> None:
    for folder in (HERE, os.path.dirname(HERE), os.path.expanduser("~")):
        for name in ("keys.txt", ".env"):
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                with open(path, encoding="utf-8-sig", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("export "):
                            line = line[7:]
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_keys()

# ---- keys and services
API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
THINKING_LEVEL = os.environ.get("THINKING_LEVEL", "minimal")  # minimal = fastest; "" = model default
ELEVEN_KEY = os.environ.get("ELEVENLABS_API_KEY")
VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "")  # empty = auto-pick a voice your plan can use
ELEVEN_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_flash_v2_5")
ELEVEN_ONLY = os.environ.get("ELEVEN_ONLY") == "1"
VOICE_CACHE = os.path.join(HERE, "voice.txt")
VOICE_DIR = os.path.join(HERE, "voice_cache")

# ---- timing
CAMERA_INDEX = int(os.environ.get("CAMERA_INDEX", "0"))
INTERVAL = float(os.environ.get("INTERVAL_SECONDS", "4"))         # pause between Gemini checks
REPEAT_COOLDOWN = float(os.environ.get("REPEAT_COOLDOWN", "10"))  # don't repeat same warning
SKIP_UNCHANGED = os.environ.get("SKIP_UNCHANGED", "1") == "1"     # skip Gemini if view is unchanged
SKIP_DIFF = 4.0          # how different (0-255) a frame must be to count as "changed"
FORCE_CALL_SECONDS = 20  # always re-check at least this often
LOG_FILE = os.environ.get("LOG_FILE", os.path.join(HERE, "detections.jsonl"))
DEBUG = os.environ.get("DEBUG") == "1"

# ---- website
SITE_URL = os.environ.get("SITE_URL", "https://seenario-phi.vercel.app").rstrip("/")
PI_SECRET = os.environ.get("PI_SECRET", "")  # set PI_SECRET in keys.txt (must match Vercel)
UPLOAD_TO_SITE = os.environ.get("UPLOAD_TO_SITE", "1") == "1"
UPLOAD_EVERY = float(os.environ.get("UPLOAD_EVERY", "3"))  # seconds between website updates

# ===== CAMERA SETUP: measure these for your build (this is what makes steps accurate) =====
CAMERA_HEIGHT_M = float(os.environ.get("CAMERA_HEIGHT_M", "1.2"))   # lens height above floor
CAMERA_PITCH_DEG = float(os.environ.get("CAMERA_PITCH_DEG", "20"))  # tilt DOWN from level
VFOV_DEG = float(os.environ.get("VFOV_DEG", "40"))                  # vertical field of view
DIST_SCALE = float(os.environ.get("DIST_SCALE", "1.0"))             # calibration factor
STEP_M = 0.75
MAX_STEPS = 5
DARK_LEVEL = 25  # average brightness (0-255) below this = camera covered/too dark
MIN_GAP = int(os.environ.get("MIN_GAP", "120"))  # free width (of 1000) needed to step into
CORRIDOR_HALF = 200  # walking path = the middle strip of the picture, 500 +/- this (of 1000)
BODY_HALF = 130      # half the width the walker needs to clear an obstacle (body plus margin)
# =========================================================================================

SEND_SIZE = (512, 384)    # picture size sent to Gemini
PREVIEW_SIZE = (320, 240)  # picture size sent to the website

LAST_BRIGHTNESS = 255.0
CLEAR = "CLEAR"

PROMPT = """
You are the eyes of a blind person who is walking forward. The photo comes from a camera worn at chest height, facing straight ahead and tilted slightly down.

YOUR JOB
List up to 4 obstacles or dangers that could affect their next five steps, nearest first. Be generous: if something might be in the way, include it. Make your best judgment even if the photo is dim, soft, or imperfect. Only report what you see. Do not give directions, because other software decides which way to step.

FOR EACH HAZARD, GIVE
- label: 1 to 3 plain words, such as chair, person, wall, stairs down, car, branch, box.
- kind: exactly one of these:
  - drop: stairs down, curb, hole, water, open edge
  - vehicle: moving car, bike, scooter
  - head: hanging or overhead things at head height or above
  - wall: wall, closed door, large blocking object
  - person: people and animals
  - object: furniture, poles, boxes, anything else
- height: "low" for things on the ground below knee height, "high" for head height or above, otherwise "normal".
- box: tight bounding box as [ymin, xmin, ymax, xmax], each from 0 to 1000 relative to the image, with (0,0) at the top-left. The box must hug the object itself. A person gets a box around just that person, and two people get two separate boxes. Never draw one big box around a group or around empty floor. The bottom edge (ymax) must be where the object touches the floor.
- on_floor: true if the object stands on the floor and its base is visible, false for hanging or floating things.
- steps_guess: your best estimate of the distance as a whole number from 1 to 8, in steps (1 step = 0.75 meters).

IGNORE
Floor patterns, shadows, flat rugs, lines on the floor, the wearer's own hands, ceiling lights, posters, things behind glass, and walls running alongside the path.

RULES
Never invent objects. A person or animal is something to walk around, not a wall. If nothing blocks the path, return an empty hazards list.
"""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "hazards": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "label": {"type": "STRING"},
                    "kind": {"type": "STRING",
                             "enum": ["drop", "vehicle", "head", "wall", "person", "object"]},
                    "height": {"type": "STRING", "enum": ["low", "normal", "high"]},
                    "box": {"type": "ARRAY", "items": {"type": "INTEGER"}},
                    "on_floor": {"type": "BOOLEAN"},
                    "steps_guess": {"type": "INTEGER"},
                },
                "required": ["label", "kind", "height", "box", "on_floor", "steps_guess"],
            },
        },
    },
    "required": ["hazards"],
}

STEP_WORDS = {1: "one step", 2: "two steps", 3: "three steps", 4: "four steps",
              5: "five steps", 6: "six steps", 7: "seven steps", 8: "eight steps"}
KIND_ORDER = {"drop": 0, "vehicle": 1, "head": 2, "wall": 3, "person": 4, "object": 5}

URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

# One reusable connection per service (much faster than reconnecting every time)
GEMINI_SESSION = requests.Session()
ELEVEN_SESSION = requests.Session()
SITE_SESSION = requests.Session()
THINKING_OK = True

_warned = set()
_throttle: dict = {}


def warn_once(key: str, msg: str) -> None:
    if key not in _warned:
        _warned.add(key)
        print(msg)


def throttled(key: str, seconds: float, msg: str) -> None:
    now = time.time()
    if now - _throttle.get(key, 0) >= seconds:
        _throttle[key] = now
        print(msg)


# ---------------------------------------------------------------- computer voice

def speak_espeak(text: str) -> None:
    """Computer voice: espeak on Pi/Linux, 'say' on Mac, pyttsx3 or PowerShell on Windows."""
    try:
        if sys.platform.startswith("linux"):
            exe = shutil.which("espeak-ng") or shutil.which("espeak")
            if not exe:
                raise FileNotFoundError("espeak")
            subprocess.run([exe, "-s", "150", text], check=False, timeout=30)
        elif sys.platform == "darwin":
            subprocess.run(["say", text], check=False, timeout=30)
        else:  # Windows
            try:
                import pyttsx3
                engine = pyttsx3.init()
                engine.setProperty("rate", 160)
                engine.say(text)
                engine.runAndWait()
            except ImportError:
                safe = text.replace("'", "''")
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "Add-Type -AssemblyName System.Speech; "
                     "(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('" + safe + "')"],
                    check=False, timeout=30)
    except FileNotFoundError:
        warn_once("tts", "No computer voice installed (on the Pi: sudo apt install espeak-ng). "
                         "Guidance will only be printed and sent to the website.")
    except Exception as e:
        warn_once("tts2", f"Voice error: {e}")


# ---------------------------------------------------------------- ElevenLabs voice

class ElevenError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status} {body[:160]}")
        self.status = status
        self.body = body


ELEVEN_OFF_REASON = ""   # set when ElevenLabs is switched off for the rest of this run
ELEVEN_RETRY_AT = 0.0    # after a temporary error, wait until this time before retrying


def play_pcm(pcm: bytes) -> None:
    """Play raw 24 kHz 16-bit mono audio on Linux (aplay/paplay), Windows or Mac."""
    if sys.platform.startswith("linux"):
        if shutil.which("aplay"):
            r = subprocess.run(["aplay", "-q", "-t", "raw", "-f", "S16_LE", "-r", "24000", "-c", "1"],
                               input=pcm, check=False, timeout=30, stderr=subprocess.DEVNULL)
            if r.returncode == 0:
                return
        if shutil.which("paplay"):
            r = subprocess.run(["paplay", "--raw", "--rate=24000", "--format=s16le", "--channels=1"],
                               input=pcm, check=False, timeout=30, stderr=subprocess.DEVNULL)
            if r.returncode == 0:
                return
        raise RuntimeError("could not play audio (aplay and paplay both failed; "
                           "check the JBL is the default output)")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm)
    wav = buf.getvalue()
    if sys.platform == "win32":
        import winsound
        winsound.PlaySound(wav, winsound.SND_MEMORY)
    else:  # Mac
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav)
            path = f.name
        subprocess.run(["afplay", path], check=False, timeout=30)
        os.remove(path)


def eleven_unavailable_reason() -> str:
    """Empty string means ElevenLabs can be used right now. Otherwise says exactly why not."""
    if not ELEVEN_KEY:
        return "no ELEVENLABS_API_KEY found (put it in keys.txt or set the variable)"
    if ELEVEN_OFF_REASON:
        return ELEVEN_OFF_REASON
    if sys.platform.startswith("linux") and not (shutil.which("aplay") or shutil.which("paplay")):
        return "no audio player installed (run: sudo apt install alsa-utils)"
    if time.time() < ELEVEN_RETRY_AT:
        return "ElevenLabs had a temporary error, will retry within a minute"
    return ""


def tts_request(voice_id: str, text: str):
    return ELEVEN_SESSION.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=pcm_24000",
        headers={"xi-api-key": ELEVEN_KEY, "Content-Type": "application/json"},
        json={"text": text, "model_id": ELEVEN_MODEL}, timeout=15)


# Free-plan voices that work through the API if listing your voices is not allowed
FALLBACK_VOICES = ["21m00Tcm4TlvDq8ikWAM", "EXAVITQu4vr4xnSDxMaL", "pNInz6obpgDQGcFmaJgB"]


def pick_voice() -> str:
    """Find a voice this account may use through the API (free plans can't use library voices)."""
    global VOICE_ID
    if VOICE_ID:
        return VOICE_ID
    if os.path.isfile(VOICE_CACHE):
        with open(VOICE_CACHE) as f:
            cached = f.read().strip()
        if cached:
            VOICE_ID = cached
            return VOICE_ID
    candidates = []
    try:
        r = ELEVEN_SESSION.get("https://api.elevenlabs.io/v1/voices",
                               headers={"xi-api-key": ELEVEN_KEY}, timeout=15)
        if r.status_code == 200:
            voices = r.json().get("voices", [])
            voices.sort(key=lambda v: 0 if v.get("category") == "premade" else 1)
            candidates = [(v["voice_id"], v.get("name", "?")) for v in voices[:12]]
        else:
            print(f"  could not list voices (HTTP {r.status_code}); trying built-in voices")
    except requests.RequestException as e:
        print(f"  could not list voices ({e}); trying built-in voices")
    candidates += [(v, "built-in voice") for v in FALLBACK_VOICES]
    last = None
    for vid, name in candidates:
        t = tts_request(vid, "Hi")
        if t.status_code == 200:
            VOICE_ID = vid
            with open(VOICE_CACHE, "w") as f:
                f.write(VOICE_ID)
            print(f"Using ElevenLabs voice: {name}")
            return VOICE_ID
        last = ElevenError(t.status_code, t.text)
        print(f"  voice '{name}' not allowed (HTTP {t.status_code})")
        if t.status_code in (401, 429) or "quota" in t.text.lower():
            break  # key or credits problem, other voices won't help
    raise last or RuntimeError("no usable ElevenLabs voice")


def get_audio(text: str):
    """Returns (pcm_bytes, from_saved_file). Repeated sentences are saved, so they cost no credits."""
    voice = pick_voice()
    key = hashlib.sha1(f"{voice}|{ELEVEN_MODEL}|{text}".encode()).hexdigest()
    path = os.path.join(VOICE_DIR, key + ".pcm")
    if os.path.isfile(path):
        with open(path, "rb") as f:
            return f.read(), True
    r = tts_request(voice, text)
    if r.status_code != 200:
        raise ElevenError(r.status_code, r.text)
    try:
        os.makedirs(VOICE_DIR, exist_ok=True)
        with open(path, "wb") as f:
            f.write(r.content)
    except OSError:
        pass
    return r.content, False


def speak(text: str) -> str:
    """Speak and wait until finished. Returns which voice was used."""
    global ELEVEN_OFF_REASON, ELEVEN_RETRY_AT, VOICE_ID
    reason = eleven_unavailable_reason()
    if not reason:
        try:
            pcm, saved = get_audio(text)
            play_pcm(pcm)
            return "ElevenLabs" + (" (saved audio)" if saved else "")
        except ElevenError as e:
            if e.status in (401, 402, 403) or "quota" in e.body.lower():
                ELEVEN_OFF_REASON = (f"ElevenLabs refused the request ({e}). Likely out of credits, "
                                     "a wrong key, or a voice your plan can't use")
                VOICE_ID = ""
                if os.path.isfile(VOICE_CACHE):
                    os.remove(VOICE_CACHE)
            else:
                ELEVEN_RETRY_AT = time.time() + 60
            reason = str(e)
        except Exception as e:
            ELEVEN_RETRY_AT = time.time() + 60
            reason = str(e)
        print(f"   ElevenLabs failed: {reason}")
    else:
        throttled("eleven-reason", 120, f"   Using computer voice because: {reason}")
    if ELEVEN_ONLY:
        print("   (ELEVEN_ONLY=1: staying silent instead of using the computer voice)")
        return "none"
    speak_espeak(text)
    return "computer voice"


# Speaking happens in a background thread so a slow voice can never freeze the camera loop.
_speech_q: "queue.Queue[str]" = queue.Queue(maxsize=1)


def _speech_worker() -> None:
    while True:
        text = _speech_q.get()
        try:
            used = speak(text)
            print(f"   voice used: {used}")
        except Exception as e:
            print(f"Speech error: {e}")


threading.Thread(target=_speech_worker, daemon=True).start()


def say(text: str) -> None:
    """Queue speech without blocking. Only the newest unspoken message is kept."""
    try:
        while True:
            _speech_q.get_nowait()  # drop an older message that hasn't been spoken yet
    except queue.Empty:
        pass
    _speech_q.put(text)


def voice_banner() -> None:
    reason = eleven_unavailable_reason()
    if reason:
        print(f"Voice: COMPUTER VOICE (ElevenLabs not in use: {reason})")
    else:
        print("Voice: ElevenLabs (every spoken line will say which voice was used)")


def voice_test() -> None:
    """ElevenLabs only, no fallback. Tells you exactly what is wrong if it fails."""
    print("ElevenLabs-only test (no computer-voice fallback)")
    if not ELEVEN_KEY:
        print("FAIL: no ELEVENLABS_API_KEY found. Put it in keys.txt (home folder) or set the variable.")
        return
    print("Key found.")
    if sys.platform.startswith("linux") and not (shutil.which("aplay") or shutil.which("paplay")):
        print("FAIL: no audio player. Run: sudo apt install alsa-utils")
        return
    try:
        voice = pick_voice()
        print(f"Voice id: {voice}  Model: {ELEVEN_MODEL}")
        r = tts_request(voice, "ElevenLabs voice test. Chair low, center, two steps. Step right.")
        print(f"HTTP {r.status_code}")
        if r.status_code != 200:
            print(r.text[:300])
        else:
            print(f"Got {len(r.content)} bytes of audio. Playing it now. "
                  "If this sounds natural, ElevenLabs is working.")
            play_pcm(r.content)
    except Exception as e:
        print(f"FAIL: {e}")
    try:
        s = ELEVEN_SESSION.get("https://api.elevenlabs.io/v1/user/subscription",
                               headers={"xi-api-key": ELEVEN_KEY}, timeout=10)
        if s.status_code == 200:
            j = s.json()
            print(f"Credits used this period: {j.get('character_count')} of {j.get('character_limit')}")
        else:
            print("(could not read your credit balance; the key may lack 'user read' permission. "
                  "Check elevenlabs.io > Usage instead.)")
    except requests.RequestException:
        pass


# ---------------------------------------------------------------- distance + message

def to_int(v, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def parse_box(h: dict):
    box = h.get("box")
    if not isinstance(box, list) or len(box) != 4:
        return None
    ymin, xmin, ymax, xmax = [max(0, min(1000, to_int(v, 0))) for v in box]
    if xmax <= xmin or ymax <= ymin:
        return None
    return ymin, xmin, ymax, xmax


def measured_steps(h: dict) -> int:
    """Steps from camera geometry for things standing on the floor; Gemini's guess otherwise."""
    guess = max(1, min(8, to_int(h.get("steps_guess"), 3)))
    box = parse_box(h)
    if box and h.get("on_floor") and h.get("kind") != "head":
        angle = CAMERA_PITCH_DEG + (box[2] / 1000 - 0.5) * VFOV_DEG
        if angle < 2:
            return 8  # at the horizon: far away
        d = CAMERA_HEIGHT_M / math.tan(math.radians(angle)) * DIST_SCALE
        return max(1, min(8, round(d / STEP_M)))
    return guess


def find_gap(chosen: dict, all_hazards: list):
    """Which way is there room to walk? Looks at every nearby obstacle (not just the chosen one),
    finds the free gaps across the picture, and returns 'left', 'right', or None if no gap."""
    n = measured_steps(chosen)
    spans = []
    for x in all_hazards:
        if x is chosen or (x.get("kind") != "head" and abs(measured_steps(x) - n) <= 1):
            b = parse_box(x)
            if b:
                spans.append([b[1], b[3]])
    spans.sort()
    merged = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    gaps, prev = [], 0
    for s, e in merged:
        if s - prev >= MIN_GAP:
            gaps.append((prev, s))
        prev = e
    if 1000 - prev >= MIN_GAP:
        gaps.append((prev, 1000))
    if not gaps:
        return None

    def cost(g):  # least sideways movement first, then the wider gap
        dist = 0 if g[0] <= 500 <= g[1] else min(abs(500 - g[0]), abs(500 - g[1]))
        return (dist, -(g[1] - g[0]))

    best = min(gaps, key=cost)
    return "left" if (best[0] + best[1]) / 2 < 500 else "right"


def build_message(data: dict) -> str:
    """Turn Gemini's hazard list into one short spoken sentence (or CLEAR)."""
    # Brightness is checked by the code, not by Gemini's opinion of the photo
    if LAST_BRIGHTNESS < DARK_LEVEL:
        return "Camera too dark or covered. Move slowly."

    all_hazards = [h for h in data.get("hazards", []) if parse_box(h) is not None]
    LANE_L, LANE_R = 500 - CORRIDOR_HALF, 500 + CORRIDOR_HALF

    # Keep hazards that overlap the walking corridor (middle half), plus drops/vehicles
    hazards = []
    for h in all_hazards:
        if measured_steps(h) > MAX_STEPS:
            continue  # too far to matter
        _, xmin, _, xmax = parse_box(h)
        if (xmax > LANE_L and xmin < LANE_R) or h.get("kind") in ("drop", "vehicle"):
            hazards.append(h)
    if not hazards:
        return CLEAR

    # Most important hazard: by type first, then nearest
    h = min(hazards, key=lambda x: (KIND_ORDER.get(x.get("kind"), 5), measured_steps(x)))
    ymin, xmin, ymax, xmax = parse_box(h)
    cx = (xmin + xmax) / 2
    pos = "left" if cx < 333 else "right" if cx > 667 else "center"
    n = measured_steps(h)
    steps = STEP_WORDS.get(n, "a few steps")
    if h.get("on_floor") and ymax >= 975:
        steps = "within " + steps
    label = str(h.get("label") or "obstacle").strip()
    if h.get("height") in ("low", "high"):
        label += f" {h['height']}"
    kind = h.get("kind")

    if xmax <= LANE_L or xmin >= LANE_R:
        # Dangerous thing beside the path, not in it: just keep away from that side
        action = "Keep right" if xmax <= LANE_L else "Keep left"
    else:
        side = find_gap(h, all_hazards)  # decided by the code from the boxes, not by the AI
        if side is None:
            if kind == "head":
                action = "Duck"
            elif kind == "person":
                action = "Slow down and wait for a gap"
            else:
                action = "Step back and turn around"
        elif kind == "drop" or (kind == "vehicle" and n <= 2):
            action = f"Step back, then go {side}"
        else:
            # how far sideways the walker must move to clear the obstacle with room for their body
            needed = (xmax + BODY_HALF - 500) if side == "right" else (500 - (xmin - BODY_HALF))
            action = f"Move slightly {side}" if needed < 160 else f"Step {side}"

    if DEBUG:
        print(f"   chosen: {h.get('label')} = {n} steps (Gemini guessed {h.get('steps_guess')}), "
              f"box x {xmin}-{xmax} -> {action}")
    return f"{label.capitalize()}, {pos}, {steps}. {action}."


# ---------------------------------------------------------------- camera

def open_camera():
    if sys.platform == "win32":
        cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
    elif sys.platform.startswith("linux"):
        cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_V4L2)  # direct driver, avoids GStreamer errors
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        else:
            cap.release()
            cap = cv2.VideoCapture(CAMERA_INDEX)
    else:
        cap = cv2.VideoCapture(CAMERA_INDEX)
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 15)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


class CameraStream:
    """Reads the webcam nonstop in the background and keeps only the newest frame.
    This removes the old-frame lag: latest() is always what the camera sees right now."""

    def __init__(self):
        self.cap = open_camera()
        self.frame = None
        self.stamp = 0.0
        self.lock = threading.Lock()
        self.stopping = False

    def opened(self) -> bool:
        return self.cap.isOpened()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        fails = 0
        while not self.stopping:
            ok, frame = self.cap.read()
            if ok:
                fails = 0
                with self.lock:
                    self.frame, self.stamp = frame, time.time()
            else:
                fails += 1
                time.sleep(0.05)
                if fails >= 100:  # camera went quiet: try to reconnect
                    self.cap.release()
                    time.sleep(1)
                    self.cap = open_camera()
                    fails = 0

    def latest(self):
        with self.lock:
            frame, stamp = self.frame, self.stamp
        if frame is None or time.time() - stamp > 3:
            raise RuntimeError("Camera is not delivering frames")
        return frame

    def close(self) -> None:
        self.stopping = True
        time.sleep(0.3)
        self.cap.release()


def encode(frame, size, quality: int) -> bytes:
    small = cv2.resize(frame, size)
    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("Could not encode frame")
    return buf.tobytes()


# ---------------------------------------------------------------- Gemini

def ask_gemini(jpeg: bytes) -> str:
    global THINKING_OK
    r = None
    for _ in range(2):
        cfg = {
            "responseMimeType": "application/json",
            "responseSchema": SCHEMA,
            "maxOutputTokens": 1000,
        }
        if THINKING_OK and THINKING_LEVEL:
            cfg["thinkingConfig"] = {"thinkingLevel": THINKING_LEVEL}
        body = {
            "contents": [{
                "role": "user",
                "parts": [
                    {"text": PROMPT},
                    {"inline_data": {
                        "mime_type": "image/jpeg",
                        "data": base64.b64encode(jpeg).decode(),
                    }},
                ]
            }],
            "generationConfig": cfg,
        }
        r = GEMINI_SESSION.post(URL, headers={"x-goog-api-key": API_KEY,
                                              "Content-Type": "application/json"},
                                json=body, timeout=25)
        if r.status_code == 400 and THINKING_OK and "thinking" in r.text.lower():
            THINKING_OK = False  # this model doesn't accept the speed setting; retry without it
            print("Note: model rejected the thinking setting, retrying without it.")
            continue
        break
    if r.status_code != 200:
        raise RuntimeError(f"Gemini {r.status_code}: {r.text[:300]}")
    reply = r.json()
    cands = reply.get("candidates") or []
    if not cands or "content" not in cands[0]:
        raise RuntimeError(f"Gemini gave no answer: {json.dumps(reply)[:200]}")
    parts = cands[0]["content"].get("parts", [])
    data = json.loads("".join(p.get("text", "") for p in parts))
    if DEBUG:
        print("RAW:", json.dumps(data))
    return build_message(data)


# ---------------------------------------------------------------- website + log

ROWS: list = []
ROWS_LOCK = threading.Lock()
UPLOAD_NOW = threading.Event()


def upload(rows: list, jpeg) -> None:
    image = ("data:image/jpeg;base64," + base64.b64encode(jpeg).decode()) if jpeg else None
    r = SITE_SESSION.post(SITE_URL + "/api/update",
                          headers={"x-api-key": PI_SECRET, "Content-Type": "application/json"},
                          json={"rows": rows, "image": image}, timeout=8)
    r.raise_for_status()


def uploader(cam: "CameraStream") -> None:
    """Sends a small fresh picture and the log to the website every few seconds, in the background,
    so uploading never slows the camera or the AI. New guidance is sent right away."""
    while True:
        UPLOAD_NOW.wait(timeout=UPLOAD_EVERY)
        UPLOAD_NOW.clear()
        try:
            jpeg = encode(cam.latest(), PREVIEW_SIZE, 60)
            with ROWS_LOCK:
                rows = list(ROWS)
            upload(rows, jpeg)
        except Exception as e:
            throttled("upload", 30, f"Website upload failed: {e}")


def log(result: str) -> None:
    try:
        entry = {"time": datetime.now().isoformat(timespec="seconds"), "result": result}
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as e:
        warn_once("log", f"Could not write log file: {e}")


# ---------------------------------------------------------------- self-check

def run_checks() -> None:
    """Tests every part once: python3 seenario_pi.py --check"""
    global LAST_BRIGHTNESS

    def report(ok: bool, name: str, detail: str = "") -> None:
        print(f"[{'OK' if ok else 'FAIL'}] {name} {detail}".rstrip())

    print(f"Platform: {sys.platform} | Gemini model: {MODEL} | Site: {SITE_URL}")
    report(bool(API_KEY), "Gemini key found", "" if API_KEY else "(add GEMINI_API_KEY to keys.txt)")
    report(bool(ELEVEN_KEY), "ElevenLabs key found (optional)")

    frame = None
    cap = open_camera()
    if cap.isOpened():
        for _ in range(15):
            cap.read()
            time.sleep(0.1)
        ok, frame = cap.read()
        if not ok:
            frame = None
        cap.release()
    if frame is not None:
        LAST_BRIGHTNESS = float(frame.mean())
    report(frame is not None, "Camera frame",
           f"(brightness {LAST_BRIGHTNESS:.0f})" if frame is not None else
           "(close other camera apps, replug the webcam, or set CAMERA_INDEX)")
    jpeg = encode(frame, SEND_SIZE, 75) if frame is not None else None
    if jpeg:
        with open(os.path.join(HERE, "test_frame.jpg"), "wb") as f:
            f.write(jpeg)
        print("   saved test_frame.jpg (open it to see what the camera sees)")

    if API_KEY and jpeg:
        try:
            t0 = time.time()
            report(True, "Gemini answered:", f"{ask_gemini(jpeg)} ({time.time() - t0:.1f}s)")
        except Exception as e:
            report(False, "Gemini", str(e)[:250])
    elif not API_KEY:
        report(False, "Gemini", "(skipped, no key)")

    voice_banner()
    used = speak("SeeNARIO check. If you can hear this, audio is working.")
    print(f"   voice used: {used}")

    try:
        upload([{"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "guidance": "SeeNARIO check OK", "latency_s": 0}],
               encode(frame, PREVIEW_SIZE, 60) if frame is not None else None)
        report(True, "Website upload", f"(open {SITE_URL} and look for 'SeeNARIO check OK')")
    except Exception as e:
        report(False, "Website upload", str(e)[:250])


# ---------------------------------------------------------------- main

def main() -> None:
    global LAST_BRIGHTNESS

    if "--check" in sys.argv:
        run_checks()
        return
    if "--voice" in sys.argv:
        voice_test()
        return
    if "--test" in sys.argv:
        voice_banner()
        print(f"   voice used: {speak('SeeNARIO speaker test. If you can hear this, audio is working.')}")
        return

    if not API_KEY:
        sys.exit("Set GEMINI_API_KEY first (environment variable or keys.txt).")

    voice_banner()
    cam = CameraStream()
    if not cam.opened():
        sys.exit("Webcam not found. Close Guvcview/other camera apps, replug the webcam, "
                 "or check CAMERA_INDEX.")
    cam.start()

    print("Warming up camera (letting exposure settle)...")
    for _ in range(50):  # wait up to 5 s for the first frame
        if cam.frame is not None:
            break
        time.sleep(0.1)
    time.sleep(1.5)

    if UPLOAD_TO_SITE:
        threading.Thread(target=uploader, args=(cam,), daemon=True).start()

    say("SeeNARIO is online.")
    last_msg, last_time, errors = "", 0.0, 0
    last_small, last_result, last_call = None, "", 0.0

    try:
        while True:
            start = time.time()
            try:
                frame = cam.latest()
                LAST_BRIGHTNESS = float(frame.mean())
                small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (64, 48))

                unchanged = (SKIP_UNCHANGED and last_small is not None and last_result == CLEAR
                             and time.time() - last_call < FORCE_CALL_SECONDS
                             and float(cv2.absdiff(small, last_small).mean()) < SKIP_DIFF)
                if unchanged:
                    print(f"[{datetime.now():%H:%M:%S}] CLEAR (view unchanged, Gemini not called)")
                    time.sleep(max(0.5, INTERVAL - (time.time() - start)))
                    continue

                result = ask_gemini(encode(frame, SEND_SIZE, 75))
                last_small, last_result, last_call = small, result, time.time()
                errors = 0
                latency = round(time.time() - start, 2)
                print(f"[{datetime.now():%H:%M:%S}] {result} ({latency}s, brightness {LAST_BRIGHTNESS:.0f})")
                log(result)

                if UPLOAD_TO_SITE:
                    with ROWS_LOCK:
                        ROWS.append({"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                                     "guidance": "Path clear" if result == CLEAR else result,
                                     "latency_s": latency})
                        del ROWS[:-20]
                    UPLOAD_NOW.set()  # send to the website right away

                repeated = result == last_msg and time.time() - last_time < REPEAT_COOLDOWN
                if result != CLEAR and not repeated:
                    say(result)
                    last_msg, last_time = result, time.time()
            except Exception as e:  # keep running through network/camera hiccups
                errors += 1
                print(f"Error: {e}")
                if "429" in str(e):
                    print("Rate limit hit, waiting 30 seconds...")
                    time.sleep(30)
                    continue
                if errors == 3:
                    say("Connection problem.")
                time.sleep(min(2 * errors, 15))
            time.sleep(max(0, INTERVAL - (time.time() - start)))
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        cam.close()


if __name__ == "__main__":
    main()
