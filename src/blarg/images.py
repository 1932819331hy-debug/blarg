"""Opt-in, bounded image staging. Source trees must not change during a build."""

import os
import shutil
import stat
import struct
import tempfile
import zlib
from contextlib import contextmanager
from pathlib import Path


EXTENSIONS = {
    ".png",
    ".apng",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".avif",
    ".svg",
    ".ico",
}
MAX_PNG_BYTES = 16 * 1024 * 1024
MAX_PIXELS = 16_000_000
MAX_SCANLINE_BYTES = 64 * 1024 * 1024
MAX_FILES = 10_000
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_ENTRIES = 20_000
MAX_DEPTH = 64
SIGNATURE = b"\x89PNG\r\n\x1a\n"


def optimize_png(data):
    """Return a strictly smaller lossless PNG, or the exact original and a reason."""

    def skip(reason):
        return data, reason

    if len(data) > MAX_PNG_BYTES:
        return skip("input limit")
    if not data.startswith(SIGNATURE):
        return skip("invalid signature")
    chunks = []
    compressed = bytearray()
    offset = 8
    state = "header"
    expected = stride = 0
    ended = False
    metadata = set()
    while offset < len(data):
        if len(data) - offset < 12:
            return skip("truncated chunk")
        size = int.from_bytes(data[offset : offset + 4], "big")
        end = offset + size + 12
        if end > len(data):
            return skip("truncated chunk")
        kind = data[offset + 4 : offset + 8]
        body = data[offset + 8 : end - 4]
        if zlib.crc32(kind + body) != int.from_bytes(data[end - 4 : end], "big"):
            return skip("invalid CRC")
        if kind == b"IHDR":
            if state != "header" or size != 13:
                return skip("invalid IHDR")
            width, height, depth, color, compression, filtering, interlace = (
                struct.unpack(">IIBBBBB", body)
            )
            if not (0 < width <= 0x7FFFFFFF and 0 < height <= 0x7FFFFFFF):
                return skip("invalid dimensions")
            if (
                depth != 8
                or color not in (2, 6)
                or compression
                or filtering
                or interlace
            ):
                return skip("unsupported PNG")
            stride = width * (3 if color == 2 else 4) + 1
            expected = stride * height
            if width * height > MAX_PIXELS or expected > MAX_SCANLINE_BYTES:
                return skip("inflation limit")
            state = "before data"
        elif kind == b"IDAT":
            if state not in ("before data", "data"):
                return skip("invalid IDAT order")
            compressed.extend(body)
            state = "data"
        elif kind in {b"gAMA", b"cHRM", b"sRGB", b"pHYs", b"tRNS"}:
            if state != "before data" or kind in metadata:
                return skip("invalid metadata order")
            metadata.add(kind)
            if kind == b"gAMA":
                valid = size == 4 and 0 < int.from_bytes(body, "big") <= 0x7FFFFFFF
            elif kind == b"cHRM":
                valid = size == 32
                if valid:
                    values = struct.unpack(">8I", body)
                    valid = all(0 <= v <= 100000 for v in values) and all(
                        values[i] + values[i + 1] <= 100000 for i in range(0, 8, 2)
                    )
            elif kind == b"sRGB":
                valid = size == 1 and body[0] <= 3
            elif kind == b"pHYs":
                valid = (
                    size == 9
                    and body[-1] <= 1
                    and all(
                        value <= 0x7FFFFFFF for value in struct.unpack(">2I", body[:8])
                    )
                )
            else:
                valid = (
                    color == 2
                    and size == 6
                    and all(value <= 255 for value in struct.unpack(">3H", body))
                )
            if not valid:
                return skip("invalid metadata")
        elif kind == b"tEXt":
            if state == "header":
                return skip("missing IHDR")
            keyword, separator, value = body.partition(b"\0")
            if (
                not separator
                or not 1 <= len(keyword) <= 79
                or keyword.startswith(b" ")
                or keyword.endswith(b" ")
                or b"  " in keyword
                or any(not (32 <= c <= 126 or 161 <= c <= 255) for c in keyword)
                or b"\0" in value
            ):
                return skip("invalid text")
            if state == "data":
                state = "after data"
        elif kind == b"IEND":
            if size or state not in ("data", "after data") or end != len(data):
                return skip("invalid IEND")
            ended = True
        else:
            return skip("unsupported chunk")
        chunks.append((kind, data[offset:end]))
        offset = end
    if not ended:
        return skip("missing IEND")
    try:
        decoder = zlib.decompressobj()
        rows = decoder.decompress(compressed, expected + 1)
        if (
            len(rows) != expected
            or not decoder.eof
            or decoder.unused_data
            or decoder.unconsumed_tail
        ):
            return skip("invalid or oversized zlib stream")
    except zlib.error:
        return skip("invalid zlib stream")
    if any(rows[i] > 4 for i in range(0, expected, stride)):
        return skip("invalid row filter")
    packed = zlib.compress(rows, 9)
    idat = (
        struct.pack(">I", len(packed))
        + b"IDAT"
        + packed
        + struct.pack(">I", zlib.crc32(b"IDAT" + packed))
    )
    output = bytearray(SIGNATURE)
    inserted = False
    for kind, original in chunks:
        if kind == b"IDAT":
            if not inserted:
                output.extend(idat)
                inserted = True
        else:
            output.extend(original)
    if len(output) >= len(data):
        return skip("no size benefit")
    return bytes(output), "optimized"


