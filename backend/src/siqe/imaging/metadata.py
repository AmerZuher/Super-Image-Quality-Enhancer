"""Reading GPS coordinates, and removing location from a file without touching its pixels.

Removal works in place and never changes the file's length: the EXIF GPS directory is
emptied and its values zeroed, and GPS fields in XMP are overwritten with spaces. Every other
offset in the file stays valid, so camera data, maker notes, colour profiles and the
compressed image are kept byte for byte. It works on any container that embeds EXIF as a TIFF
block (JPEG, WebP, HEIC/AVIF, TIFF) and on PNG, whose chunk checksums are recomputed.
"""

import mmap
import re
import struct
import zlib
from pathlib import Path

GPS_TAG = 0x8825
_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4}
_EXIF_HEADER = re.compile(rb"Exif\x00\x00(?=II\*\x00|MM\x00\*)")
_XMP_GPS = re.compile(
    rb"""(?:\s(?:exif|exifEX):GPS\w+\s*=\s*"[^"]*")|(?:<(exif|exifEX):GPS(\w+)\b[^>]*?/>)"""
    rb"""|(?:<(exif|exifEX):GPS(\w+)\b[^>]*>.*?</\3:GPS\4\s*>)""",
    re.DOTALL,
)
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class MetadataError(ValueError):
    pass


# ----------------------------------------------------------------------------- reading

_RATIONAL = re.compile(r"(-?\d+)/(\d+)")


def _rationals(text: str) -> list[float]:
    values = [int(a) / int(b) for a, b in _RATIONAL.findall(text) if int(b) != 0]
    if values:
        return values
    try:
        return [float(x) for x in text.split()]
    except ValueError:
        return []


def gps_from_fields(fields: dict[str, str]) -> tuple[float, float] | None:
    """Decimal latitude and longitude from libvips ``exif-ifd3-*`` values (name without prefix)."""
    lat = _rationals(fields.get("GPSLatitude", ""))
    lon = _rationals(fields.get("GPSLongitude", ""))
    if not lat or not lon:
        return None

    def degrees(parts: list[float]) -> float:
        d, m, s = (*parts, 0.0, 0.0)[:3]
        return d + m / 60 + s / 3600

    la, lo = degrees(lat), degrees(lon)
    if fields.get("GPSLatitudeRef", "N").strip().upper().startswith("S"):
        la = -la
    if fields.get("GPSLongitudeRef", "E").strip().upper().startswith("W"):
        lo = -lo
    if not (-90 <= la <= 90 and -180 <= lo <= 180) or (la == 0 and lo == 0):
        return None
    return round(la, 6), round(lo, 6)


# ----------------------------------------------------------------------------- removal


def _blank_gps_ifd(buf: mmap.mmap | bytearray, base: int, limit: int) -> bool:
    """Empty the GPS directory of the TIFF block at ``base``. Returns True if one was found."""
    if base + 8 > limit:
        return False
    order = buf[base : base + 2]
    if order == b"II":
        e = "<"
    elif order == b"MM":
        e = ">"
    else:
        return False
    (ifd0,) = struct.unpack(e + "I", buf[base + 4 : base + 8])
    pos = base + ifd0
    if pos + 2 > limit:
        return False
    (count,) = struct.unpack(e + "H", buf[pos : pos + 2])
    gps_offset = None
    for i in range(min(count, 1000)):
        entry = pos + 2 + 12 * i
        if entry + 12 > limit:
            break
        tag, _type, _n, value = struct.unpack(e + "HHII", buf[entry : entry + 12])
        if tag == GPS_TAG:
            gps_offset = value
            break
    if gps_offset is None:
        return False
    gps = base + gps_offset
    if gps + 2 > limit:
        return False
    (entries,) = struct.unpack(e + "H", buf[gps : gps + 2])
    for i in range(min(entries, 1000)):
        entry = gps + 2 + 12 * i
        if entry + 12 > limit:
            break
        _tag, kind, n, value = struct.unpack(e + "HHII", buf[entry : entry + 12])
        size = _TYPE_SIZES.get(kind, 1) * n
        if size > 4 and base + value + size <= limit:
            buf[base + value : base + value + size] = bytes(size)
        buf[entry : entry + 12] = bytes(12)
    buf[gps : gps + 2] = struct.pack(e + "H", 0)  # an empty directory
    if gps + 6 <= limit:
        buf[gps + 2 : gps + 6] = bytes(4)  # and no next directory
    return True


