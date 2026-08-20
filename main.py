# -*- coding: utf-8 -*-
"""
뉴스 클리핑 파이프라인 오케스트레이터
수집 → 노출 추림 → Groq 요약 → Gemini Top5 → 렌더 → Gmail 발송
로컬 프리뷰: python main.py --preview  (발송 없이 report_preview.html 생성)
"""

import sys
from datetime import datetime

import config
import collect as collector
import analyze
import render
import send as sender


def run(preview: bool = False):
    now = datetime.now(config.KST)
    print(f"[시작] {now:%Y-%m-%d %H:%M} 뉴스 클리핑")

    collected = collector.collect()
    raw_total = sum(len(v) for v in collected.values())

    # AI 중요도 선별 → 카테고리별 노출 세트
    print(f"[선별] AI 중요도 판단 (품질 AI: {analyze.QUALITY_AI})")
    display = analyze.select_display(collected)
    flat = analyze.flatten(display)

    analyze.summarize(flat)                      # Groq 기사별 요약
    digests = analyze.section_digests(display)   # Groq 섹션별 동향 요약
    top = analyze.select_top5(flat)              # 품질 AI Top5

    shown_total = len(flat)
    print(f"[정리] 수집 {raw_total}건 → 노출 {shown_total}건")
    html_body = render.build_html(display, top, shown_total, digests)

    with open("report_preview.html", "w", encoding="utf-8") as f:
        f.write(html_body)
    print("[렌더 완료] report_preview.html")

    if preview:
        print("[프리뷰 모드] 발송 생략")
        return

    if shown_total == 0:
        print("[종료] 노출 기사 0건 — 발송 생략")
        return

    sender.send(html_body)
    print("[완료]")


if __name__ == "__main__":
    run(preview="--preview" in sys.argv)
