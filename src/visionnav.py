#!/usr/bin/env python3
"""VisionNav: camera -> Gemini -> ElevenLabs voice -> SeeNARIO website. No compiling needed."""
import base64, json, os, shutil, subprocess, time, urllib.error, urllib.request
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))


def load_keys():
    path = os.path.join(HERE, "keys.txt")
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


load_keys()
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
ELEVEN_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
SITE_URL = os.environ.get("SITE_URL", "https://seenario-phi.vercel.app").rstrip("/")
PI_SECRET = os.environ.get("PI_SECRET", "seenarioPi2026xk4m")
VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel
CYCLE = 6.5  # seconds per scan; keeps under Gemini's free-tier limit
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
PROMPT = (
    "You are a navigation aid for a visually impaired walker. Look at the camera view. "
    "Name the nearest hazard in the walking path, its direction (left, center, right) and "
    "whether it is close or far. Max 6 words, e.g. 'Chair ahead, center, close'. "
    "If the path is safe, reply exactly: Path clear"
)

if not GEMINI_KEY:
    raise SystemExit("keys.txt is missing GEMINI_API_KEY (see keys.example.txt)")


def post_json(url, body, headers, timeout=15):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "visionnav-pi/1.0", **headers},
    )
    return urllib.request.urlopen(req, timeout=timeout)


def ask_gemini(jpg):
    body = {
        "system_instruction": {"parts": [{"text": PROMPT}]},
        "contents": [{"parts": [{"inline_data": {"mime_type": "image/jpeg",
                                                 "data": base64.b64encode(jpg).decode()}}]}],
        "generationConfig": {"maxOutputTokens": 30, "temperature": 0.2,
                             "thinkingConfig": {"thinkingBudget": 0}},
    }
    with post_json(GEMINI_URL, body, {"x-goog-api-key": GEMINI_KEY}) as r:
        data = json.load(r)
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def speak(text):
    if not ELEVEN_KEY:
        return
    base = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
    # FIX: use eleven_turbo_v2_5 (flash renamed) and pcm_16000 which Pi aplay handles reliably
    body = {"text": text, "model_id": "eleven_turbo_v2_5"}
    hdr = {"xi-api-key": ELEVEN_KEY}
    if shutil.which("aplay"):
        try:
            with post_json(base + "?output_format=pcm_16000", body, hdr) as r:
                audio = r.read()
            subprocess.run(["aplay", "-q", "-t", "raw", "-f", "S16_LE", "-r", "16000", "-c", "1"],
                           input=audio)
            return
        except urllib.error.HTTPError as e:
            print("voice (pcm_16000) failed:", e.code, e.read().decode()[:200], "- trying mp3")
        except Exception as e:
            print("voice (pcm) error:", e, "- trying mp3")
    players = (["mpg123", "-q", "-"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-"])
    player = next((p for p in players if shutil.which(p[0])), None)
    if player:
        try:
            body_mp3 = {"text": text, "model_id": "eleven_turbo_v2_5"}
            with post_json(base, body_mp3, hdr) as r:
                audio = r.read()
            subprocess.run(player, input=audio)
        except Exception as e:
            print("voice (mp3) failed:", e)
    else:
        print("no audio player found (need aplay, mpg123 or ffplay)")


def upload(rows, jpg):
    image = "data:image/jpeg;base64," + base64.b64encode(jpg).decode()
    with post_json(SITE_URL + "/api/update", {"rows": rows, "image": image},
                   {"x-api-key": PI_SECRET}) as r:
        return r.status


# FIX: open camera with V4L2 backend on Pi to prevent frozen frames
cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
if not cap.isOpened():
    # fallback to default backend
    cap = cv2.VideoCapture(0)
if not cap.isOpened():
    raise SystemExit("Can't open the camera. Is the webcam plugged in?")

# FIX: set buffer size to 1 so we always get the latest frame, not a stale one
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

rows = []
last_spoken, last_spoken_at = "", 0.0
print("VisionNav running (Ctrl+C to stop)")
try:
    while True:
        start = time.time()
        try:
            # FIX: grab more stale frames and do a fresh read to unfreeze
            for _ in range(5):
                cap.grab()
            ok, frame = cap.retrieve()
            if not ok:
                # try a full read as fallback
                ok, frame = cap.read()
            if not ok:
                print("no camera frame — reinitialising camera")
                cap.release()
                time.sleep(1)
                cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                time.sleep(1)
                continue
            frame = cv2.resize(frame, (640, 480))
            jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()

            guidance = ask_gemini(jpg)
            latency = round(time.time() - start, 2)
            print(f"[Guidance] {guidance} ({latency}s)")
            rows.append({"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                         "guidance": guidance, "latency_s": latency})
            rows = rows[-20:]

            try:
                upload(rows, jpg)
            except Exception as e:
                print("upload failed:", e)

            now = time.time()
            if guidance != last_spoken or (guidance != "Path clear" and now - last_spoken_at > 8):
                try:
                    speak(guidance)
                except Exception as e:
                    print("voice failed:", e)
                last_spoken, last_spoken_at = guidance, time.time()
        except Exception as e:
            print("error:", e)
            if isinstance(e, urllib.error.HTTPError) and e.code == 429:
                print("Gemini rate limit hit; waiting 30 seconds")
                time.sleep(30)

        time.sleep(max(0, CYCLE - (time.time() - start)))
except KeyboardInterrupt:
    pass
finally:
    cap.release()
    print("Stopped.")
