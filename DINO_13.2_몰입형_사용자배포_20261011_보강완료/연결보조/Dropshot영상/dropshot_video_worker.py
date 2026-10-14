"""Register Dropshot MCP video jobs/results without storing account credentials."""
import argparse,hashlib,json,os,sys,time,uuid
from pathlib import Path

def load(p):return json.loads(p.read_text('utf-8-sig'))
def write(p,d):
    p.parent.mkdir(parents=True,exist_ok=True);t=p.with_name(p.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with t.open('wb') as f:f.write(d);f.flush();os.fsync(f.fileno())
        os.replace(t,p)
    finally:t.unlink(missing_ok=True)
def jsonwrite(p,d):write(p,json.dumps(d,ensure_ascii=False,indent=2).encode())
def active(p):
    m=load(p);j=load(p.parent.parent/'job.json')
    if m.get('schema')!=1 or j['id']!=m['job_id']:raise ValueError('작업 ID/형식 오류')
    if j.get('stop_requested') or (p.parent.parent/'job.excluded.json').exists() or j.get('video_state')!='running' or j.get('render_state')!='running':raise ValueError('중지·종료된 영상 작업입니다.')
    for r in m['requests']:
        for k in ('output_file','receipt_file','state_file'):
            if (p.parent/r[k]).resolve().parent!=(p.parent/'results').resolve():raise ValueError('결과 경로 오류')
    return m
def process(a):
    p=Path(a.manifest).resolve()
    if a.command=='status':
        m=load(p);items=[r for r in m['requests'] if not r.get('superseded')];return {'total':len(items),'complete':sum((load(p.parent/r['receipt_file']) if (p.parent/r['receipt_file']).exists() else {}).get('status')=='done' for r in items)}
    m=active(p)
    if a.command=='next':
        for r in m['requests']:
            if r.get('superseded') or (p.parent/r['receipt_file']).exists():continue
            state=load(p.parent/r['state_file']) if (p.parent/r['state_file']).exists() else {}
            if hashlib.sha256(Path(r['image_path']).read_bytes()).hexdigest()!=r['image_sha256']:raise ValueError('입력 이미지 변경됨')
            return {'request':r,'state':state}
        return {'request':None}
    r=next((r for r in m['requests'] if r['id']==a.id and not r.get('superseded')),None)
    if not r:raise ValueError('현재 장면 요청을 찾을 수 없습니다.')
    statepath=p.parent/r['state_file'];state=load(statepath) if statepath.exists() else {}
    if a.command=='submitted':
        if state.get('job_id') and state['job_id']!=a.job_id:raise ValueError('이미 접수된 작업입니다. 재생성 금지')
        jsonwrite(statepath,{'job_id':a.job_id,'credits':a.credits,'submitted_at':time.time()});return {'ok':True,'job_id':a.job_id}
    receiptpath=p.parent/r['receipt_file']
    if receiptpath.exists() and load(receiptpath).get('status')=='done':return {'already_completed':True}
    receipt={'id':r['id'],'prompt_hash':r['prompt_hash'],'number':r['number'],'completed_at':time.time()}
    if a.command=='complete':
        if not state.get('job_id') or state['job_id']!=a.job_id:raise ValueError('접수된 영상 작업 ID가 다릅니다.')
        source=Path(a.source).resolve();raw=source.read_bytes()
        if source.suffix.lower()!='.mp4' or len(raw)<12 or len(raw)>128*1024*1024 or raw[4:8]!=b'ftyp':raise ValueError('MP4 결과 파일 오류')
        active(p);write(p.parent/r['output_file'],raw)
        receipt.update(status='done',job_id=a.job_id,credits=a.credits if a.credits is not None else state.get('credits'),video_sha256=hashlib.sha256(raw).hexdigest(),source='Dropshot MCP')
    else:receipt.update(status='failed',error=a.message[:1000])
    jsonwrite(receiptpath,receipt);return {'ok':True,'number':r['number'],'status':receipt['status']}
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--manifest',required=True);sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('status');sub.add_parser('next')
    for command in ('submitted','complete','fail'):
        s=sub.add_parser(command);s.add_argument('--id',required=True)
        if command!='fail':s.add_argument('--job-id',required=True);s.add_argument('--credits',type=float)
        if command=='complete':s.add_argument('--source',required=True)
        if command=='fail':s.add_argument('--message',required=True)
    try:print(json.dumps(process(parser.parse_args()),ensure_ascii=False))
    except Exception as e:print(json.dumps({'ok':False,'error':str(e)},ensure_ascii=False));sys.exit(1)
if __name__=='__main__':main()
