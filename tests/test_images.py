import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from blarg.main import build_site


def chunk(kind, data):
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data))
    )


def png(width=32, height=16, color=2, filters=None, extra=b"", level=0):
    channels = 3 if color == 2 else 4
    pixels = bytes((x // channels % 8) * 20 for x in range(width * channels)) * height
    raw = bytearray()
    prev = bytes(width * channels)
    for y in range(height):
        row = pixels[y * width * channels : (y + 1) * width * channels]
        f = (filters or [0])[y % len(filters or [0])]
        raw.append(f)
        for i, v in enumerate(row):
            a = row[i - channels] if i >= channels else 0
            b = prev[i]
            c = prev[i - channels] if i >= channels else 0
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            predictor = [
                0,
                a,
                b,
                (a + b) // 2,
                a if pa <= pb and pa <= pc else b if pb <= pc else c,
            ][f]
            raw.append((v - predictor) % 256)
        prev = row
    compressed = zlib.compress(bytes(raw), level)
    data = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color, 0, 0, 0))
        + extra
    )
    data += (
        chunk(b"IDAT", compressed[:5])
        + chunk(b"IDAT", compressed[5:])
        + chunk(b"IEND", b"")
    )
    return data, bytes(raw), pixels


def parse(data):
    result = []
    offset = 8
    while offset < len(data):
        n = int.from_bytes(data[offset : offset + 4], "big")
        kind, body = data[offset + 4 : offset + 8], data[offset + 8 : offset + 8 + n]
        assert zlib.crc32(kind + body) == int.from_bytes(
            data[offset + 8 + n : offset + 12 + n], "big"
        )
        result.append((kind, body))
        offset += 12 + n
    return result


def pixels_from_rows(raw, width, channels):
    result = bytearray()
    stride = width * channels
    for offset in range(0, len(raw), stride + 1):
        f = raw[offset]
        row = bytearray(raw[offset + 1 : offset + 1 + stride])
        prior = result[-stride:] if result else bytes(stride)
        for i in range(stride):
            left = row[i - channels] if i >= channels else 0
            above = prior[i]
            upper_left = prior[i - channels] if i >= channels else 0
            if f == 1:
                row[i] = (row[i] + left) % 256
            elif f == 2:
                row[i] = (row[i] + above) % 256
            elif f == 3:
                row[i] = (row[i] + (left + above) // 2) % 256
            elif f == 4:
                prediction = left + above - upper_left
                candidates = [left, above, upper_left]
                nearest = min(candidates, key=lambda v: abs(prediction - v))
                row[i] = (row[i] + nearest) % 256
        result.extend(row)
    return bytes(result)


class ImageBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "images").mkdir()
        (self.source / "story.md").write_text(
            "title: Story\n---\n![Chart](../images/chart.png)"
        )
        self.target = self.root / "output"

    def build(self):
        # A missing new API is reported as a deliberate feature assertion, not a collection error.
        try:
            build_site(self.source, self.target, optimize_images=True)
        except TypeError as error:
            if "optimize_images" in str(error):
                self.fail("build_site has no opt-in image build path")
            raise

    def test_real_build_shrinks_and_preserves_rows_metadata_pixels(self):
        for color in (2, 6):
            with self.subTest(color=color):
                data, raw, pixels = png(
                    color=color,
                    filters=[0, 1, 2, 3, 4],
                    extra=chunk(b"tEXt", b"Author\0Synthetic fixture"),
                )
                source = self.source / "images/chart.png"
                source.write_bytes(data)
                self.build()
                output = (self.target / "images/chart.png").read_bytes()
                self.assertLess(len(output), len(data))
                parts = parse(output)
                inflated = zlib.decompress(
                    b"".join(b for k, b in parts if k == b"IDAT")
                )
                self.assertEqual(inflated, raw)
                self.assertEqual(
                    pixels_from_rows(inflated, 32, 3 if color == 2 else 4), pixels
                )
                self.assertEqual(
                    [(k, b) for k, b in parts if k != b"IDAT"],
                    [(k, b) for k, b in parse(data) if k != b"IDAT"],
                )
                self.assertEqual(source.read_bytes(), data)
                self.assertIn(
                    "../images/chart.png",
                    (self.target / "story/index.html").read_text(),
                )

    def test_passthrough_and_disabled(self):
        data, _, _ = png(extra=chunk(b"eXIf", b"opaque metadata"))
        for name, content in [
            ("chart.png", data),
            ("x.JPG", b"jpeg opaque"),
            ("private.txt", b"never copied"),
        ]:
            (self.source / "images" / name).write_bytes(content)
        build_site(self.source, self.target)
        self.assertFalse((self.target / "images").exists())
        self.build()
        self.assertEqual((self.target / "images/chart.png").read_bytes(), data)
        self.assertEqual((self.target / "images/x.JPG").read_bytes(), b"jpeg opaque")
        self.assertFalse((self.target / "images/private.txt").exists())

    def test_asset_collision_preserves_output(self):
        (self.source / "images.md").write_text("title: Images\n---\nText")
        (self.source / "images/index.html").mkdir()
        (self.source / "images/index.html/chart.png").write_bytes(png()[0])
        self.target.mkdir()
        (self.target / "sentinel").write_bytes(b"keep")
        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual((self.target / "sentinel").read_bytes(), b"keep")

    def test_symlink_preserves_output(self):
        (self.source / "images/chart.png").symlink_to(self.source / "story.md")
        self.target.mkdir()
        (self.target / "sentinel").write_bytes(b"keep")
        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual((self.target / "sentinel").read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
