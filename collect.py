# -*- coding: utf-8 -*-
"""
수집 단계
네이버 뉴스 검색 API로 카테고리별 키워드 검색 → 중복 제거 → 기간 필터
언론사명은 originallink 도메인을 PRESS_MAP으로 매핑 (미매핑 시 도메인 노출)
"""

import html
import os
import re
import time
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import requests

import config

NAVER_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")
API_URL = "https://openapi.naver.com/v1/search/news.json"
DEBUG = os.environ.get("DEBUG") == "1"   # 진단용: 검색어별 수집 건수 출력

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    """네이버 응답의 <b> 태그와 HTML 엔티티 제거"""
    text = _TAG_RE.sub("", text or "")
    return html.unescape(text).strip()


def _press_name(originallink: str) -> str:
    """originallink 도메인 → 언론사 표기명. 미매핑이면 도메인 노출."""
    try:
        host = urlparse(originallink).netloc.lower()
        host = host[4:] if host.startswith("www.") else host
    except Exception:
        return "출처 미상"
    if host in config.PRESS_MAP:
        return config.PRESS_MAP[host]
    # 서브도메인 제거 후 재시도 (예: biz.chosun.com 미스 시 chosun.com)
    parts = host.split(".")
    if len(parts) > 2:
        base = ".".join(parts[-2:])
        if base in config.PRESS_MAP:
            return config.PRESS_MAP[base]
    return host or "출처 미상"


def _lookback_cutoff(now_kst: datetime) -> datetime:
    """매일 발송 기준: 직전 약 28시간(전일 저녁~당일 아침) 커버."""
    return now_kst - timedelta(hours=config.LOOKBACK_HOURS_WEEKDAY)


def naver_search(query: str, display: int) -> list:
    """단일 쿼리 검색. 실패 시 빈 리스트."""
    headers = {
        "X-Naver-Client-Id": NAVER_ID,
        "X-Naver-Client-Secret": NAVER_SECRET,
    }
    params = {"query": query, "display": min(display, 100), "sort": "date"}
    try:
        r = requests.get(API_URL, headers=headers, params=params, timeout=15)
        r.raise_for_status()
        return r.json().get("items", [])
    except Exception as e:
        print(f"  [수집 실패] '{query}': {e}")
        return []


def _excluded(text: str, extra=()) -> bool:
    low = text.lower()
    terms = list(config.EXCLUDE_KEYWORDS) + list(extra)
    return any(kw.lower() in low for kw in terms)


def _expand(keywords, qualifiers=None):
    """수식어가 있으면 '키워드 수식어' 조합으로 확장 (예: 프리티 알뜰폰/프리티 요금제)."""
    if not qualifiers:
        return list(keywords)
    return [f"{kw} {q}" for kw in keywords for q in qualifiers]


def _normalize(item: dict, badge: str = None) -> dict:
    title = _clean(item.get("title", ""))
    desc = _clean(item.get("description", ""))
    orig = item.get("originallink") or item.get("link", "")
    try:
        pub = parsedate_to_datetime(item.get("pubDate", "")).astimezone(config.KST)
    except Exception:
        pub = None
    press = _press_name(orig)
    return {
        "title": title,
        "desc": desc,
        "link": item.get("link") or orig,
        "orig": orig,
        "press": press,
        "pub": pub,
        "badge": badge,               # 자회사 섹션 자사/산업 구분용
        "is_major": press in config.MAJOR_PRESS,  # 주요 매체 우선 정렬용
        "is_five": press in config.FIVE_DAILIES,  # 5대 일간지 최상단 정렬용
        "is_sports": _host(orig) in config.SPORTS_DOMAINS,  # 스포츠 매체 차단용
    }


