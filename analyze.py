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
import time

import requests

import config

GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "")  # 지정 시 최우선 시도
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

# Gemini 모델 후보 — 앞에서부터 404가 아니면 사용. 모델명이 바뀌어도 살아남도록 여러 개.
GEMINI_MODEL_CANDIDATES = [m for m in [
    GEMINI_MODEL,
    "gemini-flash-latest",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
] if m]

# 품질 담당 AI 선택: gemini(기본) | claude
# Claude로 전환 시 QUALITY_AI=claude + ANTHROPIC_API_KEY 등록만 하면 됨
QUALITY_AI = os.environ.get("QUALITY_AI", "gemini").lower()

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models/"
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
    for attempt in range(4):  # 429(한도) 시 대기 후 재시도 — 요약 품질 우선
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
            if r.status_code == 429:
                wait = 8 * (attempt + 1)  # 8,16,24s 점증 대기
                ra = r.headers.get("retry-after")
                if ra:
                    try:
                        wait = min(60, int(float(ra)) + 1)
                    except Exception:
                        pass
                if attempt < 3:
                    print(f"  [Groq 429] {wait}s 대기 후 재시도 ({attempt+1}/3)")
                    time.sleep(wait)
                    continue
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            if attempt < 3 and "429" in str(e):
                time.sleep(8 * (attempt + 1))
                continue
            print(f"  [Groq 실패] {e}")
            return ""
    return ""


# 섹션별 관련성 판단 기준 (AI에게 주는 맥락)
RELEVANCE_CONTEXT = {
    "industry": "국내 이동통신·알뜰폰(MVNO)·통신 시장/정책/요금/단말 동향",
    "own": "아이즈비전·아이즈모바일(알뜰폰 사업자)의 소식",
    "competitor": "알뜰폰(MVNO) 경쟁사의 통신 사업 소식",
    "powernet": "파워넷(전원공급장치·SMPS 제조사)의 사업·실적 소식",
    "mercury": "머큐리/머큐리광통신(광케이블·광통신 장비 제조사)의 사업·실적 소식",
    "encreative": (
        "이엔크리에이티브 또는 그 브랜드(국민학교 떡볶이·국떡·밀키트·간편식)가 '주체'이거나 "
        "그 '제품이 소식의 중심'인 기사. "
        "판단 기준: (1) 국떡이 신제품·실적·입점·납품·수출·투자의 주체면 관련 있음. "
        "(2) 대기업이 '국떡 제품을 구매·기부'하는 소식처럼 국떡 제품이 거래·기부의 대상 중심이면 관련 있음(국떡에 좋은 소식). "
        "(3) 반대로 타 회사(항공·카드사 등)의 기부·행사 기사에서 그 회사의 다른 지원품으로 밀키트가 '스치듯' 언급될 뿐 국떡 제품이 중심이 아니면 관련 없음. "
        "예: '대한항공이 쌀을 기부(과거 밀키트도 지원)' → 국떡 제품이 중심 아님 → 관련 없음. "
        "'삼성이 국떡 떡볶이 1만개를 기부' → 국떡 제품이 중심 → 관련 있음."
    ),
    "ritco": "리트코(미세먼지 저감·전기집진 환경설비 기업)의 사업 소식",
}

# 계열사 산업동향(badge=산업)용 — 업종 전반 동향까지 폭넓게 관련으로 인정
RELEVANCE_CONTEXT_IND = {
    "powernet": "전원공급장치·SMPS·파워서플라이 등 전력변환 부품 업종 동향",
    "mercury": "광케이블·광통신·광섬유·FTTH 등 광통신 장비 업종 동향",
    "encreative": "밀키트·간편식(HMR)·떡볶이·K-푸드 등 간편식 업종 동향",
    "ritco": "미세먼지 저감·전기집진·배출가스 측정(TMS)·대기환경 설비 업종 동향",
}


