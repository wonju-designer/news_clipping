# -*- coding: utf-8 -*-
"""
8월 월간 아카이브 백필 (일회성)
- 네이버에서 8월 1일~어제 발행된 실제 기사를 수집
- '매일 발송분'이 아니라 '한 달치를 한 번에 정리한 월간 아카이브'로 명확히 표시
- 각 기사는 실제 발행일 그대로 노출
- AI 요약 없이 원문 설명(desc)을 요약으로 사용 (NAVER 키만 있으면 실행 가능)

실행: python backfill_august.py            (기본 8/1~어제)
      START=2026-08-01 END=2026-08-20 python backfill_august.py
결과: data/clippings/2026-08-monthly.json 생성 → dashboard.build()로 대시보드 갱신
"""

import json
import os
from datetime import datetime, timedelta

import config
import collect
import dashboard

KST = config.KST


def _month_range():
    start_s = os.environ.get("START", "2026-08-01")
    end_s = os.environ.get("END", "")
    start = datetime.strptime(start_s, "%Y-%m-%d").replace(tzinfo=KST)
    if end_s:
        end = datetime.strptime(end_s, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=KST)
    else:
        end = datetime.now(KST)  # 어제까지 자연 포함
    return start, end


def _in_range(pub, start, end):
    return pub is not None and start <= pub <= end


def _collect_terms(terms, badge, start, end, seen, extra_exclude=(), require_any=(),
                   require_context=()):
    """키워드 목록으로 수집 → 기간·필터 통과분만 반환."""
    out = []
    for q in terms:
        for item in collect.naver_search(q, 100):
            art = collect._normalize(item, badge=badge)
            if not art["pub"] or not _in_range(art["pub"], start, end):
                continue
            key = (art["title"], art["orig"])
            if key in seen:
                continue
            text = art["title"] + " " + art["desc"]
            low = text.lower()
            if collect._excluded(text, extra_exclude):
                continue
            if require_any and not any(k.lower() in low for k in require_any):
                continue
            if require_context and not any(k.lower() in low for k in require_context):
                continue
            if art["is_sports"]:
                continue
            art["summary"] = art["desc"][:120] + ("…" if len(art["desc"]) > 120 else "")
            seen.add(key)
            out.append(art)
    out.sort(key=lambda a: a["pub"], reverse=True)
    return out


def _art_json(a):
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


def run():
    start, end = _month_range()
    print(f"[백필] 기간: {start:%Y-%m-%d} ~ {end:%Y-%m-%d} (실제 발행일 기준)")

    sections = []
    grand_total = 0
    for cat in config.CATEGORIES:
        seen = set()
        if cat.get("subgroups"):
            arts = []
            for sg in cat["subgroups"]:
                sgx = sg.get("exclude", ())
                own = _collect_terms(sg["keywords"], "자사", start, end, seen,
                                     extra_exclude=sgx, require_any=sg.get("require_own", ()))
                ind = _collect_terms(sg.get("industry_keywords", []), "산업", start, end, seen,
                                     extra_exclude=sgx, require_any=sg.get("require_ind", ()))
                for x in own + ind:
                    x["subgroup"] = sg["id"]
                    x["subgroup_label"] = sg["label"]
                arts += own + ind
        elif cat.get("industry_keywords"):
            req = cat.get("require_any", ())
            ex = cat.get("exclude", ())
            own = _collect_terms(cat["keywords"], "자사", start, end, seen,
                                 extra_exclude=ex, require_any=req)
            ind = _collect_terms(cat["industry_keywords"], "산업", start, end, seen,
                                 extra_exclude=ex, require_any=req)
            arts = own + ind
        else:
            ex = cat.get("exclude", ())
            req = cat.get("require_any", ())
            quals = cat.get("qualifiers", ())
            terms = collect._expand(cat["keywords"], quals) if quals else cat["keywords"]
            arts = _collect_terms(terms, None, start, end, seen,
                                  extra_exclude=ex, require_any=req,
                                  require_context=cat.get("require_context", ()))

        sec = {
            "id": cat["id"], "num": cat["num"], "title": cat["title"],
            "digest": "",  # 월간 아카이브는 동향 요약 없이 기사 나열
            "articles": [_art_json(a) for a in arts],
        }
        if cat.get("subgroups"):
            sec["subgroups"] = [{"id": s["id"], "label": s["label"]} for s in cat["subgroups"]]
        sections.append(sec)
        grand_total += len(arts)
        print(f"  {cat['num']} {cat['title']}: {len(arts)}건")

    payload = {
        "date": f"{start:%Y-%m}",                       # 정렬용 (오늘 날짜보다 아래로)
        "label": f"{start:%Y년 %-m월} 월간 아카이브 (실제 발행 기사 일괄 정리)",
        "kind": "monthly",
        "generated_at": f"{datetime.now(KST):%Y-%m-%d %H:%M} 정리",
        "top5": [],
        "sections": sections,
        "total": grand_total,
    }

    os.makedirs(dashboard.CLIP_DIR, exist_ok=True)
    path = os.path.join(dashboard.CLIP_DIR, f"{start:%Y-%m}-monthly.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[백필] {path} 저장 · 총 {grand_total}건")

    dashboard.build()
    print("[백필] 대시보드 갱신 완료")


if __name__ == "__main__":
    run()
