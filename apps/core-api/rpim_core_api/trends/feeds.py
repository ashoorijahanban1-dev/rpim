"""Minimal RSS 2.0 / Atom parser for the radars (M19).

Legitimate syndication endpoints only (rule 5 spirit — feeds EXIST to be
fetched; no ToS-breaking scraping). stdlib ElementTree is enough for
title+link extraction and resolves no external entities; feed URLs are
operator-configured env values, never user input.
"""

import xml.etree.ElementTree as ET

_ATOM_NS = "{http://www.w3.org/2005/Atom}"


class FeedParseError(Exception):
    """Not a parsable RSS/Atom document — the caller skips this source."""


def parse_feed(xml_text: str) -> list[dict]:
    """Return [{title, link}] in document order for RSS 2.0 or Atom."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise FeedParseError(f"not valid XML: {type(exc).__name__}") from exc

    items: list[dict] = []
    if root.tag == "rss":
        for item in root.findall("./channel/item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if title:
                items.append({"title": title, "link": link})
    elif root.tag == f"{_ATOM_NS}feed":
        for entry in root.findall(f"./{_ATOM_NS}entry"):
            title = (entry.findtext(f"{_ATOM_NS}title") or "").strip()
            link_el = entry.find(f"{_ATOM_NS}link")
            link = (link_el.get("href", "") if link_el is not None else "").strip()
            if title:
                items.append({"title": title, "link": link})
    else:
        raise FeedParseError(f"unsupported feed root element: {root.tag!r}")
    return items
