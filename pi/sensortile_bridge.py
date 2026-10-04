#!/usr/bin/env python3
"""
SeeNARIO SensorTile.box bridge (runs on the Raspberry Pi).

Reads the board's accelerometer over Bluetooth LE, cuts it into 1-second windows at 50 Hz,
and classifies each window as standing / walking / stumble with YOUR trained decision tree
(the same tree as model.js, trained by ml/train.py). A stumble must be seen twice in a row
before the Pi says a warning.

The inference runs on the Raspberry Pi (an edge device). It does NOT run inside the
board's own sensor chip. Say that plainly when you present.

COMMANDS (python3 on the Pi):
  python3 sensortile_bridge.py --simulate          # no board needed: test the whole pipeline
  python3 sensortile_bridge.py --scan              # list nearby Bluetooth devices
  python3 sensortile_bridge.py --dump              # show raw packets from the board
  python3 sensortile_bridge.py                     # auto-detect the accelerometer, then run
  python3 sensortile_bridge.py --record walking_me_01.csv --seconds 60
                                                   # save board data in the format ml/train.py reads

Keep the board STILL for the first 6 seconds of a normal run: that is how the program finds
which Bluetooth packets are the accelerometer (a still board reads about 1 g).
Close the ST BLE Sensor app on your phone first. The board allows one connection at a time.
"""
import argparse
import asyncio
import bisect
import json
import math
import os
import random
import shutil
import statistics
import struct
import subprocess
import sys
import threading
import time
import urllib.request
from collections import deque

RATE = 50
WIN = 50          # samples per window (1 second)
HOP = 0.5         # seconds between windows (50% overlap)
LABELS = ["standing", "walking", "stumble"]
STATE_FILE = os.environ.get("MOTION_STATE_FILE", os.path.expanduser("~/seenario_motion.json"))
CFG_FILE = os.path.expanduser("~/.seenario_sensortile.json")
SPEAK_COOLDOWN = 6.0
HERE = os.path.dirname(os.path.abspath(__file__))