def _no_links(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError(f"Symlink path is unsupported: {part}")


def validate_roots(source, target):
    """Enabled-only safety checks, before any destructive operation."""
    _no_links(source.absolute())
    _no_links(target.absolute())
    if not source.is_dir():
        raise ValueError("Source must be a directory")
    if source.resolve().is_relative_to(target.resolve()):
        raise ValueError("Target must not be the source or its ancestor")
    if target.exists() and not target.is_dir():
        raise ValueError("Target must be a directory")


def _identity(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"Image must be a regular file: {path}")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def image_plan(source, target):
    root = source / "images"
    if root.is_symlink():
        raise ValueError("Image directory must not be a symlink")
    if not root.exists():
        return []
    if not root.is_dir():
        raise ValueError("Image root must be a directory")
    if root.resolve() == target.resolve():
        return []
    plan = []
    entries = total = 0

    def fail_walk(error):
        raise error

    for directory, directories, filenames in os.walk(
        root, followlinks=False, onerror=fail_walk
    ):
        directory = Path(directory)
        if len(directory.relative_to(root).parts) > MAX_DEPTH:
            raise ValueError("Image directory depth limit exceeded")
        entries += len(directories) + len(filenames)
        if entries > MAX_ENTRIES:
            raise ValueError("Image entry limit exceeded")
        keep = []
        for name in sorted(directories):
            child = directory / name
            if (
                name.startswith(".")
                or name in {"templates", "node_modules"}
                or child.resolve() == target.resolve()
            ):
                continue
            if child.is_symlink():
                raise ValueError(f"Symlink image directory: {child}")
            keep.append(name)
        directories[:] = keep
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            path = directory / name
            if path.suffix.lower() not in EXTENSIONS:
                continue
            _no_links(path)
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("Image escapes source directory")
            identity = _identity(path)
            total += identity[2]
            if len(plan) >= MAX_FILES or total > MAX_TOTAL_BYTES:
                raise ValueError("Image count/byte limit exceeded")
            plan.append((path, path.relative_to(source), identity))
    return plan


def check_image_destinations(plan, destinations):
    """Check new asset collisions only, leaving legacy page/page policy alone."""
    existing = set(destinations)
    for _, destination, _ in plan:
        if destination in existing or any(
            parent in existing for parent in destination.parents
        ):
            raise ValueError(f"Conflicting image output: {destination}")
        if any(destination in other.parents for other in existing):
            raise ValueError(f"Conflicting image output: {destination}")
        existing.add(destination)


@contextmanager
def stage_images(plan):
    """Finish bounded reads and optimization before caller removes its last build."""
    with tempfile.TemporaryDirectory(prefix="blarg-images-") as directory:
        staged = Path(directory)
        optimized = saved = 0
        for path, destination, identity in plan:
            _no_links(path)
            if _identity(path) != identity:
                raise ValueError(f"Image changed during build: {path}")
            output = staged / destination
            output.parent.mkdir(parents=True, exist_ok=True)
            # All temporary paths are privately created. Concurrent source mutation is unsupported.
            with path.open("rb") as source, output.open("wb") as target:
                if path.suffix.lower() == ".png" and identity[2] <= MAX_PNG_BYTES:
                    data = source.read(identity[2] + 1)
                    if len(data) != identity[2]:
                        raise ValueError(f"Image changed during build: {path}")
                    result, reason = optimize_png(data)
                    target.write(result)
                    optimized += reason == "optimized"
                    saved += len(data) - len(result)
                else:
                    remaining = identity[2]
                    while remaining:
                        block = source.read(min(1024 * 1024, remaining))
                        if not block:
                            raise ValueError(f"Image changed during build: {path}")
                        target.write(block)
                        remaining -= len(block)
                    if source.read(1):
                        raise ValueError(f"Image changed during build: {path}")
            if _identity(path) != identity:
                raise ValueError(f"Image changed during build: {path}")
        yield staged, optimized, saved


def copy_staged_images(staged, target, plan):
    for _, destination, _ in plan:
        output = target / destination
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(staged / destination, output)
