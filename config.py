# -*- coding: utf-8 -*-
"""
뉴스 클리핑 설정
- 수집 카테고리/키워드, 제외 키워드(전역/카테고리별)
- 카테고리별 노출 개수(display_max) — 이 개수만 AI가 중요도로 선별해 표시
- 언론사 도메인 → 표기명 매핑 (사실 기반, 미매핑 시 도메인 노출)
- 이메일 안전 색상값
워크플로 상단 상수만 고치면 수집 대상/노출 개수를 조정할 수 있습니다.
"""

from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

# ────────────────────────────────────────────────
# 수집 카테고리 (템플릿 4개 섹션과 1:1 대응)
#   keywords       : 넓게 수집 (노이즈는 AI 선별로 걸러냄)
#   display_max    : 리포트에 노출할 최대 건수 (AI가 중요도로 이 수만큼 선별)
#   exclude        : 해당 카테고리에만 적용할 추가 제외어
# ────────────────────────────────────────────────
CATEGORIES = [
    {
        "id": "industry",
        "num": "①",
        "title": "산업 동향",
        "subtitle": "알뜰폰·MVNO·이동통신·MNO",
        "bar_color": "#BA7517",
        "display_max": 5,
        "keywords": [
            "알뜰폰", "MVNO", "이동통신", "MNO", "정보통신부", "과기부",
            "중고폰", "SKT", "KT", "LG U+", "에스케이텔레콤", "케이티",
            "휴대전화", "갤럭시", "아이폰", "명의도용", "휴대폰", "개통",
        ],
        # 통신사 e스포츠단(T1·KT롤스터)·모바일게임 오탐 제외 (이 카테고리 한정)
        "exclude": [
            "T1", "롤스터", "LCK", "롤드컵", "e스포츠", "이스포츠",
            "리그오브레전드", "페이커", "발로란트", "배틀그라운드",
            "스타크래프트", "신작 게임", "게임 출시", "게임 업데이트",
            "기프트코드", "쿠폰 코드", "공략",
        ],
    },
    {
        "id": "own",
        "num": "②",
        "title": "자사 동향",
        "subtitle": "전체 수집",
        "bar_color": "#185FA5",
        "display_max": 6,
        "keywords": ["아이즈비전", "아이즈모바일", "CirQle"],
    },
    {
        "id": "competitor",
        "num": "③",
        "title": "경쟁사 동향",
        "subtitle": "선별",
        "bar_color": "#1D9E75",
        "display_max": 5,
        # 브랜드 기본형 (스테이지5→스테이지파이브, 세븐모바일→SK세븐모바일,
        # U모바일→U+유모바일, KCT 제거·티플러스로 커버)
        "keywords": [
            "프리티", "티플러스", "헬로모바일", "SK세븐모바일",
            "KT M모바일", "모빙", "이야기모바일", "스테이지파이브", "U+유모바일",
        ],
        # 각 브랜드 기사 중, 제목/요약에 아래 통신 맥락어가 하나라도 있어야 통과
        # (없으면 제외 → 게임·연예 등 통신 무관 기사 차단)
        "require_any": [
            "알뜰폰", "요금제", "MVNO", "이동통신", "통신사", "가입자",
            "번호이동", "유심", "USIM", "무제한", "5G", "LTE", "데이터",
        ],
        # 게임·애니·연예 오탐 제외 (이 카테고리 한정, 이중 안전장치)
        "exclude": [
            "프리티 리듬", "프리파라", "리듬게임", "e스포츠", "웹툰",
            "애니메이션", "게임 스테이지", "스테이지 클리어",
        ],
    },
    {
        "id": "subsidiary",
        "num": "④",
        "title": "자회사 동향 (머큐리)",
        "subtitle": "자사 + 산업",
        "bar_color": "#534AB7",
        "display_max": 4,
        # 자사(머큐리)와 산업(광통신) 각각 별도 노출 상한 → 한쪽이 밀리지 않게 보장
        "display_max_own": 3,
        "display_max_industry": 3,
        # 머큐리 직접 언급 → '자사' 뱃지
        "keywords": ["머큐리", "(주)머큐리", "100590"],
        # 머큐리 사업영역(광통신·네트워크) → '산업' 뱃지, 자회사 소식으로 정리
        "industry_keywords": ["광통신", "광케이블", "광전복합케이블", "네트워크 사업"],
        # 동명이인/타사/영화 등 오탐 제외 (이 카테고리에만 적용)
        "exclude": [
            "프레디 머큐리", "퀸", "머큐리 영화", "수성",
            "머큐리시스템즈", "Mercury Systems", "피닉스 머큐리", "피닉스머큐리",
        ],
    },
]

# ────────────────────────────────────────────────
# 전역 제외 키워드 (아이즈 오탐 방지 — 커뮤니티 모니터링 세트 승계)
# 제목 또는 요약에 포함되면 해당 기사 제외
# ────────────────────────────────────────────────
EXCLUDE_KEYWORDS = [
    "아이즈원", "IZ*ONE", "퍼스널아이즈", "라식", "라섹",
    "스마트아이즈", "프라이빗아이즈", "아이즈코리아",
]

