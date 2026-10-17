"""Minimal 1.12.1 (build 5875) protocol bot for the vmangos e2e tests: SRP6 logon, realm list, world session with
header crypt, character create/login, GM chat commands, far/near teleport acks and `.gps` parsing.

Stdlib only. The GM test account is provisioned straight into the realmd DB (see provision()).
"""
import hashlib
import os
import re
import secrets
import socket
import struct
import time

BUILD = 5875
N = int("894B645E89E1535BBDAD5B8B290650530801B18EBFBF5E8FAB3C82872A3E9BB7", 16)
G = 7

CMSG_CHAR_CREATE, CMSG_CHAR_ENUM, SMSG_CHAR_CREATE, SMSG_CHAR_ENUM = 0x036, 0x037, 0x03A, 0x03B
CMSG_PLAYER_LOGIN, SMSG_NEW_WORLD, SMSG_TRANSFER_PENDING, SMSG_TRANSFER_ABORTED = 0x03D, 0x03E, 0x03F, 0x040
SMSG_CHARACTER_LOGIN_FAILED, CMSG_LOGOUT_REQUEST, SMSG_LOGOUT_COMPLETE = 0x041, 0x04B, 0x04D
CMSG_MESSAGECHAT, SMSG_MESSAGECHAT = 0x095, 0x096
MSG_MOVE_TELEPORT_ACK, MSG_MOVE_WORLDPORT_ACK = 0x0C7, 0x0DC
SMSG_AUTH_CHALLENGE, CMSG_AUTH_SESSION, SMSG_AUTH_RESPONSE = 0x1EC, 0x1ED, 0x1EE
SMSG_LOGIN_VERIFY_WORLD = 0x236
AUTH_OK, CHAR_CREATE_SUCCESS = 0x0C, 0x2E
CHAT_MSG_SAY, LANG_COMMON = 0, 7

GPS_RE = re.compile(r"Map: (\d+)[\s\S]*?X: ([-\d.]+) Y: ([-\d.]+) Z: ([-\d.]+)[\s\S]*?"
                    r"GroundZ: ([-\d.]+) FloorZ: ([-\d.]+) Have height data \(Map: (\d) VMap: (\d)")


def sha1(*parts):
    h = hashlib.sha1()
    for p in parts:
        h.update(p)
    return h.digest()


def le(n, size=32):
    return n.to_bytes(size, "little")


def from_le(b):
    return int.from_bytes(b, "little")


def srp_verifier(user, password, salt=None):
    """(v, s) as vmangos stores them: big-endian hex of the numbers."""
    salt = salt if salt is not None else secrets.token_bytes(32)
    x = from_le(sha1(salt, sha1(f"{user.upper()}:{password.upper()}".encode())))
    return f"{pow(G, x, N):064X}", f"{from_le(salt):064X}"


def provision(db, user, password, gmlevel=3):
    """Create or reset a realmd account with a GM level on every realm. `db` is a pymysql connection."""
    v, s = srp_verifier(user, password)
    with db.cursor() as c:
        c.execute("SELECT id FROM account WHERE username = %s", (user.upper(),))
        row = c.fetchone()
        if row:
            c.execute("UPDATE account SET v = %s, s = %s, gmlevel = %s, locked = 0 WHERE id = %s", (v, s, gmlevel, row[0]))
            aid = row[0]
        else:
            c.execute("INSERT INTO account (username, v, s, gmlevel, joindate) VALUES (%s, %s, %s, %s, NOW())",
                      (user.upper(), v, s, gmlevel))
            aid = c.lastrowid
        c.execute("DELETE FROM account_access WHERE id = %s", (aid,))
        c.execute("INSERT INTO account_access (id, gmlevel, RealmID) VALUES (%s, %s, -1)", (aid, gmlevel))
    db.commit()
    return aid


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("socket closed")
        buf += chunk
    return buf


def _cstr(data, off):
    end = data.index(0, off)
    return data[off:end].decode("utf-8", "replace"), end + 1