def _blank_xmp(region: bytes) -> bytes | None:
    """``region`` with XMP GPS fields replaced by spaces of the same length, or None if none."""
    if b"GPS" not in region:
        return None
    out, n = _XMP_GPS.subn(lambda m: b" " * len(m.group(0)), region)
    return out if n else None


def _xmp_spans(buf: mmap.mmap | bytearray) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = buf.find(b"<x:xmpmeta")
    while start != -1:
        end = buf.find(b"</x:xmpmeta>", start)
        if end == -1:
            break
        spans.append((start, end + len(b"</x:xmpmeta>")))
        start = buf.find(b"<x:xmpmeta", end)
    return spans


def _strip_png(buf: mmap.mmap | bytearray, size: int) -> int:
    changed = 0
    pos = len(_PNG_SIGNATURE)
    while pos + 12 <= size:
        (length,) = struct.unpack(">I", buf[pos : pos + 4])
        kind = bytes(buf[pos + 4 : pos + 8])
        data_start, data_end = pos + 8, pos + 8 + length
        if data_end + 4 > size:
            break
        touched = False
        if kind == b"eXIf":
            touched = _blank_gps_ifd(buf, data_start, data_end)
        elif kind == b"iTXt" and bytes(buf[data_start : data_start + 17]) == b"XML:com.adobe.xmp":
            blanked = _blank_xmp(bytes(buf[data_start:data_end]))
            if blanked is not None:
                buf[data_start:data_end] = blanked
                touched = True
        if touched:
            crc = zlib.crc32(bytes(buf[pos + 4 : data_end])) & 0xFFFFFFFF
            buf[data_end : data_end + 4] = struct.pack(">I", crc)
            changed += 1
        if kind == b"IEND":
            break
        pos = data_end + 4
    return changed


def _webp_exif(buf: mmap.mmap | bytearray, size: int) -> list[int]:
    """TIFF block offsets of EXIF chunks in a WebP (RIFF) file; WebP stores TIFF without a prefix."""
    bases: list[int] = []
    pos = 12
    while pos + 8 <= size:
        kind = bytes(buf[pos : pos + 4])
        (length,) = struct.unpack("<I", buf[pos + 4 : pos + 8])
        if kind == b"EXIF":
            start = pos + 8
            if bytes(buf[start : start + 6]) == b"Exif\x00\x00":
                start += 6
            bases.append(start)
        pos += 8 + length + (length & 1)
    return bases


def remove_location(path: Path) -> int:
    """Remove GPS location from ``path`` in place. Returns how many blocks were changed."""
    size = path.stat().st_size
    if size < 16:
        raise MetadataError("the file is too small to be an image")
    with path.open("r+b") as handle, mmap.mmap(handle.fileno(), 0) as buf:
        if buf[:8] == _PNG_SIGNATURE:
            changed = _strip_png(buf, size)
        else:
            changed = 0
            bases: set[int] = {m.start() + 6 for m in _EXIF_HEADER.finditer(buf)}
            if buf[:4] in (b"II*\x00", b"MM\x00*"):  # TIFF: the file is the EXIF structure
                bases.add(0)
            if buf[:4] == b"RIFF" and buf[8:12] == b"WEBP":
                bases.update(_webp_exif(buf, size))
            for base in sorted(bases):
                changed += _blank_gps_ifd(buf, base, size)
            for start, end in _xmp_spans(buf):
                blanked = _blank_xmp(bytes(buf[start:end]))
                if blanked is not None:
                    buf[start:end] = blanked
                    changed += 1
        buf.flush()
    return changed
