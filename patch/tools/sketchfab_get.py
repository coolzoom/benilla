"""Download Sketchfab models (glTF archives) for scenes/*/models, then prepare them with prep_model.py.

    SKETCHFAB_TOKEN=... python patch/tools/sketchfab_get.py OUT_DIR NAME=UID [NAME=UID ...]

The token is the API token from sketchfab.com/settings/password; it is read from the environment only. Each model is
saved as OUT_DIR/NAME.zip, and its title, author, licence and page are appended to OUT_DIR/sources.txt for the credits.
"""
import json
import os
import sys
import urllib.request

API = "https://api.sketchfab.com/v3/models/"


def get(url, token=None):
    req = urllib.request.Request(url, headers={"Authorization": f"Token {token}"} if token else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def main():
    token = os.environ.get("SKETCHFAB_TOKEN")
    if not token:
        raise SystemExit("set SKETCHFAB_TOKEN")
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    for spec in sys.argv[2:]:
        name, uid = spec.split("=", 1)
        info = json.loads(get(API + uid))
        links = json.loads(get(API + uid + "/download", token))
        url = (links.get("gltf") or links.get("glb") or {}).get("url")
        if not url:
            raise SystemExit(f"{name}: no glTF download offered ({sorted(links)})")
        data = get(url)
        path = os.path.join(out, name + ".zip")
        with open(path, "wb") as fh:
            fh.write(data)
        licence = (info.get("license") or {}).get("label", "?")
        line = f"{name}: \"{info['name']}\" by {info['user']['displayName']} ({info['user']['username']}), {licence}, " \
               f"{info['viewerUrl']}"
        with open(os.path.join(out, "sources.txt"), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        print(f"{path}: {len(data) // 1024} KB - {line}")


main()
