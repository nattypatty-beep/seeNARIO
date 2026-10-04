"""Load accelerometer CSVs from the phone recorder OR from SensorTile.box / ST tools.

Handles: different column names (ax / A_x [mg] / acc_x ...), units (g, mg, m/s^2),
time columns in s / ms / us, and resampling to the 50 Hz that train.py and app.js use.
"""
import re
import numpy as np
import pandas as pd

TARGET_RATE = 50.0


def _find_axes(cols):
    low = {c: c.lower().strip() for c in cols}
    def pick(axis):
        pats = [rf"^a?c?c?e?l?_?{axis}\b", rf"^a_?{axis}\b", rf"^acc\w*_?{axis}\b", rf"^accel\w*[_ ]?{axis}\b", rf"^{axis}$"]
        for p in pats:
            for c, l in low.items():
                if re.search(p, l) and not re.search(r"gyro|^g_|angular|mag", l):
                    return c
        return None
    axes = [pick(a) for a in "xyz"]
    if None in axes:  # fall back to ax/ay/az exactly
        axes = [c for c in cols if c.lower().strip() in ("ax", "ay", "az")]
    return axes if len(axes) == 3 and None not in axes else None


def _find_time(cols):
    for c in cols:
        if re.search(r"time|timestamp|^t$", c.lower()):
            return c
    return None


def load_accel(path, rate=None):
    """Return (samples Nx3 in g at 50 Hz, info dict)."""
    df = pd.read_csv(path, comment="#")
    df.columns = [str(c).strip() for c in df.columns]
    axes = _find_axes(list(df.columns))
    if axes is None:
        raise ValueError(f"{path}: couldn't find accelerometer columns in {list(df.columns)}")
    a = df[axes].apply(pd.to_numeric, errors="coerce").dropna().to_numpy(float)
    info = {"columns": axes, "samples": len(a)}

    # units: header hint first, then magnitude
    head = " ".join(axes).lower()
    med = float(np.median(np.linalg.norm(a, axis=1))) if len(a) else 0
    if "mg" in head or med > 200:
        a, info["units"] = a / 1000.0, "mg -> g"
    elif "m/s" in head or 5 < med < 20:
        a, info["units"] = a / 9.80665, "m/s^2 -> g"
    else:
        info["units"] = "g"

    # sampling rate: time column > --rate > assume already 50 Hz
    t = None
    tc = _find_time(list(df.columns))
    if tc is not None:
        tv = pd.to_numeric(df[tc], errors="coerce").to_numpy(float)
        tv = tv[: len(a)]
        if np.all(np.isfinite(tv)) and len(tv) > 2:
            dt = float(np.median(np.diff(tv)))
            if dt >= 1000: tv = tv / 1e6       # microseconds
            elif dt > 0.2: tv = tv / 1e3       # milliseconds
            t = tv - tv[0]
            info["rate"] = 1.0 / float(np.median(np.diff(t)))
            info["time_gap_max_s"] = float(np.max(np.diff(t)))
    if t is None and rate:
        t = np.arange(len(a)) / float(rate)
        info["rate"] = float(rate)
    if "rate" not in info:
        info["rate"] = TARGET_RATE
        info["rate_assumed"] = True

    if t is not None and abs(info["rate"] - TARGET_RATE) > 1.0:  # resample to 50 Hz
        grid = np.arange(0, t[-1], 1.0 / TARGET_RATE)
        a = np.c_[[np.interp(grid, t, a[:, i]) for i in range(3)]].T
        info["resampled"] = True
    info["duration_s"] = len(a) / TARGET_RATE
    return a, info