def load_keys():
    """Same lookup as seenario_pi.py: keys.txt in this folder, the one above, or your home folder."""
    for folder in (HERE, os.path.dirname(HERE), os.path.expanduser("~")):
        p = os.path.join(folder, "keys.txt")
        if os.path.isfile(p):
            for line in open(p, encoding="utf-8-sig", errors="ignore"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_keys()
SITE_URL = os.environ.get("SITE_URL", "https://seenario-phi.vercel.app").rstrip("/")
PI_SECRET = os.environ.get("PI_SECRET", "")
_latest = {"state": None, "stumbles": 0}
_post_enabled = False


# ---------------------------------------------------------------- the trained model
def features(w):
    """w: list of (x, y, z) in g. Same features as ml/train.py and model.js."""
    mean = lambda a: sum(a) / len(a)
    sd = lambda a: math.sqrt(mean([(v - mean(a)) ** 2 for v in a]))
    m = [math.sqrt(x * x + y * y + z * z) for x, y, z in w]
    mn, mx = min(m), max(m)
    return {"mag_mean": mean(m), "mag_std": sd(m), "mag_min": mn, "mag_max": mx, "mag_ptp": mx - mn,
            "energy": mean([v * v for v in m]),
            "ax_std": sd([s[0] for s in w]), "ay_std": sd([s[1] for s in w]), "az_std": sd([s[2] for s in w])}


def classify(w):
    """Decision tree copied from model.js. If you retrain, regenerate this function."""
    f = features(w)
    if f["mag_max"] <= 1.090004563331604:
        c = 1 if f["energy"] <= 0.9915416240692139 else 0
    else:
        if f["mag_mean"] <= 1.0970352292060852:
            if f["mag_min"] <= 0.36330699920654297:
                c = 2
            else:
                c = 1
        else:
            if f["mag_max"] <= 2.5377397537231445:
                c = 2 if f["ax_std"] <= 0.19127246737480164 else 1
            else:
                c = 2
    return LABELS[c]


# ---------------------------------------------------------------- windowing
class Stream:
    """Keeps recent (time, x, y, z) samples and resamples the last second to 50 Hz."""

    def __init__(self):
        self.buf = deque(maxlen=1500)

    def add(self, t, x, y, z):
        self.buf.append((t, x, y, z))

    def window(self, now):
        b = list(self.buf)
        if len(b) < 10 or b[0][0] > now - 1.0 or b[-1][0] < now - 0.3:
            return None
        ts = [r[0] for r in b]
        out = []
        for i in range(WIN):
            t = now - 1.0 + i / WIN
            j = bisect.bisect_left(ts, t)
            if j <= 0:
                out.append(b[0][1:])
            elif j >= len(b):
                out.append(b[-1][1:])
            else:
                (t0, *p0), (t1, *p1) = b[j - 1], b[j]
                a = 0 if t1 == t0 else (t - t0) / (t1 - t0)
                out.append(tuple(p0[k] + a * (p1[k] - p0[k]) for k in range(3)))
        return out


class Decider:
    """Turns window labels into events. A stumble needs two in a row (fewer false alarms)."""

    def __init__(self, speak=True):
        self.prev = None
        self.state = "unknown"
        self.last_spoken = 0.0
        self.stumbles = 0
        self.speak = speak

    def update(self, label, now):
        event = None
        confirmed = label if label != "stumble" else ("stumble" if self.prev == "stumble" else self.state)
        if label == "stumble" and self.prev == "stumble" and self.state != "stumble":
            self.stumbles += 1
            event = "STUMBLE"
            if self.speak and now - self.last_spoken > SPEAK_COOLDOWN:
                self.last_spoken = now
                say("Warning. Unsteady movement detected.")
        self.prev = label
        if confirmed != "unknown":
            self.state = confirmed
        return self.state, event


def say(text):
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    if exe:
        subprocess.Popen([exe, text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        print("   (install espeak-ng to hear this):", text)


def post_loop():
    """Background thread: send the latest state to the website every 2 seconds."""
    warned = False
    while True:
        time.sleep(2)
        if not _latest["state"]:
            continue
        try:
            req = urllib.request.Request(
                SITE_URL + "/api/motion",
                data=json.dumps(_latest).encode(),
                headers={"Content-Type": "application/json", "x-api-key": PI_SECRET},
                method="POST")
            urllib.request.urlopen(req, timeout=8).read()
            if warned:
                print("   website upload working again")
            warned = False
        except Exception as e:
            if not warned:
                print(f"   (website upload failed: {e}. Check PI_SECRET matches Vercel, and that api/motion.js is deployed.)")
                warned = True


def start_posting():
    global _post_enabled
    if not PI_SECRET:
        print("NOTE: PI_SECRET not set in keys.txt, so the website will not be updated.")
        return
    _post_enabled = True
    threading.Thread(target=post_loop, daemon=True).start()
    print("Sending the state to", SITE_URL, "every 2 s")


def write_state(state, stumbles):
    _latest.update(state=state if state in LABELS else None, stumbles=stumbles)
    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"state": state, "stumbles": stumbles, "updated": time.time()}, f)
        os.replace(tmp, STATE_FILE)
    except OSError:
        pass


def report(stream, decider, now, raw_label=None):
    w = stream.window(now)
    if w is None:
        return
    label = classify(w)
    state, event = decider.update(label, now)
    f = features(w)
    print(f"{time.strftime('%H:%M:%S')}  window={label:<8} confirmed={state:<8} "
          f"mag_mean={f['mag_mean']:.2f} mag_max={f['mag_max']:.2f}" + ("   <-- STUMBLE" if event else ""))
    write_state(state, decider.stumbles)


# ---------------------------------------------------------------- simulation (no board)
def simulate(slow=False):
    print("SIMULATION: fake accelerometer data, real classifier. No board involved.\n")
    rng = random.Random(1)
    stream, decider = Stream(), Decider(speak=False)
    t = 0.0
    next_report = 1.0
    phases = [("standing", 8), ("walking", 10), ("stumble", 8), ("standing", 6)]
    for name, secs in phases:
        print(f"--- simulating: {name} for {secs}s")
        end = t + secs
        while t < end:
            n = int(round((t) * RATE))
            if name == "standing":
                x, y, z = rng.gauss(0, .01), rng.gauss(0, .01), 1 + rng.gauss(0, .01)
            else:
                f = 1.9
                z = 1 + 0.3 * math.sin(2 * math.pi * f * t) + rng.gauss(0, .04)
                x = 0.1 * math.sin(math.pi * f * t) + rng.gauss(0, .03)
                y = rng.gauss(0, .03)
                if name == "stumble" and (t % 1.2) < 0.3:
                    z += 2.0 * math.sin(math.pi * (t % 1.2) / 0.3)
                    x += rng.gauss(0, .4)
            stream.add(t, x, y, z)
            t += 1.0 / RATE
            if t >= next_report:
                report(stream, decider, t)
                next_report += HOP
                if slow:
                    time.sleep(HOP)  # real time, so the website can follow along
    print("\nSimulation finished. Stumbles confirmed:", decider.stumbles)


# ---------------------------------------------------------------- Bluetooth
def parse(data, fmt, offset, scale):
    """Return (x, y, z) in g or None."""
    try:
        if fmt == "i16":
            if len(data) < offset + 6:
                return None
            v = struct.unpack_from("<hhh", data, offset)
        else:
            if len(data) < offset + 12:
                return None
            v = struct.unpack_from("<fff", data, offset)
        return tuple(a * scale for a in v)
    except struct.error:
        return None


def autodetect(packets):
    """packets: {uuid: [bytes, ...]} captured while the board was still.
    Looks for 3 consecutive numbers whose length is about 1 g and that barely change."""
    cands = []
    for uuid, plist in packets.items():
        if len(plist) < 5:
            continue
        maxlen = max(len(p) for p in plist)
        for fmt, scale, size in (("i16", 0.001, 6), ("f32", 1.0, 12)):
            for off in range(0, maxlen - size + 1):
                mags = []
                for p in plist:
                    s = parse(p, fmt, off, scale)
                    if s is None or not all(math.isfinite(a) for a in s):
                        break
                    mags.append(math.sqrt(sum(a * a for a in s)))
                else:
                    med = statistics.median(mags)
                    sd = statistics.pstdev(mags)
                    if 0.9 <= med <= 1.1 and sd < 0.08:
                        cands.append((abs(med - 1) + sd, uuid, fmt, off, scale, med, sd, len(plist)))
    cands.sort()
    return cands


async def ble_main(args):
    try:
        from bleak import BleakClient, BleakScanner
    except ImportError:
        sys.exit("bleak is not installed. Run:  source ~/seenario-venv/bin/activate && pip install bleak")

    if args.scan:
        print("Scanning 10 seconds...")
        found = await BleakScanner.discover(timeout=10.0, return_adv=True)
        for addr, (dev, adv) in sorted(found.items(), key=lambda kv: -kv[1][1].rssi):
            print(f"{addr}  rssi={adv.rssi:>4}  name={dev.name or adv.local_name or '-'}")
        print("\nYour board is probably named STB_PRO or similar.")
        return

    address = args.address
    if not address:
        print(f"Looking for a device with '{args.name}' in its name (10 s)...")
        dev = await BleakScanner.find_device_by_filter(
            lambda d, a: args.name.lower() in ((d.name or a.local_name or "").lower()), timeout=10.0)
        if dev is None:
            sys.exit("Board not found. Switch it on, close the ST BLE Sensor app, and try --scan.")
        address = dev.address
        print("Found", dev.name, address)

    packets, stream, decider = {}, Stream(), Decider(speak=not args.quiet)
    cfg = None
    if os.path.isfile(CFG_FILE) and not args.redetect and not args.dump and not args.char:
        cfg = json.load(open(CFG_FILE))
        print("Using saved accelerometer setting:", cfg)
    if args.char:
        cfg = {"uuid": args.char.lower(), "fmt": args.fmt, "offset": args.offset, "scale": args.scale}

    record_rows = []

    def on_data(sender, data):
        uuid = str(getattr(sender, "uuid", sender)).lower()
        now = time.monotonic()
        if args.dump:
            print(f"{uuid}  len={len(data):>3}  {bytes(data).hex(' ')}")
            return
        if cfg is None:
            packets.setdefault(uuid, []).append(bytes(data))
        elif uuid == cfg["uuid"]:
            s = parse(bytes(data), cfg["fmt"], cfg["offset"], cfg["scale"])
            if s:
                stream.add(now, *s)
                if args.record:
                    record_rows.append((now, *s))

    async with BleakClient(address) as client:
        print("Connected. (If it asks for a PIN, it is 123456.)")
        n = 0
        for svc in client.services:
            for ch in svc.characteristics:
                if "notify" in ch.properties:
                    try:
                        await client.start_notify(ch, on_data)
                        n += 1
                    except Exception as e:  # some characteristics refuse
                        print("  could not subscribe to", ch.uuid, "-", e)
        print(f"Subscribed to {n} notifying characteristics.")
        if n == 0:
            sys.exit("Nothing to listen to. See the notes: upload an Expert-view app that streams the accelerometer.")

        if args.dump:
            print(f"Showing raw packets for {args.seconds} s. Move the board and watch which lines change.\n")
            await asyncio.sleep(args.seconds)
            return

        if cfg is None:
            print(f"\nKEEP THE BOARD STILL for {args.detect} seconds so I can find the accelerometer...")
            await asyncio.sleep(args.detect)
            cands = autodetect(packets)
            if not cands:
                got = {u: len(p) for u, p in packets.items()}
                sys.exit(f"Could not find an accelerometer reading of about 1 g. Packets seen: {got}\n"
                         "Run --dump to look at the raw bytes, or upload an Expert-view app that streams "
                         "the accelerometer, then try again.")
            print("Candidates (best first):")
            for c in cands[:5]:
                print(f"  uuid={c[1]} fmt={c[2]} offset={c[3]}  magnitude={c[5]:.3f} g  noise={c[6]:.3f}")
            _, uuid, fmt, off, scale, *_ = cands[0]
            cfg = {"uuid": uuid, "fmt": fmt, "offset": off, "scale": scale}  # the callback sees this
            json.dump(cfg, open(CFG_FILE, "w"))
            print("Using the best candidate and saving it to", CFG_FILE)

        print("\nRunning. Stand, walk, then stagger. Ctrl+C to stop.\n")
        start = time.monotonic()
        next_report = start + 1.2
        try:
            while True:
                await asyncio.sleep(0.05)
                now = time.monotonic()
                if args.record and now - start >= args.seconds:
                    break
                if not args.record and now >= next_report:
                    report(stream, decider, now)
                    next_report += HOP
        except KeyboardInterrupt:
            pass
        if args.record:
            t0 = record_rows[0][0] if record_rows else 0
            with open(args.record, "w") as f:
                f.write("time_s,ax,ay,az\n")
                for t, x, y, z in record_rows:
                    f.write(f"{t - t0:.4f},{x:.5f},{y:.5f},{z:.5f}\n")
            span = (record_rows[-1][0] - t0) if record_rows else 0
            print(f"Saved {len(record_rows)} samples ({span:.1f} s, about {len(record_rows)/max(span,1):.0f} Hz) to {args.record}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--simulate", action="store_true", help="test with fake data, no board")
    ap.add_argument("--scan", action="store_true", help="list nearby Bluetooth devices")
    ap.add_argument("--dump", action="store_true", help="print raw packets from every notifying characteristic")
    ap.add_argument("--name", default="STB", help="part of the board's Bluetooth name (default STB)")
    ap.add_argument("--address", help="Bluetooth address, if you know it")
    ap.add_argument("--seconds", type=float, default=60, help="length for --dump or --record")
    ap.add_argument("--detect", type=float, default=6, help="seconds of stillness used to find the accelerometer")
    ap.add_argument("--redetect", action="store_true", help="ignore the saved accelerometer setting")
    ap.add_argument("--char", help="manual: characteristic UUID of the accelerometer")
    ap.add_argument("--fmt", choices=["i16", "f32"], default="i16")
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--scale", type=float, default=0.001, help="multiply raw values by this to get g")
    ap.add_argument("--record", help="save a CSV for ml/train.py (use with --seconds)")
    ap.add_argument("--post", action="store_true", help="with --simulate: also update the website")
    ap.add_argument("--no-post", action="store_true", help="do not send the state to the website")
    ap.add_argument("--quiet", action="store_true", help="do not speak warnings")
    args = ap.parse_args()
    if args.simulate:
        if args.post:
            start_posting()
        return simulate(args.post)
    if not (args.scan or args.dump or args.record) and not args.no_post:
        start_posting()
    try:
        asyncio.run(ble_main(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