def relevance_filter(articles: list, ctx_key: str, batch: int = 30, lenient: bool = False) -> list:
    """AI로 각 기사가 해당 주제와 실제 관련 있는지 판단해 무관한 기사를 제거.
    제목·요약만으로 판단. AI 실패 시 원본 유지(보수적).
    lenient=True: 업종 동향까지 폭넓게 인정(확실히 무관한 것만 제외) — 계열사 산업동향용."""
    if not articles or not GROQ_KEY:
        return articles
    topic = (RELEVANCE_CONTEXT_IND.get(ctx_key) if lenient else None) or RELEVANCE_CONTEXT.get(ctx_key)
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
        if lenient:
            system = (
                "너는 관대한 업종 동향 판별기다. 기사가 주어진 '업종'과 조금이라도 관련되면 관련 있음으로 둔다. "
                "그 업종의 기술·제품·시장·정책·타사 동향도 모두 관련 있음. "
                "확실히 다른 분야(정치·연예·스포츠·언론사명·전혀 무관한 산업)일 때만 관련 없음으로 분류한다. "
                "애매하면 반드시 관련 있음으로 남긴다. "
                'JSON만 출력: {"irrelevant":[확실히 무관한 기사 번호만]}'
            )
        else:
            system = (
                "너는 엄격한 뉴스 관련성 판별기다. 핵심 기준: 기사의 '주체(주인공)' 또는 '중심 소재'가 주제의 회사/제품인가? "
                "주체가 다른 회사이고 주제 키워드가 스치듯 언급될 뿐이면 반드시 관련 없음으로 분류한다. "
                "예1: 통신 주제인데 기사 주체가 언론사(AP통신·교도통신)·정치인·연예인·위성통신 기기면 관련 없음. "
                "예2: '대한항공이 쌀을 기부(예전에 밀키트도 지원)'처럼 주체가 항공사이고 밀키트가 곁다리로만 나오면 관련 없음. "
                "예3: '삼성이 국떡 떡볶이 1만개를 기부'처럼 해당 브랜드 제품이 거래·기부의 '중심'이면 관련 있음. "
                "예4: '국떡이 대한항공 기내식에 납품'처럼 주체가 해당 브랜드면 관련 있음. "
                "요컨대 그 회사/제품이 '주인공이거나 소식의 중심'이면 관련 있음, 배경에 스치면 관련 없음. "
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
        if i + batch < len(articles):
            time.sleep(2)  # 배치 간 간격으로 429(분당 한도) 완화
    removed = len(articles) - len(kept)
    if removed:
        print(f"    [관련성 필터] {ctx_key}: {removed}건 제외 ({len(articles)}→{len(kept)})")
    return kept


_GEMINI_OK_MODEL = None  # 처음 성공한 모델명을 기억해 이후엔 그것만 사용


def _gemini(prompt: str) -> str:
    global _GEMINI_OK_MODEL
    candidates = [_GEMINI_OK_MODEL] if _GEMINI_OK_MODEL else list(GEMINI_MODEL_CANDIDATES)
    last_err = None
    for model in candidates:
        try:
            r = requests.post(
                f"{_GEMINI_BASE}{model}:generateContent",
                params={"key": GEMINI_KEY},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.2},
                },
                timeout=60,
            )
            if r.status_code == 404:      # 모델명 무효 → 다음 후보로
                last_err = f"404 {model}"
                continue
            r.raise_for_status()
            _GEMINI_OK_MODEL = model      # 작동하는 모델 기억
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            last_err = e
            if "404" in str(e):
                continue
            break
    print(f"  [Gemini 실패] {last_err}")
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


def archive_subset(collected: dict) -> dict:
    """대시보드 저장용 — 아카이브 분량(산업 30 등)을 우선순위 순으로 선별(3일치 그대로 저장).
    지난 소식 화면에서 발행일 필터는 대시보드가 처리.
    정렬: 산업·자사·경쟁사 = 사업어→주요일간지→최신 / 계열사 = 자사먼저→사업어→주요일간지→최신."""
    out = {}
    for cat in config.CATEGORIES:
        arts = list(collected.get(cat["id"], []))
        if cat.get("subgroups"):
            capped = []
            for sg in cat["subgroups"]:
                sg_arts = [a for a in arts if a.get("subgroup") == sg["id"]]
                p_ind = tuple(sg.get("priority_ind", ()))

                def _key(a, pi=p_ind):
                    low = (a.get("title", "") + " " + a.get("desc", "")).lower()
                    tier = 0 if (pi and any(t.lower() in low for t in pi)) else 1
                    maj = 0 if a.get("is_major") else 1
                    ts = a["pub"].timestamp() if a.get("pub") else 0
                    return (tier, maj, -ts)

                own = sorted([a for a in sg_arts if a.get("badge") == "자사"], key=_key)
                ind = sorted([a for a in sg_arts if a.get("badge") != "자사"], key=_key)
                total_cap = config.ARCHIVE_MAX_PER_COMPANY
                n_own = min(len(own), config.ARCHIVE_OWN_PER_COMPANY)
                n_ind = min(len(ind), config.ARCHIVE_IND_PER_COMPANY)
                left = total_cap - (n_own + n_ind)
                if left > 0:
                    n_own += min(left, len(own) - n_own)
                    left = total_cap - (n_own + n_ind)
                    n_ind += min(left, len(ind) - n_ind)
                capped += own[:n_own] + ind[:n_ind]
            out[cat["id"]] = capped
        else:
            top = config.TOP_PRIORITY
            pt = cat.get("priority_terms", ())

            def _key2(a, pt=pt):
                low = (a.get("title", "") + " " + a.get("desc", "")).lower()
                if any(t.lower() in low for t in top):
                    tier = 0
                elif pt and any(t.lower() in low for t in pt):
                    tier = 1
                else:
                    tier = 2
                maj = 0 if a.get("is_major") else 1
                ts = a["pub"].timestamp() if a.get("pub") else 0
                return (tier, maj, -ts)

            arts = sorted(arts, key=_key2)
            cap = config.ARCHIVE_MAX_BY_SECTION.get(cat["id"], config.ARCHIVE_MAX_PER_SECTION)
            out[cat["id"]] = arts[:cap]
    return out


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
        "너는 통신업계 뉴스 편집자다. 각 기사를 한국어로 자연스럽게 완결된 1문장(60~90자)으로 "
        "요약한다. 반드시 문장을 끝맺어라(중간에 끊지 말 것). '…'로 끝내지 말 것. "
        "원문 표현을 그대로 베끼지 말고 핵심을 새로 서술하라. 같은 내용을 반복하지 말 것. "
        "제목과 겹치는 내용은 빼고 본문의 새 정보를 담아라. " + GUARDRAIL + " "
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
        if s:
            a["summary"] = s
        else:
            # 폴백: 문장 끝(.!?다요) 기준으로 잘라 완결되게, 없으면 원문 그대로
            d = a.get("desc", "")
            if len(d) <= 90:
                a["summary"] = d
            else:
                cut = d[:90]
                # 마지막 문장 종결 지점 찾기
                import re as _re
                m = list(_re.finditer(r"[.!?다]\s", cut))
                if m:
                    a["summary"] = cut[: m[-1].end()].strip()
                else:
                    a["summary"] = cut.rstrip() + "…"


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
