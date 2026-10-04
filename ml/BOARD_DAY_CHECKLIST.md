# SensorTile.box day-one checklist

## 0. Before touching the board
- [ ] Ask your instructor/TA which ST tool is expected for the on-device model (NanoEdge AI Studio, the sensor's machine learning core, or STM32Cube.AI) and whether starter firmware is provided.
- [ ] Decide where the board is worn (belt or wrist) and use the **same spot and orientation for every recording and the final demo**.

## 1. Record data (accelerometer, same sampling rate every time, note it in `RATE` in train.py)
Save one CSV per recording with columns `ax, ay, az` (in g), named `<label>_<number>.csv`.
- [ ] `standing_01..03.csv` — 60 s each, include small shifts and arm movement
- [ ] `walking_01..03.csv` — 60 s each, vary pace a little; include turns
- [ ] `stumble_01..03.csv` — a safe stagger or sudden stop **every 1–2 seconds**; trim so every second of the file contains one. (Labels are per file, so a mostly-walking file labeled "stumble" will teach the model the wrong thing.)
- [ ] Get at least 3 files per label so some are held out for testing. More people/sessions = more trustworthy accuracy.
- Do the stumbles safely: a stagger or sudden stop on flat ground, nothing risky.

## 2. Train and check
- [ ] `python train.py --data data/`
- [ ] Record the held-out accuracy, confusion matrix, and false-stumble rate while walking. These go in your presentation.
- [ ] If walking gets flagged as stumble often, record more varied walking data before changing the model.

## 3. Deploy to the board
- [ ] Use the ST tool your instructor named to turn the labeled data into a model and flash it onto the board.
- [ ] Firmware sends **one byte** over Bluetooth when the state changes: 0 = standing, 1 = walking, 2 = stumble.
- [ ] Note the BLE service and characteristic UUIDs.

## 4. Connect the site
- [ ] Put the UUIDs into `BOX_SERVICE` and `BOX_CHAR` at the top of `app.js`.
- [ ] Open the site in Chrome or Edge over HTTPS, click "Connect SensorTile.box".
- [ ] Walk, stand, stagger: confirm the wearable label changes and a stumble appears in the log.
- [ ] Walk toward an obstacle: confirm the "STOP —" urgent alert.

## 5. Demo honestly
- Say which parts run on the board (the motion model) and which run in the cloud (the Gemini camera analysis).
- Show your held-out accuracy and false-alarm numbers, not just a live demo.
