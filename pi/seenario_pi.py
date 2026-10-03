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

PROMPT = (
    "You are the eyes for a blind person walking forward, wearing a chest-level camera. "
    "Look at the image. Only report the single most important obstacle or hazard in their path "
    "(people, stairs, drop-offs, poles, vehicles, doors, walls, curbs, furniture, objects on the ground). "
    "Reply with ONE short spoken sentence in this order: "
    "what it is, where it is in the frame, how far away, and how to avoid it. "
    "Position: say left, center, or right, and add high (overhead or head level) "
    "or low (on the ground) when it matters. "
    "Distance: use steps (for example, 'about two steps'). "
    "Avoidance: tell them exactly what to do, such as 'step left', 'step right', "
    "'move slightly left', or 'stop' if there is no safe way around or it is a drop-off or stairs. "
    "Always step toward the side with more free space. "
    "Examples: "
    "'Chair low, center, two steps ahead. Step right.' "
    "'Person left, one step away. Move slightly right.' "
    "'Low hanging branch high, center, three steps. Duck or step left.' "
    "'Stairs down, center, two steps. Stop.' "
    "If the path ahead is clear, reply with exactly: CLEAR"
)

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
