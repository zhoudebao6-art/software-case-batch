"""Real filesystem/SQLite exports on synthetic cases; no production pass claims."""
from pathlib import Path
from contextlib import closing
import sys
import sqlite3
import gzip
import io
import zipfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import test_product_flow as flow
import test_construction_progress as progress
import proflow
from common import write_json, digest, delivery_paths
from runtime_cache import POLICY, evidence_path, member, snapshot
from source_delivery import selected_files, RETAINED_DIRECTORY_POLICY


class RuntimeCacheTests(unittest.TestCase):
    def fixture(self):
        f=flow.FlowTests();f.setUp();self.addCleanup(f.tearDown)
        f.run.update(source_delivery_policy=POLICY,delivery_layout_version='system-code-directory-v5')
        f.run.pop('source_zip');write_json(f.work/'.product-v2/run.json',f.run)
        return f

    def files(self,f,files):
        for name,value in files.items():
            p=f.work/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(value)

    def test_cache_export_preserves_complete_source_and_frozen_evidence(self):
        f=self.fixture()
        files={'app/main.py':b'print(1)','app/backend/store.py':b'print(2)',
               'app/web/index.js':b'let value=1;', 'app/tests/test_store.py':b'assert 1',
               'app/.cache/result.json':b'{"value":12}', 'runtime/index.idx':b'123',
               'app/.cache/cache_loader.py':b'print(3)'}
        self.files(f,files)
        spec={'source_roots':['app'],'runtime_cache_roots':['runtime'],
              'delivery_files':['app/main.py'],'exclude':[{'path':'app/.cache/result.json','reason':'runtime-state'}]}
        with patch('subprocess.Popen',side_effect=AssertionError('no startup')):
            result=proflow.pack_source(f.work,f.out,f.manifest('source',spec))
        self.assertEqual(set(result['files']),set(files))
        self.assertEqual(set(result['runtime_cache_files']),{'app/.cache/result.json','runtime/index.idx'})
        (f.work/'app/.cache/result.json').write_text('{"value":15}')
        status=proflow.workflow_status(f.work,f.out,f.run)
        self.assertEqual(status['steps']['source_package']['state'],'completed')
        for name in files:
            self.assertEqual(digest(evidence_path(f.work,f.run,result,name)),result['files'][name])
        frozen=evidence_path(f.work,f.run,result,'app/.cache/result.json');frozen.write_text('{}')
        with self.assertRaisesRegex(ValueError,'snapshot changed'):
            evidence_path(f.work,f.run,result,'app/.cache/result.json')
        self.assertTrue(proflow.scan_delivery(f.out,run=f.run)['passed'])

    def test_live_sqlite_wal_is_backed_up_without_stopping_or_mutating_source(self):
        f=self.fixture();self.files(f,{'app/main.py':b'print(1)'})
        (f.work/'runtime').mkdir();db=f.work/'runtime/state.sqlite'
        conn=sqlite3.connect(db);self.addCleanup(conn.close)
        conn.execute('PRAGMA journal_mode=WAL');conn.execute('PRAGMA wal_autocheckpoint=0')
        conn.execute('CREATE TABLE results(id INTEGER PRIMARY KEY,value REAL)')
        conn.execute('INSERT INTO results VALUES(1,12.5)');conn.commit()
        self.assertTrue(Path(str(db)+'-wal').is_file())
        before={p.name:digest(p) for p in db.parent.iterdir() if not p.name.endswith('-shm')}
        result=proflow.pack_source(f.work,f.out,f.manifest('source',{'source_roots':['app'],'runtime_cache_roots':['runtime']}))
        dst=delivery_paths(f.run)['source_zip']/'runtime/state.sqlite'
        with closing(sqlite3.connect(dst)) as check:self.assertEqual(check.execute('SELECT value FROM results').fetchall(),[(12.5,)])
        self.assertFalse(any(x.endswith(('-wal','-shm')) for x in result['files']))
        self.assertEqual(before,{p.name:digest(p) for p in db.parent.iterdir() if not p.name.endswith('-shm')})
        conn.execute('INSERT INTO results VALUES(2,20)');conn.commit()
        frozen=evidence_path(f.work,f.run,result,'runtime/state.sqlite')
        self.assertEqual(digest(frozen),result['files']['runtime/state.sqlite'])
        self.assertTrue(proflow.scan_delivery(f.out,run=f.run)['passed'])

    def test_private_runtime_data_excluded_and_post_export_tamper_detected(self):
        f=self.fixture();self.files(f,{'app/main.py':b'print(1)',
            'app/.cache/data.json':b'{"value":1}',
            'app/.cache/auth.json':b'{"access_token":"secret-fixture"}',
            'app/.cache/rows.csv':b'id,access_token\n1,secret-fixture\n',
            'app/.cache/storage-state.json':b'{"cookies":[]}'})
        db=f.work/'app/.cache/state.db'
        with closing(sqlite3.connect(db)) as conn:
            conn.execute('CREATE TABLE users(id INTEGER,password_hash TEXT)')
            conn.execute("INSERT INTO users VALUES(1,'secret-fixture')")
            conn.commit()
        result=proflow.pack_source(f.work,f.out,f.manifest('source',{'source_roots':['app']}))
        self.assertEqual(set(result['files']),{'app/main.py','app/.cache/data.json'})
        target=delivery_paths(f.run)['source_zip']/'app/.cache/data.json'
        target.write_text('{"session_token":"secret-fixture"}')
        self.assertFalse(proflow.scan_delivery(f.out,run=f.run)['passed'])
        self.assertNotIn('secret-fixture',str(result))

    def test_legacy_policy_and_unsafe_cache_scope(self):
        f=self.fixture();self.files(f,{'app/main.py':b'print(1)','app/.cache/result.json':b'{}'})
        legacy=dict(f.run,source_delivery_policy=RETAINED_DIRECTORY_POLICY)
        self.assertEqual(selected_files({'source_roots':['app']},legacy,f.work),['app/main.py'])
        for root in ('..','../outside','E:/cache','/tmp/cache','.'):
            with self.assertRaises(ValueError):
                selected_files({'source_roots':['app'],'runtime_cache_roots':[root]},f.run,f.work)

    def test_cache_changes_do_not_invalidate_code_but_actual_inputs_and_code_do(self):
        f=progress.DependencyFixture();f.setUp();self.addCleanup(f.tearDown)
        f.run['source_delivery_policy']=POLICY
        f.file('runtime/cache/data.json','{"value":1}')
        write_json(f.manifest,{'source_roots':['web','LICENSES'],'files':['app.py'],
                             'runtime_cache_roots':['runtime/cache']})
        self.assertEqual(f.gate()['status'],'ready')
        f.file('runtime/cache/data.json','{"value":2}')
        self.assertEqual(f.gate()['status'],'ready')
        f.file('data/input.csv','编号,值\n001,99\n')
        with self.assertRaises(ValueError):f.gate()
        f.file('data/input.csv','编号,值\n001,10\n')
        f.file('web/app.js','changed code')
        with self.assertRaisesRegex(ValueError,'snapshot'):f.gate()

    def test_no_cache_is_required_and_code_cannot_be_disguised_as_cache(self):
        f=self.fixture();self.files(f,{'app/main.py':b'print(1)'})
        result=proflow.pack_source(f.work,f.out,f.manifest('source',{'source_roots':['app']}))
        self.assertEqual(result['runtime_cache_files'],{})
        p=f.work/'.product-v2/source-cache/fake/main.py';p.parent.mkdir(parents=True);p.write_bytes(b'print(1)')
        result['runtime_cache_evidence']['app/main.py']=p.relative_to(f.work).as_posix()
        result['runtime_cache_files']['app/main.py']=digest(p)
        result['runtime_cache_roots']=['app']
        with self.assertRaises(ValueError):
            evidence_path(f.work,f.run,result,'app/main.py')

    def test_cache_types_and_normal_domain_session_are_preserved(self):
        f=self.fixture()
        keep={'app/main.py':b'print(1)','app/game/session.json':b'{"players":2}',
              'app/game/results.csv':b'session_id,score\n1,35\n',
              'app/.cache/result.txt':b'calculated 25', 'app/.cache/state':b'17',
              'app/.cache/000001.ldb':b'computed-index',
              'app/.cache/results.json.gz':gzip.compress(b'{"value":25}')}
        self.files(f,keep)
        result=proflow.pack_source(f.work,f.out,f.manifest('source',{'source_roots':['app']}))
        self.assertEqual(set(result['files']),set(keep))
        self.assertEqual(set(result['runtime_cache_files']),{p for p in keep if '/.cache/' in p})
        self.assertFalse(member('app/.cache/settings.json',{'source_roots':['app']}))
        with self.assertRaises(ValueError):member('app/settings.json',{'source_roots':['app'],'runtime_cache_roots':['app']})

    def test_private_text_and_compressed_cache_are_not_exported(self):
        f=self.fixture();self.files(f,{'app/main.py':b'print(1)',
            'app/.cache/token.txt':b'Bearer fixture-secret-token',
            'app/.cache/token.json.gz':gzip.compress(b'{"access_token":"fixture-secret"}')})
        result=proflow.pack_source(f.work,f.out,f.manifest('source',{'source_roots':['app']}))
        self.assertEqual(set(result['files']),{'app/main.py'})

    def test_sqlite_free_pages_removed_and_nested_secret_rejected(self):
        f=self.fixture();db=f.work/'cache.db';target=f.work/'snapshot.db'
        with closing(sqlite3.connect(db)) as conn:
            conn.execute('PRAGMA secure_delete=OFF')
            conn.execute('CREATE TABLE results(payload TEXT)')
            conn.execute('INSERT INTO results VALUES(?)',('removed-sensitive-fixture'*300,));conn.commit()
            conn.execute('DELETE FROM results');conn.commit()
        self.assertIn(b'removed-sensitive-fixture',db.read_bytes())
        original=digest(db);self.assertIsNone(snapshot(db,target))
        self.assertNotIn(b'removed-sensitive-fixture',target.read_bytes())
        self.assertEqual(original,digest(db))
        with closing(sqlite3.connect(db)) as conn:
            conn.execute('INSERT INTO results VALUES(?)',('{"access_token":"fixture-secret"}',));conn.commit()
        self.assertEqual(snapshot(db,f.work/'private.db'),'private-runtime-database')

    def test_immutable_seed_database_keeps_original_bytes(self):
        f=self.fixture();self.files(f,{'app/main.py':b'print(1)'})
        db=f.work/'app/seed.sqlite'
        with closing(sqlite3.connect(db)) as conn:
            conn.execute('CREATE TABLE values_table(value REAL)');conn.commit()
        original=digest(db)
        result=proflow.pack_source(f.work,f.out,f.manifest('source',{'source_roots':['app']}))
        self.assertEqual(result['files']['app/seed.sqlite'],original)
        self.assertEqual(result['runtime_snapshots'],{})

    def test_scanned_bytes_cannot_be_replaced_before_copy(self):
        f=self.fixture();self.files(f,{'app/main.py':b'print(1)','app/.cache/result.json':b'{"value":12}'})
        original_scan=proflow.scan_text
        def swap(name,data):
            result=original_scan(name,data)
            if name=='app/.cache/result.json':(f.work/name).write_bytes(b'{"access_token":"fixture-secret"}')
            return result
        with patch('proflow.scan_text',side_effect=swap),self.assertRaisesRegex(ValueError,'changed while exporting'):
            proflow.pack_source(f.work,f.out,f.manifest('source',{'source_roots':['app']}))
        self.assertFalse(delivery_paths(f.run)['source_zip'].exists())

    def test_prepare_has_no_old_blanket_cache_exclusion(self):
        f=self.fixture()
        prompt=(f.work/'.product-v2/深化命令词.txt').read_text('utf8')
        self.assertNotIn('日志、缓存、依赖目录与凭据',prompt)
        self.assertIn('连续业务闭环',prompt)

    def test_nested_private_profile_is_not_delivered(self):
        f=self.fixture();stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            z.writestr('profile/storage-state.json','{"origins":[{"localStorage":[{"name":"login","value":"private"}]}]}')
        self.files(f,{'app/main.py':b'print(1)','app/.cache/capture.zip':stream.getvalue(),
            'app/.cache/storage-state.json.gz':gzip.compress(b'{"origins":[]}')})
        result=proflow.pack_source(f.work,f.out,f.manifest('source',{'source_roots':['app']}))
        self.assertEqual(set(result['files']),{'app/main.py'})

    def test_implicit_rowid_references_are_never_silently_renumbered(self):
        f=self.fixture();db=f.work/'rowids.db'
        with closing(sqlite3.connect(db)) as conn:
            conn.execute('CREATE TABLE results(value REAL)')
            conn.execute('INSERT INTO results(rowid,value) VALUES(3,11),(14,22)')
            conn.execute('CREATE TABLE annotations(result_id INTEGER)')
            conn.execute('INSERT INTO annotations VALUES(14)');conn.commit()
        original=digest(db)
        with self.assertRaisesRegex(ValueError,'implicit rowid'):
            snapshot(db,f.work/'snapshot.db')
        self.assertEqual(original,digest(db))

    def test_sqlite_fast_filter_keeps_all_secret_rules_and_escaped_fields(self):
        from runtime_cache import sqlite_private
        f=self.fixture();db=f.work/'secrets.db'
        with closing(sqlite3.connect(db)) as conn:
            conn.execute('CREATE TABLE payloads(value TEXT)');conn.commit()
            for value in ('{"azure_storage_key":"fixture-key"}', 'Bearer\u00a0fixture-secret-token',
                          '{"access\\u005ftoken":"fixture-key"}'):
                conn.execute('DELETE FROM payloads');conn.execute('INSERT INTO payloads VALUES(?)',(value,));conn.commit()
                self.assertTrue(sqlite_private(db),value)


if __name__=='__main__':unittest.main()
