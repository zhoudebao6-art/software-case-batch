"""Read explicit source figure numbers; do not classify images or execute prose."""
import re
import xml.etree.ElementTree as ET
import zipfile

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def source_figure_numbers(source_docx):
    """Reserve Arabic numbers in captions and body references, including 图1(a).

    Join Word runs before matching, because a caption number may occupy a
    separate run. A reference without an image still reserves its number;
    actual caption/reference consistency remains a human source-audit task.
    """
    with zipfile.ZipFile(source_docx) as package:
        root = ET.fromstring(package.read('word/document.xml'))
    numbers = set()
    for paragraph in root.iter('{'+W+'}p'):
        text = ''.join(node.text or '' for node in paragraph.iter('{'+W+'}t'))
        numbers.update(int(match) for match in re.findall(r'图\s*([0-9０-９]+)', text))
    return sorted(numbers)
