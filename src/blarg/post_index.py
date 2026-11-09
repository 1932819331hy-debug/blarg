from datetime import date, datetime, timedelta
from urllib.parse import quote

from markupsafe import Markup, escape


def _post_date(value):
    """Order valid ISO dates by exact UTC microseconds, without datetime bounds."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return (False, 0)
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, datetime.min.time())
    if not isinstance(value, datetime):
        return (False, 0)
    # UTC conversion can cross years 1/9999. Integer arithmetic preserves both
    # those valid instants and microsecond distinctions near the upper bound.
    offset = value.utcoffset() or timedelta(0)
    local_microseconds = (
        ((value.toordinal() * 24 + value.hour) * 60 + value.minute) * 60 + value.second
    ) * 1_000_000 + value.microsecond
    offset_microseconds = (
        offset.days * 86400 + offset.seconds
    ) * 1_000_000 + offset.microseconds
    return (True, local_microseconds - offset_microseconds)


def write_post_indexes(source, target, template, posts):
    """Add collection indexes without changing the builder's flat article URLs."""
    for collection in ("blog", "posts"):
        if not (source / collection).is_dir():
            continue
        destination = target / collection / "index.html"
        if destination.exists():
            continue
        entries = [
            (page.relative_to(source), metadata)
            for page, metadata in posts
            if page.relative_to(source).parts[0] == collection
            and len(page.relative_to(source).parts) > 1
        ]
        entries.sort(key=lambda entry: entry[0].as_posix())
        entries.sort(key=lambda entry: _post_date(entry[1].get("date")), reverse=True)
        items = []
        for page, metadata in entries:
            link = "../" + quote(page.stem, safe="") + "/"
            title = metadata.get("title") or page.stem
            items.append(f'<li><a href="{escape(link)}">{escape(title)}</a></li>')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            template.render(
                body=Markup("<ul>\n" + "\n".join(items) + "\n</ul>"),
                frontmatter={"title": collection.capitalize()},
            ),
            encoding="utf-8",
        )
