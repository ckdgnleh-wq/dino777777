"""Single production version per run. Original production archives are preserved."""
from pathlib import Path
import ctypes,hashlib,json,os,re,secrets,subprocess,sys,threading,time,webbrowser
import urllib.request,urllib.error
API_SHA='2493d8adb9b9a988e4b068d60c3958a4a2bb1acbf58b26e9f0ee0a37cc712f7f'

def prepare_local_runtime_paths(base):
    try:
        helper=Path(base)/'R3_변경소스/local_runtime_paths.py'
        namespace={'__file__':str(helper),'__name__':'_dino_local_runtime_paths'}
        exec(compile(helper.read_text('utf-8'),str(helper),'exec'),namespace)
        result=namespace['repair'](base)
    except Exception as error:
        result={'error':type(error).__name__,'message':str(error)}
    directory=Path(base)/'logs';directory.mkdir(exist_ok=True)
    with (directory/'로컬경로_확인.log').open('a',encoding='utf-8') as log:
        log.write(time.strftime('%Y-%m-%d %H:%M:%S')+' '+json.dumps(result,ensure_ascii=False)+'\n')

def whale_executable():
    paths=[]
    for variable in ('LOCALAPPDATA','ProgramFiles','ProgramFiles(x86)'):
        location=os.environ.get(variable)
        if location:
            paths.extend(Path(location)/folder/'Application/whale.exe' for folder in ('Naver/Naver Whale','Naver Whale'))
    return next((p for p in paths if p.is_file()),None)

def prefer_extension_browser():
    path=whale_executable()
    if path:webbrowser.register('dino-whale',None,webbrowser.BackgroundBrowser(str(path)),preferred=True)
    return path

def install_ready_browser(base, family):
    """Defer DINO's window until the hub and both selected engines are ready.

    The legacy hub opens its browser before app.run. A synchronous wait there
    would prevent the hub from starting, so this wait belongs in a thread.
    """
    from urllib.parse import urlsplit
    if getattr(webbrowser,'_dino_ready_installed',False):return
    original=webbrowser.open
    pending={'value':False};guard=threading.Lock();base=Path(base)
    def deferred(url,new=0,autoraise=True):
        parts=urlsplit(url)
        if parts.hostname in ('127.0.0.1','localhost') and parts.port==5910 and os.environ.get('DINO_NO_BROWSER')=='1':
            return True
        if parts.hostname not in ('127.0.0.1','localhost') or parts.port!=5910:
            return original(url,new=new,autoraise=autoraise)
        with guard:
            if pending['value']:return True
            pending['value']=True
        def open_when_ready():
            try:
                deadline=time.monotonic()+75
                while time.monotonic()<deadline:
                    try:
                        with urllib.request.urlopen('http://127.0.0.1:5910/api/v10/selection',timeout=2) as response:
                            state=json.load(response)
                        if not state.get('ok') or state.get('family')!=family:raise ValueError('edition starting')
                        endpoint='/api/r5/bootstrap' if family=='api' else '/api/r3/bootstrap'
                        for port in (5911,5912):
                            with urllib.request.urlopen('http://127.0.0.1:'+str(port)+endpoint,timeout=2) as response:
                                if not json.load(response).get('ok'):raise ValueError('engine starting')
                        target='http://127.0.0.1:5910/?mode='+('shorts' if state.get('mode')=='shorts' else 'longform')+'&_startup='+str(time.time_ns())
                        opened=original(target,new=new,autoraise=autoraise)
                        if not opened:os.startfile(target)
                        outcome='ready_window_opened family='+family
                        break
                    except (OSError,ValueError,urllib.error.URLError):time.sleep(.4)
                else:outcome='ready_window_timeout family='+family
                directory=base/'logs';directory.mkdir(exist_ok=True)
                with (directory/'실행창_복구.log').open('a',encoding='utf-8') as log:
                    log.write(time.strftime('%Y-%m-%d %H:%M:%S')+' '+outcome+'\n')
            finally:
                with guard:pending['value']=False
        threading.Thread(target=open_when_ready,name='DINO-ready-browser',daemon=True).start()
        return True
    webbrowser.open=deferred;webbrowser._dino_ready_installed=True

