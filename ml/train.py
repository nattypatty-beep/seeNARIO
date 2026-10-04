"""Train the standing / walking / stumble classifier for the SensorTile.box.

Usage:
  python train.py --synth            # test the pipeline on fake data (no board needed)
  python train.py --data data/       # real recordings

Real data: one CSV per recording in data/, named <label>_<anything>.csv, e.g.
  standing_01.csv, walking_03.csv, stumble_02.csv
Each CSV needs columns ax, ay, az (acceleration in g). If your export uses other
column names or mg units, edit load_csv() below.

Why a small decision tree: it is easy to explain in a presentation and maps onto
the board's on-sensor machine learning core / small embedded models. Check with
your instructor which ST tool (NanoEdge AI Studio, MLC, STM32Cube.AI) they expect.
"""
import argparse, glob, os, pickle
import numpy as np, pandas as pd
from sklearn.tree import DecisionTreeClassifier, export_text
from sklearn.metrics import accuracy_score, confusion_matrix, classification_report

LABELS = ["standing", "walking", "stumble"]  # byte sent by the board: 0, 1, 2
RATE = 52  # Hz; set to the rate you record at on the board


def windows(a, rate=RATE):
    """Yield feature vectors for 1-second windows, 50% overlap. a: (n, 3) array in g."""
    w = rate
    for i in range(0, len(a) - w + 1, w // 2):
        seg = a[i:i + w]
        m = np.linalg.norm(seg, axis=1)
        yield [m.mean(), m.std(), m.min(), m.max(), np.ptp(m), (m ** 2).mean(),
               *seg.std(axis=0)]


FEATS = ["mag_mean", "mag_std", "mag_min", "mag_max", "mag_ptp", "energy",
         "ax_std", "ay_std", "az_std"]


def load_csv(path):
    df = pd.read_csv(path)
    return df[["ax", "ay", "az"]].to_numpy(float)


def synth_recording(label, n=RATE * 40, rng=None):
    rng = rng or np.random.default_rng()
    t = np.arange(n) / RATE
    noise = lambda s: rng.normal(0, s, n)
    if label == "standing":
        z = 1 + noise(0.01); x, y = noise(0.01), noise(0.01)
    else:
        f = rng.uniform(1.6, 2.1)
        z = 1 + 0.3 * np.sin(2 * np.pi * f * t) + noise(0.04)
        x, y = 0.1 * np.sin(np.pi * f * t) + noise(0.03), noise(0.03)
        if label == "stumble":
            # Stumble recordings must be trimmed/recorded so EVERY window holds an
            # event (windows are labeled by file). Simulated here as one per second.
            for s in range(0, 39):
                k = int(s * RATE) + 10
                z[k:k + 15] += rng.uniform(1.5, 2.5) * np.sin(np.linspace(0, np.pi, 15))
                x[k:k + 15] += rng.normal(0, 0.4, 15)
    return np.c_[x, y, z]


def gather(args):
    recs = []  # (label_idx, recording_id, array)
    if args.synth:
        rng = np.random.default_rng(0)
        for li, lab in enumerate(LABELS):
            for r in range(6):
                recs.append((li, f"{lab}_{r}", synth_recording(lab, rng=rng)))
    else:
        for p in sorted(glob.glob(os.path.join(args.data, "*.csv"))):
            lab = os.path.basename(p).split("_")[0]
            if lab in LABELS:
                recs.append((LABELS.index(lab), os.path.basename(p), load_csv(p)))
        if len({r[0] for r in recs}) < 3:
            raise SystemExit("Need recordings for all three labels in " + args.data)
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--synth", action="store_true")
    args = ap.parse_args()
    recs = gather(args)

    # Hold out whole recordings (every 3rd per label) so test windows never overlap
    # training windows. Splitting windows randomly would inflate accuracy.
    train, test, seen = [], [], {}
    for li, rid, arr in recs:
        seen[li] = seen.get(li, 0) + 1
        (test if seen[li] % 3 == 0 else train).append((li, rid, arr))
    if not test:
        raise SystemExit("Record at least 3 files per label so some can be held out.")

    def xy(rs):
        X, y = [], []
        for li, _, arr in rs:
            for f in windows(arr):
                X.append(f); y.append(li)
        return np.array(X), np.array(y)

    Xtr, ytr = xy(train); Xte, yte = xy(test)
    clf = DecisionTreeClassifier(max_depth=4, min_samples_leaf=5,
                                 class_weight="balanced", random_state=0).fit(Xtr, ytr)
    pred = clf.predict(Xte)

    print(f"train windows: {len(ytr)}   held-out windows: {len(yte)}")
    print(f"held-out accuracy: {accuracy_score(yte, pred):.3f}\n")
    print("confusion matrix (rows = true, cols = predicted):", LABELS)
    print(confusion_matrix(yte, pred, labels=[0, 1, 2]), "\n")
    print(classification_report(yte, pred, labels=[0, 1, 2], target_names=LABELS,
                                zero_division=0))
    walk = yte == 1
    if walk.any():
        fa = (pred[walk] == 2).mean()
        print(f"false stumble alarms during normal walking: {fa:.1%} of windows")

    print("\nDecision tree rules:\n" + export_text(clf, feature_names=FEATS))
    with open("model.pkl", "wb") as f:
        pickle.dump(clf, f)
    print("saved model.pkl")


if __name__ == "__main__":
    main()
