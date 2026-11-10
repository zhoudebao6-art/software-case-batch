"""Retain all actual project files after identified cleanup, on synthetic trees."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import proflow
from common import write_json, digest, delivery_paths
from source_delivery import RETAINED_DIRECTORY_POLICY, selected_files, execution_kinds
from retained_source import exclusion
from test_product_flow import FlowTests

class RetainedSourceTests(unittest.TestCase):
    def fixture(self):
        f=FlowTests();f.setUp();self.addCleanup(f.tearDown)
        f.run.update(source_delivery_policy=RETAINED_DIRECTORY_POLICY,delivery_layout_version='system-code-directory-v5')
        f.run.pop('source_zip');write_json(f.work/'.product-v2/run.json',f.run)
        return f

    def test_all_files_survive_small_delivery_selection(self):
        f=self.fixture()
        keep={'app/server.py':'print(1)', 'app/backend/domain.py':'def value(x): return x',
              'app/backend/parser.py':'def parse(x): return x',
              'app/backend/analysis.json':'{"threshold":4}',
              'app/web/page.tsx':'export const Page=()=>null;',
              'app/web/theme.css':'body { color:black; }',
              'app/tests/test_domain.py':'assert 1 == 1',
              'app/package-lock.json':'{}','app/requirements.txt':'numpy',
              'app/start.ps1':'Write-Output ready','app/Dockerfile':'FROM python:3.12',
              'app/.env.example':'PORT=9000','app/assets/icon.svg':'<svg/>',
              'app/LICENSE':'Copyright project', 'outside.py':'print(2)'}
        remove={'app/README.md':'internal','app/source_analysis.py':'internal',
                'app/prompts/build.txt':'internal','app/evidence/review.json':'{}',
                'app/node_modules/library.js':'dependency','app/.env':'secret',
                'app/runtime.log':'log','app/credentials.json':'secret'}
        for n,v in {**keep,**remove}.items():
            p=f.work/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(v,encoding='utf-8')
        before={n:digest(f.work/n) for n in {**keep,**remove}}
        manifest=f.manifest('source',{'source_roots':['app'], 'files':['outside.py'],
                                     'exclude':[{'path':'app/evidence/review.json','reason':'production-record'}],
                                     'delivery_files':['app/server.py']})
        with (patch('zipfile.ZipFile',side_effect=AssertionError('no compression')),
              patch('subprocess.Popen',side_effect=AssertionError('no runtime'))):
            result=proflow.pack_source(f.work,f.out,manifest)
        self.assertEqual(set(result['files']),set(keep))
        self.assertEqual(result['retained_count'],len(keep))
        self.assertEqual(before,{n:digest(f.work/n) for n in before})
        self.assertTrue(proflow.scan_delivery(f.out,run=f.run)['passed'])
        self.assertEqual(set(execution_kinds(f.run)),{'algorithm','api','persistence','browser','build'})
        self.assertTrue(delivery_paths(f.run)['source_zip'].is_dir())

    def test_roots_cannot_escape_or_silently_narrow(self):
        f=self.fixture();(f.work/'app').mkdir();(f.work/'app/a.py').write_text('print(1)')
        for spec in ({'files':['app/a.py']}, {'source_roots':['../other']},
                     {'source_roots':['missing']},
                     {'source_roots':['app'],'exclude':['**/*.py']}):
            with self.assertRaises(ValueError):selected_files(spec,f.run,f.work)

    def test_business_materials_and_configuration_not_keyword_pruned(self):
        for name in ['backend/analysis.json','backend/formulas.json','parser.py',
                     'tests/fixtures/sample.pdf','app/design/model.json','web/prompts/retrieval.py',
                     'config.yml','deploy.ps1','LICENSES/NOTICE.txt',
                     'deployment/config.yml','app/prompts/classify.txt','app/prompt.json']:
            self.assertIsNone(exclusion(name),name)
        for name in ['.env','web/.env.production','.product-v2/review.json','build_word.py','source_analysis.py']:
            self.assertIsNotNone(exclusion(name),name)

    def test_duplicate_overlapping_roots_union_and_frozen_v2_stays_subset(self):
        f=self.fixture();(f.work/'app').mkdir()
        for n in ('a.py','b.py'):(f.work/'app'/n).write_text('print(1)')
        spec={'source_roots':['app','app'], 'files':['app/a.py','app/b.py'], 'delivery_files':['app/a.py']}
        self.assertEqual(selected_files(spec,f.run,f.work),['app/a.py','app/b.py'])
        self.assertEqual(selected_files(spec,{'source_delivery_policy':'main-code-directory-v2'},f.work),['app/a.py'])

    def test_business_named_directories_resources_and_secret_configs(self):
        f=self.fixture()
        keep={'app/backend/sessions/store.py':b'print(1)',
              'app/backend/evidence/service.py':b'print(1)',
              'app/web/recordings/player.ts':b'export const play=()=>true;',
              'app/tests/fixtures/readonly.sqlite':b'SQLite format 3\x00test fixture',
              'app/assets/tokenizer.model.gz':b'compressed model fixture',
              'app/config/ca.pem':b'-----BEGIN CERTIFICATE-----\npublic-test\n-----END CERTIFICATE-----',
              'app/.npmrc':b'registry=https://registry.npmjs.org\n',
              'app/openapi.json':b'{"properties":{"api_key":{"type":"string"},"password":{"type":"string"}}}',
              'app/password-policy.json':b'{"password":{"min_length":12}}',
              'app/auth.toml':b'password = true',
              'app/config/environment.json':b'{"api_key":"${API_KEY}"}'}
        secrets={'app/private/.npmrc':b'//registry.npmjs.org/:_authToken=synthetic-secret-1',
                 'app/.pypirc':b'[repository]\npassword=synthetic-secret-2',
                 'app/credentials/service-account.json':b'{"private_key":"synthetic-secret-3"}',
                 'app/config/private.pem':b'-----BEGIN RSA PRIVATE KEY-----\nsynthetic'}
        for name,data in {**keep,**secrets}.items():
            p=f.work/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        result=proflow.pack_source(f.work,f.out,f.manifest('source',{'source_roots':['app']}))
        self.assertEqual(set(result['files']),set(keep))
        self.assertEqual({x['path'] for x in result['excluded']},set(secrets))
        self.assertTrue(proflow.scan_delivery(f.out,run=f.run)['passed'])
        target=delivery_paths(f.run)['source_zip']/'app/.npmrc'
        target.write_bytes(secrets['app/private/.npmrc'])
        scanned=proflow.scan_delivery(f.out,run=f.run)
        self.assertFalse(scanned['passed'])

    def test_link_inside_project_is_rejected_without_reading_target(self):
        import os
        f=self.fixture();(f.work/'app').mkdir();outside=f.root/'outside';outside.mkdir()
        (outside/'private.py').write_text('private')
        try:os.symlink(outside,f.work/'app/linked',target_is_directory=True)
        except OSError as exc:self.skipTest('Host cannot create symlink: '+str(exc))
        with self.assertRaisesRegex(ValueError,'link/reparse'):
            selected_files({'source_roots':['app']},f.run,f.work)

    def test_exact_cleanup_normalizes_relative_spelling(self):
        f=self.fixture();(f.work/'app').mkdir();(f.work/'app/process.json').write_text('{}')
        spellings=['./app/process.json','app//process.json','app\\process.json']
        if sys.platform=='win32':spellings.append('APP/PROCESS.JSON')
        for spelling in spellings:
            spec={'source_roots':['app'],'files':['./app/process.json'],
                  'exclude':[{'path':spelling,'reason':'production-record'}]}
            files=selected_files(spec,f.run,f.work)
            self.assertEqual(files,['app/process.json'])
            self.assertEqual(exclusion(files[0],extra=spec['exclude']),'declared-production-record')

if __name__=='__main__':unittest.main()
