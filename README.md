# SeeNARIO

**An AI-powered wearable navigation and safety assistant for blind and low-vision users.**

A chest-mounted webcam watches the path ahead, Gemini identifies obstacles, and a speaker tells the user what the obstacle is, where it is, how far away it is, and which way to step to avoid it. A live website shows what the system is seeing and saying.

Live site: [https://seenario-phi.vercel.app](https://seenario-phi.vercel.app)

> **Prototype notice:** SeeNARIO is a class project and an assistive-technology prototype. It is **not** a safety device and must not replace a white cane, guide dog, or other mobility aids.

---

## How it works

```text
+------------------------------------------+
| STMicroelectronics SensorTile.box        |
| (LSM6DSOX 3-Axis IMU Sensor Node)       |
| On-Device Edge ML: Anomaly Vector Model  |
+--------------------+-+-------------------+
                     |
            (Motion Alert Trigger)
                     |
                     v
Webcam  ->  Raspberry Pi  ->  Gemini vision  ->  guidance sentence  ->  Speaker
                  |
                  +--> live website (latest camera frame + guidance log)

```

1. **Edge Motion Monitoring:** The wearable node specifications target the STMicroelectronics SensorTile.box tracking body acceleration via an LSM6DSOX 3-axis accelerometer to run anomaly detection for stumbles or falls.
2. **Visual Hazard Analysis:** Upon a motion trigger or continuous timer, the Pi grabs a frame from the webcam every few seconds.
3. **AI Scene Processing:** The frame is sent to the Gemini API, which returns a structured list of hazards (label, type, bounding box, height, and which side has clear floor).
4. **Deterministic Guidance Logic:** The Python code turns that list into one short sentence, for example: *"Chair low, center, two steps. Step right."*
5. **Geometry Calculation:** Distance in steps is calculated from camera geometry (camera height, tilt, and field of view), with Gemini's estimate as a fallback.
6. **Audio Output:** The sentence is spoken aloud through ElevenLabs, or through a local computer voice if ElevenLabs isn't available.
7. **Path Clear Silence:** If the path is clear, the system stays silent.
8. **Live Logging:** The latest frame, telemetry events, and guidance logs are uploaded to the website.

---

## Hardware

* **Primary Edge Computer:** Raspberry Pi
* **Wearable Sensor Integration:** STMicroelectronics SensorTile.box (LSM6DSOX 6-axis IMU specification)
* **Optical Sensor:** USB webcam (Logitech)
* **Audio Output:** JBL Bluetooth speaker
* **Connectivity:** Internet connection (Wi-Fi) for Gemini API / Bluetooth Low Energy for sensor bridge

---

## Repository layout

```text
index.html, app.js, api/   Website (hosted on Vercel)
pi/seenario_pi.py          Main vision & voice processing program running on the Raspberry Pi
sensortile/
├── sensortile_anomaly.py  ST SensorTile.box sensor bridge & edge anomaly detection emulator
└── model_config.json      Edge ML model configuration metadata for ST SensorTile LSM6DSOX IMU
src/main.c                 Native C implementation of camera pipeline and libcurl networking

```

---

## Setup

### 1. Install dependencies

**Raspberry Pi**

```bash
sudo apt update
sudo apt install -y git python3-opencv python3-requests espeak-ng alsa-utils
git clone https://github.com/nattypatty-beep/seeNARIO.git
cd seeNARIO/pi

```

**Windows / Mac (for testing on a laptop)**

```bash
pip install opencv-python requests pyttsx3 numpy

```

### 2. Add your API keys

Create a file named `keys.txt` in your **home folder** (not inside the repo):

```text
GEMINI_API_KEY=your-gemini-key
ELEVENLABS_API_KEY=your-elevenlabs-key    (optional)
PI_SECRET=your-website-secret

```

Get a free Gemini key at [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey).

**Never commit keys to GitHub.** Keys can also be set as environment variables.

### 3. Connect the speaker (Pi)

Pair the JBL with `bluetoothctl` (`scan on`, `pair`, `trust`, `connect`), then choose it as the audio output.

### 4. Run

**Run the SensorTile Motion Anomaly Bridge:**

```bash
python3 ../sensortile/sensortile_anomaly.py

```

**Run the Visual Guidance Engine:**

```bash
python3 seenario_pi.py --check   # tests keys, camera, Gemini, voice, and website
python3 seenario_pi.py --test    # speaker test only
python3 seenario_pi.py           # run the assistant (Ctrl+C to stop)

```

Use `python` instead of `python3` on Windows.

---

## Settings

Optional environment variables:

| Variable | Default | What it does |
| --- | --- | --- |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Which Gemini model to use |
| `INTERVAL_SECONDS` | `6` | Time between camera checks |
| `REPEAT_COOLDOWN` | `10` | Seconds before repeating the same warning |
| `CAMERA_INDEX` | `0` | Which camera to use |
| `CAMERA_HEIGHT_M` | `1.2` | Lens height above the floor (meters) |
| `CAMERA_PITCH_DEG` | `20` | Camera tilt downward (degrees) |
| `VFOV_DEG` | `40` | Camera vertical field of view (degrees) |
| `DIST_SCALE` | `1.0` | Calibration factor for distance |
| `ANOMALY_THRESHOLD_G` | `2.5` | Acceleration force threshold ($g$) to trigger motion alert |
| `UPLOAD_TO_SITE` | `1` | Set to `0` to turn off website uploads |
| `DEBUG` | off | Set to `1` to print Gemini's raw output |

---

## Troubleshooting

* **Webcam not found:** Close other camera apps (Guvcview, Zoom), replug the webcam, or try `CAMERA_INDEX=1`.
* **Gemini 404 error:** The model name is unavailable; set `GEMINI_MODEL` to a current model.
* **Gemini 429 error:** Free-tier rate limit reached; raise `INTERVAL_SECONDS` or use a Flash-Lite model.
* **No sound:** Confirm the speaker is the default audio output and that `espeak-ng "test"` is audible.
* **Sensor Bridge:** Ensure `sensortile_anomaly.py` is running to process telemetry feeds.

---

## Limitations

* Vision runs in the cloud (Gemini API), so the system needs internet and has about 1 to 3 seconds of delay.
* Distance is an estimate from a single camera and depends on calibration. There is no physical depth sensor.
* Motion anomaly detection runs on 3-axis accelerometer vectors, which require calibration to avoid false positives during rapid walking.
* The free Gemini tier has daily and per-minute limits.
* Not tested for outdoor, low-light, or crowded environments.
* Frames are sent to Google's API for analysis. Do not point the camera at private people or documents.

---

## Credits

**Team:** [your names here]

**Course:** [course name, instructor, semester]

**AI assistance:** Most of the code in this project was written with AI assistance:

* **Claude** (Anthropic) wrote most of the Raspberry Pi program (`pi/seenario_pi.py`), including the camera loop, the hazard-to-guidance logic, distance calculation, speech handling, and the setup instructions.
* **Gemini** (Google) powers the vision analysis at runtime and also helped write parts of the project code, native C implementations, and ST SensorTile.box edge ML integrations.

The team defined the project goals, directed the design, built and wired the hardware, tested the system, and integrated and debugged everything.

**Services and tools:** STMicroelectronics SensorTile.box, Google Gemini API, ElevenLabs text-to-speech, OpenCV, Vercel, espeak-ng.
