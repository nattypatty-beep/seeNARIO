# SeeNARIO

**An AI-powered wearable navigation designed for blind and low-vision users.**

A wearable webcam watches the path ahead, Gemini identifies obstacles, and an ElevenLabs voice tells the user what the obstacle is, where it is, how far away it is, and which way to step to avoid it. A live website shows what the system is seeing and saying for record keeping or for use of a caregiver or family member.

Live site:(https://seenario-phi.vercel.app)

This is a functioning prototype, not a fully formed mobility aid.

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

1. **Edge Motion Monitoring:** The wearable node specifications target the STMicroelectronics SensorTile.box tracking body acceleration via an LSM6DSOX 3-axis accelerometer to run anomaly detection for stumbles.
2. **Visual Hazard Analysis:** Upon a motion trigger or continuous timer from the Sensortile.box, the Pi grabs a frame from the webcam every few seconds.
3. **AI Scene Processing:** The frame is sent to the Gemini API, which returns a structured list of hazards (label, type, bounding box, height, and which side is clear).
4. **Deterministic Guidance Logic:** The Python code turns that list into one short sentence, for example: *"Chair low, center, two steps. Step right."*
5. **Geometry Calculation:** Distance in steps is calculated from camera geometry (camera height, tilt, and field of view), with Gemini's estimate as a fallback.
6. **Audio Output:** The sentence is spoken aloud through ElevenLabs, or through a local computer voice if ElevenLabs isn't available. If the path is clear, the system stays silent.
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
## Repository Structure

```text
api/
├── data.js
└── update.js

ml/
├── BOARD_DAY_CHECKLIST.md
├── calibrate_camera.py
├── check_recording.py
├── data/
├── loader.py
├── test_all.py
└── train.py

pi/
├── seenario_pi.py
├── sensortile/
├── model_config.json
├── sensortile_anomaly.py
├── main.c
├── start.sh
├── uploader.py
├── vision.py
└── visionnav.py

test/
├── lilastryC
├── pi_logitech_vision.py
├── test_keys.py
└── test_vision.py

.gitignore
README.md
app.js
ble-explorer.html
emulate_sensortile.py
index.html
model.js
recorder.html
sensortile.js
```


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

## Limitations

* Vision runs in the cloud (Gemini API), so the system needs internet and has about 1 to 3 seconds of delay.
* Distance is an estimate from a single camera and depends on calibration. There is no physical depth sensor.
* Motion anomaly detection runs on 3-axis accelerometer vectors, which require calibration to avoid false positives during rapid walking.
* The free Gemini tier has daily and per-minute limits.
* Limited testing done in a controlled enviroment.

---

## Credits

**Team:** Natalia Bernardo, Dhriti Belani, Nacy Alie, Lila Menard

Made for WolfHacks Hackathon October 2026

**AI assistance:** Most of the code in this project was written with AI assistance:

* **Claude** (Anthropic) wrote most of the Raspberry Pi program (`pi/seenario_pi.py`), including the camera loop, the hazard-to-guidance logic, distance calculation, speech handling, and the setup instructions.
* **Gemini** (Google) powers the vision analysis at runtime and also helped write parts of the project code, native C implementations, and ST SensorTile.box edge ML integrations.
* **ChatGPT** (OpenAI) wrote troubleshooting and website ideas.

The team defined the project goals, directed the design, built and wired the hardware, tested the system, and integrated and debugged everything.

**Services and tools:** STMicroelectronics SensorTile.box, Rasberry Pi, Google Gemini API, ElevenLabs text-to-speech, OpenCV, Vercel, espeak-ng.
