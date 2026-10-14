import argparse,json
from pathlib import Path
import codex_image_worker as worker
def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['next','status','submitted','complete']);p.add_argument('--manifest',required=True);p.add_argument('--id');p.add_argument('--job-id');p.add_argument('--source');a=p.parse_args()
    path=Path(a.manifest);manifest=worker.active_manifest(path)
    pending=[r for r in manifest['requests'] if not r.get('superseded') and not worker.receipt(path,r)]
    if a.command in ('status','next'):
        row=pending[0] if pending else None
        if row:
            state=path.parent/'results'/(row['id']+'.mcp-state.json')
            row={**row,'state':worker.load(state) if state.exists() else None}
        print(json.dumps({'request':row,'pending':len(pending)},ensure_ascii=False));return
    row=next((r for r in pending if r['id']==a.id),None)
    if not row:raise ValueError('현재 대기 중인 요청 ID가 아닙니다.')
    if a.command=='submitted':
        state=path.parent/'results'/(row['id']+'.mcp-state.json')
        if state.exists() and worker.load(state).get('job_id')!=a.job_id:raise ValueError('이미 다른 생성 작업이 기록되었습니다.')
        worker.write_atomic(state,json.dumps({'job_id':a.job_id,'id':row['id']}).encode());print('{"ok":true}');return
    import sys
    sys.argv=[str(Path(__file__).with_name('codex_image_worker.py')),'--manifest',str(path),'complete','--id',a.id,'--source',a.source]
    worker.main()
if __name__=='__main__':main()
