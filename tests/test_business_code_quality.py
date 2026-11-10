"""New diagrams join the actual delivery without changing historical packages."""
from pathlib import Path
import tempfile, unittest, sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from common import delivery_paths, SYSTEM_CODE_LAYOUT
import system_diagrams as diagrams
from PIL import Image
class DiagramTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.run={'output':str(self.root),'delivery_layout_version':SYSTEM_CODE_LAYOUT}
        self.system=delivery_paths(self.run)['system'];self.system.mkdir()
    def test_native_small_readable_images_and_no_legacy_requirement(self):
        for name,size in [('时序图',(964,614)),('设计图',(1048,198))]:
            Image.new('RGB',size,'white').save(self.system/(name+'.png'))
        self.assertEqual(set(diagrams.validate(self.root,self.root,self.run)),set(diagrams.NAMES))
        self.assertEqual(diagrams.validate(self.root,self.root,{}),{})
        self.assertEqual(self.system.name,'系统代码')
    def test_missing_corrupt_and_unknown_fail_without_creating_files(self):
        with self.assertRaises(ValueError):diagrams.validate(self.root,self.root,self.run)
        (self.system/'时序图.png').write_bytes(b'broken')
        with self.assertRaises(OSError):diagrams.validate(self.root,self.root,self.run)
        with self.assertRaises(ValueError):diagrams.enabled({'system_diagram_policy':'unknown'})
    def test_legacy_layout_paths_are_unchanged(self):
        self.assertEqual(delivery_paths({'output':str(self.root),'title':'旧案','delivery_layout_version':'research-materials-v3'})['system_name'],'研发证明材料-旧案')
        self.assertEqual(delivery_paths({'output':str(self.root),'delivery_layout_version':'system-materials-v2'})['system_name'],'系统材料')
if __name__=='__main__':unittest.main()
