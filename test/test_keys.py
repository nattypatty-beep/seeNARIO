"""Checks your Gemini key, ElevenLabs key, and website from your normal computer.
Put a keys.txt (see src/keys.example.txt) in this same folder, then run:  python test_keys.py"""
import json, os, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(HERE, "keys.txt")
if os.path.exists(path):
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
ELEVEN_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
SITE_URL = os.environ.get("SITE_URL", "https://seenario-phi.vercel.app").rstrip("/")
PI_SECRET = os.environ.get("PI_SECRET", "seenarioPi2026xk4m")
VOICE = "21m00Tcm4TlvDq8ikWAM"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"


def post(url, body, headers):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "visionnav-test/1.0", **headers})
    return urllib.request.urlopen(req, timeout=20)


def check(name, fn):
    try:
        print(f"[ OK ] {name}: {fn()}")
    except urllib.error.HTTPError as e:
        print(f"[FAIL] {name}: HTTP {e.code} {e.read()[:200].decode(errors='ignore')}")
    except Exception as e:
        print(f"[FAIL] {name}: {e}")


def gemini():
    body = {"contents": [{"parts": [{"text": "Reply with one word: ready"}]}],
            "generationConfig": {"maxOutputTokens": 20, "thinkingConfig": {"thinkingBudget": 0}}}
    with post(GEMINI_URL, body, {"x-goog-api-key": GEMINI_KEY}) as r:
        return "Gemini said: " + json.load(r)["candidates"][0]["content"]["parts"][0]["text"].strip()


def eleven_mp3():
    body = {"text": "Chair ahead, center, close", "model_id": "eleven_flash_v2_5"}
    with post(f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}", body, {"xi-api-key": ELEVEN_KEY}) as r:
        data = r.read()
    with open(os.path.join(HERE, "test.mp3"), "wb") as f:
        f.write(data)
    return f"saved test.mp3 ({len(data)} bytes). Double-click it to hear the voice"


def eleven_pcm():
    body = {"text": "Path clear", "model_id": "eleven_flash_v2_5"}
    with post(f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}?output_format=pcm_24000", body,
              {"xi-api-key": ELEVEN_KEY}) as r:
        return f"{len(r.read())} bytes (the Pi speaker format works)"


def site():
    body = {"rows": [{"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                      "guidance": "Test from test_keys.py", "latency_s": 0}], "image": None}
    with post(SITE_URL + "/api/update", body, {"x-api-key": PI_SECRET}) as r:
        return f"HTTP {r.status}. Open {SITE_URL} and look for 'Test from test_keys.py'"


if GEMINI_KEY:
    check("Gemini key", gemini)
else:
    print("[SKIP] Gemini: no GEMINI_API_KEY in keys.txt")
if ELEVEN_KEY:
    check("ElevenLabs voice (mp3)", eleven_mp3)
    check("ElevenLabs voice (Pi format)", eleven_pcm)
else:
    print("[SKIP] ElevenLabs: no ELEVENLABS_API_KEY in keys.txt")
check("Website upload", site)
