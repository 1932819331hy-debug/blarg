from html.parser import HTMLParser

from blarg.main import build_site


class Links(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.hrefs = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs.append(dict(attrs)["href"])


def page(source, name, date=None, title="Post"):
    path = source / name
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = f"title: {title!r}\n"
    if date is not None:
        metadata += f"date: {date!r}\n"
    path.write_text(metadata + "---\nBody")


def test_post_collections_have_independent_chronological_indexes(tmp_path):
    source, target = tmp_path / "source", tmp_path / "site"
    page(source, "posts/new.md", "2024-01-01T00:00:00Z")
    page(source, "posts/deep/old.md", "2023-01-01T00:00:00Z")
    page(source, "blog/news.md", "2025-01-01T00:00:00Z")
    page(source, "notes/other.md", "2026-01-01T00:00:00Z")
    build_site(source, target)
    assert (target / "posts/index.html").exists()
    assert Links((target / "posts/index.html").read_text()).hrefs == [
        "../new/",
        "../old/",
    ]
    assert Links((target / "blog/index.html").read_text()).hrefs == ["../news/"]
    assert (target / "new/index.html").exists()
    assert not (target / "notes/index.html").exists()


def test_dates_normalize_offsets_and_keep_unknown_dates_last(tmp_path):
    source, target = tmp_path / "source", tmp_path / "site"
    for name, date in [
        ("a", None),
        ("b", "invalid"),
        ("c", "2024-01-01"),
        ("d", "2024-01-01T01:00:00+02:00"),
        ("e", "2024-01-01T00:00:00"),
        ("f", "2024-01-01T00:00:00Z"),
    ]:
        page(source, f"posts/{name}.md", date)
    build_site(source, target)
    assert (target / "posts/index.html").exists()
    assert Links((target / "posts/index.html").read_text()).hrefs == [
        "../c/",
        "../e/",
        "../f/",
        "../d/",
        "../a/",
        "../b/",
    ]


def test_post_links_are_relative_encoded_and_labels_escaped(tmp_path):
    source, target = tmp_path / "source", tmp_path / "site"
    page(source, 'posts/a #?%".md', "2024-01-01", "<script>alert(1)</script>")
    build_site(source, target)
    assert (target / "posts/index.html").exists()
    text = (target / "posts/index.html").read_text()
    assert Links(text).hrefs == ["../a%20%23%3F%25%22/"]
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


def test_failed_posts_and_node_modules_do_not_enter_post_index(tmp_path):
    source, target = tmp_path / "source", tmp_path / "site"
    page(source, "posts/good.md", "2024-01-01")
    page(source, "posts/node_modules/skipped.md", "2025-01-01")
    (source / "posts/bad.md").write_text("title: [\n---\nBad")
    build_site(source, target)
    assert (target / "posts/index.html").exists()
    assert Links((target / "posts/index.html").read_text()).hrefs == ["../good/"]


def test_custom_output_wins_and_absent_collections_are_unchanged(tmp_path):
    source, target = tmp_path / "source", tmp_path / "site"
    page(source, "blog.md", title="Custom blog")
    page(source, "blog/story.md", "2024-01-01")
    build_site(source, target)
    assert "Custom blog" in (target / "blog/index.html").read_text()
    assert not (target / "posts/index.html").exists()
    assert (target / "index.html").exists()


def test_earliest_valid_date_precedes_unknown_date(tmp_path):
    source, target = tmp_path / "source", tmp_path / "site"
    page(source, "posts/a.md")
    page(source, "posts/z.md", "0001-01-01")
    build_site(source, target)
    assert Links((target / "posts/index.html").read_text()).hrefs == ["../z/", "../a/"]


def test_extreme_offset_dates_remain_valid_with_exact_instant_order(tmp_path):
    source, target = tmp_path / "source", tmp_path / "site"
    for name, value in [
        ("missing", None),
        ("min", "0001-01-01T00:00:00+14:00"),
        ("max", "9999-12-31T23:59:59.999999-14:00"),
        ("a", "9999-12-31T22:59:59.999998-15:00"),
        ("z", "9999-12-31T23:59:59.999998-14:00"),
        ("bad", "invalid"),
    ]:
        page(source, f"posts/{name}.md", value)
    build_site(source, target)
    assert Links((target / "posts/index.html").read_text()).hrefs == [
        "../max/",
        "../a/",
        "../z/",
        "../min/",
        "../bad/",
        "../missing/",
    ]


def test_empty_collection_and_native_yaml_dates_use_selected_template(
    tmp_path, monkeypatch
):
    from jinja2 import DictLoader, Environment

    import blarg.main as main

    monkeypatch.setattr(
        main,
        "template_env",
        Environment(
            loader=DictLoader(
                {"custom.html": "CUSTOM {{ frontmatter.title }} {{ body }}"}
            )
        ),
    )
    source, target = tmp_path / "source", tmp_path / "site"
    (source / "blog").mkdir(parents=True)
    page(source, "posts/old.md")
    (source / "posts/old.md").write_text(
        "title: Native date\ndate: 2020-01-01\n---\nBody"
    )
    page(source, "posts/new.md")
    (source / "posts/new.md").write_text(
        "title: Native timestamp\ndate: 2021-01-01T00:00:00Z\n---\nBody"
    )
    build_site(source, target, "custom.html")
    assert (target / "blog/index.html").read_text().startswith("CUSTOM Blog")
    assert Links((target / "blog/index.html").read_text()).hrefs == []
    assert Links((target / "posts/index.html").read_text()).hrefs == [
        "../new/",
        "../old/",
    ]
