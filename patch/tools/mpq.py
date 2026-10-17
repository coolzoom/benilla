"""Minimal StormLib (Homebrew libstorm) wrapper: read files from the client archive chain and build MPQs."""
import ctypes
import os
from ctypes import POINTER, byref, c_bool, c_char, c_char_p, c_uint32, c_uint64, c_void_p

_lib = ctypes.CDLL(os.environ.get("STORMLIB", "/opt/homebrew/lib/libstorm.dylib"))

_lib.SFileOpenArchive.argtypes = [c_char_p, c_uint32, c_uint32, POINTER(c_void_p)]
_lib.SFileOpenArchive.restype = c_bool
_lib.SFileCreateArchive.argtypes = [c_char_p, c_uint32, c_uint32, POINTER(c_void_p)]
_lib.SFileCreateArchive.restype = c_bool
_lib.SFileCloseArchive.argtypes = [c_void_p]
_lib.SFileCloseArchive.restype = c_bool
_lib.SFileHasFile.argtypes = [c_void_p, c_char_p]
_lib.SFileHasFile.restype = c_bool
_lib.SFileOpenFileEx.argtypes = [c_void_p, c_char_p, c_uint32, POINTER(c_void_p)]
_lib.SFileOpenFileEx.restype = c_bool
_lib.SFileGetFileSize.argtypes = [c_void_p, POINTER(c_uint32)]
_lib.SFileGetFileSize.restype = c_uint32
_lib.SFileReadFile.argtypes = [c_void_p, c_void_p, c_uint32, POINTER(c_uint32), c_void_p]
_lib.SFileReadFile.restype = c_bool
_lib.SFileCloseFile.argtypes = [c_void_p]
_lib.SFileCloseFile.restype = c_bool
_lib.SFileCreateFile.argtypes = [c_void_p, c_char_p, c_uint64, c_uint32, c_uint32, c_uint32, POINTER(c_void_p)]
_lib.SFileCreateFile.restype = c_bool
_lib.SFileWriteFile.argtypes = [c_void_p, c_void_p, c_uint32, c_uint32]
_lib.SFileWriteFile.restype = c_bool
_lib.SFileFinishFile.argtypes = [c_void_p]
_lib.SFileFinishFile.restype = c_bool


class FindData(ctypes.Structure):
    _fields_ = [
        ("cFileName", c_char * 1024),
        ("szPlainName", c_char_p),
        ("dwHashIndex", c_uint32),
        ("dwBlockIndex", c_uint32),
        ("dwFileSize", c_uint32),
        ("dwFileFlags", c_uint32),
        ("dwCompSize", c_uint32),
        ("dwFileTimeLo", c_uint32),
        ("dwFileTimeHi", c_uint32),
        ("lcLocale", c_uint32),
    ]


_lib.SFileFindFirstFile.argtypes = [c_void_p, c_char_p, POINTER(FindData), c_char_p]
_lib.SFileFindFirstFile.restype = c_void_p
_lib.SFileFindNextFile.argtypes = [c_void_p, POINTER(FindData)]
_lib.SFileFindNextFile.restype = c_bool
_lib.SFileFindClose.argtypes = [c_void_p]
_lib.SFileFindClose.restype = c_bool

MPQ_OPEN_READ_ONLY = 0x100
MPQ_CREATE_LISTFILE = 0x00100000
MPQ_CREATE_ATTRIBUTES = 0x00200000
MPQ_FILE_COMPRESS = 0x00000200
MPQ_FILE_REPLACEEXISTING = 0x80000000
MPQ_COMPRESSION_ZLIB = 0x02

CLIENT_DIR = os.environ.get("WOW_CLIENT", "/Users/mac/Downloads/git/wow1121cn")

# 1.12.1 mounts the base archives, then patch.MPQ, then every patch-?.MPQ (one character), later ones
# overriding earlier ones; there are no locale subfolders.
BASE_ARCHIVES = ("dbc", "fonts", "interface", "misc", "model", "sound", "speech", "terrain", "texture", "wmo",
                 "base", "backup", "speech2")


