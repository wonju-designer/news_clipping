# -*- coding: utf-8 -*-
"""
분석 단계
- Groq: 노출 기사 배치 요약 (기사당 1~2문장)
- Gemini: 오늘의 핵심 Top 5 선별
공통 가드레일: 제공된 제목·요약 텍스트 밖의 사실 생성/추론 금지 (허위 방지)
"""

import json
import os
import re

import requests

import config

GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

# 품질 담당 AI 선택: gemini(기본) | claude
# Claude로 전환 시 QUALITY_AI=claude + ANTHROPIC_API_KEY 등록만 하면 됨
QUALITY_AI = os.environ.get("QUALITY_AI", "gemini").lower()

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)
CLAUDE_URL = "https://api.anthropic.com/v1/messages"

GUARDRAIL = (
    "다음 규칙을 반드시 지켜라. "
    "1) 제공된 제목과 요약 텍스트에 실제로 있는 내용만 사용한다. "
    "2) 없는 수치·인용·원인·전망을 지어내지 않는다. "
    "3) 추측·해석·대응 제언을 덧붙이지 않는다. "
    "4) 불확실하면 원문 표현을 그대로 요약한다."
)


def _parse_json(text: str):
    """```json 펜스 제거 후 파싱. 실패 시 None."""
    if not text:
        return None
    text = re.sub(r"```(?:json)?", "", text).strip()
    m = re.search(r"[\[{].*[\]}]", text, re.DOTALL)
    if m:
        text = m.group(0)
    try:
        return json.loads(text)
    except Exception as e:
        print(f"  [JSON 파싱 실패] {e}")
        return None


def _groq(system: str, user: str) -> str:
    try:
        r = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            json={
                "model": GROQ_MODEL,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"  [Groq 실패] {e}")
        return ""


def _gemini(prompt: str) -> str:
    try:
        r = requests.post(
            GEMINI_URL,
            params={"key": GEMINI_KEY},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2},
            },
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"  [Gemini 실패] {e}")
        return ""