def ensure_status_console(base):
    if os.name!='nt' or os.environ.get('DINO_CONSOLE_HOSTED')=='1':return False
    base=Path(base);script=base/'DINO_실행상태.cmd'
    if not script.is_file():return False
    marker=base/'logs/실행콘솔.json'
    try:
        pid=int(json.loads(marker.read_text('utf-8-sig'))['pid'])
        if process_running(pid):return True
    except (OSError,ValueError,KeyError,TypeError):pass
    env=child_environment();env['DINO_CONSOLE_HOSTED']='1'
    # cmd.exe parses its own command string; list2cmdline's escaped inner
    # quotes do not protect a batch path containing spaces and parentheses.
    command='"'+os.environ.get('COMSPEC','cmd.exe')+'" /d /s /c ""'+str(script)+'""'
    subprocess.Popen(command,cwd=str(base),env=env,
                     creationflags=subprocess.CREATE_NEW_CONSOLE|subprocess.CREATE_NEW_PROCESS_GROUP)
    return True

def process_running(pid):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32];kernel.OpenProcess.restype=ctypes.c_void_p
    handle=kernel.OpenProcess(0x1000,False,pid)
    if not handle:return False
    try:
        code=ctypes.c_uint32()
        return bool(kernel.GetExitCodeProcess(ctypes.c_void_p(handle),ctypes.byref(code))) and code.value==259
    finally:kernel.CloseHandle(ctypes.c_void_p(handle))

def fresh_idle_workspace(state):
    # A repeated launch can discard an inactive editor selection, while a real
    # generation or render stays protected by the engine's workspace gate.
    if state.get('family')!='api':return False
    port=5912 if state.get('mode')=='shorts' else 5911
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/r5/bootstrap',timeout=3) as response:boot=json.loads(response.read())
        req=urllib.request.Request(f'http://127.0.0.1:{port}/api/r5/workspace',method='POST',data=b'{"action":"new_if_idle"}',
                                   headers={'Content-Type':'application/json','X-Dino-R5-Session':boot['token']})
        with urllib.request.urlopen(req,timeout=8) as response:return json.loads(response.read()).get('ok') is True
    except (OSError,ValueError,KeyError):return False

def reopen_existing_window(base,wait_seconds=0):
    """Repeated launches bring back the running editor without restarting jobs."""
    if os.environ.get('DINO_NO_BROWSER')=='1':return False
    deadline=time.monotonic()+wait_seconds
    while True:
        try:
            with urllib.request.urlopen('http://127.0.0.1:5910/api/v10/selection',timeout=1) as response:
                state=json.loads(response.read())
            ready=(state.get('ok') is True and state.get('exclusive') is True
                   and state.get('family') in ('api','v10'))
        except (OSError,ValueError,AttributeError):ready=False
        if ready:
            fresh_idle_workspace(state)
            prefer_extension_browser()
            url='http://127.0.0.1:5910/'
            if not webbrowser.open(url,new=2):os.startfile(url)
            try:
                folder=Path(base)/'logs';folder.mkdir(exist_ok=True)
                with (folder/'실행창_복구.log').open('a',encoding='utf-8') as log:
                    log.write(time.strftime('%Y-%m-%d %H:%M:%S')+' existing_window_reopened\n')
            except OSError:pass
            return True
        if time.monotonic()>=deadline:return False
        time.sleep(.25)

def child_environment():
    env={k:v for k,v in os.environ.items() if not k.upper().startswith('_PYI_') and k.upper() not in
         {'_MEIPASS2','PYTHONHOME','PYTHONPATH','TCL_LIBRARY','TK_LIBRARY','DINO_COMPONENT_DIR','DINO_PORT',
          'DINO_EXCLUSIVE_API','DINO_MANAGER_ROOT','DINO_MANAGER_PID'}}
    env['PYINSTALLER_RESET_ENVIRONMENT']='1'
    runtime=str(getattr(sys,'_MEIPASS','') or '')
    if runtime:env['PATH']=os.pathsep.join(p for p in env.get('PATH','').split(os.pathsep) if not p.casefold().startswith(runtime.casefold()))
    return env

