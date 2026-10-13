"""Local browser-tool fixture. This is not a delivered business application."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import hashlib
import os
import sys
from pathlib import Path
PAGE='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>业务工具验证</title>
<style>body{margin:0;font:20px 'Microsoft YaHei',sans-serif;color:#26374a;background:#edf1f5}header{background:#223951;color:white;padding:26px 55px}main{max-width:1400px;margin:45px auto;background:white;padding:36px;border-radius:12px}button,input,select{font:inherit;padding:12px;margin:8px;border:1px solid #acbac8;border-radius:6px}button{background:#1764a1;color:white;cursor:pointer}section{padding:24px;border:1px solid #d9e1e8;margin-top:24px}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:22px;border-bottom:1px solid #dde3e9}.hint{color:#5b6d80}h1{font-size:28px}#panel,#history,#saved{display:none}</style>
<header>运行业务管理 · 工具执行验证</header><main><h1 id="ready">设备任务</h1><p class="hint">浏览记录、调整处理优先级、保存并导出执行结果</p>
<input id="query" placeholder="输入设备编号"><button id="search">查询</button>
<section><table><tr><th>设备</th><th>任务</th><th>状态</th><th>操作</th></tr><tr id="row"><td>设备01</td><td>运行状态检查</td><td id="state">待处理</td><td><button id="detail">查看详情</button></td></tr></table></section>
<section id="panel"><h2>任务详情 · 设备01</h2><p>当前负责人：运行管理组；检查周期：每日；计划批次：20261012</p><label>处理优先级<select id="priority"><option value="normal">常规</option><option value="high">优先</option></select></label><button id="save">保存任务</button><p id="saved"></p></section>
<button id="history-button">查看处理记录</button><section id="history">处理记录：<span id="history-content"></span></section><button id="export">导出记录</button></main>
<script>const el=id=>document.getElementById(id);el('search').onclick=()=>{el('row').style.display=el('query').value==='设备01'?'table-row':'none'};el('detail').onclick=()=>el('panel').style.display='block';el('save').onclick=async()=>{const r=await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({priority:el('priority').value})});const v=await r.json();el('saved').textContent='已保存：'+v.label;el('saved').style.display='block';el('state').textContent='已安排'};el('history-button').onclick=async()=>{const r=await fetch('/api/state');const v=await r.json();el('history-content').textContent=v.label;el('history').style.display='block'};el('export').onclick=()=>{const a=document.createElement('a');a.href='/api/export';a.download='records.csv';a.click()};</script></html>'''
STORE=Path(__file__).with_name('state.json')
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        if self.path=='/favicon.ico':self.send_response(204);self.end_headers();return
        if self.path=='/api/health':
            run=json.loads(Path(__file__).with_name('.product-v2').joinpath('run.json').read_text(encoding='utf8'))
            data=json.dumps({'run_id':run['run_id'],'workspace':run['workspace'],'version':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'pid':os.getpid()}).encode('utf8');mime='application/json'
        elif self.path=='/api/state':
            data=STORE.read_bytes() if STORE.exists() else b'{"label":"pending"}';mime='application/json'
        elif self.path=='/api/export':data='编号,优先级\r\n1,优先\r\n'.encode('utf-8-sig');mime='text/csv'
        else:data=PAGE.encode('utf8');mime='text/html; charset=utf-8'
        self.send_response(200);self.send_header('Content-Type',mime)
        if self.path=='/api/export':self.send_header('Content-Disposition','attachment; filename=records.csv')
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_POST(self):
        value=json.loads(self.rfile.read(int(self.headers['Content-Length'])));value['label']='优先处理' if value['priority']=='high' else '常规处理'
        data=json.dumps(value,ensure_ascii=False).encode('utf8');STORE.write_bytes(data)
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
if __name__=='__main__':HTTPServer(('127.0.0.1',int(sys.argv[1])),Handler).serve_forever()
