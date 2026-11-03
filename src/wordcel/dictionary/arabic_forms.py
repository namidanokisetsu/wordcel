"""Resolve Arabic form redirects without crossing homographic lexical entries."""
from dataclasses import replace
import json


def _legacy_rules(labels):
    words = set(" ".join(labels).split())
    if words & {"perfective", "imperfective", "indicative", "subjunctive", "jussive", "imperative", "participle"}:
        return frozenset({"v"})
    if words & {"triptote", "diptote", "definite", "indefinite", "construct", "genitive", "accusative", "nominative"}:
        return frozenset({"n", "adj", "num"})
    return frozenset()


def lookup_forms(library, packs, term, limit):
    entries = {entry.id: entry for entry in library._lookup_keys(packs, {term: "exact"}, limit)}
    paths, depths, cached = {}, {}, {}
    frontier = [(term, (), frozenset())]
    seen = {(term, frozenset()): 0}
    for depth in range(1, 4):
        following, queued = [], {}
        for candidate, parent, inherited in frontier:
            for _, meta, db in packs:
                modern = meta.get("form_metadata_version") == "1"
                columns = "target,labels,rules" if modern else "target,labels,'' AS rules"
                condition = "key=? OR reading_key=?" if modern else "key=?"
                rows = db.execute(f"SELECT {columns} FROM forms WHERE {condition} LIMIT 64",
                                  (candidate, candidate) if modern else (candidate,))
                for row in rows:
                    target = row["target"]
                    labels = tuple(json.loads(row["labels"])) or ("inflected form",)
                    rules = frozenset(row["rules"].split()) or _legacy_rules(labels)
                    if inherited and rules and not inherited & rules:
                        continue
                    rules = rules or inherited
                    state = (target, rules)
                    if seen.get(state, depth) < depth or state not in seen and len(seen) >= 128:
                        continue
                    seen[state] = depth
                    if target not in cached:
                        cached[target] = library._lookup_keys(packs, {target: "form"}, limit)
                    found = [entry for entry in cached[target]
                             if not rules or not entry.rules or rules.intersection(entry.rules)]
                    path = parent + labels
                    for entry in found:
                        if entry.id in entries and entries[entry.id].route == "exact":
                            continue
                        if depths.get(entry.id, depth) < depth:
                            continue
                        entries.setdefault(entry.id, entry)
                        depths[entry.id] = depth
                        alternatives = paths.setdefault(entry.id, [])
                        if path not in alternatives and len(alternatives) < 8:
                            alternatives.append(path)
                    # A real headword terminates this path. Its spelling may also
                    # be an unrelated inflection; following that edge mixes senses.
                    pending = queued.setdefault(state, [])
                    if not found and path not in pending and len(pending) < 8:
                        pending.append(path)
                        following.append((target, path, rules))
        frontier = following
        if not frontier:
            break
    result = []
    for identity, entry in entries.items():
        alternatives = paths.get(identity, ())
        if alternatives:
            labels = alternatives[0] if len(alternatives) == 1 else (
                " OR ".join(" · ".join(path) for path in alternatives),)
            entry = replace(entry, inflection=labels)
        result.append(entry)
    return tuple(result[:limit])