# ────────────────────────────────────────────────
# 언론사 도메인 → 표기명 (originallink 도메인 기준)
# 미매핑 도메인은 도메인 자체를 노출 (허위 표기 방지)
# ────────────────────────────────────────────────
PRESS_MAP = {
    "yna.co.kr": "연합뉴스", "hankyung.com": "한국경제", "mk.co.kr": "매일경제",
    "etnews.com": "전자신문", "ddaily.co.kr": "디지털데일리", "inews24.com": "아이뉴스24",
    "mt.co.kr": "머니투데이", "sedaily.com": "서울경제", "chosun.com": "조선일보",
    "donga.com": "동아일보", "joongang.co.kr": "중앙일보", "hani.co.kr": "한겨레",
    "khan.co.kr": "경향신문", "edaily.co.kr": "이데일리", "fnnews.com": "파이낸셜뉴스",
    "newsis.com": "뉴시스", "news1.kr": "뉴스1", "zdnet.co.kr": "지디넷코리아",
    "bloter.net": "블로터", "theelec.kr": "디일렉", "thelec.kr": "디일렉",
    "asiae.co.kr": "아시아경제", "heraldcorp.com": "헤럴드경제", "dt.co.kr": "디지털타임스",
    "biz.chosun.com": "조선비즈", "moneys.co.kr": "머니S", "seoul.co.kr": "서울신문",
    "kmib.co.kr": "국민일보", "hankookilbo.com": "한국일보", "segye.com": "세계일보",
    "aitimes.com": "AI타임스", "it.chosun.com": "IT조선", "kbench.com": "케이벤치",
    "nate.com": "네이트뉴스", "ajunews.com": "아주경제", "wowtv.co.kr": "한국경제TV",
    "yonhapnewstv.co.kr": "연합뉴스TV", "ytn.co.kr": "YTN", "sbs.co.kr": "SBS",
    "imbc.com": "MBC", "kbs.co.kr": "KBS", "tf.co.kr": "더팩트",
}

# ────────────────────────────────────────────────
# 주요 매체 우선순위 (표기명 기준)
# 이 목록에 든 매체를 상위로 정렬 → '주요 일간지 소식부터' 노출
# ────────────────────────────────────────────────
MAJOR_PRESS = {
    # 종합일간지
    "연합뉴스", "조선일보", "중앙일보", "동아일보", "한겨레", "경향신문",
    "한국일보", "국민일보", "서울신문", "세계일보",
    # 경제지
    "매일경제", "한국경제", "서울경제", "파이낸셜뉴스", "이데일리",
    "머니투데이", "아시아경제", "헤럴드경제", "아주경제", "조선비즈",
    # 통신/IT 전문지 (본 도메인 핵심)
    "전자신문", "디지털데일리", "디지털타임스", "지디넷코리아", "블로터", "디일렉",
    # 통신사/방송
    "뉴시스", "뉴스1", "YTN", "연합뉴스TV",
}

# 스포츠 신문 도메인 제외 (수집 단계에서 원천 차단)
SPORTS_DOMAINS = {
    "sports.chosun.com", "sports.donga.com", "sportsseoul.com",
    "isplus.com", "sports.khan.co.kr", "osen.co.kr", "mydaily.co.kr",
    "xportsnews.com", "spotvnews.co.kr", "sportalkorea.com",
    "interfootball.co.kr", "mhnews.co.kr", "sportsq.co.kr",
    "sportskhan.news", "star.mt.co.kr", "star.ohmynews.com",
}

# ────────────────────────────────────────────────
# 수집/선별 파라미터
# ────────────────────────────────────────────────
DISPLAY_PER_QUERY = 40       # 쿼리당 네이버 최대 수집 (max 100)
CANDIDATE_CAP = 40           # 카테고리별 AI 선별 투입 후보 상한 (프롬프트 크기 제어)
LOOKBACK_HOURS_WEEKDAY = 28  # 평일: 전일 저녁~당일 아침 커버
LOOKBACK_HOURS_MONDAY = 76   # 월요일: 주말 포함
TOP_N = 5                    # 오늘의 핵심 개수

# ────────────────────────────────────────────────
# 이메일 안전 색상값 (템플릿 CSS 변수 치환용)
# ────────────────────────────────────────────────
COLORS = {
    "surface_2": "#ffffff", "surface_1": "#f6f7f9", "surface_0": "#edeff2",
    "border": "#e4e7eb", "text_primary": "#1a1d21", "text_secondary": "#4b5158",
    "text_muted": "#8b9199", "text_accent": "#185fa5",
    "header_bg": "#0C447C", "header_sub": "#85B7EB",
}

# 조직 표준 서체 Pretendard 우선, 미보유 클라이언트 대비 폴백
FONT_STACK = (
    "'Pretendard', -apple-system, BlinkMacSystemFont, "
    "'Apple SD Gothic Neo', 'Malgun Gothic', 'Segoe UI', sans-serif"
)
