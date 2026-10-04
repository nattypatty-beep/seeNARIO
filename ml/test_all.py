#!/usr/bin/env python3
"""Self-tests. Run:  python test_all.py   (all lines should say PASS)"""
import json, os, shutil, subprocess, sys, tempfile
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import loader, calibrate_camera as cal, check_recording as chk

tmp = tempfile.mkdtemp()
fails = []
def test(name):
    def deco(fn):
        try: fn(); print("PASS ", name)
        except Exception as e: fails.append(name); print("FAIL ", name, "->", repr(e))
    return deco

def walking(n=104 * 30, rate=104.0, seed=0):
    t = np.arange(n) / rate; r = np.random.default_rng(seed)
    z = 1 + 0.3 * np.sin(2 * np.pi * 1.8 * t) + r.normal(0, .03, n)
    return t, np.c_[r.normal(0, .03, n), r.normal(0, .03, n), z]

@test("loader: ST-style CSV (mg, ms time, 104 Hz) -> g at 50 Hz")
def _():
    t, a = walking()
    df = pd.DataFrame({"Time [ms]": t * 1000, "A_x [mg]": a[:, 0] * 1000, "A_y [mg]": a[:, 1] * 1000, "A_z [mg]": a[:, 2] * 1000,
                       "G_x [mdps]": 5, "G_y [mdps]": 5, "G_z [mdps]": 5})
    p = os.path.join(tmp, "walking_st.csv"); df.to_csv(p, index=False)
    out, info = loader.load_accel(p)
    assert abs(np.median(np.linalg.norm(out, axis=1)) - 1.0) < 0.1, "units not converted"
    assert abs(len(out) / 50 - 30) < 1, f"resampling wrong: {len(out)} samples"
    assert info["units"].startswith("mg") and info.get("resampled")

@test("loader: phone CSV (ax,ay,az) unchanged")
def _():
    _, a = walking(n=3000, rate=50)
    p = os.path.join(tmp, "walking_phone.csv"); pd.DataFrame(a, columns=["ax", "ay", "az"]).to_csv(p, index=False)
    out, info = loader.load_accel(p)
    assert out.shape == (3000, 3) and info["units"] == "g" and not info.get("resampled")

@test("loader: no time column + --rate resamples")
def _():
    _, a = walking(rate=104)
    p = os.path.join(tmp, "walking_norate.csv"); pd.DataFrame(a, columns=["acc_x", "acc_y", "acc_z"]).to_csv(p, index=False)
    out, _ = loader.load_accel(p, rate=104)
    assert abs(len(out) / 50 - len(a) / 104) < 1

@test("calibration recovers height/tilt from noisy measurements")
def _():
    r = np.random.default_rng(1); d = np.array([1.5, 3.0, 4.5, 6.0, 3.75])
    y = (np.degrees(np.arctan(1.2 / d)) - 20) / 40 + 0.5 + r.normal(0, 0.004, len(d))
    f = cal.fit(y, d, vfov=40)
    assert abs(f["height_m"] - 1.2) < 0.15 and abs(f["tilt_deg"] - 20) < 2.5, f

@test("calibration fits a different camera (height 0.9 m, tilt 30 deg)")
def _():
    d = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    y = (np.degrees(np.arctan(0.9 / d)) - 30) / 40 + 0.5
    f = cal.fit(y, d, vfov=40)
    assert abs(f["height_m"] - 0.9) < 0.1 and abs(f["tilt_deg"] - 30) < 2, f

@test("check_recording flags a dead (flat) sensor")
def _():
    p = os.path.join(tmp, "walking_dead.csv")
    pd.DataFrame({"ax": np.zeros(3000), "ay": np.zeros(3000), "az": np.ones(3000)}).to_csv(p, index=False)
    res, _ = chk.check(p)
    assert any(l == "FAIL" for l, _ in res)

@test("train.py synthetic run + model.js matches Python predictions")
def _():
    here = os.path.dirname(os.path.abspath(__file__)); work = tempfile.mkdtemp()
    subprocess.run([sys.executable, os.path.join(here, "train.py"), "--synth", "--export-js"], cwd=work, check=True, capture_output=True)
    assert os.path.exists(os.path.join(work, "model.js"))
    if not shutil.which("node"): print("      (node not installed, skipping JS parity)"); return
    import pickle, train
    clf = pickle.load(open(os.path.join(work, "model.pkl"), "rb")); r = np.random.default_rng(9); bad = n = 0
    for li, lab in enumerate(train.LABELS):
        arr = train.synth_recording(lab, rng=r)
        for i in range(0, 50 * 20, 50):
            seg = arr[i:i + 50]; py = train.LABELS[int(clf.predict([list(train.windows(seg))[0]])[0])]
            js = subprocess.run(["node", "-e", f"console.log(require('{work}/model.js').classifyMotion({json.dumps([{'x': x, 'y': y, 'z': z} for x, y, z in seg.tolist()])}))"],
                                capture_output=True, text=True).stdout.strip()
            n += 1; bad += py != js
    assert bad == 0, f"{bad}/{n} mismatches"

shutil.rmtree(tmp, ignore_errors=True)
print("\nALL TESTS PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
