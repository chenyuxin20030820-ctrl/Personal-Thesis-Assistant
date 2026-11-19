import io
import unittest

from docx import Document
from openpyxl import Workbook, load_workbook

from app.pdf_export import render_text_pdf
from app.report_template import extract_template, render_office_document, render_filled_report


class ReportTemplateTests(unittest.TestCase):
    def test_markdown_and_invalid_type(self):
        self.assertEqual(extract_template('guide.md', '# 研究目的\n研究方法'.encode())[0], 'markdown')
        with self.assertRaisesRegex(ValueError, '仅支持'):
            extract_template('guide.txt', b'plain text')

    def test_word_template_and_word_output(self):
        source = Document()
        source.add_heading('研究目的', 1)
        source.add_paragraph('说明研究目标')
        buffer = io.BytesIO()
        source.save(buffer)
        format_name, text = extract_template('guide.docx', buffer.getvalue())
        self.assertEqual(format_name, 'docx')
        self.assertIn('研究目的', text)
        rendered = render_office_document('论文阅读报告', '# 研究目的\n目标描述', 'docx')
        result = Document(io.BytesIO(rendered))
        self.assertTrue(any('目标描述' in paragraph.text for paragraph in result.paragraphs))

    def test_excel_template_and_excel_output(self):
        source = Workbook()
        source.active['A1'] = '研究方法'
        buffer = io.BytesIO()
        source.save(buffer)
        format_name, text = extract_template('guide.xlsx', buffer.getvalue())
        self.assertEqual(format_name, 'xlsx')
        self.assertIn('研究方法', text)
        rendered = render_office_document('论文阅读报告', '# 研究方法\n=HYPERLINK("bad")', 'xlsx')
        result = load_workbook(io.BytesIO(rendered))
        self.assertEqual(result.active['B3'].value, '=HYPERLINK("bad")')
        self.assertEqual(result.active['B3'].data_type, 's')

    def test_pdf_template(self):
        body = render_text_pdf('阅读报告模板', '研究目的\n研究方法\n主要发现')
        format_name, text = extract_template('guide.pdf', body)
        self.assertEqual(format_name, 'pdf')
        self.assertIn('研究目的', text)

    def test_fills_excel_template_cells(self):
        template = Workbook()
        sheet = template.active
        sheet['A1'], sheet['B1'], sheet['C1'] = '类别', '项目', '内容'
        sheet['B2'] = '文献题目'
        sheet['B3'] = '研究方法'
        sheet['A4'] = '研究结论'
        sheet.merge_cells('B4:C4')
        source = io.BytesIO()
        template.save(source)
        result = render_filled_report('测试论文',
            '## 文献题目\n测试论文\n\n## 研究方法\n面板回归\n\n## 研究结论\n结论明确',
            'xlsx', source.getvalue())
        filled = load_workbook(io.BytesIO(result)).active
        self.assertEqual(filled['C2'].value, '测试论文')
        self.assertEqual(filled['C3'].value, '面板回归')
        self.assertEqual(filled['B4'].value, '结论明确')

    def test_fills_word_and_markdown_placeholders(self):
        template = Document()
        template.add_paragraph('研究目的：{{研究目的}}')
        source = io.BytesIO()
        template.save(source)
        report = '## 研究目的\n解释因果机制'
        filled = Document(io.BytesIO(render_filled_report('论文', report, 'docx', source.getvalue())))
        self.assertIn('解释因果机制', filled.paragraphs[0].text)
        markdown = render_filled_report('论文', report, 'markdown', '# 模板\n{{研究目的}}'.encode())
        self.assertIn('解释因果机制', markdown.decode())


if __name__ == '__main__':
    unittest.main()
