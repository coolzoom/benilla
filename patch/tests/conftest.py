import json
import os
import subprocess
import sys

import pytest

PATCH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PATCH, "tools"))
sys.path.insert(0, os.path.join(PATCH, "tests", "e2e"))

import mpq  # noqa: E402

SCENE = os.environ.get("SCENE", "tiangong")


def server_env():
    """DataDir / WORLD_DB / MYSQL_ARGS / WOW_CLIENT exactly as install.sh resolves them."""
    script = f'. "{PATCH}/pipeline/server_env.sh"; ' \
             'printf "%s\\n" "$WOW_CLIENT" "$DATA_DIR" "$WORLD_DB" "$MYSQL_ARGS" "$MANGOSD_CONF"'
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout.splitlines()
    return dict(zip(("client", "data_dir", "world_db", "mysql_args", "conf"), out))


def db_connect(database):
    """A pymysql connection from the mangosd config's credentials, or skip."""
    pymysql = pytest.importorskip("pymysql")
    env = server_env()
    args = dict(a[:2] and (a[1], a[2:]) for a in env["mysql_args"].split())
    try:
        return pymysql.connect(host=args.get("h", "127.0.0.1"), port=int(args.get("P", 3306)), user=args.get("u", "root"),
                               password=args.get("p", ""), database=database, connect_timeout=3, charset="utf8mb4")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no database {database}: {e}")


@pytest.fixture(scope="session")
def patch_dir():
    return PATCH


@pytest.fixture(scope="session")
def manifest():
    path = os.path.join(PATCH, "build", SCENE, "manifest.json")
    if not os.path.exists(path):
        pytest.skip(f"scene {SCENE} not built (run pipeline/build.py --scene {SCENE})")
    with open(path) as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def cfg(manifest):
    return manifest["config"]


@pytest.fixture(scope="session")
def client_mpq():
    with mpq.Archive(os.path.join(PATCH, "client", "patch-5.MPQ")) as a:
        return {n: a.read(n) for n in a.list()}


@pytest.fixture(scope="session")
def lower_mpq(client_mpq):
    return {k.lower(): v for k, v in client_mpq.items()}
