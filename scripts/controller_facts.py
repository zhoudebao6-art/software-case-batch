"""Incremental short controller facts. Advisory only; never modify batch state or sign evidence."""
import argparse
import hashlib
import json
from pathlib import Path
from common import no_links,read_json,write_json


def collect(session,cache_path):
    session=no_links(session);cache_path=no_links(cache_path)
    if session==cache_path or session.suffix.lower()!='.jsonl':
        raise ValueError('Distinct real session log and internal cache required')
    stat=session.stat()
    with session.open('rb') as stream:
        header=stream.readline()
        identity={'path':str(session),'device':stat.st_dev,'inode':stat.st_ino,
                  'header_sha256':hashlib.sha256(header).hexdigest()}
        previous=read_json(cache_path) if cache_path.exists() else {}
        if previous.get('identity')!=identity or previous.get('offset',0)>stat.st_size:
            previous={'identity':identity,'offset':0,'calls':{},'outputs':{},'usage':{}}
        stream.seek(previous['offset'])
        new_events=0
        while True:
            offset=stream.tell();line=stream.readline()
            if not line or not line.endswith(b'\n'):
                previous['offset']=offset
                break
            previous['offset']=stream.tell()
            try:event=json.loads(line)
            except (json.JSONDecodeError,UnicodeDecodeError):continue
            new_events+=1;payload=event.get('payload',{})
            if event.get('type')=='token_usage_record':
                rid=payload.get('response_id');usage=payload.get('usage',{})
                if rid and isinstance(usage,dict):
                    keys=('input_tokens','cached_input_tokens','output_tokens')
                    selected={k:usage.get(k,0) for k in keys}
                    if all(isinstance(v,int) and not isinstance(v,bool) and v>=0 for v in selected.values()):
                        old=previous['usage'].get(rid,{})
                        # Cached input is a subset of input, not additional usage.
                        total=lambda value:value.get('input_tokens',0)+value.get('output_tokens',0)
                        if total(selected)>=total(old):previous['usage'][rid]=selected
            if event.get('type')!='response_item':continue
            if payload.get('type')=='function_call' and payload.get('name','').split('.')[-1]=='spawn_agent':
                try:args=json.loads(payload.get('arguments','{}'))
                except (json.JSONDecodeError,TypeError):continue
                previous['calls'][payload['call_id']]={k:args.get(k) for k in ('task_name','model','reasoning_effort','fork_turns')}
            elif payload.get('type')=='function_call_output' and payload.get('call_id') in previous['calls']:
                result=payload.get('output')
                try:result=json.loads(result) if isinstance(result,str) else result
                except json.JSONDecodeError:continue
                if isinstance(result,dict) and result.get('task_name'):
                    previous['outputs'][payload['call_id']]=result['task_name']
    cache_path.parent.mkdir(parents=True,exist_ok=True)
    write_json(cache_path,previous)
    calls=[dict(call_id=cid,agent_id=previous['outputs'][cid],**args)
           for cid,args in previous['calls'].items() if cid in previous['outputs']]
    usage={key:sum(row.get(key,0) for row in previous['usage'].values())
           for key in ('input_tokens','cached_input_tokens','output_tokens')}
    return {'kind':'advisory-controller-facts','new_events':new_events,'offset':previous['offset'],
            'calls':calls,'unique_responses':len(previous['usage']),'usage':usage,
            'limitation':'Incremental cache is not integrity evidence. Final gates re-read actual logs; no batch phase is inferred or overwritten.'}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session',required=True);parser.add_argument('--cache',required=True)
    args=parser.parse_args(argv)
    try:
        print(json.dumps(collect(args.session,args.cache),ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print('ERROR: '+str(exc));return 2


if __name__=='__main__':raise SystemExit(main())
