#!/usr/bin/env python3
"""Verdict for run_client_test.sh: read benilla's log and the in-world screenshots.

    client_check.py <client.log> <manifest.json> <shot.png> [<shot.png> ...]

Passes when the server put the client on the custom map (`.gps` echoed back as `net: server says`), the client's own
Lua reports the zone name, no MPQ/asset load failed for our files, and at least one screenshot is a real render.
"""
import json
import os
import re
import sys

NOISE_LIMIT = 0.06  # mean |gradient|: clean render ~0.02, a mis-decoded texture ~0.12


def screenshot_metrics(path):
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(path).convert("RGB").resize((1024, 640)), dtype=np.float32) / 255
    g = a.mean(2)
    hf = float(np.abs(np.diff(g, axis=1)).mean() + np.abs(np.diff(g, axis=0)).mean())
    return {"noise": hf, "mean": float(g.mean()), "std": float(g.std())}


def main(log_path, manifest_path, *shots):
    cfg = json.load(open(manifest_path))["config"]
    log = open(log_path, encoding="utf8", errors="replace").read()
    errors = []

    said = "\n".join(re.findall(r"server says.*", log))
    m = re.search(r"Map: (\d+) \(([^)]*)\) Zone: (\d+)", said)
    print("server .gps:", m.group(0) if m else "(none)")
    if not m or int(m.group(1)) != cfg["map_id"] or int(m.group(3)) != cfg["area_id"]:
        errors.append(f"server never reported map {cfg['map_id']} zone {cfg['area_id']} back to the client")

    zone = re.findall(r"probe-log: TGZONE=([^;\n]*)", log)
    port = log.rfind(f"worldport: mapId {cfg['map_id']} ")
    after = log[port:] if port >= 0 else ""
    done = port >= 0 and "worldport: ack sent" in after and "loading screen: cleared" in after
    print("worldport onto our map:", "acked, loading screen cleared" if done else "not completed")
    if not done:
        errors.append(f"the client never completed a worldport onto map {cfg['map_id']}")
    print("client zone text:", zone)
    if cfg["name"] not in zone:
        errors.append(f"client GetRealZoneText() never returned {cfg['name']!r}")

    ours = cfg["directory"].lower()
    bad = [ln for ln in log.splitlines() if ours in ln.lower() and re.search(r"\b(ERROR|WARN)\b|fail|missing", ln, re.I)]
    for ln in bad[:10]:
        print("asset problem:", ln)
    if bad:
        errors.append(f"{len(bad)} log lines report problems loading {cfg['directory']} files")
    if re.search(r"panicked at", log):
        errors.append("client panicked")

    good = 0
    for shot in shots:
        if not os.path.exists(shot):
            print("screenshot missing:", shot)
            continue
        mt = screenshot_metrics(shot)
        print("screenshot:", shot, {k: round(v, 4) for k, v in mt.items()})
        if mt["noise"] <= NOISE_LIMIT and mt["mean"] >= 0.05 and mt["std"] >= 0.02:
            good += 1
    if not good:
        errors.append("no usable in-world screenshot (missing, blank, or noisy)")

    for e in errors:
        print("FAIL:", e)
    print("PASS" if not errors else "FAILED")
    return 0 if not errors else 1


if __name__ == "__main__":
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    sys.exit(main(*sys.argv[1:]))
