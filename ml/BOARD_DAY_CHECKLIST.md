# SensorTile.box board-day guide

Based on ST's documentation. Anything marked **(unverified)** is a guess about screens or behavior I couldn't confirm, so follow the on-screen prompts if they differ.

## Step 0. Before you touch it
- [ ] Look at the box label. **SensorTile.box PRO** (STEVAL-MKBOXPRO) or the **original** (STEVAL-MKSBOX1V1)? This guide is written for the **PRO**. See "If you have the original" at the bottom.
- [ ] MyST account created on st.com, and you've opened **ST AIoT Craft** once in **Chrome or Edge** and signed in.
- [ ] USB-C cable (PRO) or micro-USB (original) that carries data, not charge-only.
- [ ] Board charged.
- [ ] Phone has the **ST BLE Sensor** app (Android/iOS).
- [ ] Teammates know the plan so you split roles: one wears the board, one logs and labels, one records video.

## Step 1. Check the board works (10 min)
1. Switch the board on and open **ST BLE Sensor** on your phone.
2. Tap the board in the device list. When asked for a pairing PIN, it is **123456**.
3. Open one of the built-in apps (for example the data logger or the human activity recognition one) and move the board. You should see the readings change.
4. If the board doesn't appear: close the app, switch your phone's Bluetooth off and on, power-cycle the board, and try again. If it still fails, your instructor or ST's quick start guide are next.

## Step 2. Put the data-logging firmware on it (15 min)
1. Open **AIoT Craft** in Chrome or Edge on a computer. Open the **human activity recognition** example project (it targets the PRO and its LSM6DSV16X sensor).
2. Plug the board into the computer with USB-C.
3. Enter **DFU mode**: hold **user button 2** while turning the board on with its power switch.
4. In AIoT Craft click **Update the firmware**, then **Flash firmware**. The firmware is called **FP-SNS-DATALOG2_Datalog2**. Chrome will ask permission to access the device, so allow it.
5. After flashing, the board should show up in AIoT Craft. **(unverified)** You may need to switch the board off and on again.

## Step 3. Try ST's example first (15 min)
Run the human activity recognition example on your board. It classifies running, walking, standing, and sitting. This proves your whole toolchain works before you build your own model. Screenshot it.

## Step 4. Build your model (the main task)
1. In AIoT Craft, start a **new project** (or clone the example) targeting **SensorTile.box PRO** with the **LSM6DSV16X machine learning core**. **(unverified: exact menu names)**
2. Define three classes: `standing`, `walking`, `stumble`.
3. Wear the board where you'll wear it in the demo (belt or wrist) and **keep it in exactly the same position and orientation for everything**.
4. **Log data and label it** with the tool's data-collection view. Aim for several minutes per class, from at least two people:
   - standing: still, with small shifts and arm movement
   - walking: normal pace with turns, some slower and some faster
   - stumble: a safe stagger or sudden stop every 1 to 2 seconds for the whole recording, on flat ground. Don't actually risk a fall.
5. Click **Train**. The tool picks features, filters, and window size automatically.
6. Write down what accuracy or confusion results the tool reports. **(unverified: exactly what it displays)** These are your presentation numbers. If it confuses walking and stumble, record more varied data and retrain.
7. **Deploy:** the trained model is downloaded and programmed onto the board, where it runs inside the sensor's machine learning core. Test it live: stand, walk, stagger. **Screen-record this.** This is your "model deployed to the edge device" evidence.

## Step 5. Show it working with the rest of the project
Your website runs the camera and Gemini part. The easiest honest demo:
- the board classifying live (in AIoT Craft or ST's app, on screen)
- the website showing the camera alerts
- the phone motion mode as a clearly-labeled backup

## Step 6. Optional: connect the board to your website
This is the least certain part. I found no documentation showing how to read the board's classifier result from a custom web page, so treat it as a stretch goal.
1. Install **nRF Connect** (free phone app), scan, and connect to the board running your deployed firmware. Note which services and characteristics appear.
2. Open `ble-explorer.html` (served from your site, in Chrome/Edge), enter those service UUIDs, connect, and watch which characteristics send changing data while you move the board.
3. If one of them clearly carries the classification, put its UUIDs and decoding into `BOX_SERVICE` / `BOX_CHAR` in `app.js` and adjust the `connectBox` byte reading. If nothing obvious shows up, stop and use the Step 5 demo.

## Step 7. Evidence to collect (do this as you go)
- [ ] Photo of the board being worn
- [ ] Screenshot of the example project working (Step 3)
- [ ] Screenshot of your data labeled by class (Step 4)
- [ ] Screenshot of the training results with accuracy numbers
- [ ] Screen recording of the deployed model classifying live
- [ ] Short demo video of the whole system

## If you have the original SensorTile.box
ST's AIoT Craft support list names the PRO, not the original, so I can't promise this path works. ST says the original board's Expert Mode in the phone app lets you build custom apps without programming, and its motion sensor also has a machine learning core. Ask your instructor which tools to use before spending time on it.

## Troubleshooting
- **Browser doesn't see the board:** use Chrome or Edge, try another cable, retry DFU mode.
- **Board won't pair:** close the ST app, toggle phone Bluetooth, power-cycle the board.
- **Model confuses walking and stumble:** record more varied walking, make stumbles more clearly different, and keep the board position identical.
