"""Copied source equations are material; original equations and symbols stay intact."""
import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from contracts import math_signature, repeated_source_formulas
from common import digest, read_json, write_json
import test_contracts as fixtures
import test_explanation_context as context_fixtures

M = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def equation(content):
    return ET.fromstring(f'<m:oMath xmlns:m="{M}" xmlns:w="{W}">{content}</m:oMath>')


def run(text):
    return '<m:r><m:t>'+text+'</m:t></m:r>'


def paragraph(formula):
    node = ET.Element('{'+W+'}p')
    node.append(copy.deepcopy(formula))
    return node


class FormulaReuseTests(unittest.TestCase):
    def setUp(self):
        self.original = equation(
            '<m:sSub><m:e>'+run('G')+'</m:e><m:sub>'+run('r,k')+'</m:sub></m:sSub>'
            +run('=')+'<m:nary><m:naryPr><m:chr m:val="∑"/></m:naryPr>'
            '<m:sub>'+run('h∈S')+'</m:sub><m:sup/><m:e>'+run('wI(c=k)')+'</m:e></m:nary>')

    def duplicates(self, added, source=None):
        source = source or [paragraph(self.original)]
        blocks = copy.deepcopy(source) + [paragraph(added)]
        return repeated_source_formulas(source, blocks, range(len(source)))

    def test_color_font_size_copy_is_rejected_with_source_location(self):
        added = copy.deepcopy(self.original)
        for r in added.iter('{'+M+'}r'):
            props = ET.SubElement(r, '{'+W+'}rPr')
            ET.SubElement(props, '{'+W+'}color', {'{'+W+'}val': 'FF0000'})
            ET.SubElement(props, '{'+W+'}sz', {'{'+W+'}val': '20'})
            ET.SubElement(props, '{'+W+'}rFonts', {'{'+W+'}ascii': 'Cambria Math'})
        self.assertEqual(self.duplicates(added)[0]['source_blocks'], [0])

    def test_original_duplicate_formulas_are_not_removed_or_rejected(self):
        source = [paragraph(self.original), paragraph(self.original)]
        before = [ET.tostring(b) for b in source]
        self.assertEqual(repeated_source_formulas(source, copy.deepcopy(source), [0, 1]), [])
        self.assertEqual(before, [ET.tostring(b) for b in source])

    def test_split_runs_match_but_case_and_changed_operator_do_not(self):
        one = equation(run('A=B+C'))
        split = equation(run('A')+run('=')+run('B')+run('+')+run('C'))
        self.assertEqual(math_signature(one), math_signature(split))
        self.assertNotEqual(math_signature(one), math_signature(equation(run('a=B+C'))))
        self.assertNotEqual(math_signature(one), math_signature(equation(run('A=B-C'))))

    def test_same_flat_text_with_different_fraction_structure_is_distinct(self):
        one = equation(run('y=')+'<m:f><m:num>'+run('ab')+'</m:num><m:den>'+run('c')+'</m:den></m:f>')
        other = equation(run('y=')+'<m:f><m:num>'+run('a')+'</m:num><m:den>'+run('bc')+'</m:den></m:f>')
        self.assertNotEqual(math_signature(one), math_signature(other))

    def test_subscripts_superscripts_hats_and_operator_properties_are_not_erased(self):
        sub = equation(run('y=')+'<m:sSub><m:e>'+run('a')+'</m:e><m:sub>'+run('b')+'</m:sub></m:sSub>')
        sup = equation(run('y=')+'<m:sSup><m:e>'+run('a')+'</m:e><m:sup>'+run('b')+'</m:sup></m:sSup>')
        self.assertNotEqual(math_signature(sub), math_signature(sup))
        other = copy.deepcopy(self.original)
        other.find('.//{'+M+'}chr').set('{'+M+'}val', '∏')
        self.assertEqual(self.duplicates(other), [])
        hat = equation(run('y=')+'<m:acc><m:accPr><m:chr m:val="̂"/></m:accPr><m:e>'+run('x')+'</m:e></m:acc>')
        self.assertNotEqual(math_signature(hat), math_signature(equation(run('y=x'))))

    def test_mathematical_script_and_vector_style_are_preserved(self):
        plain = equation(run('x=y'))
        bold = equation('<m:r><m:rPr><m:sty m:val="b"/></m:rPr><m:t>x=y</m:t></m:r>')
        script = equation('<m:r><m:rPr><m:scr m:val="script"/></m:rPr><m:t>x=y</m:t></m:r>')
        self.assertNotEqual(math_signature(plain), math_signature(bold))
        self.assertNotEqual(math_signature(plain), math_signature(script))

    def test_symbol_reference_and_distinct_derivation_are_allowed(self):
        symbol = equation('<m:sSub><m:e>'+run('G')+'</m:e><m:sub>'+run('r,k')+'</m:sub></m:sSub>')
        self.assertEqual(self.duplicates(symbol, [paragraph(symbol)]), [])
        self.assertEqual(self.duplicates(equation(run('R=G/2'))), [])

    def test_inline_and_table_copies_are_found(self):
        original = paragraph(self.original)
        table = ET.Element('{'+W+'}tbl')
        table.append(paragraph(self.original))
        result = repeated_source_formulas([original], [copy.deepcopy(original), table], [0])
        self.assertEqual(result[0]['added_block'], 1)

    def test_inequality_relation_is_checked(self):
        formula = equation(run('p≤q+r'))
        self.assertTrue(self.duplicates(formula, [paragraph(formula)]))

    def test_snapshot_rejects_copy_but_v1_frozen_policy_is_unchanged(self):
        context = context_fixtures.ExplanationContextTests()
        context.setUp()
        try:
            original = ET.tostring(paragraph(self.original), encoding='unicode')
            source_body = original + ''.join(map(fixtures.p, context.prose))
            with zipfile.ZipFile(context.f.source, 'w') as z:
                z.writestr('word/document.xml', fixtures.doc(source_body))
            context.f.run['source_docx_sha256'] = digest(context.f.source)
            for figure in context.f.figures:
                figure['explanation_after_source_block'] += 1
            body = (original+fixtures.p(context.prose[0])+context.references[0]+original
                    +fixtures.p(context.prose[1])+context.references[1]+fixtures.p(context.prose[2]))
            context.write(body)
            with self.assertRaisesRegex(ValueError, 'Added complete formula repeats'):
                context.snapshot()
            context.f.run['explanation_context_policy'] = 'source-context-v1'
            self.assertEqual(context.snapshot()['explanation_context_policy'], 'source-context-v1')
        finally:
            context.tearDown()

    def test_document_upgrade_and_package_policy_inheritance(self):
        from proflow import prepare
        f = fixtures.ContractTests()
        f.setUp()
        try:
            base, _, _ = f.revision_fixture()
            path = base / '.product-v2/run.json'
            previous = read_json(path)
            for i, policy in enumerate((None, 'source-context-v1', 'source-context-v2')):
                prior = dict(previous)
                if policy:
                    prior['explanation_context_policy'] = policy
                else:
                    prior.pop('explanation_context_policy', None)
                write_json(path, prior)
                for scope in ('document', 'package'):
                    work = f.root / f'formula-{i}-{scope}'
                    work.mkdir()
                    result = prepare(work, f.root/f'out-{i}-{scope}', '设备运行控制',
                                     f.source, base, revision_scope=scope)
                    expected = 'source-context-v2' if scope == 'document' else policy
                    self.assertEqual(result.get('explanation_context_policy'), expected)
                    before = digest(work / '.product-v2/run.json')
                    prepare(work, f.root/f'out-{i}-{scope}', '设备运行控制',
                            f.source, base, revision_scope=scope)
                    self.assertEqual(digest(work / '.product-v2/run.json'), before)
        finally:
            f.tearDown()

    def check_snapshot_relation(self, original_formula, added_formula, must_reject):
        context = context_fixtures.ExplanationContextTests()
        context.setUp()
        try:
            original = ET.tostring(paragraph(original_formula), encoding='unicode')
            added = ET.tostring(paragraph(added_formula), encoding='unicode')
            with zipfile.ZipFile(context.f.source, 'w') as z:
                z.writestr('word/document.xml',
                           fixtures.doc(original + ''.join(map(fixtures.p, context.prose))))
            context.f.run['source_docx_sha256'] = digest(context.f.source)
            for figure in context.f.figures:
                figure['explanation_after_source_block'] += 1
            context.write(original+fixtures.p(context.prose[0])+context.references[0]+added
                          +fixtures.p(context.prose[1])+context.references[1]+fixtures.p(context.prose[2]))
            if must_reject:
                with self.assertRaisesRegex(ValueError, 'Added complete formula repeats'):
                    context.snapshot()
            else:
                self.assertEqual(context.snapshot()['explanation_context_policy'], 'source-context-v2')
        finally:
            context.tearDown()

    def test_empty_math_run_properties_cannot_disguise_full_copy_in_snapshot(self):
        original = equation(run('y=x+1'))
        added = equation('<m:r><m:rPr/><m:t>y=x+1</m:t></m:r>')
        self.check_snapshot_relation(original, added, must_reject=True)

    def test_conditional_subscript_symbol_is_not_a_full_equation_in_snapshot(self):
        symbol = equation('<m:sSub><m:e>'+run('x')+'</m:e><m:sub>'+run('i≥0')+'</m:sub></m:sSub>')
        self.check_snapshot_relation(symbol, copy.deepcopy(symbol), must_reject=False)

    def test_literal_indicator_condition_across_runs_is_not_a_full_equation(self):
        for content in (run('I(c=k)'), run('I(')+run('c')+run('=k)'),
                        run('I（c=k）'), run('I([c=k])')):
            with self.subTest(content=content):
                symbol = equation(content)
                self.check_snapshot_relation(symbol, copy.deepcopy(symbol), must_reject=False)

    def test_outer_relation_with_literal_indicator_still_rejects_full_copy(self):
        for content in (run('y=I(c=k)'), run('I(')+run('c=k)')+run('=y')):
            with self.subTest(content=content):
                formula = equation(content)
                self.check_snapshot_relation(formula, copy.deepcopy(formula), must_reject=True)


if __name__ == '__main__':
    unittest.main()
