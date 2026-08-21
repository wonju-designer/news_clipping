# -*- coding: utf-8 -*-
"""
대시보드용 데이터 저장
- 매일 클리핑 결과를 data/clippings/YYYY-MM-DD.json 으로 저장
- data/index.json 에 날짜 목록을 갱신 (대시보드가 이걸 읽어 아카이브 구성)
저장소(Private)에 누적되며, 대시보드 HTML이 파일을 직접 읽는다.
"""

import json
import os
from datetime import datetime

import config

DATA_DIR = "data"
CLIP_DIR = os.path.join(DATA_DIR, "clippings")
INDEX_PATH = os.path.join(DATA_DIR, "index.json")

SHORT = {
    "industry": "산업", "own": "자사",
    "competitor": "경쟁사", "subsidiary": "자회사", "group": "그룹",
}


def _art_json(a: dict) -> dict:
    pub = a.get("pub")
    return {
        "title": a.get("title", ""),
        "summary": a.get("summary", a.get("desc", "")),
        "press": a.get("press", ""),
        "date": f"{pub:%Y-%m-%d}" if pub else "",
        "datetime": f"{pub:%Y-%m-%d %H:%M}" if pub else "",
        "link": a.get("link", ""),
        "badge": a.get("badge") or "",
        "subgroup": a.get("subgroup") or "",
        "subgroup_label": a.get("subgroup_label") or "",
    }


def save(doc_display: dict, top: list, digests: dict) -> str:
    """하루치 클리핑을 JSON으로 저장하고 인덱스를 갱신. 저장 경로 반환."""
    now = datetime.now(config.KST)
    day = f"{now:%Y-%m-%d}"

    sections = []
    for cat in config.CATEGORIES:
        arts = doc_display.get(cat["id"], [])
        sec = {
            "id": cat["id"],
            "num": cat["num"],
            "title": cat["title"],
            "digest": (digests or {}).get(cat["id"], ""),
            "articles": [_art_json(a) for a in arts],
        }
        if cat.get("subgroups"):
            sec["subgroups"] = [{"id": sg["id"], "label": sg["label"]}
                                for sg in cat["subgroups"]]
        sections.append(sec)

    payload = {
        "date": day,
        "generated_at": f"{now:%Y-%m-%d %H:%M}",
        "top5": [
            {"rank": t["rank"], "headline": t["headline"],
             "category": SHORT.get(_cat_id(t), t.get("cat_title", "")),
             "link": t.get("link", "")}
            for t in (top or [])
        ],
        "sections": sections,
        "total": sum(len(s["articles"]) for s in sections),
    }

    os.makedirs(CLIP_DIR, exist_ok=True)
    path = os.path.join(CLIP_DIR, f"{day}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    _update_index(day, payload["total"])
    print(f"[아카이브] {path} 저장 · 인덱스 갱신")
    return path


def _cat_id(top_item: dict) -> str:
    # top 항목의 cat_title로 역매핑
    rev = {c["title"]: c["id"] for c in config.CATEGORIES}
    return rev.get(top_item.get("cat_title", ""), "")


def _update_index(day: str, total: int) -> None:
    idx = {"days": []}
    if os.path.exists(INDEX_PATH):
        try:
            with open(INDEX_PATH, encoding="utf-8") as f:
                idx = json.load(f)
        except Exception:
            idx = {"days": []}

    days = [d for d in idx.get("days", []) if d.get("date") != day]
    days.append({"date": day, "total": total})
    days.sort(key=lambda d: d["date"], reverse=True)
    idx["days"] = days
    idx["updated_at"] = day

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)
