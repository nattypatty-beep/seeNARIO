#!/usr/bin/env python3
"""Sanity-check motion recordings (phone recorder or SensorTile.box exports) BEFORE training.

  python check_recording.py data/*.csv
  python check_recording.py logs/walking_01.csv --rate 104    (CSV without a time column)

Prints PASS / WARN lines so you catch dead sensors, wrong units, gaps, or mislabeled
recordings while you can still re-record.
"""
import argparse, glob, os, sys
import numpy as np
from loader import load_accel

HINTS = {  # rough expectations for movement size, only used if the file name starts with the label
    "standing": lambda s, mx: (s < 0.10, "standing should be nearly flat (std < 0.10 g)"),
    "walking": lambda s, mx: (0.10 < s < 1.5, "walking should show steady movement (std 0.10-1.5 g)"),
    "stumble": lambda s, mx: (mx > 1.8, "a stumble should include a clear spike (max > 1.8 g)"),
}


def check(path, rate=None):
    out = []
    try:
        a, info = load_accel(path, rate)
    except Exception as e:
        return [("FAIL", str(e))], None
    mag = np.linalg.norm(a, axis=1)
    std, mx = float(mag.std()), float(mag.max())
    out.append(("INFO", f"{len(a)} samples at 50 Hz after loading = {info['duration_s']:.0f} s | units {info['units']} | source rate {info['rate']:.0f} Hz"
                f"{' (ASSUMED: pass --rate if wrong)' if info.get('rate_assumed') else ''}"))
    out.append(("INFO", f"mean |a| {mag.mean():.2f} g, std {std:.3f} g, max {mx:.2f} g, axis means {np.round(a.mean(axis=0), 2).tolist()}"))
    if info["duration_s"] < 30: out.append(("WARN", "short recording (< 30 s)"))
    if std < 0.004: out.append(("FAIL", "flat line: the sensor looks dead or the file is wrong"))
    if not 0.7 < float(np.median(mag)) < 1.6: out.append(("WARN", f"median |a| is {np.median(mag):.2f} g; at rest it should be about 1.0 g (unit guess wrong?)"))
    if info.get("time_gap_max_s", 0) > 0.25: out.append(("WARN", f"gap of {info['time_gap_max_s']:.2f} s in the timestamps (dropped data)"))
    if (np.abs(a) > 15).any(): out.append(("WARN", "values beyond +/-15 g: units or full-scale range may be wrong"))
    lab = os.path.basename(path).split("_")[0]
    if lab in HINTS:
        ok, msg = HINTS[lab](std, mx)
        out.append(("PASS" if ok else "WARN", f"label '{lab}': " + ("movement matches" if ok else "movement does not match. " + msg)))
    if not any(l in ("FAIL", "WARN") for l, _ in out): out.append(("PASS", "looks good"))
    return out, a.mean(axis=0)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("files", nargs="+"); ap.add_argument("--rate", type=float)
    args = ap.parse_args()
    files = [f for p in args.files for f in sorted(glob.glob(p))]
    worst, means = 0, []
    for f in files:
        res, m = check(f, args.rate)
        print(f"\n{f}")
        for lvl, msg in res: print(f"  {lvl:5s} {msg}")
        worst = max(worst, {"FAIL": 2, "WARN": 1}.get(res[-1][0] if len(res) == 1 else max((l for l, _ in res), key=lambda l: {"FAIL": 2, "WARN": 1}.get(l, 0)), 0))
        if m is not None: means.append(m)
    if len(means) > 1:
        spread = float(np.max(np.linalg.norm(np.array(means) - np.mean(means, axis=0), axis=1)))
        print(f"\nOrientation consistency across files: spread {spread:.2f} g " + ("(good)" if spread < 0.35 else "(WARN: board orientation changed between recordings; keep it identical)"))
    sys.exit(1 if worst == 2 else 0)


if __name__ == "__main__":
    main()
