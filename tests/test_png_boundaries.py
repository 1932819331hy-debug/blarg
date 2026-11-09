import struct
import unittest
import zlib
from unittest.mock import patch

from test_images import chunk, parse, pixels_from_rows, png

from blarg.images import optimize_png


def assemble(parts):
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunk(k, b) for k, b in parts)


class PNGBoundaries(unittest.TestCase):
    def test_seeded_finite_filter_and_color_matrix(self):
        # Finite enumeration, not a property-testing-library run.
        for width in (1, 2, 17, 63):
            for color in (2, 6):
                for mode in range(5):
                    with self.subTest(width=width, color=color, mode=mode):
                        data, raw, pixels = png(width, 9, color, [mode])
                        output, reason = optimize_png(data)
                        self.assertLess(len(output), len(data))
                        self.assertEqual(reason, "optimized")
                        parts = parse(output)
                        inflated = zlib.decompress(
                            b"".join(b for k, b in parts if k == b"IDAT")
                        )
                        self.assertEqual(inflated, raw)
                        self.assertEqual(
                            pixels_from_rows(inflated, width, 3 if color == 2 else 4),
                            pixels,
                        )
                        self.assertEqual(optimize_png(output)[0], output)

    def test_malformed_and_unsupported_exact_copies(self):
        data, raw, _ = png()
        parts = parse(data)
        header = parts[0]
        packed = zlib.compress(raw)
        variants = {
            "signature": b"broken" + data[6:],
            "CRC": data[:-1] + bytes([data[-1] ^ 1]),
            "truncated chunk": data[:-5],
            "missing IEND": data[:-12],
            "trailing": data + b"after",
            "duplicate IHDR": assemble([header, header] + parts[1:]),
            "no IDAT": assemble([header, (b"IEND", b"")]),
            "separated IDAT": assemble(
                [
                    header,
                    (b"IDAT", packed[:5]),
                    (b"tEXt", b"Key\0x"),
                    (b"IDAT", packed[5:]),
                    (b"IEND", b""),
                ]
            ),
            "unknown critical": assemble([header, (b"ABCD", b"")] + parts[1:]),
            "unknown ancillary": assemble([header, (b"vpAg", b"")] + parts[1:]),
            "ICC": assemble([header, (b"iCCP", b"x\0\0opaque")] + parts[1:]),
            "animation": assemble(
                [header, (b"acTL", struct.pack(">II", 1, 0))] + parts[1:]
            ),
            "invalid keyword": assemble([header, (b"tEXt", b" bad\0x")] + parts[1:]),
        }
        for label, stream in [
            ("truncated zlib", packed[:-2]),
            ("extra zlib", packed + zlib.compress(b"x")),
            ("too many rows", zlib.compress(raw + b"x")),
            ("invalid filter", zlib.compress(b"\5" + raw[1:])),
        ]:
            variants[label] = assemble([header, (b"IDAT", stream), (b"IEND", b"")])
        for label, index, value in [
            ("16bit", 8, 16),
            ("greyscale", 9, 0),
            ("indexed", 9, 3),
            ("interlaced", 12, 1),
            ("compression", 10, 1),
        ]:
            altered = bytearray(header[1])
            altered[index] = value
            variants[label] = assemble([(b"IHDR", bytes(altered))] + parts[1:])
        for label, value in variants.items():
            with self.subTest(label=label):
                output, reason = optimize_png(value)
                self.assertEqual(output, value)
                self.assertNotEqual(reason, "optimized")

    def test_zero_benefit_and_limits(self):
        data, _, _ = png(1, 1, level=9)
        single = assemble(
            [(k, b) for k, b in parse(data) if k != b"IDAT"][:-1]
            + [
                (b"IDAT", b"".join(b for k, b in parse(data) if k == b"IDAT")),
                (b"IEND", b""),
            ]
        )
        self.assertEqual(optimize_png(single), (single, "no size benefit"))
        for constant in ("MAX_PNG_BYTES", "MAX_PIXELS", "MAX_SCANLINE_BYTES"):
            with self.subTest(constant=constant), patch("blarg.images." + constant, 0):
                self.assertEqual(optimize_png(data)[0], data)
        header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        bomb = assemble(
            [
                (b"IHDR", header),
                (b"IDAT", zlib.compress(b"\0" * 1_000_000)),
                (b"IEND", b""),
            ]
        )
        self.assertEqual(optimize_png(bomb)[0], bomb)
        huge = assemble(
            [
                (b"IHDR", struct.pack(">IIBBBBB", 1000000, 1000000, 8, 6, 0, 0, 0)),
                (b"IDAT", b""),
                (b"IEND", b""),
            ]
        )
        self.assertEqual(optimize_png(huge)[0], huge)

    def test_common_metadata_preserved(self):
        metadata = [
            (b"gAMA", struct.pack(">I", 45455)),
            (
                b"cHRM",
                struct.pack(
                    ">8I", 31270, 32900, 64000, 33000, 30000, 60000, 15000, 6000
                ),
            ),
            (b"sRGB", b"\0"),
            (b"pHYs", struct.pack(">IIB", 2835, 2835, 1)),
            (b"tRNS", struct.pack(">3H", 20, 40, 60)),
        ]
        original, raw, pixels = png(extra=b"".join(chunk(k, b) for k, b in metadata))
        output, reason = optimize_png(original)
        self.assertEqual(reason, "optimized")
        self.assertLess(len(output), len(original))
        self.assertEqual(
            [(k, b) for k, b in parse(output) if k != b"IDAT"],
            [(k, b) for k, b in parse(original) if k != b"IDAT"],
        )
        inflated = zlib.decompress(
            b"".join(b for k, b in parse(output) if k == b"IDAT")
        )
        self.assertEqual(inflated, raw)
        self.assertEqual(pixels_from_rows(inflated, 32, 3), pixels)

    def test_invalid_metadata_is_not_optimized(self):
        for kind, body in [
            (b"gAMA", b"\0" * 4),
            (b"cHRM", b"x"),
            (b"sRGB", b"\4"),
            (b"pHYs", struct.pack(">IIB", 1, 1, 2)),
            (b"tRNS", struct.pack(">3H", 256, 0, 0)),
        ]:
            data, _, _ = png(extra=chunk(kind, body))
            with self.subTest(kind=kind):
                self.assertEqual(optimize_png(data)[0], data)
        for color in (2, 6):
            data, _, _ = png(color=color)
            parts = parse(data)
            bad = assemble(parts[:-1] + [(b"sRGB", b"\0"), parts[-1]])
            self.assertEqual(optimize_png(bad)[0], bad)
        duplicate, _, _ = png(extra=chunk(b"sRGB", b"\0") * 2)
        self.assertEqual(optimize_png(duplicate)[0], duplicate)
