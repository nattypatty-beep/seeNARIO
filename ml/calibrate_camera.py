#!/usr/bin/env python3
"""Calibrate SeeNARIO's distance estimate (camera height + tilt, optionally field of view).

The Pi program estimates distance as:   d = height / tan(tilt + (y - 0.5) * vfov)
where y is where the object touches the floor in the picture (0 = top, 1 = bottom).
You measure a few real distances; this script finds the height/tilt that fit best.

HOW TO COLLECT POINTS (5 minutes)
  1. Mount the camera exactly as it will be worn/demoed. Do not move it afterwards.
  2. Tape marks on the floor straight ahead at 1.5 m, 3.0 m, 4.5 m ... (each 0.75 m = 1 step).
     Use at least 4 marks, spread from near to ~5 steps.
  3. Stand a box (or your shoe) at each mark and grab a frame. Note the row (y pixel)
     where the object's base touches the floor.
  4. Give this script the pairs, either by clicking on a photo or typing them.

USAGE
  python calibrate_camera.py --points "340:1.5,262:3.0,214:4.5,190:6.0" --image-height 384
  python calibrate_camera.py --click frame.jpg          (needs OpenCV; click each floor contact, type the distance)
  python calibrate_camera.py --points ... --fit-fov     (also fit field of view; needs 5+ points)
"""
import argparse, sys
import numpy as np


def predict(y_norm, h, tilt_deg, vfov_deg):
    ang = np.radians(tilt_deg + (np.asarray(y_norm, float) - 0.5) * vfov_deg)
    return h / np.tan(ang)


def fit(y_norm, d, vfov=None):
    """Grid-search tilt (and fov); camera height has a closed-form best fit for each guess."""
    y_norm, d = np.asarray(y_norm, float), np.asarray(d, float)
    best = None
    for fov in ([vfov] if vfov else np.arange(20.0, 91.0, 1.0)):
        for tilt in np.arange(0.0, 60.01, 0.1):
            ang = np.radians(tilt + (y_norm - 0.5) * fov)
            if np.any(ang < np.radians(0.5)) or np.any(ang > np.radians(89)):
                continue
            t = np.tan(ang)
            h = np.sum(d / t) / np.sum(1.0 / t ** 2)
            err = float(np.sqrt(np.mean((h / t - d) ** 2)))
            if best is None or err < best["rmse_m"]:
                best = {"height_m": float(h), "tilt_deg": float(tilt), "vfov_deg": float(fov), "rmse_m": err}
    return best


def parse_points(s, image_height):
    ys, ds = [], []
    for pair in s.split(","):
        y, dist = pair.split(":")
        ys.append(float(y) / image_height)
        ds.append(float(dist))
    return np.array(ys), np.array(ds)


def click_points(path):
    import cv2
    img = cv2.imread(path)
    if img is None:
        sys.exit(f"Could not open {path}")
    h = img.shape[0]
    clicks = []
    def on(ev, x, y, *_):
        if ev == cv2.EVENT_LBUTTONDOWN:
            clicks.append(y); cv2.circle(img, (x, y), 4, (0, 255, 0), -1); cv2.imshow("click floor contacts, press q", img)
    cv2.imshow("click floor contacts, press q", img)
    cv2.setMouseCallback("click floor contacts, press q", on)
    while cv2.waitKey(50) & 0xFF != ord("q"):
        pass
    cv2.destroyAllWindows()
    ds = [float(input(f"Distance (m) for click {i+1} at y={y}px: ")) for i, y in enumerate(clicks)]
    return np.array(clicks, float) / h, np.array(ds)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", help='"y_pixel:distance_m,..."')
    ap.add_argument("--image-height", type=float, default=384, help="height in pixels of the frame the y values refer to")
    ap.add_argument("--click")
    ap.add_argument("--vfov", type=float, default=40.0, help="vertical field of view in degrees if you are not fitting it")
    ap.add_argument("--fit-fov", action="store_true")
    a = ap.parse_args()
    if a.click:
        y, d = click_points(a.click)
    elif a.points:
        y, d = parse_points(a.points, a.image_height)
    else:
        ap.error("give --points or --click")
    need = 5 if a.fit_fov else 3
    if len(d) < need:
        sys.exit(f"Need at least {need} points, got {len(d)}.")
    r = fit(y, d, None if a.fit_fov else a.vfov)
    print(f"\nBest fit:  camera height {r['height_m']:.2f} m,  tilt {r['tilt_deg']:.1f} deg,  vertical FOV {r['vfov_deg']:.0f} deg")
    print(f"Typical error: {r['rmse_m']:.2f} m  ({r['rmse_m']/0.75:.1f} steps)\n")
    print("  measured   predicted   error")
    for yy, dd in sorted(zip(y, d), key=lambda p: p[1]):
        p = float(predict(yy, r["height_m"], r["tilt_deg"], r["vfov_deg"]))
        print(f"  {dd:6.2f} m   {p:6.2f} m   {p-dd:+.2f} m")
    if r["rmse_m"] > 0.4:
        print("\nWARNING: error is large. Check that the camera did not move, y is where the object touches the floor, and distances are to that same spot.")
    print("\nPut these in seenario_pi.py (look for the camera height, tilt and field-of-view settings; starting values were 1.2 m, 20 deg, 40 deg):")
    print(f"  height = {r['height_m']:.2f}   tilt = {r['tilt_deg']:.1f}   vfov = {r['vfov_deg']:.0f}")


if __name__ == "__main__":
    main()
