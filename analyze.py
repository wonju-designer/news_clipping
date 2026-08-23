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
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
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


# 섹션별 관련성 판단 기준 (AI에게 주는 맥락)
RELEVANCE_CONTEXT = {
    "industry": "국내 이동통신·알뜰폰(MVNO)·통신 시장/정책/요금/단말 동향",
    "own": "아이즈비전·아이즈모바일(알뜰폰 사업자)의 소식",
    "competitor": "알뜰폰(MVNO) 경쟁사의 통신 사업 소식",
    "powernet": "파워넷(전원공급장치·SMPS 제조사)의 사업·실적 소식",
    "mercury": "머큐리/머큐리광통신(광케이블·광통신 장비 제조사)의 사업·실적 소식",
    "encreative": "이엔크리에이티브(국민학교 떡볶이·밀키트·간편식 브랜드)의 사업 소식",
    "ritco": "리트코(미세먼지 저감·전기집진 환경설비 기업)의 사업 소식",
}


def relevance_filter(articles: list, ctx_key: str, batch: int = 20) -> list:
    """AI로 각 기사가 해당 주제와 실제 관련 있는지 판단해 무관한 기사를 제거.
    제목·요약만으로 판단. AI 실패 시 원본 유지(보수적)."""
    if not articles or not GROQ_KEY:
        return articles
    topic = RELEVANCE_CONTEXT.get(ctx_key)
    if not topic:
        return articles
    kept = []
    for i in range(0, len(articles), batch):
        chunk = articles[i:i + batch]
        lines = []
        for idx, a in enumerate(chunk):
            t = (a.get("title", "") or "")[:80]
            d = (a.get("desc", a.get("summary", "")) or "")[:100]
            lines.append(f"{idx}. {t} / {d}")
        system = (
            "너는 뉴스 관련성 판별기다. 각 기사가 주어진 주제와 '직접' 관련 있는지만 판단한다. "
            "회사명·키워드가 스치듯 언급될 뿐 주제가 다르면 관련 없음으로 본다. "
            "예: 통신 주제인데 언론사명(AP통신 등)·위성통신·정치·연예 기사면 관련 없음. "
            "간편식 브랜드 주제인데 타사의 기부·행사에 밀키트가 잠깐 나오면 관련 없음. "
            'JSON만 출력: {"irrelevant":[관련없는 기사 번호 목록]}'
        )
        user = f"주제: {topic}\n\n기사 목록:\n" + "\n".join(lines)
        out = _groq(system, user)
        data = _parse_json(out)
        bad = set()
        if isinstance(data, dict) and isinstance(data.get("irrelevant"), list):
            for n in data["irrelevant"]:
                if isinstance(n, int) and 0 <= n < len(chunk):
                    bad.add(n)
        kept += [a for idx, a in enumerate(chunk) if idx not in bad]
    removed = len(articles) - len(kept)
    if removed:
        print(f"    [관련성 필터] {ctx_key}: {removed}건 제외 ({len(articles)}→{len(kept)})")
    return kept


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


def _ptier(art: dict, priority_terms=(), top_terms=None) -> int:
    """우선순위 티어: 0=최상위(알뜰폰 등 top_terms), 1=일반 우선(priority_terms), 2=그 외."""
    top_terms = config.TOP_PRIORITY if top_terms is None else top_terms
    low = (art.get("title", "") + " " + art.get("desc", "")).lower()
    if top_terms and any(t.lower() in low for t in top_terms):
        return 0
    if priority_terms and any(t.lower() in low for t in priority_terms):
        return 1
    return 2


def _rank(articles: list, n: int, cat_title: str, priority_terms=(), top_terms=None) -> list:
    """카테고리 후보를 AI가 중요도로 상위 n건 선별. 실패 시 티어(알뜰폰 최우선)·최신순 폴백."""
    if len(articles) <= n:
        return articles
    # 티어(알뜰폰 최상위) → 최신순 : 후보 정렬 + 폴백 순서
    articles = sorted(
        articles,
        key=lambda a: (_ptier(a, priority_terms, top_terms), -a["pub"].timestamp()),
    )
    numbered = [
        f"[{i}] ({a.get('press','')}) {a['title']}" for i, a in enumerate(articles)
    ]
    tt = config.TOP_PRIORITY if top_terms is None else top_terms
    pr = ("최우선: " + ", ".join(tt) + " 관련 기사를 가장 먼저 고른다. ") if tt else ""
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


