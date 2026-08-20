# -*- coding: utf-8 -*-
"""
발송 단계
Gmail SMTP로 REPORT_TO(쉼표 구분) 수신자에게 HTML 메일 발송
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from datetime import datetime

import config

GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_PASS = os.environ.get("GMAIL_APP_PASSWORD", "")
REPORT_TO = os.environ.get("REPORT_TO", "")


def _recipients() -> list:
    return [addr.strip() for addr in REPORT_TO.split(",") if addr.strip()]


def send(html_body: str) -> bool:
    to_list = _recipients()
    if not (GMAIL_USER and GMAIL_PASS and to_list):
        print("[발송 생략] GMAIL_USER/GMAIL_APP_PASSWORD/REPORT_TO 미설정")
        return False

    now = datetime.now(config.KST)
    subject = f"[뉴스 클리핑] 아이즈비전 {now:%Y-%m-%d}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr(("아이즈비전 뉴스 클리핑", GMAIL_USER))
    msg["To"] = ", ".join(to_list)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(GMAIL_USER, GMAIL_PASS)
            s.sendmail(GMAIL_USER, to_list, msg.as_string())
        print(f"[발송 완료] {len(to_list)}명: {', '.join(to_list)}")
        return True
    except Exception as e:
        print(f"[발송 실패] {e}")
        return False
