#!/usr/bin/env python3
"""Sends the latest detections + camera frame from the Pi to your Vercel site."""
import base64, collections, json, os, sys, time, urllib.request

SITE_URL = os.environ.get("SITE_URL", "").rstrip("/")
PI_SECRET = os.environ.get("PI_SECRET", "")
LOG_FILE = "logs.json"
IMAGE_FILE = "scene.jpg"

if not SITE_URL or not PI_SECRET:
    sys.exit("Set SITE_URL and PI_SECRET first (see start.sh)")


def last_rows(n=20):
    rows = collections.deque(maxlen=n)
    try:
        with open(LOG_FILE) as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except FileNotFoundError:
        pass
    return list(rows)


def push(rows):
    image = None
    try:
        with open(IMAGE_FILE, "rb") as f:
            image = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()
    except FileNotFoundError:
        pass
    body = json.dumps({"rows": rows, "image": image}).encode()
    req = urllib.request.Request(
        SITE_URL + "/api/update",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-api-key": PI_SECRET,
            "User-Agent": "visionnav-pi/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status


print("Uploading to", SITE_URL)
last_mtime = 0
while True:
    try:
        m = os.path.getmtime(LOG_FILE)
        if m != last_mtime:
            status = push(last_rows())
            last_mtime = m
            print("uploaded", status)
    except FileNotFoundError:
        pass
    except Exception as e:
        print("upload failed:", e)
    time.sleep(1)
