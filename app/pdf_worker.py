"""Render a Chinese text document to PDF. Reads UTF-8 JSON from stdin, writes PDF bytes."""

import io
import json
import os
import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


def font_path():
    candidates = [os.getenv('PDF_CJK_FONT',''),
        r'C:\Windows\Fonts\simhei.ttf', r'C:\Windows\Fonts\msyhbd.ttf',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']
    return next((value for value in candidates if value and Path(value).is_file()), None)


def make_pdf(title, body):
    font = font_path()
    if not font:
        raise RuntimeError('没有找到中文字体；请设置 PDF_CJK_FONT 为支持中文的 TTF 文件')
    pdfmetrics.registerFont(TTFont('PaperChinese',font))
    output = io.BytesIO()
    page = canvas.Canvas(output,pagesize=A4,pageCompression=1)
    page.setTitle(title[:200])
    width,height = A4
    left,right,top,bottom = 46,46,48,48
    y = height-top
    page_number = 1

    def new_page():
        nonlocal y,page_number
        page.setFont('PaperChinese',8)
        page.setFillColorRGB(.45,.5,.58)
        page.drawRightString(width-right,25,str(page_number))
        page.showPage()
        page_number += 1
        y = height-top

    def write_line(text,size=10.5,spacing=17):
        nonlocal y
        if y < bottom+spacing:
            new_page()
        page.setFont('PaperChinese',size)
        page.setFillColorRGB(.08,.15,.28)
        page.drawString(left,y,text)
        y -= spacing

    def wrap(text,size,max_width):
        line = ''
        for char in text:
            candidate = line+char
            if line and pdfmetrics.stringWidth(candidate,'PaperChinese',size)>max_width:
                yield line
                line = char
            else:
                line = candidate
        if line:
            yield line

    for line in wrap(title,16,width-left-right):
        write_line(line,16,24)
    y -= 14
    for raw in body.splitlines():
        raw = raw.strip()
        if not raw:
            y -= 9
            continue
        heading = raw.startswith('#')
        text = raw.lstrip('#').strip() if heading else raw
        size = 12 if heading else 10.5
        for line in wrap(text,size,width-left-right):
            write_line(line,size,20 if heading else 17)
        if heading:
            y -= 5
    page.setFont('PaperChinese',8)
    page.setFillColorRGB(.45,.5,.58)
    page.drawRightString(width-right,25,str(page_number))
    page.save()
    return output.getvalue()


if __name__ == '__main__':
    payload = json.loads(sys.stdin.buffer.read().decode('utf-8'))
    sys.stdout.buffer.write(make_pdf(payload['title'],payload['body']))
