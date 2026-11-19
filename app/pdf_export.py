"""Run the PDF renderer using an interpreter with ReportLab installed."""

import json
import os
import subprocess
import sys
from pathlib import Path


def renderer_python():
    explicit = os.getenv('PDF_RENDER_PYTHON')
    if explicit:
        return Path(explicit)
    try:
        import reportlab  # noqa: F401
        return Path(sys.executable)
    except ImportError:
        bundled = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
        if bundled.is_file():
            return bundled
        raise RuntimeError('PDF 生成功能需要 ReportLab；请安装 requirements.txt 或设置 PDF_RENDER_PYTHON')


def render_text_pdf(title,body):
    payload = json.dumps({'title':title,'body':body},ensure_ascii=False).encode('utf-8')
    try:
        result = subprocess.run([str(renderer_python()),str(Path(__file__).with_name('pdf_worker.py'))],
            input=payload,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120,check=False)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise RuntimeError('PDF 生成进程未能完成') from exc
    if result.returncode or not result.stdout.startswith(b'%PDF-'):
        message = result.stderr.decode('utf-8',errors='replace')[-800:]
        raise RuntimeError(f'PDF 生成失败：{message or "未知错误"}')
    return result.stdout
