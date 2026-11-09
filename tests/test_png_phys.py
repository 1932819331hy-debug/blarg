"""PNG3 7.1 / 11.3.4.3 boundary regressions, independently packed with valid CRCs."""

import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from test_images import chunk, parse, png

from blarg.images import optimize_png
from blarg.main import build_site


class PhysicalDimensionsTests(unittest.TestCase):
    def test_out_of_range_axes_pass_through(self):
        for x, y in [
            (0x80000000, 1),
            (0xFFFFFFFF, 1),
            (1, 0x80000000),
            (1, 0xFFFFFFFF),
        ]:
            for unit in (0, 1):
                with self.subTest(x=x, y=y, unit=unit):
                    original, _, _ = png(
                        extra=chunk(b"pHYs", struct.pack(">IIB", x, y, unit))
                    )
                    parse(
                        original
                    )  # Independent CRC check, including the altered metadata.
                    output, status = optimize_png(original)
                    self.assertEqual(output, original)
                    self.assertEqual(status, "invalid metadata")

    def test_valid_axis_and_unit_boundaries_preserve_metadata(self):
        for x in (0, 0x7FFFFFFF):
            for y in (0, 0x7FFFFFFF):
                for unit in (0, 1):
                    with self.subTest(x=x, y=y, unit=unit):
                        metadata = struct.pack(">IIB", x, y, unit)
                        original, raw, _ = png(extra=chunk(b"pHYs", metadata))
                        output, status = optimize_png(original)
                        self.assertEqual(status, "optimized")
                        self.assertLess(len(output), len(original))
                        parts = parse(output)
                        self.assertEqual(
                            [b for k, b in parts if k == b"pHYs"], [metadata]
                        )
                        self.assertEqual(
                            zlib.decompress(
                                b"".join(b for k, b in parts if k == b"IDAT")
                            ),
                            raw,
                        )

    def test_bad_unit_and_peer_integer_fields_remain_passthrough(self):
        for unit in (2, 255):
            original, _, _ = png(extra=chunk(b"pHYs", struct.pack(">IIB", 1, 1, unit)))
            self.assertEqual(optimize_png(original)[0], original)
        # These existing fixed-field checks already exclude >2**31-1.
        for value in (0x80000000, 0xFFFFFFFF):
            original, _, _ = png(extra=chunk(b"gAMA", struct.pack(">I", value)))
            self.assertEqual(optimize_png(original)[0], original)
            for index in range(8):
                values = [0] * 8
                values[index] = value
                original, _, _ = png(extra=chunk(b"cHRM", struct.pack(">8I", *values)))
                self.assertEqual(optimize_png(original)[0], original)

    def test_real_build_copies_invalid_phys_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            target = Path(directory) / "output"
            (source / "images").mkdir(parents=True)
            (source / "page.md").write_text("title: Page\n---\ntext")
            original, _, _ = png(
                extra=chunk(b"pHYs", struct.pack(">IIB", 0x80000000, 1, 1))
            )
            (source / "images/chart.png").write_bytes(original)
            build_site(source, target, optimize_images=True)
            self.assertEqual((target / "images/chart.png").read_bytes(), original)
            self.assertEqual((source / "images/chart.png").read_bytes(), original)
