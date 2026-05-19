from dataclasses import dataclass, field
import xml.etree.ElementTree as ET


@dataclass
class RawItem:
    guid: str
    link: str
    title: str
    description: str
    categories: list[str] = field(default_factory=list)
    announce_type: str = ""
    dc_creator: str = ""
    pub_date: str = ""


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def parse_feed(xml_bytes: bytes) -> list[RawItem]:
    root = ET.fromstring(xml_bytes)
    items: list[RawItem] = []
    for item_el in root.iter():
        if _local(item_el.tag) != "item":
            continue
        data = {"guid": "", "link": "", "title": "", "description": "",
                "announce_type": "", "dc_creator": "", "pub_date": ""}
        categories: list[str] = []
        for child in item_el:
            name = _local(child.tag)
            text = (child.text or "").strip()
            if name == "category":
                if text:
                    categories.append(text)
            elif name == "announce_type":
                data["announce_type"] = text
            elif name == "creator":
                data["dc_creator"] = text
            elif name == "pubDate":
                data["pub_date"] = text
            elif name in data:
                data[name] = text
        items.append(RawItem(categories=categories, **data))
    return items
