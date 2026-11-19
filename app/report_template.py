"""Read one user report template and export generated text in its file format."""

import io
import re
import zipfile
from pathlib import Path

from docx import Document
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from pypdf import PdfReader

from .pdf_export import render_text_pdf

MAX_TEMPLATE_BYTES = 5 * 1024 * 1024
MAX_TEMPLATE_TEXT = 20_000
TEMPLATE_FORMATS = {'.md': 'markdown', '.markdown': 'markdown', '.pdf': 'pdf',
    '.docx': 'docx', '.xlsx': 'xlsx'}
CONTENT_TYPES = {'markdown': 'text/markdown; charset=utf-8', 'pdf': 'application/pdf',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}
EXTENSIONS = {'markdown': 'md', 'pdf': 'pdf', 'docx': 'docx', 'xlsx': 'xlsx'}


def template_format(filename):
    return TEMPLATE_FORMATS.get(Path(filename or '').suffix.casefold())


def _check_office_zip(body, required_member):
    if not zipfile.is_zipfile(io.BytesIO(body)):
        raise ValueError('Office 模板文件格式无效')
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        names = archive.namelist()
        if required_member not in names or '[Content_Types].xml' not in names:
            raise ValueError('Office 模板与文件扩展名不匹配')
        if len(names) > 300 or sum(item.file_size for item in archive.infolist()) > 30 * 1024 * 1024:
            raise ValueError('Office 模板解压后过大')


def extract_template(filename, body):
    """Return (format, readable instructions); reject unsupported or image-only files."""
    format_name = template_format(filename)
    if not format_name:
        raise ValueError('模板仅支持 Markdown、PDF、Word（.docx）或 Excel（.xlsx）')
    if not body or len(body) > MAX_TEMPLATE_BYTES:
        raise ValueError('模板文件不能为空，且不能超过 5 MB')
    try:
        if format_name == 'markdown':
            text = body.decode('utf-8-sig')
        elif format_name == 'pdf':
            if not body.lstrip().startswith(b'%PDF-'):
                raise ValueError('PDF 模板文件内容无效')
            reader = PdfReader(io.BytesIO(body))
            if reader.is_encrypted or len(reader.pages) > 30:
                raise ValueError('PDF 模板不能加密或超过 30 页')
            text = '\n\n'.join((page.extract_text() or '') for page in reader.pages)
        elif format_name == 'docx':
            _check_office_zip(body, 'word/document.xml')
            document = Document(io.BytesIO(body))
            lines = [paragraph.text for paragraph in document.paragraphs]
            lines += [' | '.join(cell.text for cell in row.cells)
                for table in document.tables for row in table.rows]
            text = '\n'.join(lines)
        else:
            _check_office_zip(body, 'xl/workbook.xml')
            workbook = load_workbook(io.BytesIO(body), read_only=True, data_only=False,
                keep_links=False)
            lines = []
            if len(workbook.worksheets) > 10 or any(sheet.max_row > 500 or sheet.max_column > 30
                    for sheet in workbook.worksheets):
                raise ValueError('Excel 模板最多支持 10 个工作表、每表 500 行和 30 列')
            for sheet in workbook.worksheets:
                lines.append(f'工作表：{sheet.title}')
                for row in sheet.iter_rows(values_only=True):
                    cells = [str(value) for value in row if value is not None
                        and not str(value).startswith('=')]
                    if cells:
                        lines.append(' | '.join(cells))
            workbook.close()
            text = '\n'.join(lines)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('模板文件无法读取，请检查文件是否损坏') from exc
    text = text.strip()
    if not text:
        raise ValueError('模板没有可提取的文字，请上传含文字或栏目名称的文件')
    if len(text) > MAX_TEMPLATE_TEXT:
        raise ValueError('模板文字不能超过 2 万字符，请精简模板')
    return format_name, text


def _blocks(content):
    for raw in (content or '').splitlines():
        line = raw.strip()
        if not line:
            continue
        heading = re.match(r'^(#{1,6})\s+(.+)$', line)
        if heading:
            yield 'heading', heading.group(2)
        elif line.startswith(('- ', '* ')):
            yield 'bullet', line[2:]
        else:
            yield 'text', line


def report_sections(content):
    """Map Markdown headings to their evidence-backed Chinese answers."""
    sections = {}
    current = None
    for raw in (content or '').splitlines():
        match = re.match(r'^#{1,6}\s+(.+?)\s*$', raw.strip())
        if match:
            current = match.group(1).strip()
            sections.setdefault(current, [])
        elif current and raw.strip():
            sections[current].append(raw.strip())
    return {key: '\n'.join(lines).strip() for key, lines in sections.items()}


def _label_key(value):
    return re.sub(r'[^\w\u4e00-\u9fff]', '', re.split(r'[（(]', str(value or ''))[0]).casefold()


def _answer_for(label, sections):
    key = _label_key(label)
    for heading, answer in sections.items():
        if _label_key(heading) == key and answer:
            return answer
    for heading, answer in sections.items():
        other = _label_key(heading)
        if key and other and (key.startswith(other) or other.startswith(key)) and answer:
            return answer
    return '原文未提供'


