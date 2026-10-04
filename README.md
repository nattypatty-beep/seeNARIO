# SeeNARIO

**An AI-powered navigation assistant for blind and low-vision users.**
A chest-mounted webcam watches the path ahead, Gemini identifies obstacles, and a speaker tells the user what the obstacle is, where it is, how far away it is, and which way to step to avoid it. A live website shows what the system is seeing and saying.

Live site: https://seenario-phi.vercel.app

> **Prototype notice:** SeeNARIO is a class project and an assistive-technology prototype. It is **not** a safety device and must not replace a white cane, guide dog, or other mobility aids.

---

## How it works

```
Webcam  ->  Raspberry Pi  ->  Gemini vision  ->  guidance sentence  ->  Speaker
                  |
                  +--> live website (latest camera frame + guidance log)
```

1. The Pi grabs a frame from the webcam every few seconds.
2. The frame is sent to the Gemini API, which returns a structured list of hazards (label, type, bounding box, height, and which side has clear floor).
3. The Python code (not the AI) turns that list into one short sentence, for example: *"Chair low, center, two steps. Step right."*
4. Distance in steps is calculated from camera geometry (camera height, tilt, and field of view), with Gemini's estimate as a fallback.
5. The sentence is spoken aloud through ElevenLabs, or through a local computer voice if ElevenLabs isn't available.
6. If the path is clear, the system stays silent.
7. The latest frame and guidance log are uploaded to the website.

## Hardware

- Raspberry Pi
- USB webcam (Logitech)
- JBL Bluetooth speaker
- Internet connection (Wi-Fi) for the Gemini API

## Repository layout

```
index.html, app.js, api/   Website (hosted on Vercel)
pi/seenario_pi.py          Main program that runs on the Raspberry Pi
```

## Setup

### 1. Install dependencies

**Raspberry Pi**
```
sudo apt update
sudo apt install -y git python3-opencv python3-requests espeak-ng alsa-utils
git clone https://github.com/nattypatty-beep/seeNARIO.git
cd seeNARIO/pi
```

**Windows / Mac (for testing on a laptop)**
```
pip install opencv-python requests pyttsx3
```

### 2. Add your API keys

Create a file named `keys.txt` in your **home folder** (not inside the repo):

```
GEMINI_API_KEY=your-gemini-key
ELEVENLABS_API_KEY=your-elevenlabs-key   (optional)
PI_SECRET=your-website-secret
```

Get a free Gemini key at https://aistudio.google.com/apikey.
**Never commit keys to GitHub.** Keys can also be set as environment variables.

### 3. Connect the speaker (Pi)

Pair the JBL with `bluetoothctl` (`scan on`, `pair`, `trust`, `connect`), then choose it as the audio output.

### 4. Run

```
python3 seenario_pi.py --check   # tests keys, camera, Gemini, voice, and website
python3 seenario_pi.py --test    # speaker test only
python3 seenario_pi.py           # run the assistant (Ctrl+C to stop)
```

Use `python` instead of `python3` on Windows.

## Settings

Optional environment variables:

| Variable | Default | What it does |
|---|---|---|
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Which Gemini model to use |
| `INTERVAL_SECONDS` | `6` | Time between camera checks |
| `REPEAT_COOLDOWN` | `10` | Seconds before repeating the same warning |
| `CAMERA_INDEX` | `0` | Which camera to use |
| `CAMERA_HEIGHT_M` | `1.2` | Lens height above the floor (meters) |
| `CAMERA_PITCH_DEG` | `20` | Camera tilt downward (degrees) |
| `VFOV_DEG` | `40` | Camera vertical field of view (degrees) |
| `DIST_SCALE` | `1.0` | Calibration factor for distance |
| `UPLOAD_TO_SITE` | `1` | Set to `0` to turn off website uploads |
| `DEBUG` | off | Set to `1` to print Gemini's raw output |

## Troubleshooting

- **Webcam not found:** close other camera apps (Guvcview, Zoom), replug the webcam, or try `CAMERA_INDEX=1`.
- **Gemini 404 error:** the model name is unavailable; set `GEMINI_MODEL` to a current model.
- **Gemini 429 error:** free-tier rate limit reached; raise `INTERVAL_SECONDS` or use a Flash-Lite model.
- **No sound:** confirm the speaker is the default audio output and that `espeak-ng "test"` is audible.

## Limitations

- Vision runs in the cloud (Gemini API), so the system needs internet and has about 1 to 3 seconds of delay.
- Distance is an estimate from a single camera and depends on calibration. There is no depth sensor.
- The free Gemini tier has daily and per-minute limits.
- Not tested for outdoor, low-light, or crowded environments.
- Frames are sent to Google's API for analysis. Do not point the camera at private people or documents.

## Credits

**Team:** [your names here]
**Course:** [course name, instructor, semester]

**AI assistance:** Most of the code in this project was written with AI assistance:
- **Claude** (Anthropic) wrote most of the Raspberry Pi program (`pi/seenario_pi.py`), including the camera loop, the hazard-to-guidance logic, distance calculation, speech handling, and the setup instructions.
- **Gemini** (Google) powers the vision analysis at runtime and also helped write parts of the project code.

The team defined the project goals, directed the design, built and wired the hardware, tested the system, and integrated and debugged everything.

**Services and tools:** Google Gemini API, ElevenLabs text-to-speech, OpenCV, Vercel, espeak-ng.
