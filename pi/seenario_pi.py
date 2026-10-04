#!/usr/bin/env python3
"""
SeeNARIO
Webcam -> Gemini vision -> spoken guidance (ElevenLabs or espeak) -> live website.

Works on both a Windows/Mac laptop and a Raspberry Pi.

RUN:
    python3 seenario_pi.py --test    # check the speaker works
    python3 seenario_pi.py           # run the assistant (Ctrl+C to stop)

KEYS: environment variables, or a keys.txt file (lines like GEMINI_API_KEY=...) in this
folder, the folder above it, or your home folder.

OPTIONAL SETTINGS (environment variables):
    GEMINI_MODEL, INTERVAL_SECONDS, REPEAT_COOLDOWN, CAMERA_INDEX, LOG_FILE, DEBUG,
    CAMERA_HEIGHT_M, CAMERA_PITCH_DEG, VFOV_DEG, DIST_SCALE, UPLOAD_TO_SITE
    (set DEBUG=1 to print Gemini's raw hazard list)
"""
import base64
import json
import math
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

import cv2
import requests

HERE = os.path.dirname(os.path.abspath(__file__))


def load_keys() -> None:
    for folder in (HERE, os.path.dirname(HERE), os.path.expanduser("~")):
        for name in ("keys.txt", ".env"):
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                for line in open(path):
                    line = line.strip()
                    if line.startswith("export "):
                        line = line[7:]
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_keys()

API_KEY = os.environ.get("GEMINI_API_KEY")
ELEVEN_KEY = os.environ.get("ELEVENLABS_API_KEY")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
CAMERA_INDEX = int(os.environ.get("CAMERA_INDEX", "0"))
INTERVAL = float(os.environ.get("INTERVAL_SECONDS", "6"))        # pause between checks
REPEAT_COOLDOWN = float(os.environ.get("REPEAT_COOLDOWN", "4"))  # don't repeat same warning
LOG_FILE = os.environ.get("LOG_FILE", "detections.jsonl")
DEBUG = os.environ.get("DEBUG") == "1"

SITE_URL = os.environ.get("SITE_URL", "https://seenario-phi.vercel.app").rstrip("/")
PI_SECRET = os.environ.get("PI_SECRET", "seenarioPi2026xk4m")
UPLOAD_TO_SITE = os.environ.get("UPLOAD_TO_SITE", "1") == "1"
VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel

# ===== CAMERA SETUP: measure these for your build (this is what makes steps accurate) =====
CAMERA_HEIGHT_M = float(os.environ.get("CAMERA_HEIGHT_M", "1.2"))   # lens height above floor
CAMERA_PITCH_DEG = float(os.environ.get("CAMERA_PITCH_DEG", "20"))  # tilt DOWN from level
VFOV_DEG = float(os.environ.get("VFOV_DEG", "40"))                  # vertical field of view
DIST_SCALE = float(os.environ.get("DIST_SCALE", "1.0"))             # calibration factor
STEP_M = 0.75
MAX_STEPS = 5
DARK_LEVEL = 25  # average brightness (0-255) below this = camera covered/too dark
# =========================================================================================

LAST_BRIGHTNESS = 255.0

PROMPT = """
You are the eyes of a blind person who is walking forward. The photo comes from a camera worn at chest height, facing straight ahead and tilted slightly down.

YOUR JOB
List every obstacle or danger that could affect their next five steps. Be generous: if something might be in the way, include it. Make your best judgment even if the photo is dim, soft, or imperfect. Set image_ok to false only if the photo is almost completely black or fully covered.

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
- box: bounding box as [ymin, xmin, ymax, xmax], each from 0 to 1000 relative to the image, with (0,0) at the top-left. The bottom edge (ymax) must be where the object touches the floor.
- on_floor: true if the object stands on the floor and its base is visible, false for hanging or floating things.
- steps_guess: your best estimate of the distance as a whole number from 1 to 8, in steps (1 step = 0.75 meters).

ALSO GIVE
- free_side: which side of the walking corridor has clear floor to sidestep into. Use "left", "right", "both", or "none". The corridor is the middle half of the image width (x from 250 to 750).

IGNORE
Floor patterns, shadows, flat rugs, lines on the floor, the wearer's own hands, ceiling lights, posters, things behind glass, and walls running alongside the path.

RULES
Never invent objects. If nothing blocks the path, return an empty hazards list.
"""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "image_ok": {"type": "BOOLEAN"},
        "free_side": {"type": "STRING", "enum": ["left", "right", "both", "none"]},
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
    "required": ["image_ok", "free_side", "hazards"],
}

