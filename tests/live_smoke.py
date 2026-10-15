"""Opt-in real browser/media/process smoke; never touches an existing case."""
import csv
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from proflow import prepare,clean_csv,pack_source,scan_delivery
from common import digest,write_json
from process_guard import register,stop,owned_processes,inventory

root=Path(tempfile.mkdtemp(prefix='product-v2-live-',dir=os.environ['TEMP']))
work=root/'case';work.mkdir();out=root/'delivery'
source_docx=work/'工具验证原件.docx'
with zipfile.ZipFile(source_docx,'w') as z:z.writestr('word/document.xml','<document/>')
run=prepare(work,out,'业务工具验证',source_docx)
server=work/'app.py';shutil.copyfile(Path(__file__).with_name('fixture_server.py'),server)
with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
process=subprocess.Popen([sys.executable,str(server),str(port)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
try:
    for _ in range(50):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}',timeout=1) as r:assert r.status==200
            break
        except OSError:time.sleep(.1)
    registered=[]
    # A Windows venv launcher may spawn the actual listening Python process.
    for owned in owned_processes(work,inventory()):
        if str(server).casefold() in owned['command'].casefold(): registered.append(register(work,owned['pid']))
    print(json.dumps({'fixture':str(root),'registration':registered},ensure_ascii=False),flush=True)
    plan={'url':f'http://127.0.0.1:{port}/','ready':'#ready','health_path':'/api/health','version':digest(server),'input_files':['app.py'],'duration_seconds':60,'steps':[
        {'at':2,'action':'fill','selector':'#query','value':'设备01','expect':'#query'},
        {'at':10,'action':'click','selector':'#search','expect':'#row','text':'设备01'},
        {'at':20,'action':'click','selector':'#detail','expect':'#panel'},
        {'at':30,'action':'select','selector':'#priority','value':'high','expect':'#priority'},
        {'at':40,'action':'click','selector':'#save','expect':'#saved','text':'已保存'},
        {'at':48,'action':'click','selector':'#history-button','expect':'#history','text':'优先处理'},
        {'at':56,'action':'download','selector':'#export','expect':'#history'}]}
    plan_path=work/'.product-v2/plan.json';write_json(plan_path,plan)
    recording=subprocess.run([os.environ['SCB_PRO_NODE'],str(Path(__file__).resolve().parents[1]/'scripts/record.cjs'),'--workspace',str(work),'--plan',str(plan_path)])
    assert recording.returncode==0,'Real recording failed'
    assert json.loads((work/'state.json').read_text(encoding='utf8'))['priority']=='high'
    cleanup=stop(work);assert cleanup['status']=='stopped',cleanup
    process.wait(timeout=5)
    data=work/'operations.csv'
    with data.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['编号','值','生成数据','数据来源'])
        for i in range(100000):writer.writerow([f'{i:06d}',f'{i/100:.3f}','是','fixture'])
    before=digest(data)
    keep=work/'.product-v2/keep.json';write_json(keep,{'files':[{'path':'operations.csv','reason':'规模与精度核验','primary_key':['编号'],'min_rows':100000}]})
    cleaning=clean_csv(work,out,keep);assert digest(data)==before
    (work/'README.md').write_text('Internal fixture instructions',encoding='utf8')
    (work/'extracted_text.txt').write_text('Internal extraction fixture',encoding='utf8')
    source=work/'.product-v2/source.json';write_json(source,{'files':['app.py','README.md','extracted_text.txt']})
    packaging=pack_source(work,out,source);scan=scan_delivery(out);assert scan['passed'],scan['hits']
    result={'fixture':str(root),'workspace':str(work),'video':run['video'],
            'rows':cleaning['files'][0]['rows'],'excluded':[x['path'] for x in packaging['excluded']],
            'process_status':cleanup['status'],'pid':process.pid,'port':port,'scan_passed':True,
            'scope':'Isolated tools fixture only; not a completed user case'}
    evidence=Path(__file__).resolve().parents[1]/'evidence/live-smoke.json';write_json(evidence,result)
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
finally:
    if process.poll() is None:
        try:stop(work)
        finally:
            if process.poll() is None:process.terminate();process.wait(timeout=5)
