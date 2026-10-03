#!/usr/bin/env python3
"""Sends a webcam frame from the Pi to the SeeNARIO site every 3 seconds."""
import base64, json, os, time, urllib.request
import cv2

SITE_URL = os.environ.get("SITE_URL", "https://seenario-phi.vercel.app").rstrip("/")
PI_SECRET = os.environ.get("PI_SECRET", "seenarioPi2026xk4m")

cap = cv2.VideoCapture(0)
if not cap.isOpened():
    raise SystemExit("Can't open the camera. Is the webcam plugged in?")

rows = []
print("Sending camera frames to", SITE_URL, "(Ctrl+C to stop)")
while True:
    for _ in range(3):
        cap.grab()  # skip stale buffered frames
    ok, frame = cap.read()
    if not ok:
        print("no frame")
        time.sleep(1)
        continue
    frame = cv2.resize(frame, (640, 480))
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    image = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()
    rows.append({"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "guidance": "Camera feed live", "latency_s": 0})
    rows = rows[-20:]
    req = urllib.request.Request(
        SITE_URL + "/api/update",
        data=json.dumps({"rows": rows, "image": image}).encode(),
        method="POST",
        headers={"Content-Type": "application/json",
                 "x-api-key": PI_SECRET,
                 "User-Agent": "visionnav-pi/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            print("uploaded", r.status)
    except Exception as e:
        print("upload failed:", e)
    time.sleep(3)
