# -*- coding: utf-8 -*-
"""
렌더 단계
업로드된 템플릿을 이메일 안전 버전으로 재구성해 데이터를 주입한다.
- CSS 변수 → 실제 색상값
- 아이콘 폰트 → 이메일 안전 요소(🔥)
- 헤더/섹션 정렬 flex → table (Outlook 대비)
반환: 완성된 HTML 문자열
"""

import html
from datetime import datetime

import config

C = config.COLORS
FONT = config.FONT_STACK
WD_KR = ["월", "화", "수", "목", "금", "토", "일"]
SHORT = {
    "산업 동향": "산업",
    "자사 동향": "자사",
    "경쟁사 동향": "경쟁사",
    "자회사 동향 (머큐리)": "자회사",
}


def esc(s: str) -> str:
    return html.escape(s or "")


def _mmdd(pub: datetime) -> str:
    return f"{pub:%m.%d}" if pub else ""


def _source_line(art: dict) -> str:
    date = _mmdd(art.get("pub"))
    link = esc(art.get("link", "#"))
    parts = [esc(art.get("press", "")), date]
    text = " · ".join(p for p in parts if p)
    return (
        f'<div style="font-size:12px;color:{C["text_muted"]};margin-top:2px;">'
        f'{text} · '
        f'<a href="{link}" target="_blank" '
        f'style="color:{C["text_accent"]};text-decoration:none;">원문보기 ↗</a>'
        f'</div>'
    )


def _article_block(art: dict, last: bool, badge: str = None) -> str:
    border = (
        "" if last
        else f"border-bottom:0.5px solid {C['border']};padding-bottom:14px;margin-bottom:14px;"
    )
    title = esc(art.get("title", ""))
    summary = esc(art.get("summary", ""))

    badge_html = ""
    title_style = "font-size:14px;font-weight:600;line-height:1.5;margin-bottom:6px;"
    if badge:
        bcolor = {"자사": ("#26215C", "#CECBF6"), "산업": ("#663806", "#FAC775")}
        fg, bg = bcolor.get(badge, ("#333", "#ddd"))
        badge_html = (
            f'<span style="font-size:10px;font-weight:600;color:{fg};background:{bg};'
            f'padding:1px 7px;border-radius:10px;margin-right:6px;">{badge}</span>'
        )
        # 뱃지 + 제목 한 줄
        title_line = (
            f'<div style="margin-bottom:6px;line-height:1.5;">'
            f'{badge_html}'
            f'<span style="font-size:14px;font-weight:600;color:{C["text_primary"]};">{title}</span>'
            f'</div>'
        )
    else:
        title_line = (
            f'<div style="color:{C["text_primary"]};{title_style}">{title}</div>'
        )

    return (
        f'<div style="{border}">'
        f'{title_line}'
        f'<div style="font-size:13px;color:{C["text_secondary"]};line-height:1.6;margin-bottom:8px;">{summary}</div>'
        f'{_source_line(art)}'
        f'</div>'
    )


def _section(cat: dict, articles: list) -> str:
    if not articles:
        body = (
            f'<div style="font-size:13px;color:{C["text_muted"]};padding:6px 0 10px;">'
            f'해당 기간 수집된 기사가 없습니다.</div>'
        )
    else:
        blocks = []
        for i, art in enumerate(articles):
            blocks.append(
                _article_block(art, last=(i == len(articles) - 1), badge=art.get("badge"))
            )
        body = "".join(blocks)

    # 헤더: 제목(좌) / 건수(우) — table로 정렬
    header = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin-bottom:14px;"><tr>'
        f'<td style="font-size:15px;font-weight:600;color:{C["text_primary"]};">'
        f'<span style="display:inline-block;width:4px;height:14px;background:{cat["bar_color"]};'
        f'vertical-align:middle;margin-right:8px;"></span>'
        f'{cat["num"]} {esc(cat["title"])}</td>'
        f'<td align="right" style="font-size:12px;color:{C["text_muted"]};">'
        f'{esc(cat["subtitle"])} · {len(articles)}건</td>'
        f'</tr></table>'
    )
    return (
        f'<div style="padding:16px 24px;border-top:8px solid {C["surface_0"]};">'
        f'{header}{body}</div>'
    )


def _top5(top: list) -> str:
    rows = []
    for t in top:
        label = SHORT.get(t["cat_title"], t["cat_title"])
        rows.append(
            f'<tr>'
            f'<td valign="top" style="font-size:13px;font-weight:600;color:{C["text_accent"]};'
            f'width:18px;padding:4px 0;">{t["rank"]}</td>'
            f'<td style="font-size:14px;color:{C["text_primary"]};line-height:1.5;padding:4px 0;">'
            f'{esc(t["headline"])} '
            f'<span style="font-size:11px;color:{C["text_muted"]};">[{esc(label)}]</span></td>'
            f'</tr>'
        )
    if not rows:
        rows.append(
            f'<tr><td style="font-size:13px;color:{C["text_muted"]};padding:4px 0;">'
            f'선별된 핵심 기사가 없습니다.</td></tr>'
        )
    return (
        f'<div style="padding:20px 24px;border-bottom:8px solid {C["surface_0"]};">'
        f'<div style="font-size:13px;font-weight:600;color:{C["text_accent"]};margin-bottom:12px;">'
        f'🔥 오늘의 핵심 Top 5</div>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
        f'{"".join(rows)}</table></div>'
    )


def build_html(collected_display: dict, top: list, total: int) -> str:
    """collected_display: {cat_id: [articles]} (노출용), top: Top5 리스트"""
    now = datetime.now(config.KST)
    meta = f"{now:%Y년 %-m월 %-d일} ({WD_KR[now.weekday()]}) · 오전 8:00 · 총 {total}건"

    header = (
        f'<div style="background:{C["header_bg"]};padding:20px 24px;">'
        f'<div style="font-size:20px;font-weight:600;color:#ffffff;letter-spacing:-0.3px;">'
        f'아이즈비전 뉴스 클리핑</div>'
        f'<div style="font-size:13px;color:{C["header_sub"]};margin-top:4px;">{meta}</div>'
        f'</div>'
    )

    sections = "".join(
        _section(cat, collected_display.get(cat["id"], []))
        for cat in config.CATEGORIES
    )

    footer = (
        f'<div style="padding:14px 24px;background:{C["surface_1"]};text-align:center;">'
        f'<div style="font-size:11px;color:{C["text_muted"]};line-height:1.5;">'
        f'아이즈비전 뉴스 클리핑 · AI 자동 수집·요약 · 평일 오전 8시 발송<br>'
        f'본 리포트는 네이버 뉴스 기반 AI 요약이며, 정확한 내용은 원문 확인이 필요합니다.</div></div>'
    )

    card = (
        f'<div style="max-width:640px;margin:0 auto;background:{C["surface_2"]};'
        f'border:0.5px solid {C["border"]};border-radius:12px;overflow:hidden;'
        f'font-family:{FONT};">'
        f'{header}{_top5(top)}{sections}{footer}</div>'
    )

    return (
        f'<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>아이즈비전 뉴스 클리핑</title></head>'
        f'<body style="margin:0;padding:16px 8px;background:#eef0f3;font-family:{FONT};">'
        f'{card}</body></html>'
    )