def _host(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def collect() -> dict:
    """카테고리별 기사 딕셔너리 반환. 기간 필터·중복 제거·제외어 적용."""
    now = datetime.now(config.KST)
    cutoff = _lookback_cutoff(now)
    print(f"[수집] 기준: {cutoff:%Y-%m-%d %H:%M} ~ {now:%Y-%m-%d %H:%M} (KST)")

    result = {}

    def _gather(keywords, seen, badge=None, extra_exclude=(), require_any=(), protect_terms=()):
        bucket = []
        for kw in keywords:
            raw_n = 0
            kept_before = len(bucket)
            for raw in naver_search(kw, config.DISPLAY_PER_QUERY):
                raw_n += 1
                art = _normalize(raw, badge)
                if not art["orig"] or art["orig"] in seen:
                    continue
                if art["is_sports"]:            # 스포츠 신문 원천 차단
                    continue
                if art["pub"] is None or art["pub"] < cutoff:
                    continue
                text = art["title"] + " " + art["desc"]
                low = text.lower()
                # 전역 제외어(범죄·아이즈 오탐 등)는 항상 적용
                if _excluded(text, ()):
                    continue
                # 카테고리 제외어: 단, protect_terms가 있으면 예외 유지
                if extra_exclude and any(k.lower() in low for k in extra_exclude):
                    if not (protect_terms and any(p.lower() in low for p in protect_terms)):
                        continue
                # 필수 조건어: 하나라도 없으면 제외
                if require_any and not any(t.lower() in low for t in require_any):
                    continue
                seen.add(art["orig"])
                bucket.append(art)
            if DEBUG:
                print(f"    · '{kw}': 원시 {raw_n} → 통과 {len(bucket) - kept_before}")
            time.sleep(0.1)  # API 예의
        # 주요 매체 우선, 그다음 최신순 → '주요 일간지 소식부터'
        bucket.sort(key=lambda a: (0 if a["is_major"] else 1, -a["pub"].timestamp()))
        return bucket

    def _expand(keywords, qualifiers):
        """qualifiers가 있으면 '키워드 + 수식어' 조합으로 검색어 확장."""
        if not qualifiers:
            return list(keywords)
        return [f"{kw} {q}" for kw in keywords for q in qualifiers]

    # 섹션별 독립 수집 — 중복 제거를 '섹션 내부'로만 적용.
    # 따라서 같은 기사가 산업동향·경쟁사 등 여러 섹션에 함께 나올 수 있음(중복 허용).
    for cat in config.CATEGORIES:
        ex = cat.get("exclude", ())
        req = cat.get("require_any", ())
        prot = cat.get("protect_terms", ())
        quals = cat.get("qualifiers", ())
        pt = cat.get("priority_terms", ())
        cat_seen = set()  # 섹션 내부 중복만 제거 (섹션 간 중복은 허용)
        if cat["id"] == "subsidiary":
            own = _gather(cat["keywords"], cat_seen, badge="자사", extra_exclude=ex,
                          require_any=req, protect_terms=prot)
            ind = _gather(cat.get("industry_keywords", []), cat_seen, badge="산업",
                          extra_exclude=ex, require_any=req, protect_terms=prot)
            items = (own + ind)
        else:
            queries = _expand(cat["keywords"], quals)
            items = _gather(queries, cat_seen, extra_exclude=ex,
                            require_any=req, protect_terms=prot)
            # 후보 컷 전에 티어(알뜰폰 최상위) 순으로 정렬 → 상한에서 잘려나가지 않게
            if pt:
                top = config.TOP_PRIORITY
                def _tier(a):
                    low = (a["title"] + " " + a["desc"]).lower()
                    if any(t.lower() in low for t in top):
                        return 0
                    if any(t.lower() in low for t in pt):
                        return 1
                    return 2
                items.sort(key=lambda a: (_tier(a), -a["pub"].timestamp()))
        result[cat["id"]] = items[: config.CANDIDATE_CAP]
        print(f"  {cat['num']} {cat['title']}: {len(items)}건")

    total = sum(len(v) for v in result.values())
    print(f"[수집 완료] 총 {total}건")
    return result


if __name__ == "__main__":
    from pprint import pprint
    pprint(collect())
