"""Register images made by the built-in Codex image tool. No generation API."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid


def write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:temporary.unlink(missing_ok=True)


def load(path):return json.loads(path.read_text('utf-8-sig'))


def active_manifest(path):
    manifest = load(path)
    if manifest.get('schema') != 1:raise ValueError('지원하지 않는 요청 형식입니다.')
    job = load(path.parent.parent / 'job.json')
    excluded = (path.parent.parent / 'job.excluded.json').exists()
    if excluded or job.get('stop_requested') or job.get('status') not in ('running','images_running'):
        raise ValueError('중지·종료된 작업입니다. V13에서 이어 제작을 먼저 선택하세요.')
    if job.get('id') != manifest.get('job_id'):raise ValueError('작업 ID가 일치하지 않습니다.')
    for item in manifest['requests']:
        for key in ('output_file','receipt_file'):
            resolved = (path.parent / item[key]).resolve()
            if resolved.parent != (path.parent / 'results').resolve():raise ValueError('요청 파일 경로가 올바르지 않습니다.')
    return manifest


def receipt(path,item):
    file = path.parent / item['receipt_file']
    if not file.exists():return None
    result = load(file)
    if result.get('id') != item['id'] or result.get('prompt_hash') != item['prompt_hash']:raise ValueError('완료 기록과 요청이 일치하지 않습니다.')
    if result.get('status') == 'done':
        file = path.parent / item['output_file']
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != result.get('image_sha256'):raise ValueError('완료 이미지가 없거나 변경되었습니다.')
    return result


def process(args):
    path = Path(args.manifest).resolve()
    if args.command == 'status':
        manifest = load(path)
        items = [r for r in manifest['requests'] if not r.get('superseded')]
        results = [receipt(path,r) or {} for r in items]
        return {'total':len(items),'complete':sum(r.get('status')=='done' for r in results),
                'failed':sum(r.get('status')=='failed' for r in results),'manifest_path':str(path)}
    manifest = active_manifest(path)
    if args.command == 'next':
        for item in manifest['requests']:
            if item.get('superseded') or receipt(path,item):continue
            lease = path.parent / 'results' / (item['id'] + '.lease')
            if lease.exists():
                if time.time() - lease.stat().st_mtime < 1800:continue
                lease.unlink(missing_ok=True)
            try:
                fd = os.open(str(lease), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:continue
            with os.fdopen(fd, 'w') as stream:stream.write(str(time.time()))
            return {'request':item,'instructions':'Use the built-in image tool, inspect the output, then complete with this request id. Do not generate collages.'}
        return {'request':None,'message':'남은 요청이 없거나 다른 생성 작업이 처리 중입니다.'}
    item = next((r for r in manifest['requests'] if r['id']==args.id and not r.get('superseded')), None)
    if not item:raise ValueError('현재 장면 요청을 찾을 수 없습니다.')
    previous = receipt(path,item)
    if previous and previous.get('status') == 'done':return {'already_completed':True,'id':item['id']}
    result = {'id':item['id'],'prompt_hash':item['prompt_hash'],'number':item['number'],'completed_at':time.time()}
    if args.command == 'complete':
        source = Path(args.source).resolve()
        if source.suffix.lower() not in ('.png','.jpg','.jpeg','.webp'):raise ValueError('생성된 이미지 파일만 등록할 수 있습니다.')
        if not source.is_file() or source.stat().st_size > 20*1024*1024:raise ValueError('이미지 파일은 20MB 이하여야 합니다.')
        raw = source.read_bytes()
        if not (raw.startswith(b'\x89PNG\r\n\x1a\n') or raw.startswith(b'\xff\xd8\xff') or (raw.startswith(b'RIFF') and raw[8:12]==b'WEBP')):raise ValueError('이미지 파일 형식이 올바르지 않습니다.')
        # Recheck after reading so a stopped job cannot accept a late generation.
        latest = active_manifest(path)
        if not any(r['id']==item['id'] and not r.get('superseded') for r in latest['requests']):raise ValueError('장면 요청이 변경됐습니다.')
        write_atomic(path.parent/item['output_file'],raw)
        result.update(status='done',image_sha256=hashlib.sha256(raw).hexdigest(),source='Codex built-in image tool')
    else:result.update(status='failed',error=args.message[:1000])
    write_atomic(path.parent/item['receipt_file'],json.dumps(result,ensure_ascii=False,indent=2).encode())
    (path.parent/'results'/(item['id']+'.lease')).unlink(missing_ok=True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('status');sub.add_parser('next')
    complete=sub.add_parser('complete');complete.add_argument('--id',required=True);complete.add_argument('--source',required=True)
    fail=sub.add_parser('fail');fail.add_argument('--id',required=True);fail.add_argument('--message',required=True)
    try:print(json.dumps({'ok':True,**process(parser.parse_args())},ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'ok':False,'error':str(error)},ensure_ascii=False));sys.exit(1)


if __name__ == '__main__':main()
