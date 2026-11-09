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

### Blog and post indexes

Directories named `blog` or `posts` directly inside the source directory get
their own generated `blog/index.html` or `posts/index.html`. Each lists the
successfully built Markdown files in that directory and its subdirectories.
Other directories are unchanged, including nested directories named `blog` or
`posts` outside those two collections. The source directory's own name does not
make it a collection.

The defaults for these indexes are newest first by the frontmatter `date` (ISO
date or datetime). Dates without a timezone use UTC; timezone offsets are
normalized to UTC. Missing or invalid dates remain listed after dated posts.
Equal dates and undated posts are ordered by source-relative filename. Titles
come from frontmatter, falling back to the filename stem, and are HTML-escaped.

Article output paths remain flat, with encoded relative links such as
`../my-post/` from the collection index. Existing filename collision behavior
is unchanged. The selected Markdown template also renders collection indexes.
An already generated file at a collection's index destination wins, for example
the output of `blog.md`; an empty collection otherwise gets an empty index.
The existing root index and reported source-file count are unchanged.


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