def logon(host, port, user, password, timeout=10.0):
    """SRP6 logon against realmd; returns (session key K, [(name, address)])."""
    user = user.upper()
    s = socket.create_connection((host, port), timeout=timeout)
    try:
        body = (b"WoW\0" + bytes([1, 12, 1]) + struct.pack("<H", BUILD) + b"68x\0" + b"niW\0" + b"NChz" +
                struct.pack("<II", 480, 0x0100007F) + bytes([len(user)]) + user.encode())
        s.sendall(struct.pack("<BBH", 0, 3, len(body)) + body)
        head = _recv_exact(s, 3)
        if head[2] != 0:
            raise RuntimeError(f"logon challenge refused: error {head[2]}")
        rest = _recv_exact(s, 32 + 1 + 1 + 1 + 32 + 32 + 16 + 1)
        B = from_le(rest[0:32])
        g = rest[33]
        n_len = rest[34]
        n = from_le(rest[35:35 + n_len])
        salt = rest[35 + n_len:35 + n_len + 32]
        assert g == G and n == N, "unexpected SRP group"
        x = from_le(sha1(salt, sha1(f"{user}:{password.upper()}".encode())))
        while True:
            a = secrets.randbelow(N - 2) + 1
            A = pow(G, a, N)
            if A % N:
                break
        u = from_le(sha1(le(A), le(B)))
        S = pow((B - 3 * pow(G, x, N)) % N, a + u * x, N)
        sb = le(S)
        e, o = sha1(sb[0::2]), sha1(sb[1::2])
        K = bytes(b for pair in zip(e, o) for b in pair)
        hn, hg = sha1(le(N)), sha1(bytes([G]))
        M1 = sha1(bytes(p ^ q for p, q in zip(hn, hg)), sha1(user.encode()), salt, le(A), le(B), K)
        s.sendall(bytes([1]) + le(A) + M1 + b"\0" * 20 + bytes([0, 0]))
        head = _recv_exact(s, 2)
        if head[1] != 0:
            raise RuntimeError(f"logon proof refused: error {head[1]} (wrong password or SRP mismatch)")
        proof = _recv_exact(s, 20 + 4)
        if proof[:20] != sha1(le(A), M1, K):
            raise RuntimeError("server proof M2 mismatch")
        s.sendall(bytes([0x10]) + b"\0" * 4)
        hdr = _recv_exact(s, 3)
        data = _recv_exact(s, struct.unpack_from("<H", hdr, 1)[0])
        count = data[4]
        off, realms = 5, []
        for _ in range(count):
            off += 5
            name, off = _cstr(data, off)
            addr, off = _cstr(data, off)
            off += 4 + 3
            realms.append((name, addr))
        return K, realms
    finally:
        s.close()


