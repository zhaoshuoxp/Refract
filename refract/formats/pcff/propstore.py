"""The `Zval` property store in PCFF chunk 0x0852 (Prism 10+ graph colours).

Chunk payload:  b"Zval" <u32 compressed_len> <u32 raw_len> <zlib stream>
Decompressed, a tree of tagged values:

  Mval <u32 type> <u32 body_len> <body> Mend
    type 1  scalar  body = raw bytes (colours are 4 bytes R,G,B,A)
    type 5  dict    body = (Dkey <u32 n> <n bytes key> Dval <Mval>)* Dfin
    type 6  array   body = Asiz <u32 count> (Aval <Mval>)* Afin

Every key seen in the corpus names a colour (PCFF_Plot::fillcolor,
IPGAxSeg::textcolor, PCFF_Graph::bkgndcolor, ...). The legacy RGB fields
elsewhere in the blob are not what Prism 10+ renders from when this store is
present (E7g/E7h: editing every legacy copy changed nothing).
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field

TAG = 0x0852


@dataclass
class Scalar:
    raw: bytes

    @property
    def rgba(self) -> str:
        return self.raw.hex()


@dataclass
class Dict:
    items: list[tuple[str, object]] = field(default_factory=list)

    def get(self, key: str):
        return next((v for k, v in self.items if k == key), None)


@dataclass
class Array:
    items: list[object] = field(default_factory=list)


class _Reader:
    def __init__(self, b: bytes):
        self.b, self.i = b, 0

    def tag(self, expect: bytes) -> None:
        got = self.b[self.i:self.i + 4]
        if got != expect:
            raise ValueError(f"expected {expect!r} at {self.i}, got {got!r}")
        self.i += 4

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.b, self.i)[0]
        self.i += 4
        return v

    def value(self):
        self.tag(b"Mval")
        typ, n = self.u32(), self.u32()
        start = self.i
        if typ == 1:
            v = Scalar(self.b[self.i:self.i + n])
            self.i += n
        elif typ == 5:
            v = Dict()
            while self.b[self.i:self.i + 4] == b"Dkey":
                self.i += 4
                k = self.b[self.i + 4:self.i + 4 + self.u32()].decode("latin-1")
                self.i += len(k)
                self.tag(b"Dval")
                v.items.append((k, self.value()))
            self.tag(b"Dfin")
        elif typ == 6:
            v = Array()
            self.tag(b"Asiz")
            count = self.u32()
            for _ in range(count):
                self.tag(b"Aval")
                v.items.append(self.value())
            self.tag(b"Afin")
        else:
            raise ValueError(f"unknown Mval type {typ} at {start - 12}")
        if self.i - start != n:
            raise ValueError(f"Mval length mismatch at {start - 12}: declared {n}, used {self.i - start}")
        self.tag(b"Mend")
        return v


def _enc(v) -> bytes:
    if isinstance(v, Scalar):
        typ, body = 1, v.raw
    elif isinstance(v, Dict):
        typ = 5
        body = b"".join(b"Dkey" + struct.pack("<I", len(k)) + k.encode("latin-1") + b"Dval" + _enc(x)
                        for k, x in v.items) + b"Dfin"
    elif isinstance(v, Array):
        typ = 6
        body = b"Asiz" + struct.pack("<I", len(v.items)) + b"".join(b"Aval" + _enc(x) for x in v.items) + b"Afin"
    else:
        raise TypeError(v)
    return b"Mval" + struct.pack("<II", typ, len(body)) + body + b"Mend"


def decode_payload(payload: bytes):
    if payload[:4] != b"Zval":
        raise ValueError("not a Zval payload")
    n = struct.unpack_from("<I", payload, 4)[0]
    raw = zlib.decompressobj().decompress(payload[12:12 + n])
    r = _Reader(raw)
    v = r.value()
    if r.i != len(raw):
        raise ValueError(f"trailing bytes in property store: {len(raw) - r.i}")
    return v, raw, payload[12 + n:]


def encode_payload(v, level: int = 6, tail: bytes = b"") -> bytes:
    raw = _enc(v)
    comp = zlib.compress(raw, level)
    return b"Zval" + struct.pack("<II", len(comp), len(raw)) + comp + tail


def walk(v, path: str = ""):
    """Yield (path, Scalar) for every leaf."""
    if isinstance(v, Scalar):
        yield path, v
    elif isinstance(v, Dict):
        for k, x in v.items:
            yield from walk(x, f"{path}/{k}")
    elif isinstance(v, Array):
        for i, x in enumerate(v.items):
            yield from walk(x, f"{path}[{i}]")
