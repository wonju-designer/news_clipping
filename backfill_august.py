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

import glob
import json
import os
from datetime import datetime, timedelta

import config
import collect
import analyze
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


def _purge_old_backfill(start=None, end=None):
    """기존 백필 파일(backfill_note 있는 것) 삭제. 매일 클리핑은 보존.
    start·end를 주면 그 기간 안의 백필 파일만 삭제(부분 재생성 가능)."""
    s = f"{start:%Y-%m-%d}" if start else None
    e = f"{end:%Y-%m-%d}" if end else None
    removed = 0
    for path in glob.glob(os.path.join(dashboard.CLIP_DIR, "*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        if not (data.get("backfill_note") or data.get("kind") == "monthly"):
            continue                      # 매일 클리핑 → 보존
        day = data.get("date", "")
        if s and e and not (s <= day <= e):
            continue                      # 지정 기간 밖의 백필분 → 보존
        os.remove(path)
        removed += 1
    if removed:
        scope = f" ({s}~{e})" if s and e else ""
        print(f"[백필] 기존 소급분 {removed}건 삭제{scope} (매일 클리핑은 보존)")
    else:
        print("[백필] 삭제할 기존 소급분 없음")


def run():
    start, end = _month_range()
    print(f"[백필] 기간: {start:%Y-%m-%d} ~ {end:%Y-%m-%d} (실제 발행일 기준)")

    # 기존 소급분(backfill_note) 정리 후 새로 생성 — 지정 기간만, 매일 클리핑은 보존
    _purge_old_backfill(start, end)

    # 1) 섹션별 기사 수집 (기존과 동일)
    section_arts = {}   # cat_id -> [arts]
    for cat in config.CATEGORIES:
        seen = set()
        if cat.get("subgroups"):
            arts = []
            for sg in cat["subgroups"]:
                sgx = tuple(sg.get("exclude", ())) + tuple(config.SPORTS_EXCLUDE)
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
        # AI 관련성 필터 — 키워드가 우연히 걸린 무관 기사 제거
        if cat.get("subgroups"):
            filtered = []
            for sg in cat["subgroups"]:
                sg_arts = [a for a in arts if a.get("subgroup") == sg["id"]]
                if sg_arts:
                    filtered += analyze.relevance_filter(sg_arts, sg["id"])
            arts = filtered
        else:
            arts = analyze.relevance_filter(arts, cat["id"])
        section_arts[cat["id"]] = arts
        print(f"  {cat['num']} {cat['title']}: {len(arts)}건")

    # 2) 발행일(YYYY-MM-DD)별로 분배
    by_day = {}   # day -> {cat_id: [arts]}
    for cat in config.CATEGORIES:
        for a in section_arts[cat["id"]]:
            day = f"{a['pub']:%Y-%m-%d}"
            by_day.setdefault(day, {}).setdefault(cat["id"], []).append(a)

    os.makedirs(dashboard.CLIP_DIR, exist_ok=True)
    note = f"※ {datetime.now(KST):%Y-%m-%d} 소급 일괄 수집 (매일 발송분 아님)"
    made = 0
    for day, cats in sorted(by_day.items()):
        sections = []
        total = 0
        for cat in config.CATEGORIES:
            arts = cats.get(cat["id"], [])
            if cat.get("subgroups"):
                # 계열사 — 회사별 우선순위(자사명 → 핵심 사업어 → 나머지), 각 최신순, 회사별 상한
                capped = []
                for sg in cat["subgroups"]:
                    sg_arts = [a for a in arts if a.get("subgroup") == sg["id"]]
                    p_ind = tuple(sg.get("priority_ind", ()))
                    def _tier_sg(a, pi=p_ind):
                        low = (a.get("title", "") + " " + a.get("desc", "")).lower()
                        if pi and any(t.lower() in low for t in pi): return 0
                        return 1
                    # 자사·산업 각각 정렬(사업어 → 주요일간지 → 최신순) 후 개별 할당
                    def _key(a):
                        return (_tier_sg(a),
                                0 if a.get("is_major") else 1,
                                -(a["pub"].timestamp() if a.get("pub") else 0))
                    own = sorted([a for a in sg_arts if a.get("badge") == "자사"], key=_key)
                    ind = sorted([a for a in sg_arts if a.get("badge") != "자사"], key=_key)
                    # 유연 할당: 자사 6 + 산업 4 목표, 한쪽이 적으면 다른 쪽이 남은 자리 채움 (총 10)
                    total_cap = config.ARCHIVE_MAX_PER_COMPANY
                    n_own = min(len(own), config.ARCHIVE_OWN_PER_COMPANY)
                    n_ind = min(len(ind), config.ARCHIVE_IND_PER_COMPANY)
                    left = total_cap - (n_own + n_ind)
                    if left > 0:                                  # 남은 자리 채우기
                        n_own += min(left, len(own) - n_own)
                        left = total_cap - (n_own + n_ind)
                        n_ind += min(left, len(ind) - n_ind)
                    capped += own[:n_own] + ind[:n_ind]           # 자사 먼저 노출
                arts = capped
            else:
                # 산업·자사·경쟁사 — 알뜰폰·MVNO 최우선 → priority_terms → 나머지
                top = config.TOP_PRIORITY
                pt = cat.get("priority_terms", ())
                def _tier(a):
                    low = (a.get("title", "") + " " + a.get("desc", "")).lower()
                    if any(t.lower() in low for t in top): return 0
                    if pt and any(t.lower() in low for t in pt): return 1
                    return 2
                arts = sorted(arts, key=lambda a: (
                    _tier(a),
                    0 if a.get("is_major") else 1,
                    -(a["pub"].timestamp() if a.get("pub") else 0),
                ))
                cap = config.ARCHIVE_MAX_BY_SECTION.get(cat["id"], config.ARCHIVE_MAX_PER_SECTION)
                arts = arts[:cap]
            sec = {
                "id": cat["id"], "num": cat["num"], "title": cat["title"],
                "digest": "", "articles": [_art_json(a) for a in arts],
            }
            if cat.get("subgroups"):
                sec["subgroups"] = [{"id": s["id"], "label": s["label"]}
                                    for s in cat["subgroups"]]
            sections.append(sec)
            total += len(arts)
        payload = {
            "date": day,
            "backfill_note": note,          # 대시보드에 '소급 정리' 표시
            "generated_at": f"{datetime.now(KST):%Y-%m-%d %H:%M} 소급 정리",
            "top5": [],
            "sections": sections,
            "total": total,
        }
        with open(os.path.join(dashboard.CLIP_DIR, f"{day}.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        made += 1

    print(f"[백필] {made}개 날짜별 파일 생성 (소급 표시 포함)")
    dashboard.build()
    print("[백필] 대시보드 갱신 완료")


if __name__ == "__main__":
    run()