STEP_WORDS = {1: "one step", 2: "two steps", 3: "three steps", 4: "four steps",
              5: "five steps", 6: "six steps", 7: "seven steps", 8: "eight steps"}
KIND_ORDER = {"drop": 0, "vehicle": 1, "head": 2, "wall": 3, "person": 4, "object": 5}

URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"


# ---------------------------------------------------------------- speech

def play_pcm(pcm: bytes) -> None:
    """Play raw 24 kHz 16-bit mono audio on Linux (aplay), Windows (winsound) or Mac (afplay)."""
    if sys.platform.startswith("linux"):
        subprocess.run(["aplay", "-q", "-t", "raw", "-f", "S16_LE", "-r", "24000", "-c", "1"],
                       input=pcm, check=False)
        return
    import io
    import wave
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
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav)
            path = f.name
        subprocess.run(["afplay", path], check=False)
        os.remove(path)


def eleven_ready() -> bool:
    if not ELEVEN_KEY:
        return False
    if sys.platform.startswith("linux"):
        return bool(shutil.which("aplay"))
    return True


def speak(text: str) -> None:
    if eleven_ready():
        try:
            r = requests.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}?output_format=pcm_24000",
                headers={"xi-api-key": ELEVEN_KEY, "Content-Type": "application/json"},
                json={"text": text, "model_id": "eleven_flash_v2_5"}, timeout=15)
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code} {r.text[:200]}")
            play_pcm(r.content)
            return
        except Exception as e:
            print(f"ElevenLabs failed ({e}); using espeak instead")
    speak_espeak(text)


def speak(text: str) -> None:
    if ELEVEN_KEY and sys.platform.startswith("linux") and shutil.which("aplay"):
        try:
            r = requests.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}?output_format=pcm_24000",
                headers={"xi-api-key": ELEVEN_KEY, "Content-Type": "application/json"},
                json={"text": text, "model_id": "eleven_flash_v2_5"}, timeout=15)
            r.raise_for_status()
            subprocess.run(["aplay", "-q", "-t", "raw", "-f", "S16_LE", "-r", "24000", "-c", "1"],
                           input=r.content, check=False)
            return
        except Exception as e:
            print(f"ElevenLabs failed ({e}); using espeak instead")
    speak_espeak(text)


# ---------------------------------------------------------------- distance + message

def measured_steps(h: dict) -> int:
    """Steps from camera geometry for things standing on the floor; Gemini's guess otherwise."""
    guess = max(1, min(8, int(h.get("steps_guess", 3))))
    if h.get("on_floor") and h.get("kind") != "head":
        angle = CAMERA_PITCH_DEG + (h["box"][2] / 1000 - 0.5) * VFOV_DEG
        if angle < 2:
            return 8  # at the horizon: far away
        d = CAMERA_HEIGHT_M / math.tan(math.radians(angle)) * DIST_SCALE
        return max(1, min(8, round(d / STEP_M)))
    return guess


def build_message(data: dict) -> str:
    """Turn Gemini's hazard list into one short spoken sentence (or CLEAR)."""
    # Brightness is checked by the code, not by Gemini's opinion of the photo
    if LAST_BRIGHTNESS < DARK_LEVEL:
        return "Camera too dark or covered. Move slowly."

    # Keep hazards that overlap the walking corridor (middle half), plus drops/vehicles
    hazards = []
    for h in data.get("hazards", []):
        try:
            ymin, xmin, ymax, xmax = h["box"]
        except (KeyError, ValueError):
            continue
        if measured_steps(h) > MAX_STEPS:
            continue  # too far to matter
        if (xmax > 250 and xmin < 750) or h.get("kind") in ("drop", "vehicle"):
            hazards.append(h)
    if not hazards:
        return "CLEAR"

    # Most important hazard: by type first, then nearest
    h = min(hazards, key=lambda x: (KIND_ORDER.get(x.get("kind"), 5), measured_steps(x)))
    ymin, xmin, ymax, xmax = h["box"]
    cx = (xmin + xmax) / 2
    pos = "left" if cx < 333 else "right" if cx > 667 else "center"
    n = measured_steps(h)
    steps = STEP_WORDS.get(n, "a few steps")
    if h.get("on_floor") and ymax >= 975:
        steps = "within " + steps
    if DEBUG:
        print(f"   chosen: {h.get('label')} = {n} steps (Gemini guessed {h.get('steps_guess')})")
    label = h.get("label", "obstacle")
    if h.get("height") in ("low", "high"):
        label += f" {h['height']}"

    # Which way to go
    free = data.get("free_side", "none")
    if free in ("left", "right"):
        side = free
    elif free == "both":
        side = "right" if cx < 500 else "left"  # away from the hazard
    else:
        side = None
    if side == pos:  # "clear side" is where the hazard is: don't trust it
        side = None

    kind = h.get("kind")
    if side is None:
        action = "Duck" if kind == "head" else "Step back and turn around"
    elif kind in ("drop",) or (kind == "vehicle" and n <= 2):
        action = f"Step back, then go {side}"
    elif pos == "left" and side == "right":
        action = "Move slightly right"
    elif pos == "right" and side == "left":
        action = "Move slightly left"
    else:
        action = f"Step {side}"

    return f"{label.capitalize()}, {pos}, {steps}. {action}."


