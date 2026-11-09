import os
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, unquote, urljoin, urlsplit

import test_images
from test_images import png

from blarg.images import image_plan, stage_images
from blarg.main import build_site


class Images(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            self.sources.append(dict(attrs)["src"])


class ImageIntegrationTests(test_images.ImageBuildTests):
    # Reuse fixture setup, not inherited test runs.
    test_real_build_shrinks_and_preserves_rows_metadata_pixels = None
    test_passthrough_and_disabled = None
    test_asset_collision_preserves_output = None
    test_symlink_preserves_output = None

    def sentinel(self):
        self.target.mkdir(exist_ok=True)
        (self.target / "sentinel").write_bytes(b"keep")

    def test_real_module_cli(self):
        (self.source / "images/chart.png").write_bytes(png()[0])
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "blarg.cli",
                "build",
                "--source",
                str(self.source),
                "--target",
                str(self.target),
                "--optimize-images",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.target / "images/chart.png").is_file())
        self.assertIn("1 optimized", result.stdout)
        noflag = subprocess.run(
            [
                sys.executable,
                "-m",
                "blarg.cli",
                "build",
                "--source",
                str(self.source),
                "--target",
                str(self.target),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(noflag.returncode, 0, noflag.stdout + noflag.stderr)
        self.assertFalse((self.target / "images").exists())

    def test_no_images_matches_disabled_bytes_and_pages(self):
        build_site(self.source, self.target)
        snapshot = {
            p.relative_to(self.target): p.read_bytes()
            for p in self.target.rglob("*")
            if p.is_file()
        }
        self.build()
        self.assertEqual(
            snapshot,
            {
                p.relative_to(self.target): p.read_bytes()
                for p in self.target.rglob("*")
                if p.is_file()
            },
        )

    def test_real_authored_urls_root_and_prefix(self):
        names = ["chart.png", "space #?%雪.PNG"]
        for name in names:
            (self.source / "images" / name).write_bytes(png()[0])
        nested = self.source / "nested"
        nested.mkdir()
        refs = "\n".join(
            f"![image](../images/{quote(name)}?v=1#part)" for name in names
        )
        refs += "\n![reference][pic]\n\n[pic]: ../images/chart.png\n\n![remote](https://example.org/a.png)\n"
        (nested / "entry.md").write_text("title: Entry\n---\n" + refs)
        self.build()
        parser = Images()
        parser.feed((self.target / "entry/index.html").read_text())
        self.assertEqual(len(parser.sources), 4)
        for prefix in ("/", "/prefix/"):
            for url in parser.sources[:-1]:
                resolved = urlsplit(
                    urljoin("https://example.test" + prefix + "entry/", url)
                )
                self.assertEqual(resolved.netloc, "example.test")
                local = self.target / unquote(resolved.path.removeprefix(prefix))
                self.assertTrue(local.is_file(), local)
        self.assertEqual(parser.sources[-1], "https://example.org/a.png")

    def test_filters_formats_and_stale_removal(self):
        for name in [".hidden", "templates", "node_modules"]:
            directory = self.source / "images" / name
            directory.mkdir()
            (directory / "skip.png").write_bytes(png()[0])
        contents = {
            f"a.{ext}": b"opaque-" + ext.encode()
            for ext in ("apng", "jpg", "jpeg", "gif", "webp", "avif", "svg", "ico")
        }
        for name, data in contents.items():
            (self.source / "images" / name).write_bytes(data)
        self.build()
        self.assertEqual(
            {p.name for p in (self.target / "images").iterdir()}, set(contents)
        )
        for name, data in contents.items():
            self.assertEqual((self.target / "images" / name).read_bytes(), data)
            (self.source / "images" / name).unlink()
        self.build()
        self.assertFalse((self.target / "images").exists())

    def test_target_under_images_is_excluded(self):
        self.target = self.source / "images/generated"
        self.target.mkdir()
        (self.target / "old.png").write_bytes(png()[0])
        (self.source / "images/chart.png").write_bytes(png()[0])
        self.build()
        self.assertTrue((self.target / "images/chart.png").exists())
        self.assertFalse((self.target / "images/generated").exists())

    def test_source_ancestor_target_and_symlink_parent_rejected(self):
        for target in [self.source, self.root]:
            with self.subTest(target=target), self.assertRaises(ValueError):
                build_site(self.source, target, optimize_images=True)
            self.assertTrue((self.source / "story.md").exists())
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            build_site(self.source, alias / "output", optimize_images=True)
        self.assertTrue((self.source / "story.md").exists())

    def test_symlink_directory_root_and_fifo_rejected(self):
        images = self.source / "images"
        images.rmdir()
        images.symlink_to(self.root, target_is_directory=True)
        self.sentinel()
        with self.assertRaises(ValueError):
            self.build()
        images.unlink()
        images.mkdir()
        link = images / "linked"
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.build()
        link.unlink()
        os.mkfifo(images / "pipe.png")
        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual((self.target / "sentinel").read_bytes(), b"keep")

    def test_count_size_traversal_limits_preserve_output(self):
        (self.source / "images/chart.png").write_bytes(png()[0])
        self.sentinel()
        for constant in ("MAX_FILES", "MAX_TOTAL_BYTES", "MAX_ENTRIES"):
            with (
                self.subTest(constant=constant),
                patch("blarg.images." + constant, 0),
                self.assertRaises(ValueError),
            ):
                self.build()
            self.assertEqual((self.target / "sentinel").read_bytes(), b"keep")
        (self.source / "images/deep").mkdir()
        with patch("blarg.images.MAX_DEPTH", 0), self.assertRaises(ValueError):
            self.build()
        self.assertEqual((self.target / "sentinel").read_bytes(), b"keep")

    def test_over_limit_png_stream_copy_and_changed_source(self):
        data = png()[0]
        path = self.source / "images/chart.png"
        path.write_bytes(data)
        with patch("blarg.images.MAX_PNG_BYTES", 1):
            self.build()
        self.assertEqual((self.target / "images/chart.png").read_bytes(), data)
        plan = image_plan(self.source, self.target)
        path.write_bytes(b"changed")
        with self.assertRaises(ValueError), stage_images(plan):
            self.fail("changed source was staged")

    def test_legacy_duplicate_pages_are_not_newly_rejected(self):
        (self.source / "nested").mkdir()
        (self.source / "nested/story.md").write_text("title: Second\n---\ntext")
        (self.source / "images/story.png").write_bytes(png()[0])
        self.build()
        self.assertTrue((self.target / "story/index.html").exists())
        self.assertTrue((self.target / "images/story.png").exists())

    def test_walk_errors_preserve_output(self):
        self.sentinel()
        original = os.scandir

        def scandir(path):
            if not isinstance(path, int) and Path(path) == self.source / "images":
                raise PermissionError("synthetic inaccessible image directory")
            return original(path)

        with patch("os.scandir", scandir), self.assertRaises(PermissionError):
            self.build()
        self.assertEqual((self.target / "sentinel").read_bytes(), b"keep")