def _order(arts: list, priority_terms=(), top_terms=None) -> None:
    """알뜰폰 티어 → 5대 일간지 → 주요매체 → 최신순 (in-place). 알뜰폰이 최우선."""
    arts.sort(key=lambda a: (
        _ptier(a, priority_terms, top_terms),
        0 if a.get("is_five") else 1,
        0 if a.get("is_major") else 1,
        -a["pub"].timestamp(),
    ))


def _major_first(arts: list) -> None:
    _order(arts)


def select_display(collected: dict, doc: bool = False) -> dict:
    """카테고리별로 AI 중요도 선별 적용 → {cat_id: [노출 기사]} 반환.
    doc=True면 문서(첨부)용으로 섹션별 개수를 DOC_MAX_PER_SECTION까지 확장."""
    display = {}
    for cat in config.CATEGORIES:
        items = collected.get(cat["id"], [])

        if cat.get("subgroups"):
            # 회사별 소그룹: 각 회사 아래 자사+연관산업을 각각 선별
            picked = []
            for sg in cat["subgroups"]:
                sg_arts = [a for a in items if a.get("subgroup") == sg["id"]]
                own = [a for a in sg_arts if a.get("badge") == "자사"]
                ind = [a for a in sg_arts if a.get("badge") == "산업"]
                p_own = sg.get("priority_own", ())
                p_ind = sg.get("priority_ind", ())
                co = sg.get("doc_own", 5) if doc else sg.get("email_own", 2)
                ci = sg.get("doc_ind", 4) if doc else sg.get("email_ind", 1)
                op = _rank(own, co, sg["label"], p_own, top_terms=p_own)
                ip = _rank(ind, ci, sg["label"], p_ind, top_terms=p_ind)
                _order(op, p_own, top_terms=p_own)
                _order(ip, p_ind, top_terms=p_ind)
                picked += op + ip
            for art in picked:
                art["cat_id"] = cat["id"]
                art["cat_title"] = cat["title"]
            display[cat["id"]] = picked
            tag = "문서" if doc else "메일"
            print(f"  {cat['num']} {cat['title']}({tag}): 후보 {len(items)} → 선별 {len(picked)}")
            continue

        if cat.get("industry_keywords"):
            # 자사(머큐리)와 산업(광통신)을 분리해 각각 선별 → 둘 다 반드시 노출
            own = [a for a in items if a.get("badge") == "자사"]
            ind = [a for a in items if a.get("badge") == "산업"]
            p_own = cat.get("priority_own", ())
            p_ind = cat.get("priority_industry", ())
            if doc:
                cap_own = (config.DOC_MAX_PER_SECTION + 1) // 2   # 8
                cap_ind = config.DOC_MAX_PER_SECTION // 2         # 7
            else:
                cap_own = cat.get("display_max_own", 3)
                cap_ind = cat.get("display_max_industry", 3)
            own_pick = _rank(own, cap_own, "자회사 동향(머큐리)", p_own, top_terms=p_own)
            ind_pick = _rank(ind, cap_ind,
                             "자회사 관련 산업(광통신·네트워크)", p_ind, top_terms=p_ind)
            _order(own_pick, p_own, top_terms=p_own)
            _order(ind_pick, p_ind, top_terms=p_ind)
            picked = own_pick + ind_pick  # 자사 먼저, 그다음 산업
        else:
            pt = cat.get("priority_terms", ())
            cap = config.DOC_MAX_PER_SECTION if doc else cat.get("display_max", 4)
            picked = _rank(items, cap, cat["title"], pt)
            _order(picked, pt)

        for art in picked:
            art["cat_id"] = cat["id"]
            art["cat_title"] = cat["title"]
        display[cat["id"]] = picked
        tag = "문서" if doc else "메일"
        print(f"  {cat['num']} {cat['title']}({tag}): 후보 {len(items)} → 선별 {len(picked)}")
    return display


