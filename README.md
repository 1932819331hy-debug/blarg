# Blarg README

A static site generator

## Features

- Fast
- Simple
- Easy

## Installation:

```
git clone git@github.com:pydanny/blarg.git
cd blarg
pip install -e .
```

## Building:

```
blarg build .
```


## Serving the site:

```
blarg serve
```

## Release to PyPI

Create a pull request that:

1. Adds release notes to `CHANGELOG.md`.

2. Updates the `VERSION` constant in `pyproject.toml` and .

Commit these changes in a single commit with subject matching
`Bump version to v...`.

After merging the pull request, push an annotated tag to Github with:

```sh
make tag
```

This will trigger a Github action to publish the package to PyPI.

Note: Until we're configured, just do this to release:

```
pip install -U build twine
python -m build
twine upload dist/*
```
## Optional image assets (initial PNG optimization support)

Use `blarg build --source posts --target site --optimize-images`, or
`build_site(source, target, optimize_images=True)`. This is **off by default**.
The enabled build copies selected files from `source/images/` to `target/images/`,
retaining subdirectories. Allowed extensions (case-insensitive): PNG, APNG, JPG,
JPEG, GIF, WebP, AVIF, SVG and ICO. Other files are not copied. SVG remains trusted
author content; it is not sanitized. No network requests or image dependencies
are added.

Write image URLs for the output location. For example, `nested/story.md` becomes
`story/index.html`; use `![Chart](../images/chart.png)` for `images/chart.png`.
URLs are not rewritten. Encode spaces and reserved characters in authored URLs.
Source-relative references beside Markdown are not automatically relocated.

Only eligible static, non-interlaced 8-bit RGB/RGBA PNGs are recompressed, and only
when the whole file becomes smaller. IDAT compression changes, but filtered
scanlines, pixels and all metadata bytes stay unchanged. Supported ancillary
chunks are tEXt, gAMA, cHRM, sRGB, pHYs and RGB tRNS. ICC/EXIF, unknown chunks,
animation, other PNG variants, invalid PNGs and files without savings pass through
unchanged. Other listed formats also pass through unchanged. Copying is not
validation, repair or a security guarantee. Nothing is resized, converted or
stripped. The build reports copied/optimized counts and bytes saved separately
from page counts. This is a first increment, not comprehensive image optimization.

PNG optimization limits are 16 MiB input, 16 million pixels and 64 MiB inflated
scanlines. Over-limit PNGs are copied in bounded chunks. Builds reject more than
10,000 image files, 1 GiB total image input, 20,000 visited image-tree entries or
64 directory levels. These defensive limits are implementation choices.
Hidden entries, templates, node_modules and generated target subtrees are excluded.
Symlinks and selected nonregular files are rejected. The enabled build rejects
source/ancestor targets, symlink path components, and asset output collisions.
These checks do not change the disabled build's existing behavior or independently
reject existing page/page conflicts.

Image discovery, collision checks, bounded staging and optimization happen before
clearing the old output. Source images are never modified. Do not mutate the source
tree while building; observed changes fail, but hostile concurrent filesystem
changes are not supported. Normal builds still replace the target directory.
Unrelated page rendering and final output I/O are not transactional. Disabling the
option or removing source images removes stale copied assets on the next build.