def spawn_independent(args,folder,env):
    runtime=str(getattr(sys,'_MEIPASS','') or '')
    ctypes.windll.kernel32.SetDllDirectoryW(None)
    try:return subprocess.Popen(args,cwd=str(folder),env=env,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP,
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=True)
    finally:
        if runtime:ctypes.windll.kernel32.SetDllDirectoryW(runtime)

def run_exclusive_api_if_selected(base):
    base=Path(base).resolve()
    prepare_local_runtime_paths(base)
    ensure_status_console(base)
    prefer_extension_browser()
    if reopen_existing_window(base):raise SystemExit(0)
    try:family=json.loads((base/'사용버전.json').read_text(encoding='utf-8')).get('family')
    except (OSError,ValueError):family='v10'
    if family!='api':
        install_ready_browser(base,'v10')
        webbrowser.open('http://127.0.0.1:5910/',new=2)
        return
    # This guard belongs to the launcher; the original R5 owns its own port mutex.
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_wchar_p]
    kernel.CreateMutexW.restype=ctypes.c_void_p
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    mutex=kernel.CreateMutexW(None,False,'Local\\DINO_V10_API_LAUNCHER')
    if not mutex:raise OSError('R5 API 실행 보호를 시작하지 못했습니다.')
    if ctypes.get_last_error()==183:
        kernel.CloseHandle(mutex)
        if reopen_existing_window(base,wait_seconds=15):raise SystemExit(0)
        raise RuntimeError('DINO 실행 화면을 열지 못했습니다. 오류확인_실행.cmd로 실행 상태를 확인하세요.')
    original=base/'연결보조/R5_API/DINO_API.exe'
    executable=base/'연결보조/R5_API/DINO_API.exe'
    expected=json.loads((executable.parent/'연결정보.json').read_text(encoding='utf-8'))['adapter_sha256']
    if hashlib.sha256(original.read_bytes()).hexdigest()!=API_SHA or hashlib.sha256(executable.read_bytes()).hexdigest()!=expected:
        raise RuntimeError('R5 API 원본과 연결 파일을 확인하세요.')
    env=child_environment()
    env.update(DINO_HUB_PORT='5910',DINO_LONGFORM_PORT='5911',DINO_SHORTS_PORT='5912',DINO_EXCLUSIVE_API='1',
               DINO_MANAGER_ROOT=str(base),DINO_MANAGER_PID=str(os.getpid()))
    try:
        child=spawn_independent([str(executable)],executable.parent,env)
        raise SystemExit(child.wait())
    finally:kernel.CloseHandle(mutex)

def remove_duplicate_subscription_poll(html):
    """Keep engine authentication; retire only the redundant hub badge query."""
    html = re.sub(
        r'async function updateSubscriptionBadge\(\)\{\r?\n.*?\r?\n\}',
        'async function updateSubscriptionBadge(){}', html, count=1, flags=re.S)
    return html.replace('setInterval(updateSubscriptionBadge,60000);', '')


def allow_local_microphone_frames(html):
    """Delegate microphone only to the two local production frames, never camera."""
    def update(match):
        tag=match.group(0)
        if not re.search(r'\bid\s*=\s*[\"\']frame-(?:longform|shorts)[\"\']',tag,re.I):return tag
        allow=re.search(r'\ballow\s*=\s*([\"\'])(.*?)\1',tag,re.I|re.S)
        entry="microphone 'self' http://127.0.0.1:5911 http://127.0.0.1:5912 http://localhost:5911 http://localhost:5912"
        if allow:
            values=[value.strip() for value in allow.group(2).split(';') if value.strip() and value.strip().split()[0].lower()!='microphone']
            return tag[:allow.start()]+('allow="'+'; '.join([*values,entry]).replace('"','&quot;')+'"')+tag[allow.end():]
        return tag[:-1]+' allow="'+entry+'">'
    return re.sub(r'<iframe\b[^>]*>',update,html,flags=re.I)

