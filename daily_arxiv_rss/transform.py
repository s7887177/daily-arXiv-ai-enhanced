import re
from daily_arxiv_rss.parse import RawItem

_OAI_PREFIX = "oai:arXiv.org:"
_VERSION_RE = re.compile(r"v\d+$")


def _versioned_id(guid: str) -> str:
    return guid.removeprefix(_OAI_PREFIX).strip()


def _bare_id(versioned: str) -> str:
    return _VERSION_RE.sub("", versioned)


def _summary(description: str) -> str:
    marker = "Abstract: "
    idx = description.find(marker)
    if idx != -1:
        return description[idx + len(marker):].strip()
    return description.strip()


def _authors(dc_creator: str) -> list[str]:
    return [a.strip() for a in dc_creator.split(",") if a.strip()]


def build_announce_index(feeds: dict[str, list[RawItem]]) -> dict[str, dict[str, str]]:
    """category -> { versioned_id : announce_type }"""
    index: dict[str, dict[str, str]] = {}
    for category, items in feeds.items():
        index[category] = {
            _versioned_id(it.guid): it.announce_type for it in items
        }
    return index


def resolved_categories(item: RawItem,
                        announce_index: dict[str, dict[str, str]]) -> list[str]:
    cats = list(item.categories)
    if item.announce_type != "cross":
        return cats
    vid = _versioned_id(item.guid)
    for cat in cats:
        feed = announce_index.get(cat)
        if feed and feed.get(vid) == "new":
            return [cat] + [c for c in cats if c != cat]
    return cats  # fallback: order unchanged


def to_record(item: RawItem) -> dict:
    vid = _versioned_id(item.guid)
    bare = _bare_id(vid)
    return {
        "id": vid,
        "categories": list(item.categories),
        "pdf": f"https://arxiv.org/pdf/{bare}",
        "abs": item.link,
        "authors": _authors(item.dc_creator),
        "title": item.title,
        "comment": None,
        "summary": _summary(item.description),
    }


import json
from pathlib import Path


def assemble(requested_feeds: dict[str, list[RawItem]],
             announce_index: dict[str, dict[str, str]]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for items in requested_feeds.values():
        for it in items:
            rec = to_record(it)
            if rec["id"] in seen:
                continue
            seen.add(rec["id"])
            rec["categories"] = resolved_categories(it, announce_index)
            out.append(rec)
    return out


def write_jsonl(records: list[dict], path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