def template_fields(format_name, body):
    if not body:
        return []
    fields = []
    if format_name == 'xlsx':
        workbook = load_workbook(io.BytesIO(body), read_only=True, keep_links=False)
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows():
                values = [str(cell.value).strip() for cell in row if cell.value is not None]
                if values and values[-1] not in {'类别', '项目', '内容'}:
                    fields.append(values[-1])
        workbook.close()
    elif format_name == 'docx':
        document = Document(io.BytesIO(body))
        fields = [paragraph.text.strip() for paragraph in document.paragraphs
            if paragraph.text.strip() and paragraph.style.name.startswith('Heading')]
        fields += [next((cell.text.strip() for cell in row.cells if cell.text.strip()), '')
            for table in document.tables for row in table.rows]
    elif format_name == 'markdown':
        text = body.decode('utf-8-sig')
        fields = re.findall(r'^#{1,6}\s+(.+)$', text, re.M)
    return list(dict.fromkeys(field for field in fields if field))[:80]


def _fill_placeholders(value, sections, title):
    def replacement(match):
        label = match.group(1).strip()
        answer = _answer_for(label, sections)
        return title if answer == '原文未提供' and label in {'论文标题', '文献题目'} else answer
    return re.sub(r'\{\{\s*([^{}]+?)\s*\}\}', replacement, value)


def render_filled_report(title, content, format_name, template_body):
    """Fill editable template cells/placeholders and keep the uploaded layout."""
    sections = report_sections(content)
    if format_name == 'markdown':
        template = template_body.decode('utf-8-sig') if template_body else ''
        filled = _fill_placeholders(template, sections, title) if '{{' in template else content
        return filled.encode('utf-8')
    if format_name == 'pdf':
        return render_text_pdf(f'{title} — 阅读报告', content)
    if format_name == 'docx':
        document = Document(io.BytesIO(template_body)) if template_body else Document()
        filled = 0
        for paragraph in document.paragraphs:
            if '{{' in paragraph.text:
                paragraph.text = _fill_placeholders(paragraph.text, sections, title)
                filled += 1
        for table in document.tables:
            for row in table.rows:
                cells = row.cells
                for index, cell in enumerate(cells):
                    if '{{' in cell.text:
                        cell.text = _fill_placeholders(cell.text, sections, title)
                        filled += 1
                    elif cell.text.strip() and index + 1 < len(cells) and not cells[index + 1].text.strip():
                        cells[index + 1].text = _answer_for(cell.text, sections)
                        filled += 1
        if not filled:
            document.add_heading(f'{title} — 阅读报告', 1)
            for kind, text in _blocks(content):
                if kind == 'heading':
                    document.add_heading(text, 2)
                else:
                    document.add_paragraph(text)
        output = io.BytesIO()
        document.save(output)
        return output.getvalue()
    if format_name == 'xlsx':
        workbook = load_workbook(io.BytesIO(template_body), keep_links=False) if template_body else Workbook()
        filled = 0
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows():
                cells = list(row)
                for index, cell in enumerate(cells):
                    if not isinstance(cell.value, str):
                        continue
                    if '{{' in cell.value:
                        cell.value = _fill_placeholders(cell.value, sections, title)
                        cell.data_type = 's'
                        filled += 1
                    elif (cell.value.strip() and cell.value.strip() not in {'类别', '项目', '内容'}
                            and index + 1 < len(cells) and cells[index + 1].value is None):
                        target = cells[index + 1]
                        try:
                            answer = _answer_for(cell.value, sections)
                            target.value = title if answer == '原文未提供' and _label_key(cell.value) in {'文献题目', '论文标题'} else answer
                            target.data_type = 's'
                            target.alignment = Alignment(wrap_text=True, vertical='top')
                            sheet.row_dimensions[cell.row].height = max(sheet.row_dimensions[cell.row].height or 15, 48)
                            filled += 1
                        except AttributeError:
                            continue
        if not filled:
            sheet = workbook.create_sheet('阅读报告')
            sheet.append(['栏目', '内容'])
            for heading, answer in sections.items():
                sheet.append([heading, answer])
                sheet.cell(sheet.max_row, 2).data_type = 's'
            sheet.column_dimensions['A'].width = 28
            sheet.column_dimensions['B'].width = 90
        output = io.BytesIO()
        workbook.save(output)
        return output.getvalue()
    raise ValueError('不支持的报告模板格式')


def render_office_document(title, content, format_name):
    """Export Markdown report/translation as a new Word or Excel document."""
    output = io.BytesIO()
    if format_name == 'docx':
        document = Document()
        document.add_heading(title, 0)
        for kind, text in _blocks(content):
            if kind == 'heading':
                document.add_heading(text, level=1)
            elif kind == 'bullet':
                document.add_paragraph(text, style='List Bullet')
            else:
                document.add_paragraph(text)
        document.save(output)
    elif format_name == 'xlsx':
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = '阅读结果'
        sheet.column_dimensions['A'].width = 24
        sheet.column_dimensions['B'].width = 100
        sheet.append(['类型', title[:32767]])
        sheet['B1'].data_type = 's'
        sheet['A1'].font = sheet['B1'].font = Font(bold=True, color='FFFFFF')
        sheet['A1'].fill = sheet['B1'].fill = PatternFill('solid', fgColor='1264E9')
        for kind, text in _blocks(content):
            for offset in range(0, len(text), 30000):
                sheet.append([{'heading': '标题', 'bullet': '要点', 'text': '内容'}[kind], text[offset:offset + 30000]])
                cell = sheet.cell(sheet.max_row, 2)
                cell.data_type = 's'
                cell.alignment = Alignment(wrap_text=True, vertical='top')
                if kind == 'heading':
                    cell.font = Font(bold=True, color='123E8A')
        sheet.freeze_panes = 'A2'
        workbook.save(output)
    else:
        raise ValueError('不支持的 Office 导出格式')
    return output.getvalue()
