"""Lossless ZIP container I/O for Prism bundles.

Every entry is read together with its raw local header, raw central-directory
record and raw compressed bytes. Saving without changes reproduces the input
byte for byte. Replacing an entry recompresses only that entry, using the
deflate settings Prism itself uses (level 2, memLevel 9, raw stream), and
patches only the CRC, size and offset fields of its headers.

Format facts are from prismbinder docs/format/README.md section 2 and are
re-checked by tests/test_zipio.py against the local corpus.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field

LOCAL_SIG = b"PK\x03\x04"
CD_SIG = b"PK\x01\x02"
EOCD_SIG = b"PK\x05\x06"

# Prism's deflate parameters (byte-exact with stock zlib).
PRISM_LEVEL = 2
PRISM_MEMLEVEL = 9


def prism_deflate(data: bytes) -> bytes:
    c = zlib.compressobj(PRISM_LEVEL, zlib.DEFLATED, -15, PRISM_MEMLEVEL, zlib.Z_DEFAULT_STRATEGY)
    return c.compress(data) + c.flush()


@dataclass
class ZipEntry:
    name: str
    local_header: bytearray  # 30 fixed bytes + name + extra, verbatim
    cd_record: bytearray  # 46 fixed bytes + name + extra + comment, verbatim
    compressed: bytes
    trailer: bytes = b""  # bytes between this entry's data and the next local header
    modified: bool = field(default=False, compare=False)

    @property
    def method(self) -> int:
        return struct.unpack_from("<H", self.local_header, 8)[0]

    @property
    def flags(self) -> int:
        return struct.unpack_from("<H", self.local_header, 6)[0]

    @property
    def is_dir(self) -> bool:
        return self.name.endswith("/")

    def read(self) -> bytes:
        if self.method == 0:
            return self.compressed
        if self.method == 8:
            return zlib.decompress(self.compressed, -15)
        raise ValueError(f"{self.name}: unsupported compression method {self.method}")

    def replace(self, data: bytes) -> None:
        if self.trailer:
            raise NotImplementedError(f"{self.name}: entry has a data descriptor; rewriting it is not supported")
        if self.method == 0:
            comp = data
        elif self.method == 8:
            comp = prism_deflate(data)
        else:
            raise ValueError(f"{self.name}: unsupported compression method {self.method}")
        crc = zlib.crc32(data) & 0xFFFFFFFF
        struct.pack_into("<III", self.local_header, 14, crc, len(comp), len(data))
        struct.pack_into("<III", self.cd_record, 16, crc, len(comp), len(data))
        self.compressed = comp
        self.modified = True


class ZipArchive:
    """A ZIP archive held entirely in memory, entry order preserved."""

    def __init__(self, entries: list[ZipEntry], eocd_tail: bytes, prefix: bytes = b""):
        self.entries = entries
        self.eocd_tail = eocd_tail  # EOCD comment, verbatim
        self.prefix = prefix  # any bytes before the first local header

    # ---- reading -------------------------------------------------------
    @classmethod
    def from_bytes(cls, buf: bytes) -> ZipArchive:
        eocd = buf.rfind(EOCD_SIG)
        if eocd < 0:
            raise ValueError("not a ZIP archive: end-of-central-directory record not found")
        (_, disk, cd_disk, n_disk, n_total, _cd_size, cd_off, comment_len) = struct.unpack_from("<4sHHHHIIH", buf, eocd)
        if disk or cd_disk or n_disk != n_total or cd_off == 0xFFFFFFFF:
            raise ValueError("multi-disk or ZIP64 archives are not supported")
        eocd_tail = buf[eocd + 22 : eocd + 22 + comment_len]

        records = []
        p = cd_off
        for _ in range(n_total):
            if buf[p : p + 4] != CD_SIG:
                raise ValueError(f"bad central directory signature at {p}")
            name_len, extra_len, comm_len = struct.unpack_from("<HHH", buf, p + 28)
            rec_len = 46 + name_len + extra_len + comm_len
            rec = bytearray(buf[p : p + rec_len])
            csize = struct.unpack_from("<I", rec, 20)[0]
            loff = struct.unpack_from("<I", rec, 42)[0]
            name = rec[46 : 46 + name_len].decode("utf-8")
            records.append((loff, csize, name, rec))
            p += rec_len

        order = sorted(range(len(records)), key=lambda i: records[i][0])
        if order != list(range(len(records))):
            raise ValueError("central directory order differs from physical order; not supported yet")

        entries: list[ZipEntry] = []
        prefix = buf[: records[0][0]] if records else b""
        for i, (loff, csize, name, rec) in enumerate(records):
            if buf[loff : loff + 4] != LOCAL_SIG:
                raise ValueError(f"{name}: bad local header signature")
            ln, le = struct.unpack_from("<HH", buf, loff + 26)
            hdr_len = 30 + ln + le
            data_start = loff + hdr_len
            data_end = data_start + csize
            nxt = records[i + 1][0] if i + 1 < len(records) else cd_off
            entries.append(
                ZipEntry(
                    name=name,
                    local_header=bytearray(buf[loff:data_start]),
                    cd_record=rec,
                    compressed=bytes(buf[data_start:data_end]),
                    trailer=bytes(buf[data_end:nxt]),
                )
            )
        return cls(entries, eocd_tail, prefix)

    @classmethod
    def open(cls, path: str) -> ZipArchive:
        with open(path, "rb") as f:
            return cls.from_bytes(f.read())

    # ---- access --------------------------------------------------------
    def names(self) -> list[str]:
        return [e.name for e in self.entries]

    def entry(self, name: str) -> ZipEntry:
        for e in self.entries:
            if e.name == name:
                return e
        raise KeyError(name)

    def read(self, name: str) -> bytes:
        return self.entry(name).read()

    # ---- structural edits ----------------------------------------------
    @classmethod
    def new(cls) -> ZipArchive:
        return cls([], b"")

    def has(self, name: str) -> bool:
        return any(e.name == name for e in self.entries)

    def remove(self, name: str) -> None:
        self.entries = [e for e in self.entries if e.name != name]

    def add(self, name: str, data: bytes = b"", *, index: int | None = None,
            timestamp: tuple[int, int, int, int, int, int] = (2026, 1, 1, 0, 0, 0)) -> ZipEntry:
        """Add an entry using the header profile Prism writes (prismbinder §2):
        made-by 0x033F; extract version 45 under data/tables/, else 20;
        directories stored with flag 0 and attrs 0x41FF0000; files deflated
        with flag 4 and attrs 0x81B60000 (0666)."""
        if self.has(name):
            raise ValueError(f"entry exists: {name}")
        is_dir = name.endswith("/")
        y, mo, d, h, mi, s = timestamp
        dos_time = (h << 11) | (mi << 5) | (s // 2)
        dos_date = ((y - 1980) << 9) | (mo << 5) | d
        version = 45 if name.startswith("data/tables/") and not is_dir else 20
        flags, method, attrs = (0, 0, 0x41FF0000) if is_dir else (4, 8, 0x81B60000)
        raw_name = name.encode("utf-8")
        local = bytearray(struct.pack("<4sHHHHHIIIHH", LOCAL_SIG, version, flags, method, dos_time, dos_date,
                                      0, 0, 0, len(raw_name), 0) + raw_name)
        cd = bytearray(struct.pack("<4sHHHHHHIIIHHHHHII", CD_SIG, 0x033F, version, flags, method, dos_time, dos_date,
                                   0, 0, 0, len(raw_name), 0, 0, 0, 0, attrs, 0) + raw_name)
        e = ZipEntry(name=name, local_header=local, cd_record=cd, compressed=b"")
        e.replace(data)
        if index is None:
            self.entries.append(e)
        else:
            self.entries.insert(index, e)
        return e

    def put(self, name: str, data: bytes) -> None:
        """Replace an entry's contents, or add it (and any missing parent
        directory entries) if absent."""
        if self.has(name):
            self.entry(name).replace(data)
            return
        parts = name.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            d = "/".join(parts[:i]) + "/"
            if not self.has(d):
                self.add(d)
        self.add(name, data)

    # ---- writing -------------------------------------------------------
    def to_bytes(self) -> bytes:
        out = bytearray(self.prefix)
        cd = bytearray()
        for e in self.entries:
            offset = len(out)
            out += e.local_header
            out += e.compressed
            out += e.trailer
            rec = bytearray(e.cd_record)
            struct.pack_into("<I", rec, 42, offset)
            cd += rec
        cd_off = len(out)
        out += cd
        n = len(self.entries)
        out += struct.pack("<4sHHHHIIH", EOCD_SIG, 0, 0, n, n, len(cd), cd_off, len(self.eocd_tail))
        out += self.eocd_tail
        return bytes(out)

    def save(self, path: str) -> None:
        with open(path, "wb") as f:
            f.write(self.to_bytes())
