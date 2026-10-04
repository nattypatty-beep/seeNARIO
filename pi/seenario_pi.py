#!/usr/bin/env python3
"""
SeeNARIO
Webcam -> Gemini vision -> spoken guidance through a speaker.

Works on both a Windows/Mac laptop and a Raspberry Pi.

LAPTOP SETUP:
    pip install opencv-python requests pyttsx3
    PowerShell:  $env:GEMINI_API_KEY="your-key"
    Mac:         export GEMINI_API_KEY="your-key"

RASPBERRY PI SETUP:
    sudo apt install -y python3-opencv python3-requests espeak-ng
    export GEMINI_API_KEY="your-key"

RUN:
    python seenario_pi.py --test    # check the speaker works
    python seenario_pi.py           # run the assistant (Ctrl+C to stop)

OPTIONAL SETTINGS (environment variables):
    GEMINI_MODEL, INTERVAL_SECONDS, REPEAT_COOLDOWN, CAMERA_INDEX, LOG_FILE
"""
import base64
import json
import os
import subprocess
import sys
import time
from datetime import datetime

import cv2
import requests

API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
CAMERA_INDEX = int(os.environ.get("CAMERA_INDEX", "0"))
INTERVAL = float(os.environ.get("INTERVAL_SECONDS", "6"))        # pause between checks
REPEAT_COOLDOWN = float(os.environ.get("REPEAT_COOLDOWN", "3"))  # don't repeat same warning
LOG_FILE = os.environ.get("LOG_FILE", "detections.jsonl")
PROMPT = """You are the eyes of a blind person walking forward. The photo is from a chest-height camera facing straight ahead, tilted slightly down.

Find EVERY obstacle or danger that could affect their next five steps and list each one. Be generous: if something might be in the way, list it. Do not refuse or give up because the photo is dim, soft or imperfect; make your best judgment. Set image_ok to false ONLY if the photo is almost completely black or fully covered.

For each hazard give:
- label: 1 to 3 plain words (chair, person, wall, stairs down, car, branch, box).
- kind: one of drop (stairs down, curb, hole, water, open edge), vehicle (moving car, bike, scooter), head (hanging or overhead things at head height or above), wall (wall, closed door, large blocking object), person (people and animals), object (furniture, poles, boxes, anything else).
- height: "low" for things on the ground below knee height, "high" for head height or above, otherwise "normal".
- box: tight bounding box [ymin, xmin, ymax, xmax], each 0 to 1000 relative to the image (0,0 is top-left). The bottom of the box must be where the object touches the floor.
- on_floor: true if the object stands on the floor and its base is visible, false for hanging or floating things.
- steps_guess: your best estimate of distance in steps (1 step = 0.75 m), integer 1 to 8.

Also give free_side: which side of the walking corridor has clear floor to sidestep into: "left", "right", "both", or "none". The corridor is the middle half of the image width.

Ignore: floor patterns, shadows, flat rugs, floor lines, the wearer's hands, ceiling lights, posters, things behind glass, walls running alongside the path. Never invent objects. If nothing blocks the path, return an empty hazards list."""


URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"


def speak(text: str) -> None:
    if sys.platform.startswith("linux"):  # Raspberry Pi
        subprocess.run(["espeak-ng", "-s", "150", text], check=False)
    else:  # Windows / Mac laptop
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty("rate", 160)
        engine.say(text)
        engine.runAndWait()


def grab_frame(cap) -> bytes:
    """Return the freshest frame as JPEG bytes."""
    # Flush stale buffered frames so we analyze what's in front of the user *now*
    for _ in range(3):
        cap.grab()
    ok, frame = cap.read()
    if not ok:
        raise RuntimeError("Could not read from webcam")
    frame = cv2.resize(frame, (640, 480))
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        raise RuntimeError("Could not encode frame")
    return buf.tobytes()


def ask_gemini(jpeg: bytes) -> str:
    body = {
        "contents": [{
            "parts": [
                {"text": PROMPT},
                {"inline_data": {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(jpeg).decode(),
                }},
            ]
        }],
        "generationConfig": {"temperature": 0.2},
    }
    r = requests.post(
        URL,
        headers={"x-goog-api-key": API_KEY, "Content-Type": "application/json"},
        json=body,
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def log(result: str) -> None:
    entry = {"time": datetime.now().isoformat(timespec="seconds"), "result": result}
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def main() -> None:
    if "--test" in sys.argv:
        speak("SeeNARIO speaker test. If you can hear this, audio is working.")
        return

    if not API_KEY:
        sys.exit("Set GEMINI_API_KEY first (see the setup steps at the top of this file).")

    if sys.platform == "win32":
        cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
    else:
        cap = cv2.VideoCapture(CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not cap.isOpened():
        sys.exit("Webcam not found. Check the USB connection or CAMERA_INDEX.")

    speak("SeeNARIO is online.")
    last_msg, last_time, errors = "", 0.0, 0

    try:
        while True:
            try:
                result = ask_gemini(grab_frame(cap))
                errors = 0
                print(f"[{datetime.now():%H:%M:%S}] {result}")
                log(result)

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
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        cap.release()


if __name__ == "__main__":
    main()
