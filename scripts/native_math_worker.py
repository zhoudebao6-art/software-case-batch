"""Internal UNO PDF worker; use render_native_math.py to verify Office ownership."""
import argparse
import functools
import hashlib
import json
from pathlib import Path
import time
import xml.etree.ElementTree as ET
import zipfile


def math_manifest(source):
    with zipfile.ZipFile(source) as package:
        root = ET.fromstring(package.read('word/document.xml'))
    ns = {'m': 'http://schemas.openxmlformats.org/officeDocument/2006/math',
          'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    expected = []
    for node in root.iter('{' + ns['m'] + '}oMath'):
        colors = [run.find('w:rPr/w:color', ns) for run in node.findall('.//m:r', ns)]
        values = [color.get('{' + ns['w'] + '}val', '').upper() if color is not None else '' for color in colors]
        if any(value == 'FF0000' for value in values) and not all(value == 'FF0000' for value in values):
            raise ValueError('Mixed math colors require a per-run renderer; do not approximate')
        expected.append({'index': len(expected) + 1,
                         'text': ''.join(text.text or '' for text in node.findall('.//m:t', ns)),
                         'explicit_red': bool(values) and all(value == 'FF0000' for value in values),
                         'omml_sha256': hashlib.sha256(ET.tostring(node)).hexdigest()})
    return expected


def worker(source, output, port, launcher, listener, profile_uri):
    from process_guard import inventory
    from render_native_math import verified_listener

    def check_owner():
        current = verified_listener(inventory(), launcher, profile_uri, port)
        if not current or any(current[key] != listener[key] for key in ('pid', 'created_ticks')):
            raise RuntimeError('Verified isolated Office listener changed; no UNO connection/termination')
        return current

    check_owner()  # A direct worker invocation also cannot adopt another Office.
    import uno
    from com.sun.star.beans import PropertyValue

    def prop(name, value):
        result = PropertyValue(); result.Name = name; result.Value = value
        return result

    source, output = Path(source).resolve(), Path(output).resolve()
    expected = math_manifest(source)
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver', local)
    context = None
    deadline = time.monotonic() + 50
    while time.monotonic() < deadline:
        check_owner()
        try:
            context = resolver.resolve('uno:socket,host=127.0.0.1,port=' + str(port) + ';urp;StarOffice.ComponentContext')
            break
        except Exception:
            time.sleep(.25)
    if context is None:
        raise RuntimeError('Verified isolated Office service did not become ready')
    desktop = context.ServiceManager.createInstanceWithContext('com.sun.star.frame.Desktop', context)
    document = None
    try:
        document = desktop.loadComponentFromURL(source.as_uri(), '_blank', 0,
            (prop('Hidden', True), prop('ReadOnly', False), prop('UpdateDocMode', 0)))
        objects = []
        embedded = document.getEmbeddedObjects()
        for name in embedded.getElementNames():
            obj = embedded.getByName(name)
            try:
                model = obj.Model; formula = model.Formula
            except Exception:
                continue
            objects.append((name, obj, model, formula))
        objects.sort(key=functools.cmp_to_key(lambda left, right:
            -document.Text.compareRegionStarts(left[1].Anchor, right[1].Anchor)))
        if len(objects) != len(expected):
            raise RuntimeError('Source OMML count differs from imported native math objects: ' + str((len(expected), len(objects))))
        diagnostic = [dict(exp, object_name=name, native_formula=formula,
                           services=list(model.getSupportedServiceNames()))
                      for (name, obj, model, formula), exp in zip(objects, expected)]
        (output / 'native-math-before.json').write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding='utf-8')
        mapping = []
        for (name, obj, model, formula), exp in zip(objects, expected):
            # Writer can unload older Formula models. Reacquire each live model.
            model = obj.Model
            if model.getPropertyValue('Formula') != formula:
                raise RuntimeError('Imported formula body changed before color export')
            if exp['explicit_red']:
                model.setPropertyValue('Formula', 'color hex FF0000 { ' + formula + ' }')
            after = obj.Model.getPropertyValue('Formula')
            required = 'color hex FF0000 { ' + formula + ' }' if exp['explicit_red'] else formula
            if after != required:
                raise RuntimeError('Native formula body changed during color export')
            mapping.append(dict(exp, object_name=name, native_formula_before=formula, native_formula_after=after))
        pdf = output / (source.stem + '.pdf')
        document.storeToURL(pdf.as_uri(), (prop('FilterName', 'writer_pdf_Export'), prop('Overwrite', False)))
        result = {'source': str(source), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                  'method': 'Explicit whole-object OOXML FF0000 honored by native Formula color wrapper during PDF export only; source DOCX and formula bodies unchanged',
                  'expected': mapping}
        (output / 'math-color-render-mapping.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'math_objects': len(objects), 'explicit_red_objects': sum(item['explicit_red'] for item in expected),
                          'pdf': str(pdf)}, ensure_ascii=False), flush=True)
    finally:
        if document:
            document.close(True)
        check_owner()
        desktop.terminate()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--launcher-pid', type=int, required=True)
    parser.add_argument('--launcher-created-ticks', type=int, required=True)
    parser.add_argument('--listener-pid', type=int, required=True)
    parser.add_argument('--listener-created-ticks', type=int, required=True)
    parser.add_argument('--profile-uri', required=True)
    args = parser.parse_args()
    worker(args.source, args.output, args.port,
           {'pid': args.launcher_pid, 'created_ticks': args.launcher_created_ticks},
           {'pid': args.listener_pid, 'created_ticks': args.listener_created_ticks}, args.profile_uri)
