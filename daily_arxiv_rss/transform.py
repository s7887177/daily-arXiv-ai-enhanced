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
