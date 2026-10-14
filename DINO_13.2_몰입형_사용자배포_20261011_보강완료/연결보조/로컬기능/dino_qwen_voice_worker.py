"""DINO's isolated, loopback-only Qwen Base runtime. No cloud TTS fallback."""
import argparse,base64,gc,hashlib,json,os,pathlib,queue,re,secrets,threading,time,urllib.request,urllib.error
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1')
ROOT=pathlib.Path(__file__).resolve().parent
import sys
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from local_voice_alignment import CaptionAlignmentError
MODEL='Qwen3-TTS-12Hz-0.6B-Base'
RUNTIME_VERSION='voice-memory-quality-recovery-3'
LANGS={'ko':'Korean','en':'English','ja':'Japanese','zh':'Chinese','de':'German','fr':'French','es':'Spanish','pt':'Portuguese','it':'Italian','ru':'Russian','auto':'Auto'}

def prepare_runtime_cache():
    """Numba's Windows delete-on-close probe must not traverse a junction.

    On some redirected profiles O_EXCL reports EEXIST for every fresh name.
    tempfile then retries up to 2**31-1 times, blocking imports and HTTP replies.
    Use a canonical, private cache and test it once before importing Qwen.
    """
    import tempfile
    cache=(ROOT/'cache/numba').resolve()
    cache.mkdir(parents=True,exist_ok=True)
    probe=cache/('dino-probe-'+secrets.token_hex(12)+'.tmp')
    flags=os.O_RDWR|os.O_CREAT|os.O_EXCL|getattr(os,'O_BINARY',0)|getattr(os,'O_TEMPORARY',0)
    try:
        fd=os.open(probe,flags,0o600)
        os.close(fd)
        if not getattr(os,'O_TEMPORARY',0):probe.unlink()
    except OSError as error:
        raise RuntimeError('음성 임시 캐시 폴더에 접근하지 못했습니다. 폴더 권한과 보안 프로그램을 확인하세요.') from error
    os.environ['NUMBA_CACHE_DIR']=str(cache)
    os.environ['NUMBA_NUM_THREADS']='4'
    temporary=(ROOT/'cache/temp').resolve()
    temporary.mkdir(parents=True,exist_ok=True)
    os.environ['TEMP']=os.environ['TMP']=str(temporary)
    tempfile.tempdir=str(temporary)
    return cache

def configure_weight_loading():
    """Keep the Windows fix inside this isolated voice process only."""
    if os.name!='nt':return 'native'
    import inspect,safetensors,safetensors.torch
    original=safetensors.safe_open
    if getattr(original,'_dino_pread',False):return 'pread'
    if 'backend' not in inspect.signature(original).parameters:return 'legacy'
    def low_commit_open(*args,**kwargs):
        kwargs.setdefault('backend','pread')
        return original(*args,**kwargs)
    low_commit_open._dino_pread=True
    # Qwen/Transformers import aliases of safe_open; cover already-imported
    # aliases as well as subsequent imports, without editing installed packages.
    for name,module in list(sys.modules.items()):
        if name=='safetensors' or name.startswith(('safetensors.','transformers.','qwen_tts.')):
            if getattr(module,'safe_open',None) is original:module.safe_open=low_commit_open
    return 'pread'

def memory_failure(error):
    text=str(error).casefold()
    return (isinstance(error,MemoryError) or getattr(error,'winerror',None)==1455
            or any(value in text for value in ('os error 1455','winerror 1455','out of memory')))

def split_text(text,limit=160):
    """Keep every non-space character in order; prefer sentence boundaries."""
    chunks=[]
    for paragraph in re.split(r'\n\s*\n',text.strip()):
        current=''
        for match in re.finditer(r'.+?(?:[.!?。！？](?=\s|$)|$)',paragraph.strip(),re.S):
            sentence=match.group().strip()
            if current and len(current)+len(sentence)>limit:chunks.append(current);current=''
            while len(sentence)>limit*2:
                cut=sentence.rfind(' ',0,limit)
                if cut<limit//2:cut=limit
                if current:chunks.append(current);current=''
                chunks.append(sentence[:cut].strip());sentence=sentence[cut:].strip()
            current=(current+' '+sentence).strip()
        if current:chunks.append(current)
    if re.sub(r'\s','', ''.join(chunks))!=re.sub(r'\s','',text):raise ValueError('대본 분할 검증에 실패했습니다.')
    return chunks

