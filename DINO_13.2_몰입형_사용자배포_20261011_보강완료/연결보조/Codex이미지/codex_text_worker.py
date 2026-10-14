"""Read current requests and register local Codex results; Python stdlib only."""
import argparse,json,urllib.request,uuid,os
from pathlib import Path
def http(mode,path,data=None):
    base='http://127.0.0.1:'+('5912' if mode=='shorts' else '5911')+'/api/r5/'
    headers={}
    if data is not None:
        boot=http(mode,'bootstrap');headers={'X-Dino-R5-Session':boot['token'],'Content-Type':'application/json'}
    req=urllib.request.Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
    with urllib.request.urlopen(req,timeout=10) as response:return json.load(response)
def current(path):
    req=json.loads(path.read_text('utf-8-sig'));boot=http(req['mode'],'bootstrap')
    if boot.get('active_id')!=req['job_id']:raise ValueError('현재 작업이 변경되었습니다.')
    job=http(req['mode'],'job/'+req['job_id'])['job'];state=job.get('codex_text',{})
    if job.get('stop_requested') or job.get('status') not in ('running',) or state.get('state')!='waiting' or state.get('id')!=req['id']:raise ValueError('중지되었거나 만료된 Codex 요청입니다.')
    return req
def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['status','next','complete','fail','start']);p.add_argument('--request');p.add_argument('--source');p.add_argument('--error');p.add_argument('--title');p.add_argument('--mode',choices=['shorts','longform'],default='shorts');a=p.parse_args()
    if a.command=='start':
        boot=http(a.mode,'bootstrap')
        if boot['settings'].get('text_connection')!='codex':raise ValueError('DINO에서 Codex 자료 조사·대본 모드를 먼저 선택하세요.')
        if not a.title:raise ValueError('주제를 입력하세요.')
        out=http(a.mode,'jobs',{'title':a.title,'language':'ko','stop_after':'images','auto_continue':boot['settings'].get('auto_finalize',False)})
        print(json.dumps(out,ensure_ascii=False));return
    if not a.request:raise ValueError('요청 파일이 필요합니다.')
    path=Path(a.request);req=current(path)
    if a.command in ('status','next'):print(json.dumps(req,ensure_ascii=False));return
    target=Path(req['response_file'])
    if target.parent.resolve()!=path.parent.resolve():raise ValueError('응답 파일 경로 오류')
    if target.exists():raise ValueError('이미 등록된 요청입니다. next로 다음 요청을 확인하세요.')
    receipt={'id':req['id'],'prompt_hash':req['prompt_hash'],'status':'failed' if a.command=='fail' else 'done'}
    if a.command=='complete':
        if not a.source:raise ValueError('결과 파일이 필요합니다.')
        content=Path(a.source).read_text('utf-8-sig');json.loads(content)
        receipt['content']=content
    else:receipt['error']=a.error or 'Codex 작업을 완료하지 못했습니다.'
    current(path)
    temp=target.with_suffix('.'+uuid.uuid4().hex+'.tmp');temp.write_text(json.dumps(receipt,ensure_ascii=False),'utf-8');os.replace(temp,target)
    print(json.dumps({'ok':True,'id':req['id'],'status':receipt['status']},ensure_ascii=False))
if __name__=='__main__':main()
