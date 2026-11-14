#!/usr/bin/env python3
"""Run one fictional contract through the public inspect/compose/audit CLI.

Copyright (C) 2026 朱玲凤
SPDX-License-Identifier: Apache-2.0
The generated fictional contract text is CC-BY-4.0; see ../LICENSE.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


PAIRS = [
    ('人才推荐服务协议演示样例', 'Talent Referral Services Agreement Demonstration'),
    ('虚构数据 仅供演示 不用于签署', 'Fictional data for demonstration only. Not for execution.'),
    ('甲方：示例科技有限公司', 'Party A: Example Technology Co., Ltd.'),
    ('乙方：示例人才服务有限公司', 'Party B: Example Talent Services Co., Ltd.'),
    ('一 服务与费用', 'I Services and Fees'),
    ('1. 乙方向甲方推荐候选人。服务费为人民币12,000元，仅在候选人正式入职后收取。',
     '1. Party B shall refer candidates to Party A. A service fee of CNY 12,000 shall be payable only after the candidate commences employment.'),
    ('2. 甲方应在收到有效发票后10个工作日内付款，但已书面提出异议的金额除外。',
     '2. Party A shall pay within 10 business days after receiving a valid invoice, except for any amount disputed in writing.'),
    ('事项', 'Item'), ('约定', 'Terms'),
    ('付款期限', 'Payment period'), ('收到有效发票后10个工作日内', 'Within 10 business days after receiving a valid invoice'),
    ('争议金额', 'Disputed amount'), ('书面提出异议的部分暂缓支付', 'Payment of any portion disputed in writing shall be deferred'),
    ('甲方签署：________    乙方签署：________', 'Signed for Party A: ________    Signed for Party B: ________'),
]


def run_demo(out_dir):
    root = Path(__file__).resolve().parents[1]
    out_dir = Path(out_dir).resolve()
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError('Use an empty output directory; existing files are not overwritten.')
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin = section.bottom_margin = Cm(1.8)
    section.left_margin = section.right_margin = Cm(2)
    for name in ('Normal', 'Title', 'Heading 1'):
        style = doc.styles[name]
        style.font.name = 'Times New Roman'
        style.font.size = Pt(11 if name == 'Normal' else 14)
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'), 'Songti SC')
        style.paragraph_format.space_after = Pt(5)
    doc.core_properties.author = '朱玲凤'
    doc.core_properties.title = PAIRS[0][0]
    doc.core_properties.subject = 'Public fictional Skill demonstration'
    doc.add_paragraph(PAIRS[0][0], 'Title')
    for text, _ in PAIRS[1:7]:
        doc.add_paragraph(text, 'Heading 1' if text == PAIRS[4][0] else 'Normal')
    table = doc.add_table(rows=3, cols=2)
    table.style = 'Table Grid'
    for i, (text, _) in enumerate(PAIRS[7:13]):
        cell = table.cell(i // 2, i % 2)
        cell.text = text
        cell.vertical_alignment = 1
        for run in cell.paragraphs[0].runs:
            run.bold = i < 2
    for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        borders = table._tbl.tblPr.find(qn('w:tblBorders'))
        if borders is None:
            borders = OxmlElement('w:tblBorders'); table._tbl.tblPr.append(borders)
        e = OxmlElement('w:' + edge)
        for k, v in [('val', 'single'), ('sz', '4'), ('color', 'D9D9D9')]:
            e.set(qn('w:' + k), v)
        borders.append(e)
    doc.add_paragraph(PAIRS[13][0])
    source = out_dir / 'source.docx'
    doc.save(source)
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    source_sha = sha(source)
    cli = root / 'scripts/contract_docx.py'
    commands = []
    def execute(args):
        command = [sys.executable, str(cli), *args]
        result = subprocess.run(command, cwd=out_dir, capture_output=True, text=True)
        commands.append({'argv': ['python', 'scripts/contract_docx.py', *args],
                         'exit_code': result.returncode})
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        return result.stdout
    execute(['inspect', 'source.docx', '--out', 'inventory.json'])
    inventory = json.loads((out_dir / 'inventory.json').read_text())
    mapping = inventory['translation_template']
    translations = dict(PAIRS)
    for block in mapping['blocks']:
        block['translation'] = translations[block['source_text']]
    assert len(mapping['blocks']) == len(PAIRS)
    (out_dir / 'translations.json').write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + '\n')
    plan = {'source_sha256': source_sha, 'tables': [
        {'table_index': 0, 'policy': 'flow', 'repeat_header_rows': 1, 'prevent_row_split': True}]}
    (out_dir / 'layout-plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    execute(['compose', 'source.docx', '--translations', 'translations.json', '--layout-plan',
             'layout-plan.json', '--out', 'bilingual.docx', '--manifest', 'alignment.json'])
    execute(['audit', 'bilingual.docx', '--manifest', 'alignment.json', '--out', 'audit.json'])
    audit = json.loads((out_dir / 'audit.json').read_text())
    assert sha(source) == source_sha
    assert audit['structural_pass'] and not audit['errors']
    result = {'fictional_data': True, 'blocks': len(mapping['blocks']), 'tables': 1,
              'source_sha256': source_sha, 'output_sha256': sha(out_dir / 'bilingual.docx'),
              'source_unchanged': True, 'structural_pass': True,
              'warnings': audit['warnings'], 'output_patches': 0, 'commands': commands}
    (out_dir / 'run.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', required=True)
    run_demo(parser.parse_args().out_dir)