def install_selector(app,ns,api_only=False):
    from flask import request,jsonify
    base=Path(os.environ['DINO_MANAGER_ROOT'] if api_only else ns['APP_DIR']).resolve()
    prepare_local_runtime_paths(base)
    prefer_extension_browser()
    family='api' if api_only else 'v10'
    install_ready_browser(base,family)
    try:saved_mode=json.loads((base/'사용버전.json').read_text(encoding='utf-8-sig')).get('mode')
    except (OSError,ValueError):saved_mode='longform'
    selected={'family':family,'mode':'shorts' if saved_mode=='shorts' else 'longform'}
    token=secrets.token_urlsafe(32);lock=threading.RLock();owners={};restart={'started':False}
    client=(base/'R3_변경소스/exclusive_selector_client.html').read_text(encoding='utf-8')
    ns['HTML']=allow_local_microphone_frames(remove_duplicate_subscription_poll(ns['HTML'])).replace('</body>',client.replace('__SELECTOR_TOKEN__',token).replace('__API_ONLY__','true' if api_only else 'false')+'</body>')
    @app.after_request
    def no_cached_selector(response):
        if request.path=='/' or request.path.startswith('/api/v10/'):
            response.headers['Cache-Control']='no-store, max-age=0'
        return response
    def target(value):
        if not isinstance(value,dict) or value.get('family')!=family or value.get('mode') not in ('longform','shorts'):
            raise ValueError('현재 실행 중인 버전의 작업만 수신합니다.')
        return {'family':family,'mode':value['mode']}
    def local_json(port,path,method='GET',body=None,timeout=8):
        req=urllib.request.Request(f'http://127.0.0.1:{port}{path}',data=None if body is None else json.dumps(body,ensure_ascii=False).encode(),
                                   method=method,headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=timeout) as response:return json.loads(response.read()),response.status
        except urllib.error.HTTPError as error:
            try:payload=json.loads(error.read())
            except Exception:payload={'ok':False,'error':f'HTTP {error.code}'}
            return payload,error.code
    def allowed():
        return (secrets.compare_digest(request.headers.get('X-DINO-Selector',''),token) and request.headers.get('Origin') in
                (None,'http://127.0.0.1:5910','http://localhost:5910'))
    def chosen():
        try:return json.loads((base/'사용버전.json').read_text(encoding='utf-8')).get('family')==family
        except (OSError,ValueError):return False
    def license_summary():
        with lock:port=5912 if selected['mode']=='shorts' else 5911
        result,code=local_json(port,'/api/license_status',timeout=150)
        info=result.get('data') or {}
        return {**{key:info.get(key) for key in ('days_left','expires_at_text','admin_review','unlimited')},
                'valid':code==200 and info.get('valid') is True,
                  'connection_pending':code==503 and result.get('code')=='license_connection_pending'}

    @app.route('/api/v10/license',methods=['GET'])
    def selection_license():
        try:return jsonify(ok=True,data=license_summary(),version_chosen=chosen())
        except Exception:return jsonify(ok=False,data={'valid':False},error='구독 인증을 확인하지 못했습니다.'),503

    @app.route('/api/v10/selection',methods=['GET','POST'])
    def selection():
        if request.method=='POST':
            if not allowed():return jsonify(ok=False,error='현재 화면에서 다시 선택하세요.'),403
            try:
                value=target(request.get_json(silent=True))
                with lock:selected.update(value)
            except ValueError as error:return jsonify(ok=False,error=str(error)),409
        with lock:return jsonify(ok=True,**selected,exclusive=True,version_chosen=chosen())

    @app.route('/api/v10/version',methods=['POST'])
    def change_version():
        if not allowed():return jsonify(ok=False,error='현재 화면에서 다시 선택하세요.'),403
        desired=(request.get_json(silent=True) or {}).get('family')
        if desired not in ('v10','api'):return jsonify(ok=False,error='사용할 버전을 선택하세요.'),400
        try:
            if not license_summary()['valid']:
                return jsonify(ok=False,error='구독 인증을 먼저 완료하세요.'),403
            if desired==family:
                with lock:
                    temporary=base/'사용버전.tmp'
                    temporary.write_text(json.dumps({'family':family,'mode':selected['mode'],'exclusive':True},ensure_ascii=False),encoding='utf-8')
                    os.replace(temporary,base/'사용버전.json')
                return jsonify(ok=True,restarting=False)
            for port in (5911,5912):
                if api_only:
                    boot,code=local_json(port,'/api/r5/bootstrap')
                    if boot.get('active_id'):
                        job,code=local_json(port,'/api/r5/job/'+boot['active_id']);active=job.get('job',{})
                        if active.get('status')=='running' or active.get('render_state')=='running':
                            return jsonify(ok=False,error='진행 중인 작업을 중지한 뒤 버전을 선택하세요.'),409
                else:
                    info,code=local_json(port,'/api/v7/status')
                    if (info.get('data') or info).get('running'):
                        return jsonify(ok=False,error='진행 중인 작업을 중지한 뒤 버전을 선택하세요.'),409
            with lock:
                if restart['started']:return jsonify(ok=True,restarting=True)
                selection_file=base/'사용버전.json';previous=selection_file.read_bytes() if selection_file.exists() else None
                temporary=base/'사용버전.tmp'
                temporary.write_text(json.dumps({'family':desired,'mode':selected['mode'],'exclusive':True},ensure_ascii=False),encoding='utf-8');os.replace(temporary,selection_file)
                try:
                    worker_id=int(os.environ['DINO_MANAGER_PID']) if api_only else os.getpid()
                    powershell=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
                    args=[str(powershell),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(base/'완전초기화_도우미.ps1'),
                          '-Executable',str(base/'DINO.exe'),'-WorkerId',str(worker_id)]
                    spawn_independent(args,base,child_environment())
                except Exception:
                    if previous is None:selection_file.unlink(missing_ok=True)
                    else:selection_file.write_bytes(previous)
                    raise
                restart['started']=True
            return jsonify(ok=True,restarting=True)
        except Exception:return jsonify(ok=False,error='버전 재시작을 준비하지 못했습니다. 실행 파일을 확인하세요.'),503

    @app.route('/api/v10/bridge',methods=['POST'])
    def bridge():
        data=request.get_json(silent=True) or {};path=data.get('path','');method=data.get('method','GET');body=data.get('body')
        if not isinstance(path,str) or not path.startswith('/api/v7/') or '\\' in path or '#' in path or '..' in path or method not in ('GET','POST'):
            return jsonify(ok=False,error='지원하지 않는 확장 요청입니다.'),400
        origin=request.headers.get('Origin','')
        if origin and not (origin.startswith('chrome-extension://') or origin.startswith('moz-extension://') or origin in
                           ('http://127.0.0.1:5910','http://localhost:5910')):return jsonify(ok=False,error='확장 연결을 확인하세요.'),403
        if body is not None and not isinstance(body,dict):return jsonify(ok=False,error='전송 형식 오류'),400
        owner=(str((body or {}).get('driver_id','')),str((body or {}).get('job_id','')))
        try:
            with lock:destination=target(owners.get(owner) or data.get('target') or (body or {}).get('_dino_target') or dict(selected))
            result,code=local_json(5912 if destination['mode']=='shorts' else 5911,path,method,body,timeout=85)
            if isinstance(result,dict) and isinstance(result.get('job'),dict):
                from urllib.parse import parse_qs,urlsplit
                job=result['job'];job['_dino_target']=destination
                driver=parse_qs(urlsplit(path).query).get('driver_id',[''])[0]
                if driver and job.get('id'):
                    with lock:owners[(driver,str(job['id']))]=destination
            return jsonify(result),code
        except (ValueError,OSError,urllib.error.URLError):return jsonify(ok=False,error='현재 버전과 확장 작업의 연결을 확인하세요.'),409
