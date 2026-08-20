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
    """월요일이면 주말 포함(76h), 평일이면 28h 전까지."""
    hours = (
        config.LOOKBACK_HOURS_MONDAY
        if now_kst.weekday() == 0
        else config.LOOKBACK_HOURS_WEEKDAY
    )
    return now_kst - timedelta(hours=hours)


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

    seen = set()  # orig 링크 기준 전역 중복 제거
    result = {}

    def _gather(keywords, badge=None, extra_exclude=()):
        bucket = []
        for kw in keywords:
            for raw in naver_search(kw, config.DISPLAY_PER_QUERY):
                art = _normalize(raw, badge)
                if not art["orig"] or art["orig"] in seen:
                    continue
                if art["is_sports"]:            # 스포츠 신문 원천 차단
                    continue
                if art["pub"] is None or art["pub"] < cutoff:
                    continue
                if _excluded(art["title"] + " " + art["desc"], extra_exclude):
                    continue
                seen.add(art["orig"])
                bucket.append(art)
            time.sleep(0.1)  # API 예의
        # 주요 매체 우선, 그다음 최신순 → '주요 일간지 소식부터'
        bucket.sort(key=lambda a: (0 if a["is_major"] else 1, -a["pub"].timestamp()))
        return bucket

    for cat in config.CATEGORIES:
        ex = cat.get("exclude", ())
        if cat["id"] == "subsidiary":
            own = _gather(cat["keywords"], badge="자사", extra_exclude=ex)
            ind = _gather(cat.get("industry_keywords", []), badge="산업", extra_exclude=ex)
            items = (own + ind)
        else:
            items = _gather(cat["keywords"], extra_exclude=ex)
        result[cat["id"]] = items[: config.CANDIDATE_CAP]
        print(f"  {cat['num']} {cat['title']}: {len(items)}건")

    total = sum(len(v) for v in result.values())
    print(f"[수집 완료] 총 {total}건")
    return result


if __name__ == "__main__":
    from pprint import pprint
    pprint(collect())