def client_chain(client_dir=CLIENT_DIR, extra=(), skip=()):
    """Archives in lookup order (highest priority first). `skip` drops archive file names (e.g. our own patch)."""
    d = os.path.join(client_dir, "Data")
    names = list(extra)
    have = {n.lower(): n for n in os.listdir(d)} if os.path.isdir(d) else {}
    patches = sorted((n for n in have if len(n) == len("patch-x.mpq") and n.startswith("patch-") and n.endswith(".mpq")),
                     reverse=True)
    for n in patches + ["patch.mpq"] + [b + ".mpq" for b in reversed(BASE_ARCHIVES)]:
        if n in have and have[n] not in skip and n not in {s.lower() for s in skip}:
            names.append(os.path.join(d, have[n]))
    return [n for n in names if os.path.exists(n)]


class Archive:
    def __init__(self, path, create=False, max_files=4096):
        self.path = path
        self.h = c_void_p()
        if create:
            if os.path.exists(path):
                os.remove(path)
            # v1 archive with a (listfile); no (attributes), which 1.12 archives never carry.
            ok = _lib.SFileCreateArchive(path.encode(), MPQ_CREATE_LISTFILE, max_files, byref(self.h))
        else:
            ok = _lib.SFileOpenArchive(path.encode(), 0, MPQ_OPEN_READ_ONLY, byref(self.h))
        if not ok:
            raise OSError(f"cannot open MPQ {path} (errno {ctypes.get_errno()})")

    def close(self):
        if self.h:
            _lib.SFileCloseArchive(self.h)
            self.h = c_void_p()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def has(self, name):
        return bool(_lib.SFileHasFile(self.h, name.encode()))

    def read(self, name):
        fh = c_void_p()
        if not _lib.SFileOpenFileEx(self.h, name.encode(), 0, byref(fh)):
            return None
        try:
            size = _lib.SFileGetFileSize(fh, None)
            buf = ctypes.create_string_buffer(size)
            got = c_uint32()
            _lib.SFileReadFile(fh, buf, size, byref(got), None)
            return buf.raw[:got.value]
        finally:
            _lib.SFileCloseFile(fh)

    def list(self, mask="*"):
        fd = FindData()
        hf = _lib.SFileFindFirstFile(self.h, mask.encode(), byref(fd), None)
        out = []
        if not hf:
            return out
        while True:
            out.append(fd.cFileName.decode("latin-1"))
            if not _lib.SFileFindNextFile(hf, byref(fd)):
                break
        _lib.SFileFindClose(hf)
        return out

    def write(self, name, data):
        fh = c_void_p()
        flags = MPQ_FILE_COMPRESS | MPQ_FILE_REPLACEEXISTING
        if not _lib.SFileCreateFile(self.h, name.encode(), 0, len(data), 0, flags, byref(fh)):
            raise OSError(f"SFileCreateFile failed for {name}")
        if data and not _lib.SFileWriteFile(fh, data, len(data), MPQ_COMPRESSION_ZLIB):
            raise OSError(f"SFileWriteFile failed for {name}")
        if not _lib.SFileFinishFile(fh):
            raise OSError(f"SFileFinishFile failed for {name}")


class Chain:
    """Reads a file the way the client resolves it: first archive in priority order that has it."""

    def __init__(self, paths=None):
        self.archives = [Archive(p) for p in (paths or client_chain())]

    def read(self, name):
        for a in self.archives:
            if a.has(name):
                return a.read(name)
        return None

    def where(self, name):
        return [a.path for a in self.archives if a.has(name)]

    def close(self):
        for a in self.archives:
            a.close()


def build(path, files):
    """files: dict archived_name -> bytes."""
    with Archive(path, create=True, max_files=max(64, len(files) * 2 + 16)) as a:
        for name, data in sorted(files.items()):
            a.write(name, data)
