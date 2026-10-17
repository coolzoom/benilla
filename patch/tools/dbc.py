"""WDBC reader/writer. Records are lists of uint32 words; strings live in the string block."""
import struct

LOCALE_COUNT = 8          # 1.12: enUS koKR frFR deDE zhCN zhTW esES esMX, then a flags word
ZHCN = 4
LOC_FLAGS = 0x003F007E    # the flags word on stock 1.12 rows


class DBC:
    def __init__(self, data=None, field_count=0):
        self.fields = field_count
        self.records = []
        self.strings = bytearray(b"\0")
        self._index = {}
        if data is not None:
            magic, n, f, size, ssize = struct.unpack_from("<4s4I", data)
            assert magic == b"WDBC", magic
            assert size == f * 4, (size, f)
            self.fields = f
            off = 20
            for _ in range(n):
                self.records.append(list(struct.unpack_from(f"<{f}I", data, off)))
                off += size
            self.strings = bytearray(data[off:off + ssize])

    @classmethod
    def load(cls, path):
        with open(path, "rb") as fh:
            return cls(fh.read())

    def string(self, off):
        end = self.strings.index(0, off)
        return self.strings[off:end].decode("utf-8", "replace")

    def add_string(self, s):
        if not s:
            return 0
        raw = s.encode("utf-8")
        key = bytes(raw)
        if key in self._index:
            return self._index[key]
        off = len(self.strings)
        self.strings += raw + b"\0"
        self._index[key] = off
        return off

    def find(self, rid):
        for r in self.records:
            if r[0] == rid:
                return r
        return None

    def remove(self, rid):
        self.records = [r for r in self.records if r[0] != rid]

    def put(self, rec):
        assert len(rec) == self.fields, (len(rec), self.fields)
        self.remove(rec[0])
        self.records.append(rec)
        self.records.sort(key=lambda r: r[0])

    def loc(self, text):
        """8 locale string slots + flags word, the text in every slot so any client locale shows it."""
        off = self.add_string(text)
        return [off] * LOCALE_COUNT + [LOC_FLAGS if text else 0]

    def serialize(self):
        out = bytearray(struct.pack("<4s4I", b"WDBC", len(self.records), self.fields, self.fields * 4,
                                    len(self.strings)))
        for r in self.records:
            out += struct.pack(f"<{self.fields}I", *[v & 0xFFFFFFFF for v in r])
        out += self.strings
        return bytes(out)


def f2u(v):
    return struct.unpack("<I", struct.pack("<f", v))[0]


def u2f(v):
    return struct.unpack("<f", struct.pack("<I", v))[0]


def i2u(v):
    return v & 0xFFFFFFFF