def email_subset(doc_display: dict) -> dict:
    """문서용 선별 결과에서 이메일용(섹션별 display_max) 상위만 잘라낸다."""
    email = {}
    for cat in config.CATEGORIES:
        arts = doc_display.get(cat["id"], [])
        if cat.get("subgroups"):
            out = []
            for sg in cat["subgroups"]:
                sg_arts = [a for a in arts if a.get("subgroup") == sg["id"]]
                own = [a for a in sg_arts if a.get("badge") == "자사"][: sg.get("email_own", 2)]
                ind = [a for a in sg_arts if a.get("badge") == "산업"][: sg.get("email_ind", 1)]
                out += own + ind
            email[cat["id"]] = out
        elif cat.get("industry_keywords"):
            own = [a for a in arts if a.get("badge") == "자사"][: cat.get("display_max_own", 3)]
            ind = [a for a in arts if a.get("badge") == "산업"][: cat.get("display_max_industry", 3)]
            email[cat["id"]] = own + ind
        else:
            email[cat["id"]] = arts[: cat.get("display_max", 4)]
    return email


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


def _one_digest(label: str, arts: list, hint: str = "", long: bool = False) -> str:
    """기사 목록으로 동향 요약 1개 생성. 3단 폴백."""
    if not arts:
        return ""
    bullets = "\n".join(
        f"- {a['title']}: {a.get('summary', a.get('desc',''))}" for a in arts
    )
    length = "한국어 4~5문장(320자 내외)" if long else "한국어 2~3문장(최대 160자)"
    system = (
        f"너는 통신사 임원 브리핑 편집자다. 아래 '{label}' 기사들을 종합해 "
        f"오늘의 흐름을 {length}으로 요약하라. {hint}"
        + GUARDRAIL + " 개별 기사 나열이 아니라 전체 맥락을 짚는다. "
        "출력은 요약문 그 자체만. 머리말·따옴표·목록 금지."
    )
    out = _groq(system, "기사 목록:\n" + bullets).strip().strip('"').strip()
    if not out:
        out = _quality(
            f"다음 '{label}' 기사들을 종합해 오늘의 흐름을 {length}으로 요약하라. "
            f"{hint}{GUARDRAIL} 요약문만 출력.\n\n기사 목록:\n{bullets}"
        ).strip().strip('"').strip()
    if not out:
        take = 5 if long else 3
        parts = [(a.get("summary") or a.get("desc") or "").split(". ")[0].rstrip(". ")
                 for a in arts[:take] if (a.get("summary") or a.get("desc"))]
        out = ". ".join(parts)
        if out:
            out += "."
    return out


def section_digests(display: dict) -> dict:
    """카테고리별 동향 요약 생성. {cat_id: 요약문}.
    소그룹 섹션은 {cat_id: {subgroup_id: 요약문}} 형태."""
    digests = {}
    for cat in config.CATEGORIES:
        arts = display.get(cat["id"], [])

        if cat.get("subgroups"):  # 회사별 요약 각각
            sub = {}
            for sg in cat["subgroups"]:
                sg_arts = [a for a in arts if a.get("subgroup") == sg["id"]]
                sub[sg["id"]] = _one_digest(
                    sg["label"], sg_arts,
                    hint="해당 회사 소식과 연관 산업 관점에서 정리한다. ", long=False)
            digests[cat["id"]] = sub
            continue

        hint = ""
        if cat["id"] == "group":
            hint = "계열사 소식과 연관 산업 관점에서 정리한다. "
        digests[cat["id"]] = _one_digest(
            cat["title"], arts, hint=hint, long=cat.get("digest_long"))
    return digests


def select_top5(flat: list) -> list:
    """Gemini로 Top5 선별. [{rank, headline, cat_title, link, press}] 반환.
    통신·알뜰폰·MVNO·MNO·요금제 우선. 실패 시 우선순위 폴백."""
    if not flat:
        return []

    # 티어(알뜰폰 최상위) → 자사 → 최신순
    flat = sorted(
        flat,
        key=lambda a: (_ptier(a, config.TOP5_PRIORITY, config.TOP_PRIORITY),
                       0 if a["cat_id"] == "own" else 1,
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
        catrank = {"own": 0, "industry": 1, "competitor": 2, "subsidiary": 3, "group": 4}
        used = {t["headline"] for t in top}
        ordered = sorted(
            flat,
            key=lambda a: (
                _ptier(a, config.TOP5_PRIORITY, config.TOP_PRIORITY),
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