def atomic_json(path,data):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf-8');temp.replace(path)

class FileLock:
    def __init__(self,path,check=lambda:None):self.path=path;self.check=check
    def __enter__(self):
        import msvcrt
        self.path.parent.mkdir(parents=True,exist_ok=True);self.file=self.path.open('a+b')
        self.file.seek(0);self.file.write(b'0');self.file.flush()
        while True:
            self.check();self.file.seek(0)
            try:msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1);return self
            except OSError:time.sleep(.2)
    def __exit__(self,*args):
        import msvcrt
        self.file.seek(0);msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1);self.file.close()

class Runtime:
    def __init__(self,parent):
        self.parent=parent;self.jobs={};self.queue=queue.Queue();self.lock=threading.RLock()
        self.model=None;self.prompt=None;self.aligner=None;self.busy=None;self.last_used=time.monotonic();self.weight_loading='pending'
        self.profile=json.loads((ROOT/'voice_profile.json').read_text('utf-8'))
        self.cache=ROOT/'jobs';self.cache.mkdir(exist_ok=True)
        threading.Thread(target=self.work,daemon=True).start()
    def public(self,j):return {k:v for k,v in j.items() if k not in ('cancel','text','caption_text','audio')}
    def submit(self,text,language,caption_text=None):
        if not isinstance(text,str) or not text.strip() or len(text)>50000:raise ValueError('읽을 대본은 한 번에 50,000자 이내로 입력하세요.')
        language=LANGS.get(language,language)
        if language not in LANGS.values():raise ValueError('지원하지 않는 음성 언어입니다.')
        profile_sha=hashlib.sha256(pathlib.Path(self.profile['reference_wav']).read_bytes()).hexdigest()
        caption_text=caption_text or text
        if not isinstance(caption_text,str) or len(caption_text)>50000:raise ValueError('자막 원문을 확인하세요.')
        signature=[MODEL,self.profile['revision'],profile_sha,self.profile['reference_text'],text,language,'sdpa-bf16-nonstream-42-160-v1']
        if caption_text!=text:signature.append(caption_text)
        key=hashlib.sha256(json.dumps(signature,ensure_ascii=False).encode()).hexdigest()
        with self.lock:
            old=self.jobs.get(key)
            if old and old['status'] in ('queued','running','done'):return self.public(old)
            j={'id':key,'status':'queued','message':'로컬 음성 생성 대기','chunks_done':0,'chunks_total':len(split_text(text)),'chars':len(text),'language':language,'text':text,'caption_text':caption_text,'cancel':threading.Event(),'voice':self.profile['name']}
            self.jobs[key]=j;self.queue.put(key);return self.public(j)
    def prepare_gpu(self,j):
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        token=(ROOT/'service_token.txt').read_text('utf-8').strip()
        base='http://127.0.0.1:8187'
        try:
            req=urllib.request.Request(base+'/queue',headers={'X-Dino-Image':token})
            with opener.open(req,timeout=3) as r:data=json.load(r)
            if data.get('queue_running') or data.get('queue_pending'):raise ValueError('이미지 생성이 끝난 뒤 음성을 생성하세요.')
            req=urllib.request.Request(base+'/free',data=b'{"unload_models":true,"free_memory":true}',headers={'X-Dino-Image':token,'Content-Type':'application/json'})
            with opener.open(req,timeout=10) as r:r.read()
            time.sleep(2)
        except OSError:pass

    def load(self,j):
        if self.model is not None:return
        j.update(message='내 목소리로 로컬 음성 모델을 준비합니다.',stage='loading_model')
        self.prepare_gpu(j)
        import torch
        torch.set_num_threads(4)
        self.weight_loading=configure_weight_loading()
        from qwen_tts import Qwen3TTSModel
        if not torch.cuda.is_available():raise ValueError('Qwen 로컬 음성에 필요한 NVIDIA GPU를 찾지 못했습니다.')
        model=Qwen3TTSModel.from_pretrained(str(ROOT/'models'/MODEL),device_map='cuda:0',dtype=torch.bfloat16,attn_implementation='sdpa',local_files_only=True)
        j.update(message='등록한 목소리를 준비합니다.',stage='preparing_reference')
        prompt=model.create_voice_clone_prompt(ref_audio=self.profile['reference_wav'],ref_text=self.profile['reference_text'],x_vector_only_mode=False)
        self.model,self.prompt=model,prompt
    def reset_models(self):
        self.prompt=None;self.model=None;self.aligner=None
        gc.collect()
        if 'torch' in sys.modules:
            import torch
            if torch.cuda.is_available():torch.cuda.empty_cache()
    def unload(self):
        with self.lock:
            if self.busy or not self.queue.empty():return False
            self.reset_models()
            return True
    def quarantine_unverified(self,j):
        """Preserve only this unverified request's outputs for recovery."""
        if not re.fullmatch(r'[0-9a-f]{64}',j['id']):raise ValueError('음성 캐시 ID 검증 실패')
        folder=(self.cache/j['id']).resolve()
        if folder.parent!=self.cache.resolve():raise ValueError('음성 캐시 경로 검증 실패')
        backup=folder/('unverified-'+str(time.time_ns()))
        backup.mkdir()
        targets=[folder/'speech.wav',folder/'result.json',*folder.glob('chunk-*.wav')]
        for path in targets:
            if path.is_file():
                if path.resolve().parent!=folder:raise ValueError('음성 캐시 파일 경로 검증 실패')
                path.replace(backup/path.name)
    def generate(self,j):
        import numpy as np,soundfile as sf,torch
        folder=self.cache/j['id'];folder.mkdir(exist_ok=True)
        chunks=split_text(j['text']);atomic_json(folder/'request.json',{'model':MODEL,'voice':self.profile['name'],'text':j['text'],'language':j['language'],'chunks':chunks})
        output=folder/'speech.wav';manifest=folder/'result.json'
        if output.is_file() and manifest.is_file():
            saved=json.loads(manifest.read_text('utf-8'));data,sr=sf.read(output,dtype='float32');self.check_audio(data,sr)
            if abs(len(data)/sr-saved['duration'])<0.01:
                if not saved.get('wordData'):
                    saved.update(self.align(j,output,saved['duration']));atomic_json(manifest,saved)
                j.update(status='done',message='저장된 로컬 음성 사용',chunks_done=len(chunks),duration=saved['duration'],path=str(output),elapsed=0,cached=True,wordData=saved['wordData']);return
        waves=[];parts=[];began=time.monotonic()
        for i,chunk in enumerate(chunks):
            if j['cancel'].is_set():raise InterruptedError()
            j.update(message=f'내 목소리로 낭독 중 · {i+1}/{len(chunks)}문단',chunks_done=i)
            part=folder/f'chunk-{i+1:04d}.wav';started=time.monotonic()
            if part.is_file():wave,sr=sf.read(part,dtype='float32');self.check_audio(wave,sr);cached=True
            else:
                self.load(j);torch.manual_seed(42+i+len(chunks)*j.get('quality_retries',0));torch.cuda.reset_peak_memory_stats()
                j.update(message=f'내 목소리로 낭독 중 · {i+1}/{len(chunks)}문단',stage='generating')
                wavs,sr=self.model.generate_voice_clone(text=chunk,language=j['language'],voice_clone_prompt=self.prompt,non_streaming_mode=True,max_new_tokens=2048)
                if j['cancel'].is_set():raise InterruptedError()
                wave=np.asarray(wavs[0],dtype=np.float32);self.check_audio(wave,sr)
                temp=part.with_suffix('.tmp.wav');sf.write(temp,wave,sr,subtype='PCM_16');temp.replace(part);cached=False
            duration=len(wave)/sr
            if duration>=165:raise ValueError('문단 음성이 끝까지 완성됐는지 확인이 필요합니다. 이 문단을 다시 생성하세요.')
            if waves:waves.append(np.zeros(round(sr*0.25),np.float32))
            waves.append(wave);parts.append({'index':i+1,'text':chunk,'duration':duration,'elapsed':round(time.monotonic()-started,3),'cached':cached});j['chunks_done']=i+1
        joined=np.concatenate(waves);self.check_audio(joined,sr)
        temp=output.with_suffix('.tmp.wav');sf.write(temp,joined,sr,subtype='PCM_16');temp.replace(output)
        result={'model':MODEL,'voice':self.profile['name'],'duration':len(joined)/sr,'sample_rate':sr,'chunks':parts,'text':j['text'],'elapsed':round(time.monotonic()-began,3),'quality_retries':j.get('quality_retries',0)}
        result.update(self.align(j,output,result['duration']))
        atomic_json(manifest,result);j.update(status='done',message='로컬 음성·자막 시간 완료',duration=result['duration'],path=str(output),elapsed=result['elapsed'],cached=False,wordData=result['wordData'])
    def align(self,j,path,duration):
        from faster_whisper import WhisperModel
        from local_voice_alignment import align_caption_words,read_wav_16k
        if j['cancel'].is_set():raise InterruptedError()
        j.update(message='실제 낭독에 맞춰 자막 시간을 계산합니다.',stage='aligning')
        began=time.monotonic()
        if self.aligner is None:self.aligner=WhisperModel(str(ROOT/'models/faster-whisper-small'),device='cpu',compute_type='int8',cpu_threads=4,num_workers=1,local_files_only=True)
        lang=next((code for code,name in LANGS.items() if name==j['language']),None)
        if lang=='auto':lang=None
        segments,_=self.aligner.transcribe(read_wav_16k(path),language=lang,word_timestamps=True,beam_size=3,initial_prompt=j['text'][:1000],condition_on_previous_text=False,vad_filter=True,vad_parameters={'min_silence_duration_ms':300,'speech_pad_ms':150})
        recognized=[]
        for seg in segments:
            if j['cancel'].is_set():raise InterruptedError()
            recognized.extend({'word':w.word,'start':w.start,'end':w.end} for w in seg.words or [])
            j['message']=f'실제 낭독에 맞춰 자막 시간 계산 · {min(duration,seg.end):.0f}/{duration:.0f}초'
        words,coverage=align_caption_words(j['caption_text'],recognized,duration)
        return {'wordData':words,'alignment_coverage':coverage,'alignment_seconds':round(time.monotonic()-began,3),'caption_text':j['caption_text'],'alignment_model':'faster-whisper-small'}
    @staticmethod
    def check_audio(data,sr):
        import numpy as np
        if sr<=0 or len(data)/sr<0.4 or not np.isfinite(data).all() or np.max(np.abs(data))<0.0003 or np.sqrt(np.mean(data*data))<0.00001:raise ValueError('생성된 음성에 읽는 소리가 없습니다. 같은 모델로 다시 시도하세요.')
    def work(self):
        while True:
            key=self.queue.get();j=self.jobs[key]
            with self.lock:self.busy=key
            try:
                if j['cancel'].is_set():raise InterruptedError()
                j['status']='running'
                def check():
                    if j['cancel'].is_set():raise InterruptedError()
                with FileLock(ROOT.parent/'gpu.lock',check):
                    memory_retries=0;quality_retries=0
                    while True:
                        try:self.generate(j);break
                        except Exception as error:
                            if isinstance(error,CaptionAlignmentError):
                                if quality_retries>=2:raise
                                quality_retries+=1
                                self.quarantine_unverified(j)
                                j.update(status='running',stage='recovering_speech',quality_retries=quality_retries,message='이 문장의 낭독·자막 일치를 확인해 같은 목소리로 다시 읽습니다. · '+str(quality_retries)+'/2')
                                print(time.strftime('%Y-%m-%d %H:%M:%S')+' speech quality recovery '+str(quality_retries),flush=True)
                                check();continue
                            if not memory_failure(error) or memory_retries>=2:raise
                            memory_retries+=1
                            print(time.strftime('%Y-%m-%d %H:%M:%S')+' memory recovery '+str(memory_retries)+' '+type(error).__name__,flush=True)
                            error.__traceback__=None
                            self.reset_models()
                            j.update(status='running',stage='recovering_memory',recovery_attempts=memory_retries,message='음성 모델 메모리를 정리하고 같은 목소리로 다시 준비합니다. · '+str(memory_retries)+'/2')
                            check();time.sleep(2)
            except InterruptedError:j.update(status='cancelled',message='음성을 중지했습니다. 완료된 문단은 보관했습니다.')
            except Exception as e:
                if isinstance(e,CaptionAlignmentError):message='같은 문장을 다시 읽었지만 낭독·자막 일치를 확인하지 못했습니다. 완료된 다른 문장과 등록한 목소리는 유지됩니다.'
                elif isinstance(e,MemoryError):message='음성 실행 중 PC 메모리를 확보하지 못했습니다. 다른 제작을 종료한 후 같은 목소리로 다시 시도하세요.'
                elif getattr(e,'winerror',None)==1455 or '1455' in str(e):message='Windows가 음성 모델의 가상 메모리를 확보하지 못했습니다. 자동 복구를 시도했지만 부족합니다. 다른 메모리 사용 작업을 종료한 후 다시 시도하세요. 등록한 목소리는 유지됩니다.'
                elif 'out of memory' in str(e).lower():message='GPU 메모리를 정리해 다시 시도했지만 부족합니다. 이미지 생성 완료 후 다시 시도하세요.'
                else:message='로컬 음성을 완성하지 못했습니다. 같은 모델로 다시 생성할 수 있습니다.'
                j.update(status='error',message=message,error=message,error_type=type(e).__name__)
                print(time.strftime('%Y-%m-%d %H:%M:%S')+' '+type(e).__name__+': '+str(e)[:400],flush=True)
            finally:
                with self.lock:self.busy=None;self.last_used=time.monotonic()
                self.queue.task_done()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--parent',type=int,required=True);parser.add_argument('--port',type=int,default=5930);args=parser.parse_args()
    prepare_runtime_cache()
    token=(ROOT/'service_token.txt').read_text('utf-8').strip();runtime=Runtime(args.parent)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,obj,status=200):
            data=json.dumps(obj,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def handle_request(self):
            if not secrets.compare_digest(self.headers.get('X-Dino-Voice',''),token):return self.send({'ok':False},403)
            try:
                if self.command=='GET' and self.path=='/health':return self.send({'ok':True,'service':'dino-qwen-direct-v1','runtime_version':RUNTIME_VERSION,'root':str(ROOT),'pid':os.getpid(),'parent':args.parent,'model':MODEL,'busy':bool(runtime.busy),'loaded':runtime.model is not None,'weight_loading':runtime.weight_loading})
                if self.command=='GET' and self.path.startswith('/job/'):
                    key=self.path.removeprefix('/job/');j=runtime.jobs.get(key)
                    if not j:return self.send({'ok':False,'error':'음성 작업을 찾지 못했습니다.'},404)
                    result=runtime.public(j)
                    if j['status']=='done':result['audioContent']=base64.b64encode(pathlib.Path(j['path']).read_bytes()).decode()
                    return self.send({'ok':True,'job':result})
                size=int(self.headers.get('Content-Length','0'))
                if size>400000:return self.send({'ok':False},413)
                data=json.loads(self.rfile.read(size) or b'{}')
                if self.command=='POST' and self.path=='/generate':return self.send({'ok':True,'job':runtime.submit(data.get('text'),data.get('language','ko'),data.get('caption_text'))})
                if self.command=='POST' and self.path=='/cancel':
                    for key in data.get('ids',[]):
                        if key in runtime.jobs:runtime.jobs[key]['cancel'].set()
                    return self.send({'ok':True})
                if self.command=='POST' and self.path=='/reload-profile':
                    with runtime.lock:
                        if runtime.busy or not runtime.queue.empty():raise ValueError('음성 제작 완료 후 변경하세요.')
                        runtime.unload();runtime.profile=json.loads((ROOT/'voice_profile.json').read_text('utf-8'))
                    return self.send({'ok':True})
                if self.command=='POST' and self.path=='/unload':return self.send({'ok':True,'unloaded':runtime.unload()})
                return self.send({'ok':False},404)
            except ValueError as e:return self.send({'ok':False,'error':str(e)},400)
        do_GET=handle_request;do_POST=handle_request
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    def monitor():
        import psutil
        while psutil.pid_exists(args.parent):
            if time.monotonic()-runtime.last_used>30:runtime.unload()
            time.sleep(2)
        for j in runtime.jobs.values():j['cancel'].set()
        server.shutdown();os._exit(0)
    threading.Thread(target=monitor,daemon=True).start()
    print(time.strftime('%Y-%m-%d %H:%M:%S')+' DINO Qwen local voice ready '+RUNTIME_VERSION,flush=True);server.serve_forever()
if __name__=='__main__':main()