class World:
    """One world-server session. Packets are (opcode, payload)."""

    def __init__(self, addr, user, K, log=None):
        host, port = addr.rsplit(":", 1)
        self.sock = socket.create_connection((host, int(port)), timeout=15)
        self.user, self.K = user.upper(), K
        self.si = self.sj = self.ri = self.rj = 0
        self.crypt = False
        self.log = log or (lambda *_: None)
        self.guid = None
        self.mapid = None
        self.pos = None
        self.chat = []
        self.events = []
        self._auth()

    # ---- framing
    def _enc(self, data):
        out = bytearray(data)
        for t in range(len(out)):
            x = ((out[t] ^ self.K[self.si]) + self.sj) & 0xFF
            self.si = (self.si + 1) % len(self.K)
            out[t] = self.sj = x
        return bytes(out)

    def _dec(self, data):
        out = bytearray(data)
        for t in range(len(out)):
            orig = out[t]
            out[t] = ((orig - self.rj) & 0xFF) ^ self.K[self.ri]
            self.ri = (self.ri + 1) % len(self.K)
            self.rj = orig
        return bytes(out)

    def send(self, op, payload=b""):
        hdr = struct.pack(">H", len(payload) + 4) + struct.pack("<I", op)
        if self.crypt:
            hdr = self._enc(hdr)
        self.sock.sendall(hdr + payload)

    def recv(self, timeout=None):
        self.sock.settimeout(timeout)
        hdr = _recv_exact(self.sock, 4)
        if self.crypt:
            hdr = self._dec(hdr)
        size = struct.unpack(">H", hdr[:2])[0]
        op = struct.unpack("<H", hdr[2:])[0]
        self.sock.settimeout(15)
        payload = _recv_exact(self.sock, size - 2) if size > 2 else b""
        self._handle(op, payload)
        return op, payload

    def _handle(self, op, p):
        if op == SMSG_MESSAGECHAT:
            text = p.decode("utf-8", "ignore")
            self.chat.append(text)
            self.log("chat:", " ".join(re.findall(r"[ -~\u4e00-\u9fff]{3,}", text))[:300])
        elif op in (SMSG_NEW_WORLD, SMSG_TRANSFER_PENDING, SMSG_TRANSFER_ABORTED, SMSG_LOGIN_VERIFY_WORLD):
            self.events.append((op, p))
            if op in (SMSG_NEW_WORLD, SMSG_LOGIN_VERIFY_WORLD):
                self.mapid = struct.unpack_from("<I", p)[0]
                self.pos = struct.unpack_from("<4f", p, 4)
            if op == SMSG_NEW_WORLD:
                self.send(MSG_MOVE_WORLDPORT_ACK)
        elif op == MSG_MOVE_TELEPORT_ACK:
            mask, off, guid = p[0], 1, 0
            for i in range(8):
                if mask & (1 << i):
                    guid |= p[off] << (8 * i)
                    off += 1
            counter = struct.unpack_from("<I", p, off)[0]
            self.events.append((op, p))
            self.send(MSG_MOVE_TELEPORT_ACK, struct.pack("<QII", guid, counter, int(time.time() * 1000) & 0xFFFFFFFF))

    def wait(self, ops, timeout=15.0):
        """Pump packets until one of `ops` arrives; returns (op, payload) or None on timeout."""
        end = time.time() + timeout
        while time.time() < end:
            try:
                op, p = self.recv(max(0.05, end - time.time()))
            except (socket.timeout, TimeoutError):
                return None
            if op in ops:
                return op, p
        return None

    def pump(self, seconds):
        self.wait((), seconds)

    # ---- session
    def _auth(self):
        op, p = self.recv(15)
        assert op == SMSG_AUTH_CHALLENGE, hex(op)
        server_seed = p[:4]
        client_seed = secrets.token_bytes(4)
        digest = sha1(self.user.encode(), b"\0" * 4, client_seed, server_seed, self.K)
        self.send(CMSG_AUTH_SESSION, struct.pack("<II", BUILD, 0) + self.user.encode() + b"\0" + client_seed + digest)
        self.crypt = True
        got = self.wait((SMSG_AUTH_RESPONSE,), 15)
        if not got or got[1][0] != AUTH_OK:
            raise RuntimeError(f"world auth failed: {got and got[1][:1].hex()}")

    def characters(self):
        self.send(CMSG_CHAR_ENUM)
        _, p = self.wait((SMSG_CHAR_ENUM,), 15)
        out, off = [], 1
        for _ in range(p[0]):
            guid = struct.unpack_from("<Q", p, off)[0]
            name, off = _cstr(p, off + 8)
            race, cls = p[off], p[off + 1]
            off += 9
            zone, mapid = struct.unpack_from("<II", p, off)
            off += 8 + 12 + 8 + 1 + 12 + 20 * 5
            out.append({"guid": guid, "name": name, "race": race, "class": cls, "zone": zone, "map": mapid})
        return out

    def create_character(self, name, race=1, cls=1):
        self.send(CMSG_CHAR_CREATE, name.encode() + b"\0" + bytes([race, cls, 0, 0, 0, 0, 0, 0, 0]))
        _, p = self.wait((SMSG_CHAR_CREATE,), 15)
        if p[0] != CHAR_CREATE_SUCCESS:
            raise RuntimeError(f"char create {name} failed: code 0x{p[0]:02x}")

    def login(self, guid):
        self.guid = guid
        self.send(CMSG_PLAYER_LOGIN, struct.pack("<Q", guid))
        got = self.wait((SMSG_LOGIN_VERIFY_WORLD, SMSG_CHARACTER_LOGIN_FAILED), 30)
        if not got or got[0] != SMSG_LOGIN_VERIFY_WORLD:
            raise RuntimeError(f"login failed: {got}")
        self.pump(2.0)

    def say(self, text, lang=LANG_COMMON):
        self.send(CMSG_MESSAGECHAT, struct.pack("<II", CHAT_MSG_SAY, lang) + text.encode() + b"\0")

    def command(self, text, settle=1.5):
        mark = len(self.chat)
        self.say(text)
        self.pump(settle)
        return "\n".join(self.chat[mark:])

    def gps(self, tries=3):
        for _ in range(tries):
            mark = len(self.chat)
            self.say(".gps")
            end = time.time() + 8
            while time.time() < end:
                self.wait((SMSG_MESSAGECHAT,), end - time.time())
                m = GPS_RE.search("\n".join(self.chat[mark:]))
                if m:
                    f = [float(v) for v in m.groups()[1:6]]
                    return {"map": int(m.group(1)), "x": f[0], "y": f[1], "z": f[2], "ground": f[3], "floor": f[4],
                            "have_map": m.group(7) == "1", "have_vmap": m.group(8) == "1"}
        raise RuntimeError("no .gps report: " + " | ".join(self.chat[-5:]))

    def close(self):
        try:
            self.send(CMSG_LOGOUT_REQUEST)
            self.wait((SMSG_LOGOUT_COMPLETE,), 25)
        except OSError:
            pass
        self.sock.close()


def connect(user, password, char_name, host=None, port=None, log=None):
    """Logon, pick the first realm, log in `char_name` (created as a human warrior if missing)."""
    host = host or os.environ.get("REALM_HOST", "127.0.0.1")
    port = int(port or os.environ.get("REALM_PORT", "3735"))
    K, realms = logon(host, port, user, password)
    if not realms:
        raise RuntimeError("empty realm list")
    w = World(realms[0][1], user, K, log=log)
    chars = {c["name"].lower(): c for c in w.characters()}
    if char_name.lower() not in chars:
        w.create_character(char_name)
        chars = {c["name"].lower(): c for c in w.characters()}
    w.login(chars[char_name.lower()]["guid"])
    return w
