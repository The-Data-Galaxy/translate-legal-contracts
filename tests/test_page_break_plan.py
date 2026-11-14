"""Approved source-page-break flow: no contract-specific layout patches."""
import json
from pathlib import Path
import tempfile
import unittest
from test_contract_docx import mod as m, package, mutate
from test_word_layout import xml


class PageBreakPlan(unittest.TestCase):
    def test_default_preserves_break_and_declared_flow_rebuilds_from_source(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);source=p/'source.docx';mapping=p/'map.json';plan=p/'plan.json';out=p/'out.docx';manifest=p/'manifest.json'
            package(source)
            def add_boundary(blob):
                root=m.parse(blob);body=root.find('w:body',m.NS)
                boundary=xml('<w:p><w:pPr><w:widowControl/></w:pPr><w:r><w:br w:type="page"/></w:r></w:p>')[0]
                anchor=xml('<w:p><w:r><w:t>签署区</w:t></w:r></w:p>')[0]
                body.insert(1,boundary);body.insert(2,anchor)
                return m.E.tostring(root)
            mutate(source,'word/document.xml',add_boundary)
            doc=m.inspect(source)[2]['translation_template']
            for block in doc['blocks']:block['translation']='Signature' if block['source_text']=='签署区' else 'Party A shall pay 100.'
            mapping.write_text(json.dumps(doc));selected=next(x['id'] for x in doc['blocks'] if x['source_text']=='签署区')
            base={'source_sha256':doc['source_sha256'],'tables':[]}
            plan.write_text(json.dumps(base));m.compose(source,mapping,out,manifest,plan)
            def breaks():return len(m.parse(m.load_package(out)['word/document.xml']).findall('.//w:br[@w:type="page"]',m.NS))
            self.assertEqual(breaks(),1);before=source.read_bytes()
            base['page_breaks']=[{'before':selected,'policy':'allow_flow','reason':'User permits the signature area to follow the last clause'}]
            plan.write_text(json.dumps(base));m.compose(source,mapping,out,manifest,plan)
            self.assertEqual(breaks(),0);self.assertEqual(source.read_bytes(),before)
            self.assertTrue(m.audit(out,manifest)['structural_pass'])
            self.assertEqual(len(json.loads(manifest.read_text())['blocks']),2)

    def test_rejects_content_bookmarks_sections_and_non_page_boundaries(self):
        for boundary in ('<w:r><w:t>Do not remove me</w:t><w:br w:type="page"/></w:r>',
                         '<w:bookmarkStart w:id="9" w:name="keep"/><w:r><w:br w:type="page"/></w:r>',
                         '<w:pPr><w:sectPr/></w:pPr><w:r><w:br w:type="page"/></w:r>',
                         '<w:r><w:footnoteReference w:id="1"/><w:br w:type="page"/></w:r>',
                         '<w:r><w:br/></w:r>', '<w:r><w:br w:type="page"/><w:br w:type="page"/></w:r>'):
            with self.subTest(boundary=boundary):
                root=xml('<w:document><w:body><w:p>'+boundary+'</w:p><w:p><w:r><w:t>Anchor</w:t></w:r></w:p></w:body></w:document>')[0]
                start=root.find('w:body',m.NS)[1];before=m.E.tostring(root)
                with self.assertRaises(ValueError):m.layout.apply_page_break_plan(root,{'anchor':start},{'page_breaks':[{'before':'anchor','policy':'allow_flow','reason':'approved'}]})
                self.assertEqual(m.E.tostring(root),before)

    def test_invalid_and_conflicting_plans_do_not_silently_remove_breaks(self):
        for entry in ([{'before':'anchor','policy':'allow_flow','reason':''}],
                      [{'before':'missing','policy':'allow_flow','reason':'approved'}],
                      [{'before':'anchor','policy':'unknown','reason':'approved'}],
                      [{'before':'anchor','policy':'allow_flow','reason':'approved'}]*2):
            root=xml('<w:document><w:body><w:p><w:r><w:br w:type="page"/></w:r></w:p><w:p/></w:body></w:document>')[0]
            start=root.find('w:body',m.NS)[1];before=m.E.tostring(root)
            with self.assertRaises(ValueError):m.layout.apply_page_break_plan(root,{'anchor':start},{'page_breaks':entry})
            self.assertEqual(m.E.tostring(root),before)
        root=xml('<w:document><w:body><w:p><w:r><w:br w:type="page"/></w:r></w:p><w:p><w:pPr><w:pageBreakBefore/></w:pPr></w:p></w:body></w:document>')[0]
        start=root.find('w:body',m.NS)[1]
        with self.assertRaisesRegex(ValueError,'pageBreakBefore'):m.layout.apply_page_break_plan(root,{'anchor':start},{'page_breaks':[{'before':'anchor','policy':'allow_flow','reason':'approved'}]})
        start.find('w:pPr',m.NS).clear()
        with self.assertRaisesRegex(ValueError,'Conflicting'):m.layout.apply_page_break_plan(root,{'anchor':start},{'page_breaks':[{'before':'anchor','policy':'allow_flow','reason':'approved'}],'tables':[{'policy':'new_page_block','start_before':'anchor'}]})


if __name__=='__main__':unittest.main(verbosity=2)