def _claude(prompt: str) -> str:
    try:
        r = requests.post(
            CLAUDE_URL,
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 1500,
                "temperature": 0.2,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        r.raise_for_status()
        blocks = r.json().get("content", [])
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    except Exception as e:
        print(f"  [Claude 실패] {e}")
        return ""


def _quality(prompt: str) -> str:
    """품질 담당 AI 라우터 (중요도 선별·Top5용)."""
    if QUALITY_AI == "claude":
        return _claude(prompt)
    return _gemini(prompt)


def _has_priority(art: dict, terms) -> bool:
    if not terms:
        return False
    text = (art.get("title", "") + " " + art.get("desc", "")).lower()
    return any(t.lower() in text for t in terms)


def _rank(articles: list, n: int, cat_title: str, priority_terms=()) -> list:
    """카테고리 후보를 AI가 중요도로 상위 n건 선별. 실패 시 우선순위·최신순 폴백."""
    if len(articles) <= n:
        return articles
    # 관련성(우선순위어) 우선 → 최신순. 매체 규모는 선별에서 배제(노출 순서에서만 반영)
    articles = sorted(
        articles,
        key=lambda a: (0 if _has_priority(a, priority_terms) else 1,
                       -a["pub"].timestamp()),
    )
    numbered = [
        f"[{i}] ({a.get('press','')}) {a['title']}" for i, a in enumerate(articles)
    ]
    pr = ("최우선: 다음 표현이 든 기사를 먼저 고른다 — "
          + ", ".join(priority_terms) + ". ") if priority_terms else ""
    prompt = (
        f"너는 통신사 임원 대상 조간 뉴스 브리핑 편집자다. "
        f"아래는 '{cat_title}' 후보 기사 목록이다(괄호는 매체명). "
        f"알뜰폰·MVNO·이동통신 산업과 자사(아이즈비전) 관심도 관점에서 "
        f"가장 중요한 {n}건을 골라라. 선별 원칙: "
        f"{pr}"
        f"① 알뜰폰·MVNO·이동통신 등 통신 산업 관련성이 높은 기사를 최우선한다(매체 규모보다 관련성 우선). "
        f"② 관련성이 비슷하면 5대 일간지·주요 경제지·통신IT 전문지를 우선한다. "
        f"② 게임·연예·스포츠·영화·연예인, 단순 광고·홍보·경품성, 단순 시세 기사는 반드시 제외한다. "
        f"③ 통신/사업과 무관하면 매체가 유명해도 제외한다. "
        + GUARDRAIL + " "
        f"출력은 오직 JSON 배열: [정수 인덱스 {n}개]. 그 외 텍스트 금지.\n\n"
        + "\n".join(numbered)
    )
    parsed = _parse_json(_quality(prompt))
    picks = []
    if isinstance(parsed, list):
        for idx in parsed:
            if isinstance(idx, int) and 0 <= idx < len(articles):
                art = articles[idx]
                if art not in picks:
                    picks.append(art)
            if len(picks) >= n:
                break
    if len(picks) < n:  # 폴백: (이미 우선순위 정렬된) 순서대로 보충
        for art in articles:
            if art not in picks:
                picks.append(art)
            if len(picks) >= n:
                break
    return picks[:n]


def _order(arts: list, priority_terms=()) -> None:
    """5대 일간지 → 우선순위어 → 주요매체 → 최신순 (in-place)."""
    arts.sort(key=lambda a: (
        0 if a.get("is_five") else 1,
        0 if _has_priority(a, priority_terms) else 1,
        0 if a.get("is_major") else 1,
        -a["pub"].timestamp(),
    ))


def _major_first(arts: list) -> None:
    _order(arts)


def select_display(collected: dict) -> dict:
    """카테고리별로 AI 중요도 선별 적용 → {cat_id: [노출 기사]} 반환."""
    display = {}
    for cat in config.CATEGORIES:
        items = collected.get(cat["id"], [])

        if cat["id"] == "subsidiary":
            # 자사(머큐리)와 산업(광통신)을 분리해 각각 선별 → 둘 다 반드시 노출
            own = [a for a in items if a.get("badge") == "자사"]
            ind = [a for a in items if a.get("badge") == "산업"]
            p_own = cat.get("priority_own", ())
            p_ind = cat.get("priority_industry", ())
            own_pick = _rank(own, cat.get("display_max_own", 3), "자회사 동향(머큐리)", p_own)
            ind_pick = _rank(ind, cat.get("display_max_industry", 3),
                             "자회사 관련 산업(광통신·네트워크)", p_ind)
            _order(own_pick, p_own)
            _order(ind_pick, p_ind)
            picked = own_pick + ind_pick  # 자사 먼저, 그다음 산업
        else:
            pt = cat.get("priority_terms", ())
            picked = _rank(items, cat.get("display_max", 4), cat["title"], pt)
            _order(picked, pt)

        for art in picked:
            art["cat_id"] = cat["id"]
            art["cat_title"] = cat["title"]
        display[cat["id"]] = picked
        print(f"  {cat['num']} {cat['title']}: 후보 {len(items)} → 선별 {len(picked)}")
    return display


def flatten(display: dict) -> list:
    return [a for cat in config.CATEGORIES for a in display.get(cat["id"], [])]


def summarize(flat: list) -> None:
    """Groq 배치 요약. 각 art에 'summary' 주입. 실패 시 원문 요약으로 폴백."""
    if not flat:
        return
    lines = [
        f"[{i}] 제목: {a['title']}\n요약원문: {a['desc']}"
        for i, a in enumerate(flat)
    ]
    system = (
        "너는 통신업계 뉴스 편집자다. 각 기사를 한국어 1~2문장(최대 90자)으로 "
        "간결히 요약한다. " + GUARDRAIL + " "
        '출력은 오직 JSON 배열: [{"idx":0,"summary":"..."}] 형식만. 그 외 텍스트 금지.'
    )
    user = "다음 기사들을 각각 요약하라.\n\n" + "\n\n".join(lines)
    parsed = _parse_json(_groq(system, user))

    summaries = {}
    if isinstance(parsed, list):
        for row in parsed:
            if isinstance(row, dict) and "idx" in row:
                summaries[row["idx"]] = str(row.get("summary", "")).strip()

    for i, a in enumerate(flat):
        s = summaries.get(i, "")
        a["summary"] = s if s else (a["desc"][:88] + "…" if len(a["desc"]) > 88 else a["desc"])


def section_digests(display: dict) -> dict:
    """카테고리별 동향 요약(2~3문장) 생성. {cat_id: 요약문}. 실패 시 빈 문자열."""
    digests = {}
    for cat in config.CATEGORIES:
        arts = display.get(cat["id"], [])
        if not arts:
            digests[cat["id"]] = ""
            continue
        bullets = "\n".join(
            f"- {a['title']}: {a.get('summary', a.get('desc',''))}" for a in arts
        )
        label = cat["title"]
        hint = ""
        if cat["id"] == "subsidiary":
            hint = "머큐리(자회사)와 광통신·광케이블·네트워크 사업 관점에서 정리한다. "
        if cat.get("digest_long"):
            length = "한국어 4~5문장(320자 내외)"
        else:
            length = "한국어 2~3문장(최대 160자)"
        system = (
            f"너는 통신사 임원 브리핑 편집자다. 아래 '{label}' 기사들을 종합해 "
            f"오늘의 흐름을 {length}으로 요약하라. {hint}"
            + GUARDRAIL + " 개별 기사 나열이 아니라 전체 맥락을 짚는다. "
            "출력은 요약문 그 자체만. 머리말·따옴표·목록 금지."
        )
        out = _groq(system, "기사 목록:\n" + bullets).strip()
        out = out.strip().strip('"').strip()

        if not out:  # 폴백 1: 품질 AI(Gemini/Claude)로 재시도
            out = _quality(
                f"다음 '{label}' 기사들을 종합해 오늘의 흐름을 {length}으로 요약하라. "
                f"{hint}{GUARDRAIL} 요약문만 출력.\n\n기사 목록:\n{bullets}"
            ).strip().strip('"').strip()

        if not out:  # 폴백 2: 기사 요약을 이어붙여 최소 동향 요약 구성
            take = 5 if cat.get("digest_long") else 3
            parts = []
            for a in arts[:take]:
                s = (a.get("summary") or a.get("desc") or "").strip()
                if s:
                    parts.append(s.split(". ")[0].rstrip(". "))
            out = ". ".join(parts)
            if out:
                out += "."

        digests[cat["id"]] = out
    return digests


def select_top5(flat: list) -> list:
    """Gemini로 Top5 선별. [{rank, headline, cat_title, link, press}] 반환.
    통신·알뜰폰·MVNO·MNO·요금제 우선. 실패 시 우선순위 폴백."""
    if not flat:
        return []

    pri = config.TOP5_PRIORITY
    # 우선순위어가 든 기사를 앞쪽으로 → AI 입력·폴백 모두 우선 반영
    flat = sorted(
        flat,
        key=lambda a: (0 if (_has_priority(a, pri) or a["cat_id"] == "own") else 1,
                       -a["pub"].timestamp()),
    )
    numbered = [
        f"[{i}] ({a['cat_title']}) {a['title']}"
        for i, a in enumerate(flat)
    ]
    prompt = (
        "너는 통신사 임원 대상 조간 뉴스 브리핑 편집자다. "
        "아래 후보 기사 중 오늘 가장 중요한 5건을 골라라. "
        "우선순위: ① 자사(아이즈비전/아이즈모바일/CirQle) 관련, "
        "② 통신·알뜰폰·MVNO·MNO·요금제가 든 기사. 이 둘을 최우선으로 고른다. "
        + GUARDRAIL + " "
        "headline은 해당 기사 제목을 20자 내외로 다듬되 새 사실을 넣지 마라. "
        '출력은 오직 JSON 배열: [{"idx":정수,"headline":"..."}] 5개. 그 외 텍스트 금지.\n\n'
        + "\n".join(numbered)
    )
    parsed = _parse_json(_gemini(prompt))

    top = []
    if isinstance(parsed, list):
        for rank, row in enumerate(parsed[: config.TOP_N], 1):
            if not isinstance(row, dict):
                continue
            idx = row.get("idx")
            if not isinstance(idx, int) or not (0 <= idx < len(flat)):
                continue
            art = flat[idx]
            top.append({
                "rank": rank,
                "headline": str(row.get("headline") or art["title"]).strip(),
                "cat_title": art["cat_title"],
                "link": art.get("link", ""),
                "press": art.get("press", ""),
            })

    if len(top) < config.TOP_N:  # 폴백: 통신 우선순위 → 자사 → 최신순
        catrank = {"own": 0, "industry": 1, "competitor": 2, "subsidiary": 3}
        used = {t["headline"] for t in top}
        ordered = sorted(
            flat,
            key=lambda a: (
                0 if _has_priority(a, config.TOP5_PRIORITY) else 1,
                catrank.get(a["cat_id"], 9),
                -(a["pub"].timestamp()),
            ),
        )
        for art in ordered:
            if len(top) >= config.TOP_N:
                break
            if art["title"] in used:
                continue
            top.append({
                "rank": len(top) + 1,
                "headline": art["title"],
                "cat_title": art["cat_title"],
                "link": art.get("link", ""),
                "press": art.get("press", ""),
            })
            used.add(art["title"])

    for i, t in enumerate(top, 1):
        t["rank"] = i
    return top
