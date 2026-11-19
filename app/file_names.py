"""Safe, human-readable download names for paper artifacts."""

import re


def safe_stem(title, fallback='论文'):
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', ' ', str(title or ''))
    stem = re.sub(r'\s+', ' ', stem).strip(' .')[:120].rstrip(' .')
    return stem or fallback


def original_pdf_name(title):
    return f'{safe_stem(title)}.pdf'


def chinese_pdf_name(title):
    return f'{safe_stem(title, "中文版论文")}.pdf'


def report_name(title, extension):
    return f'{safe_stem(title)}阅读报告.{extension}'
