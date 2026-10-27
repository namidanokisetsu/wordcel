"""Recognized wiktionary-to-yomitan disclosure sections."""
from contextlib import closing
from functools import lru_cache
import json
import re
import sqlite3


SECTIONS = {"grammar": "Show grammar sections", "etymology": "Show etymology",
            "examples": "Show examples"}


def is_wiktionary(title):
    return bool(re.match(r"wty-[a-z-]+$", title, re.IGNORECASE)
                or "wiktionary" in title.casefold())


def section_kind(node):
    if not isinstance(node, dict) or node.get("tag") != "details":
        return None
    data = node.get("data")
    marker = data.get("content") if isinstance(data, dict) else None
    return {"details-entry-Grammar": "grammar", "details-entry-Etymology": "etymology",
            "details-entry-examples": "examples"}.get(marker)


def sections_in(node):
    if isinstance(node, list):
        return set().union(*(sections_in(child) for child in node))
    if isinstance(node, dict):
        kind = section_kind(node)
        return sections_in(node.get("content")) | ({kind} if kind else set())
    return set()


@lru_cache(maxsize=128)
def pack_sections(path, modified, size):
    """Called on a settings worker; file identity invalidates cached capabilities."""
    found = set()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        for (definitions,) in db.execute(
                "SELECT definitions FROM terms WHERE definitions LIKE '%details-entry-%'"):
            found.update(sections_in(json.loads(definitions)))
            if found == SECTIONS.keys():
                break
    return frozenset(found)
