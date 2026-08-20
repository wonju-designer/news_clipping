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
import docx_report
import send as sender


def run(preview: bool = False):
    now = datetime.now(config.KST)
    print(f"[시작] {now:%Y-%m-%d %H:%M} 뉴스 클리핑")

    collected = collector.collect()
    raw_total = sum(len(v) for v in collected.values())

    # 문서(첨부)용으로 섹션별 넓게 선별 → 이메일은 그 상위만 사용
    print(f"[선별] AI 중요도 판단 (품질 AI: {analyze.QUALITY_AI})")
    doc_display = analyze.select_display(collected, doc=True)
    doc_flat = analyze.flatten(doc_display)

    analyze.summarize(doc_flat)                       # Groq 기사별 요약(문서 전체)
    digests = analyze.section_digests(doc_display)    # Groq 섹션별 동향 요약
    top = analyze.select_top5(doc_flat)               # 품질 AI Top5

    # 이메일용: 문서 선별 결과에서 섹션별 상위만 잘라냄
    email_display = analyze.email_subset(doc_display)
    email_total = sum(len(v) for v in email_display.values())
    doc_total = len(doc_flat)
    print(f"[정리] 수집 {raw_total}건 → 이메일 {email_total}건 / 문서 {doc_total}건")

    html_body = render.build_html(email_display, top, email_total, digests)

    with open("report_preview.html", "w", encoding="utf-8") as f:
        f.write(html_body)
    print("[렌더 완료] report_preview.html")

    # 첨부용 워드 문서 생성 (더 많은 기사 수록)
    docx_path = f"아이즈비전_뉴스클리핑_{now:%Y%m%d}.docx"
    try:
        docx_report.build_docx(doc_display, top, digests, docx_path, doc_total)
        print(f"[문서 생성] {docx_path}")
    except Exception as e:
        print(f"[문서 생성 실패] {e}")
        docx_path = None

    if preview:
        print("[프리뷰 모드] 발송 생략")
        return

    if email_total == 0:
        print("[종료] 노출 기사 0건 — 발송 생략")
        return

    sender.send(html_body, docx_path)
    print("[완료]")


if __name__ == "__main__":
    run(preview="--preview" in sys.argv)