# ---------------------------------------------------------------- camera + Gemini

def open_camera():
    if sys.platform == "win32":
        cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
    elif sys.platform.startswith("linux"):
        cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_V4L2)  # direct driver, avoids GStreamer errors
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    else:
        cap = cv2.VideoCapture(CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def grab_frame(cap) -> bytes:
    """Return the freshest frame as JPEG bytes."""
    global LAST_BRIGHTNESS
    # Flush stale buffered frames so we analyze what's in front of the user *now*
    for _ in range(4):
        cap.grab()
    ok, frame = cap.read()
    if not ok:
        raise RuntimeError("Could not read from webcam")
    frame = cv2.resize(frame, (640, 480))
    LAST_BRIGHTNESS = float(frame.mean())
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("Could not encode frame")
    return buf.tobytes()


def ask_gemini(jpeg: bytes) -> str:
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
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": SCHEMA,
            "maxOutputTokens": 1500,
        },
    }
    r = requests.post(
        URL,
        headers={"x-goog-api-key": API_KEY, "Content-Type": "application/json"},
        json=body,
        timeout=25,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Gemini {r.status_code}: {r.text[:300]}")
    parts = r.json()["candidates"][0]["content"]["parts"]
    data = json.loads("".join(p.get("text", "") for p in parts))
    if DEBUG:
        print("RAW:", json.dumps(data))
    return build_message(data)


# ---------------------------------------------------------------- website + log

def upload(rows: list, jpeg: bytes) -> None:
    image = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()
    r = requests.post(SITE_URL + "/api/update",
                      headers={"x-api-key": PI_SECRET, "Content-Type": "application/json"},
                      json={"rows": rows, "image": image}, timeout=15)
    r.raise_for_status()


def log(result: str) -> None:
    entry = {"time": datetime.now().isoformat(timespec="seconds"), "result": result}
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------- main

def main() -> None:
        print("Voice:", "ElevenLabs" if eleven_ready() else "espeak (no ElevenLabs key or no audio player)")

    if "--test" in sys.argv:
        speak("SeeNARIO speaker test. If you can hear this, audio is working.")
        return

    if not API_KEY:
        sys.exit("Set GEMINI_API_KEY first (environment variable or keys.txt).")

    cap = open_camera()
    if not cap.isOpened():
        sys.exit("Webcam not found. Close Guvcview/other camera apps, replug the webcam, "
                 "or check CAMERA_INDEX.")

    print("Warming up camera (letting exposure settle)...")
    for _ in range(15):
        cap.read()
        time.sleep(0.1)

    speak("SeeNARIO is online.")
    last_msg, last_time, errors = "", 0.0, 0
    rows: list = []

    try:
        while True:
            start = time.time()
            try:
                jpeg = grab_frame(cap)
                result = ask_gemini(jpeg)
                errors = 0
                latency = round(time.time() - start, 2)
                print(f"[{datetime.now():%H:%M:%S}] {result} ({latency}s, brightness {LAST_BRIGHTNESS:.0f})")
                log(result)

                if UPLOAD_TO_SITE:
                    rows.append({"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                                 "guidance": "Path clear" if result == "CLEAR" else result,
                                 "latency_s": latency})
                    rows = rows[-20:]
                    try:
                        upload(rows, jpeg)
                    except Exception as e:
                        print(f"Upload failed: {e}")

                is_clear = result.strip().upper().startswith("CLEAR")
                repeated = result == last_msg and time.time() - last_time < REPEAT_COOLDOWN
                if not is_clear and not repeated:
                    speak(result)
                    last_msg, last_time = result, time.time()
            except Exception as e:  # keep running through network/camera hiccups
                errors += 1
                print(f"Error: {e}")
                if "429" in str(e):
                    print("Rate limit hit, waiting 30 seconds...")
                    time.sleep(30)
                    continue
                if errors == 3:
                    speak("Connection problem.")
                time.sleep(min(2 * errors, 15))
            time.sleep(max(0, INTERVAL - (time.time() - start)))
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        cap.release()


if __name__ == "__main__":
    main()
