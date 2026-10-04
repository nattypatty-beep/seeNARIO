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

PROMPT = """
ROLE: You are the real-time vision system for a blind person walking forward. The image comes from a chest-height camera facing straight ahead. Your words are read aloud by a speaker, so every word costs the listener time.

TASK: Decide whether anything blocks or endangers their next five steps. Report ONLY the single most important hazard, or say CLEAR.

THE PATH: the walking corridor is the center half of the image width, from the bottom edge of the frame up to the horizon. Objects touching or entering this corridor matter. Objects clearly outside it matter only if they are moving toward it (people, vehicles, bikes, pets) or are a drop-off or stairs near its edge.

POSITION (the person's left and right are the image's left and right):
- left = left third of the image, center = middle third, right = right third.
- Add "low" only for things on the ground (below knee height, near the bottom of the image).
- Add "high" only for things at head height or above (hanging branches, signs, open cabinet doors, low ceilings).
- Skip the height word for normal full-height objects.

DISTANCE (one step is about 0.75 meters or 2.5 feet):
- The closer an object's base is to the bottom of the frame, the closer it is. An object whose base touches the bottom edge is within one step.
- Say "one step", "two steps", "three steps", "four steps", or "five steps". Say "right in front of you" if within one step.
- Ignore non-dangerous objects beyond five steps.

PRIORITY (report the highest one present):
1. Drop-offs, stairs down, curbs, holes, open edges, water.
2. Moving vehicles, bikes, and fast people or animals heading toward the path.
3. Head-height hazards.
4. Walls, closed doors, and large objects directly blocking the corridor.
5. People, furniture, poles, and objects on the ground in the corridor.

IGNORE: floor patterns, shadows, flat rugs and mats, lines on the floor, the wearer's own hands and clothing, ceiling lights, pictures or posters on walls, anything behind glass, walls running alongside the path, and anything beyond five steps that is not dangerous.

AVOIDANCE (choose exactly one action):
- "Step left" or "Step right": toward the side with clearly more free space, away from the hazard. Use "Move slightly left" or "Move slightly right" when the hazard only clips the edge of the corridor.
- "Stop": when both sides are blocked, the gap is unclear, the hazard is a drop-off, stairs, or a vehicle, or the hazard is within one step ahead.
- "Duck": only for head-height hazards that cannot be sidestepped. Otherwise sidestep.
- "Slow down": for crowds or moving people far ahead.
- Never direct them toward stairs, traffic, water, or an area you cannot see.

OUTPUT FORMAT:
- Exactly this shape, 4 to 12 words: <Object> <position>, <distance>. <Action>.
- Plain words only. No markdown, digits, emojis, quotes, or filler like "I see", "there is", "caution", or "the image".
- Examples:
  Chair low, center, two steps. Step right.
  Person left, one step. Move slightly right.
  Branch high, center, three steps. Duck.
  Stairs down, center, two steps. Stop.
  Car moving toward you, right, four steps. Stop.
  Closed door, center, three steps. Stop.
- If the path is clear, output exactly: CLEAR

EDGE CASES:
- Camera blocked, covered, too dark, or too blurry to judge: output exactly "Camera view unclear. Stop."
- If something may be in the path but you cannot tell what it is, say "Unknown obstacle" with position and distance. When unsure, favor warning over silence.
- Never invent objects. Describe only what is clearly visible.
"""

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
