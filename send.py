# -*- coding: utf-8 -*-
"""
발송 단계
Gmail SMTP로 REPORT_TO(쉼표 구분) 수신자에게 HTML 메일 발송
"""

import os
import smtplib
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from email import encoders
from datetime import datetime

import config

GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_PASS = os.environ.get("GMAIL_APP_PASSWORD", "")
REPORT_TO = os.environ.get("REPORT_TO", "")


def _recipients() -> list:
    return [addr.strip() for addr in REPORT_TO.split(",") if addr.strip()]


def _attach(msg, path):
    """워드 문서를 첨부. Korean 파일명은 RFC2231로 인코딩."""
    if not (path and os.path.exists(path)):
        return
    with open(path, "rb") as f:
        part = MIMEBase(
            "application",
            "vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        part.set_payload(f.read())
    encoders.encode_base64(part)
    fname = os.path.basename(path)
    # 한글 파일명 안전 처리
    part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", fname))
    msg.attach(part)


def send(html_body: str, attachment_path: str = None) -> bool:
    to_list = _recipients()
    if not (GMAIL_USER and GMAIL_PASS and to_list):
        print("[발송 생략] GMAIL_USER/GMAIL_APP_PASSWORD/REPORT_TO 미설정")
        return False

    now = datetime.now(config.KST)
    subject = f"[뉴스 클리핑] 아이즈비전 {now:%Y-%m-%d}"

    # 본문(HTML) + 첨부를 함께 담기 위해 mixed 컨테이너 사용
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = formataddr(("아이즈비전 뉴스 클리핑", GMAIL_USER))
    msg["To"] = ", ".join(to_list)

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt)

    _attach(msg, attachment_path)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(GMAIL_USER, GMAIL_PASS)
            s.sendmail(GMAIL_USER, to_list, msg.as_string())
        note = " (+첨부)" if attachment_path and os.path.exists(attachment_path) else ""
        print(f"[발송 완료]{note} {len(to_list)}명: {', '.join(to_list)}")
        return True
    except Exception as e:
        print(f"[발송 실패] {e}")
        return False
