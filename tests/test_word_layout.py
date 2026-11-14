"""Six compact behavior groups for the published formatting/composition path."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile
from test_contract_docx import mod as m, package, mutate


def xml(text):
    return m.parse(('<w:root xmlns:w="'+m.NS['w']+'">'+text+'</w:root>').encode())


class LayoutRegression(unittest.TestCase):
    def test_01_boolean_and_style_inheritance(self):
        for value in ('0','false','off'):
            p=xml('<w:p><w:r><w:rPr><w:b w:val="'+value+'"/></w:rPr><w:t>label</w:t></w:r></w:p>')[0]
            self.assertFalse(m.layout.paragraph_is_bold(p,{}))
        styles=xml('<w:style w:styleId="Base"><w:rPr><w:b/></w:rPr></w:style><w:style w:styleId="Child"><w:basedOn w:val="Base"/></w:style>')
        styles={x.get(m.W+'styleId'):x for x in styles}
        p=xml('<w:p><w:pPr><w:pStyle w:val="Child"/></w:pPr><w:r><w:t>label</w:t></w:r></w:p>')[0]
        self.assertTrue(m.layout.paragraph_is_bold(p,styles))
        m.E.SubElement(styles['Child'],m.W+'rPr').append(m.E.Element(m.W+'b'))
        self.assertFalse(m.layout.paragraph_is_bold(p,styles),'Style toggles must not be treated as absolute True')
        run=p.find('w:r',m.NS);rp=m.E.Element(m.W+'rPr');run.insert(0,rp);m.E.SubElement(rp,m.W+'b',{m.W+'val':'1'})
        self.assertTrue(m.layout.paragraph_is_bold(p,styles),'Direct formatting overrides styles')
        rp[0].set(m.W+'val','0')
        self.assertFalse(m.layout.paragraph_is_bold(p,styles))

    def test_02_new_paragraph_has_independent_table_format(self):
        root=xml('<w:tbl><w:tr><w:tc><w:p><w:pPr><w:pageBreakBefore/><w:jc w:val="both"/></w:pPr><w:r><w:rPr><w:b w:val="0"/></w:rPr><w:t>Value</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')
        source=root.find('.//w:p',m.NS);before=m.E.tostring(source)
        target=m.english_p(source,'Translated value')
        self.assertEqual(m.value(target,'w:pPr/w:jc'),'left')
        self.assertIsNone(target.find('w:pPr/w:pageBreakBefore',m.NS))
        self.assertEqual(m.value(target,'w:r/w:rPr/w:b'),'0')
        self.assertEqual(m.value(target,'w:r/w:rPr/w:sz'),'22')
        self.assertEqual(m.value(target,'w:r/w:rPr/w:szCs'),'22')
        self.assertEqual(m.E.tostring(source),before)

    def test_03_short_block_uses_selected_anchor_not_text(self):
        for title in ('Receiving details','Other small business block'):
            root=xml('<w:document><w:body><w:p><w:r><w:t>'+title+'</w:t></w:r></w:p><w:p><w:r><w:t>Introduction</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')[0]
            p=root.find('w:body/w:p',m.NS)
            original=m.E.tostring(p)
            m.layout.apply_table_plan(root,{'anchor':p},{'tables':[{'table_index':0,'policy':'new_page_block','start_before':'anchor','reason':'Keep a critical short business block together'}]})
            body=root.find('w:body',m.NS)
            self.assertIs(body[1],p)
            self.assertIsNotNone(body[0].find('w:r/w:br[@w:type="page"]',m.NS))
            self.assertEqual(m.E.tostring(p),original)
            self.assertEqual(''.join(root.itertext()),title+'IntroductionCell')

    def test_04_long_tables_flow_with_header_not_forced_same_page(self):
        rows=''.join('<w:tr><w:tc><w:p><w:r><w:t>Row '+str(i)+'</w:t></w:r></w:p></w:tc></w:tr>' for i in range(8))
        root=xml('<w:document><w:body><w:p><w:r><w:t>Heading</w:t></w:r></w:p><w:tbl>'+rows+'</w:tbl></w:body></w:document>')[0]
        p=root.find('w:body/w:p',m.NS);text=''.join(root.itertext())
        with self.assertRaisesRegex(ValueError,'Long tables'):
            m.layout.apply_table_plan(root,{'anchor':p},{'tables':[{'table_index':0,'policy':'new_page_block','start_before':'anchor','reason':'wrong'}]})
        m.layout.apply_table_plan(root,{}, {'tables':[{'table_index':0,'policy':'flow','repeat_header_rows':1,'prevent_row_split':True}]})
        self.assertIsNone(root.find('.//w:br',m.NS))
        self.assertEqual(len(root.findall('.//w:tblHeader',m.NS)),1)
        self.assertEqual(len(root.findall('.//w:cantSplit',m.NS)),8)
        self.assertEqual(''.join(root.itertext()),text)

    def test_05_page_field_slots_preserve_count_and_reject_other_fields(self):
        source=xml('<w:p><w:r><w:t>Page </w:t></w:r><w:r><w:fldChar w:fldCharType="begin"/><w:instrText>PAGE</w:instrText><w:fldChar w:fldCharType="end"/></w:r><w:r><w:t> of </w:t></w:r><w:r><w:fldChar w:fldCharType="begin"/><w:instrText>NUMPAGES</w:instrText><w:fldChar w:fldCharType="end"/></w:r></w:p>')[0]
        before=m.E.tostring(source)
        target=m.layout.page_field_paragraph(source,{'translation':'Page  of ','field_template':'Page {PAGE} of {NUMPAGES}'},{})
        self.assertEqual(m.layout.field_codes(target),['PAGE','NUMPAGES'])
        self.assertEqual(m.ptext(target),'Page  of ')
        self.assertEqual(m.E.tostring(source),before)
        with self.assertRaises(ValueError):
            m.layout.page_field_paragraph(source,{'translation':'Page  of ','field_template':'Page {NUMPAGES} of {PAGE}'},{})
        source.find('.//w:instrText',m.NS).text='REF private_bookmark'
        with self.assertRaises(ValueError):m.layout.field_codes(source)

    def test_06_formal_compose_preserves_guards_and_binds_plan(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'source.docx';mapping=root/'map.json';plan=root/'plan.json';out=root/'out.docx';manifest=root/'manifest.json'
            package(source)
            doc=m.inspect(source)[2]['translation_template'];doc['blocks'][0]['translation']='Party A shall pay 100.'
            mapping.write_text(json.dumps(doc));plan.write_text(json.dumps({'source_sha256':doc['source_sha256'],'tables':[]}))
            before=source.read_bytes();m.compose(source,mapping,out,manifest,plan)
            self.assertEqual(source.read_bytes(),before);self.assertTrue(m.audit(out,manifest)['structural_pass'])
            with self.assertRaises(ValueError):m.compose(source,mapping,plan,manifest,plan)
            plan.write_text(json.dumps({'source_sha256':'bad','tables':[]}))
            with self.assertRaises(ValueError):m.compose(source,mapping,out,manifest,plan)
            package(source,field=True)
            doc=m.inspect(source)[2]['translation_template'];doc['blocks'][0]['translation']='Not supported'
            mapping.write_text(json.dumps(doc));plan.write_text(json.dumps({'source_sha256':doc['source_sha256'],'tables':[]}))
            with self.assertRaisesRegex(ValueError,'outside headers/footers'):m.compose(source,mapping,out,manifest,plan)
            with self.assertRaisesRegex(ValueError,'Complex Word features'):m.build(source,mapping,out,manifest)


if __name__=='__main__':unittest.main(verbosity=2)
