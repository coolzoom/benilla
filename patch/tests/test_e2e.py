"""Live vmangos test: a GM bot runs `.tele <name>`, must land on the custom map at the manifest spawn, must stand on
server-side collision (map + vmap height data), stay there, and every walk-path probe must report the expected floor.

Skipped when realmd is not reachable. Env: REALM_HOST / REALM_PORT (127.0.0.1:3735), TEST_USER / TEST_PASS /
TEST_CHAR (a dedicated GM account the test provisions; never a player's account).
"""
import os
import socket

import pytest

import wowbot
from conftest import db_connect

USER = os.environ.get("TEST_USER", "TIANGONG")
PASS = os.environ.get("TEST_PASS", "tiangong")
CHAR = os.environ.get("TEST_CHAR", "Yunque")
REALMD_DB = os.environ.get("REALMD_DB", "m425realmd")


@pytest.fixture(scope="module")
def bot(cfg):
    host, port = os.environ.get("REALM_HOST", "127.0.0.1"), int(os.environ.get("REALM_PORT", "3735"))
    try:
        socket.create_connection((host, port), timeout=2).close()
    except OSError:
        pytest.skip(f"realmd not reachable at {host}:{port}")
    wowbot.provision(db_connect(REALMD_DB), USER, PASS)
    w = wowbot.connect(USER, PASS, CHAR, host, port, log=print)
    w.command(".gm on")
    yield w
    w.close()


def test_tele_enter_and_stand(bot, cfg, manifest):
    bot.events.clear()
    bot.say(f".tele {cfg['tele_name']}")
    got = bot.wait((wowbot.SMSG_NEW_WORLD, wowbot.SMSG_TRANSFER_ABORTED), 15)
    if bot.mapid != cfg["map_id"]:
        # Already on the map from an earlier run: `.tele` is a near teleport then.
        assert got is None or got[0] != wowbot.SMSG_TRANSFER_ABORTED, f"transfer aborted: {got[1].hex()}"
    bot.pump(3)
    aborted = [p for op, p in bot.events if op == wowbot.SMSG_TRANSFER_ABORTED]
    assert not aborted, f"SMSG_TRANSFER_ABORTED {aborted[0].hex()}"
    r = bot.gps()
    print("arrival", r)
    sx, sy, sz, _ = manifest["spawn"]
    assert r["map"] == cfg["map_id"]
    assert abs(r["x"] - sx) < 3 and abs(r["y"] - sy) < 3 and abs(r["z"] - sz) < 3, (r, manifest["spawn"])
    assert r["have_map"] and r["have_vmap"], f"server height data missing: {r}"
    assert r["floor"] > -100000 and abs(sz - r["floor"]) < 2.5, f"no floor under spawn: {r}"
    zone = bot.command(".gps", settle=2)
    assert f"Zone: {cfg['area_id']} ({cfg['name']})" in zone, zone

    bot.pump(8)
    r2 = bot.gps()
    assert r2["map"] == cfg["map_id"] and r["z"] - r2["z"] < 3, f"player moved off/fell: {r} -> {r2}"


def test_walk_probes_have_server_floor(bot, cfg, manifest):
    if not manifest["probes"]:
        pytest.skip("manifest has no probes")
    bad = []
    for i, (x, y, z) in enumerate(manifest["probes"]):
        bot.command(f".go xyz {x:.3f} {y:.3f} {z + 1.5:.3f} {cfg['map_id']}", settle=2)
        r = bot.gps()
        print(f"probe {i} ({x:.1f}, {y:.1f}): expected floor {z:.2f}, server floor {r['floor']:.2f} "
              f"ground {r['ground']:.2f}")
        if r["map"] != cfg["map_id"] or abs(r["floor"] - z) > 1.5 or abs(r["x"] - x) > 1 or abs(r["y"] - y) > 1:
            bad.append((i, (x, y, z), r))
    assert not bad, f"server collision disagrees with the built geometry: {bad}"
