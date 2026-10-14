(()=>{
'use strict';const W=window,E=id=>document.getElementById(id),wait=ms=>new Promise(r=>setTimeout(r,ms));let token='',modelsKnown=false;const models=W.DinoLocalModels={};
const V=W.DinoLocalVoice={ready:false,provider:'inworld',voice:'',revision:'',active:new Set(),isLocal:()=>V.ready&&V.provider==='qwen'};
async function apiOnce(path,data){const opts={headers:{'Content-Type':'application/json','X-Dino-Local-Session':token}};if(data!==undefined){opts.method='POST';opts.body=JSON.stringify(data)}const r=await fetch('/api/local-v12/'+path,opts),d=await r.json();if(!r.ok||!d.ok){const error=Error(d.error||'로컬 기능 연결을 확인하세요.');error.retryable=r.status>=500||(r.status===409&&/timed out|WinError 10061/i.test(error.message));throw error}return d}
async function api(path,data){const polling=data===undefined&&path.startsWith('voice/job/'),deadline=Date.now()+30000;for(let attempt=0;;attempt++){try{return await apiOnce(path,data)}catch(error){const temporary=error instanceof TypeError||error.retryable;if(!polling||!temporary)throw error;if(attempt>=3||Date.now()>=deadline)throw Error('로컬 음성 서버 연결이 끊겼습니다. 등록한 목소리는 유지됩니다. 같은 모델로 다시 생성해 주세요.');W.phLog?.(5,'음성 진행 상태 연결을 다시 확인합니다.','#00d9ff');await wait(1000*(attempt+1))}}}
V.call=(path,data)=>api('voice/'+path,data);
async function speak(text){const spoken=typeof W.ttsReadingFix==='function'?W.ttsReadingFix(text):text;let {job}=await api('voice/generate',{text:spoken,caption_text:text,language:W.DINO_R5?.job?.language||W.DINO_R3?.options?.resolved||'ko'});V.active.add(job.id);const began=Date.now();let last='';try{while(['queued','running'].includes(job.status)){if(W.ttsCancelled||W.autoStop){await api('voice/cancel',{ids:[job.id]});throw Error('로컬 음성을 중지했습니다.')}if(Date.now()-began>7200000){await api('voice/cancel',{ids:[job.id]});throw Error('로컬 음성 생성 시간이 초과되었습니다.');}if(last!==job.message){W.phLog?.(5,job.message,'#00d9ff');last=job.message}await wait(700);job=(await api('voice/job/'+job.id)).job}if(job.status!=='done')throw Error(job.error||job.message);if(!job.audioContent)job=(await api('voice/job/'+job.id)).job;const raw=atob(job.audioContent),bytes=Uint8Array.from(raw,c=>c.charCodeAt(0)),blob=new Blob([bytes],{type:'audio/wav'}),duration=typeof W.dino75CheckSpeech==='function'?await W.dino75CheckSpeech(blob):await W.getExactDur(blob);if(Math.abs(duration-job.duration)>.1||!job.wordData?.length)throw Error('로컬 음성·자막 시간을 확인하지 못했습니다.');return {blob,duration,wordData:job.wordData,provider:'qwen',voice:V.voice,model:'Qwen3-TTS-12Hz-0.6B-Base'}}finally{V.active.delete(job.id)}}
function scrubPublicNames(){const pattern=/(?:openai\/)?gpt[- ]?6[- ]?luna|DeepSeek\s*V?4\.?1\s*Flash|deepseek(?:\/deepseek)?[- ]v4[- .]1[- ]flash|Z[- ]Image\s*Turbo|GPT Image 2|Qwen3?[- ]TTS(?: Base)?|FLUX\.2 klein 4B/gi;for(const id of ['r5-log','r5-status','r5-work-text-summary','r5-writer-note','r5-model-note','v75-source-help']){const host=E(id);if(!host)continue;const walker=document.createTreeWalker(host,NodeFilter.SHOW_TEXT);let n;while((n=walker.nextNode())){const next=n.textContent.replace(pattern,'설정한 모델');if(next!==n.textContent)n.textContent=next}}}
// Remove the manual clipboard action. Keep an inert status anchor for the legacy updater.
function removeCodexCopyAction(){
  const control=E('r13-codex-copy');
  if(!control||control.tagName!=='BUTTON')return;
  const anchor=document.createElement('span');
  anchor.id=control.id;anchor.hidden=true;anchor.setAttribute('aria-hidden','true');
  control.replaceWith(anchor);
}
function mount(){scrubPublicNames();E('dino-local-install-button')?.remove();mountVoicePicker();mountSetupLayout();tidyPendingRequests();
const settings=E('dino-settings-content');
if(settings&&!E('dino-local-settings')){
  const section=document.createElement('details');section.id='dino-local-settings';section.style.cssText='margin:16px 0;padding:16px;border:1px solid #29c9b4;border-radius:12px;background:#10272a;color:#e7f9f6';
  const heading=document.createElement('summary');heading.textContent='내 PC 설치·목소리';heading.style.cssText='cursor:pointer;font-weight:bold;font-size:16px';
  const hint=document.createElement('p');hint.textContent='모델 설치, 내 목소리 등록·선택은 여기에서 관리합니다. 한 번 등록한 목소리와 설치된 모델은 재실행해도 유지됩니다.';hint.style.cssText='font-size:13px;line-height:1.6';
  const frame=document.createElement('iframe');frame.id='dino-local-settings-frame';frame.title='내 PC 모델 설치와 내 목소리 설정';frame.setAttribute('allow','microphone');frame.style.cssText='display:block;width:100%;height:850px;border:0;background:#0f1525;border-radius:8px';
  section.append(heading,hint,frame);section.addEventListener('toggle',()=>{if(section.open&&!frame.getAttribute('src'))frame.src='/dino-local'});
  settings.appendChild(section);
}
const select=E('r5-image_model');if(select){
  select.classList.remove('r5-hidden');select.style.display='block';
  const state=W.DINO_R5||{},busy=!!(state.busy||state.starting||state.finishing||state.queueActive);
  for(const opt of select.options)if(opt.value.startsWith('local:')){
    const installed=models[opt.value]===true,status=installed?'설치 완료':modelsKnown?'미설치':'설치 확인 중';
    const name=opt.value.includes('flux')?'FLUX.2 klein 4B':'Z-Image Turbo',label='내 PC · '+name+' · '+status;
    if(opt.textContent!==label)opt.textContent=label;opt.disabled=!installed;
    opt.title=installed?'내 PC에서 생성합니다.':'설정 → 내 PC 설치·목소리에서 설치하세요.';
    const source=E('r5-image-provider')?.querySelector('option[value="'+opt.value+'"]');
    if(source){const sourceLabel='로컬 · '+name+' · '+status;if(source.textContent!==sourceLabel)source.textContent=sourceLabel;source.disabled=!installed;source.title=opt.title;}
    const card=document.querySelector('[data-image-model="'+opt.value+'"]');
    if(card){card.disabled=busy||!installed;const badge=card.querySelector('.r5-model-provider'),text='내 PC · '+status;if(badge&&badge.textContent!==text)badge.textContent=text;}
  }
  const localChoice=select.value.startsWith('local:'),installed=models[select.value]===true;
  const hint=E('r5-model-selection-status'),text=localChoice?(installed?'설치 완료 · 이미지 API 요금 없이 내 PC에서 생성합니다.':modelsKnown?'미설치 · 설정 → 내 PC 설치·목소리에서 설치한 후 선택하세요.':'내 PC 모델 설치 상태를 확인하고 있습니다.'):select.value.startsWith('codex:')?'Codex PC앱 · 이미지 요청과 결과를 연결합니다.':'API · '+(select.value.startsWith('kie:')?'KIE':'OpenRouter')+' 연결을 사용합니다.';
  if(hint&&hint.textContent!==text)hint.textContent=text;
  const thumbs=E('r5-thumbnail_provider');if(thumbs){
    let local=thumbs.querySelector('[value=local]');if(!local){local=new Option('내 PC · 설치 확인 중','local');thumbs.add(local);}
    const key=localChoice?select.value:'local:z-image-turbo-fp8',ready=models[key]===true;
    const label='내 PC · '+(key.includes('flux')?'FLUX.2 klein 4B':'Z-Image Turbo')+' · '+(ready?'설치 완료':modelsKnown?'미설치':'설치 확인 중');
    if(local.textContent!==label)local.textContent=label;local.disabled=!ready;
  }
}
if(E('r5-text-menu')){const heading=E('r5-text-menu').querySelector('label:has(#r5-thumbnail_provider)');if(heading?.firstChild?.nodeType===3&&heading.firstChild.textContent!=='썸네일 생성 방식 ')heading.firstChild.textContent='썸네일 생성 방식 '}
}
async function refreshModels(){const d=await api('status');for(const [feature,key] of [['flux','local:flux-2-klein-4b-fp8'],['zimage','local:z-image-turbo-fp8'],['qwen','qwen']])models[key]=d.features?.[feature]?.installed===true;modelsKnown=true;mount()}
async function init(){const boot=await api('bootstrap');token=boot.token;await refreshModels();V.provider=boot.settings.provider;V.voice=boot.settings.voice;V.revision=boot.settings.voice_revision||'';for(let i=0;i<400&&(typeof W.ttsOneCall!=='function'||(W.DINO_R5&&!W.DINO_R5.ready));i++)await wait(100);if(typeof W.ttsOneCall!=='function')return;const oldTts=W.ttsOneCall,oldVid=W.getVID,oldRun=W.runTTSFull;W.ttsOneCall=async function(text,...args){if(!V.isLocal())return oldTts.call(this,text,...args);try{return await speak(text)}catch(e){if(W.dino75Speech?.errors&&W.dino75SpeechText)W.dino75Speech.errors.set(W.dino75SpeechText(text),e.message);throw e}};if(oldVid)W.getVID=function(){return V.isLocal()?'local:voice:'+V.voice+':'+V.revision:oldVid.apply(this,arguments)};if(oldRun)W.runTTSFull=async function(){try{return await oldRun.apply(this,arguments)}finally{if(V.isLocal())await api('voice/unload',{}).catch(()=>{})}};V.ready=true}
let voiceReferenceReady=false,voiceSaving=false;
function mountSetupLayout(){
 if(!W.DINO_R5?.ready||!E('r5-work')||E('dino-production-layout'))return;
 const workspace=E('dino-main-workspace'),writer=E('v75-writer');if(!workspace||!writer)return;
 const style=document.createElement('style');style.textContent=`
 #dino-production-layout{display:grid;grid-template-columns:minmax(360px,440px) minmax(0,1fr);gap:20px;align-items:start;margin:16px 0}
 #dino-setup-panel{position:sticky;top:120px;max-height:calc(100vh - 140px);overflow:auto;background:#111b29;border:1px solid #53667d;border-radius:14px;padding:0 16px 16px;scrollbar-gutter:stable}
 #dino-setup-heading{position:sticky;top:0;z-index:5;background:#111b29;padding:16px 0 12px;border-bottom:1px solid #3c4b5e;margin-bottom:14px}
 #dino-setup-heading h2,#dino-results-panel h2{font-size:20px;margin:0 0 6px;color:#f2f7ff}
 #dino-setup-heading p{font-size:13px;color:#b9c6d8;margin:0 0 10px}#dino-setup-heading nav{display:flex;gap:7px;flex-wrap:wrap}#dino-setup-heading a{background:#26354a;color:#dce9fa;padding:7px 10px;border-radius:7px;font-size:13px;text-decoration:none}
 #dino-setup-panel .r5-card,#dino-setup-panel .v75-box{padding:12px;margin:12px 0;min-width:0}#dino-setup-panel .r5-grid{grid-template-columns:1fr!important}#dino-setup-panel input:not([type=checkbox]),#dino-setup-panel select,#dino-setup-panel textarea{font-size:14px;max-width:100%;box-sizing:border-box}#dino-setup-panel h3{font-size:17px}
 #dino-setup-panel #r5-actions{position:sticky;bottom:-16px;z-index:4;background:#111b29;padding:14px 0;border-top:1px solid #3c4b5e;display:grid;grid-template-columns:1fr 1fr}#dino-setup-panel #r5-actions button:first-child{grid-column:1 / -1;font-size:17px;padding:14px}
 #dino-results-panel{min-width:0}#dino-results-panel .dino-result-card{background:#111b29;border:1px solid #3e4f64;border-radius:12px;padding:16px;margin:0 0 16px}#dino-results-panel #r5-progress{width:100%;margin:12px 0}#dino-results-panel textarea{width:100%;box-sizing:border-box}#dino-results-panel #phases{margin-top:18px}
 #dino-setup-panel #r5-image-picker{border-top:1px solid #425267;padding-top:14px}#dino-setup-panel #r5-settings h3{font-size:17px}#dino-setup-panel #r5-reference-panel{scroll-margin-top:100px}
 #step-btns{display:grid!important;grid-template-columns:repeat(6,minmax(0,1fr))!important;gap:4px!important}#step-btns button{padding:6px 3px!important;font-size:11px!important;min-height:35px!important}#sticky-progress-bar{padding:9px!important}#auto-go{display:none!important}
 @media(max-width:1050px){#dino-production-layout{grid-template-columns:1fr}#dino-setup-panel{position:static;max-height:none;overflow:visible}#dino-setup-heading{position:static}#dino-setup-panel #r5-actions{bottom:0}#dino-setup-panel .r5-grid{grid-template-columns:repeat(auto-fit,minmax(240px,1fr))!important}#sticky-progress-bar{position:static!important}}
 `;document.head.append(style);
 const layout=document.createElement('section');layout.id='dino-production-layout';
 const aside=document.createElement('aside');aside.id='dino-setup-panel';aside.setAttribute('aria-label','제작 설정 모음');
 aside.innerHTML='<div id="dino-setup-heading"><h2>제작 설정 · 여기서 한 번에</h2><p>주제부터 음성·영상까지 아래 순서대로 준비하세요.</p><nav aria-label="설정 위치"><a href="#v75-topic">주제·대본</a><a href="#r5-image-picker">이미지</a><a href="#dino-voice-picker">음성</a><a href="#sub-style-card">편집</a><a href="#r5-settings">API 계정</a></nav></div>';
 const result=document.createElement('main');result.id='dino-results-panel';result.innerHTML='<h2>진행 상태·완성 파일</h2><p class="r5-note">제작 진행, Codex PC앱에 보낼 요청문, 대본과 영상 결과를 여기서 확인하세요.</p>';
 writer.before(layout);layout.append(aside,result);aside.append(writer);
 const progress=document.createElement('section');progress.className='dino-result-card';progress.innerHTML='<h3>제작 진행</h3>';
 for(const id of ['r5-status','r5-progress','r5-stats','r5-queue-status'])if(E(id))progress.append(E(id));
 const log=E('r5-log')?.closest('details');if(log)progress.append(log);result.append(progress);
 const textRequest=E('r13-text-request');if(textRequest){const card=document.createElement('section');card.className='dino-result-card';card.id='dino-codex-text-handoff';card.innerHTML='<h3>Codex PC앱에 보낼 자료·대본 요청</h3><p class="r5-note">요청문이 준비되면 복사하여 Codex PC앱에서 DINO 폴더를 연 대화에 붙여넣어 보내세요.</p>';card.append(textRequest);if(E('r13-text-copy'))card.append(E('r13-text-copy'));result.append(card);const update=()=>{card.hidden=E('r5-text_connection')?.value!=='codex';card.style.display=card.hidden?'none':'block'};E('r5-text_connection')?.addEventListener('change',update);update();}
 const picker=E('r5-image-picker'),choices=E('r5-image-choices');if(picker&&choices){choices.before(picker);choices.open=false;E('r5-image-choice-summary').textContent='이미지 모델 상세 비교 · 선택';}
 if(E('r5-image-provider')){E('r5-image-provider').previousElementSibling.textContent='이미지 생성 · Codex / API / 로컬';E('r5-image-provider').setAttribute('aria-label','이미지 생성 · Codex / API / 로컬');}
 const thumb=E('r5-thumbnail_provider')?.closest('label');if(thumb&&picker)picker.append(thumb);
 for(const id of ['r13-codex-panel','r5-dropshot-panel','r5-project-tools','phases','file-menu-box','yt-info'])if(E(id))result.append(E(id));
 for(const id of ['sub-style-card','title-style-card','r5-settings'])if(E(id))aside.append(E(id));
  const apiTitle=E('r5-settings')?.querySelector('h3');if(apiTitle)apiTitle.textContent='API 계정 입력 · API 사용 시 선택';
 const effects=E('dino-scene-effects-row');if(effects)aside.insertBefore(effects,E('sub-style-card')||E('r5-settings'));
 if(E('dino-settings-open')){const other=document.createElement('div');other.id='dino-setup-other-actions';aside.insertBefore(other,E('sub-style-card')||E('r5-settings'));other.append(E('dino-settings-open'));}
 for(const link of E('dino-setup-heading').querySelectorAll('nav a'))link.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();const target=E(link.getAttribute('href').slice(1));if(!target)return;if(getComputedStyle(aside).overflowY==='auto'){const delta=target.getBoundingClientRect().top-aside.getBoundingClientRect().top-E('dino-setup-heading').getBoundingClientRect().height-16;aside.scrollTo({top:aside.scrollTop+delta,behavior:'smooth'})}else target.scrollIntoView({block:'start',behavior:'smooth'});});
  const actions=E('r5-actions');if(actions)aside.append(actions);
  for(const id of ['dino-settings-open','r5-open-settings'])if(E(id)){const label=id==='dino-settings-open'?'기타 설정':'기타 설정 열기';if(E(id).textContent!==label)E(id).textContent=label;}
 const concise=document.createElement('style');concise.textContent='#dino-setup-panel #r5-writer-note,#dino-setup-panel #r5-work-text-summary,#dino-setup-panel #r5-length-note,#dino-setup-panel #r5-model-note,#dino-setup-panel #dino-caption-options-help,#dino-setup-panel #r5-image-size,#dino-setup-panel #r5-open-settings{display:none!important}#dino-setup-panel #r5-image-picker>p:not(#r5-model-selection-status){display:none!important}#dino-setup-panel #r5-settings>p{display:none!important}';document.head.append(concise);
 const textChoice=E('r5-text_connection')?.closest('.r5-card');if(textChoice){const paragraph=textChoice.querySelector('p');if(paragraph)paragraph.textContent='제작 시작 후 요청문을 복사해 Codex PC앱의 대화에 보내세요.';}
 const heading=writer.querySelector('h3');if(heading){const paragraph=heading.nextElementSibling;if(paragraph?.tagName==='P')paragraph.textContent='주제 또는 대본을 입력하세요.';}
 for(const id of ['r13-codex-panel','r5-dropshot-panel']){const panel=E(id);if(panel){const paragraph=panel.querySelector('p');if(paragraph)paragraph.textContent=id==='r13-codex-panel'?'요청문 복사 → Codex PC앱의 대화에 붙여넣기':'요청문을 Codex PC앱의 대화에 보내면 영상 결과를 받습니다.';}}
}
function tidyPendingRequests(){
 const text=E('dino-codex-text-handoff');if(text){const show=E('r5-text_connection')?.value==='codex'&&!E('r13-text-copy')?.disabled;text.hidden=!show;text.style.display=show?'block':'none';}
 for(const [panel,request] of [['r13-codex-panel','r13-codex-request'],['r5-dropshot-panel','r5-dropshot-request']])if(E(panel)&&E(request))E(panel).style.display=E(panel).hidden||!E(request).value.trim()?'none':'';
}
function mountVoicePicker(){
 const host=E('r5-work');if(!host)return;
 let panel=E('dino-voice-picker');
 if(!panel){
  panel=document.createElement('section');panel.id='dino-voice-picker';panel.style.cssText='margin:16px 0;padding:16px;border:1px solid #52637a;border-radius:10px';
  panel.innerHTML='<h3 style="margin:0 0 10px">음성 만들기</h3><label for="dino-voice-source">사용할 음성 방식</label><select id="dino-voice-source" style="display:block;width:100%;padding:12px;font-size:15px"><option value="inworld">인월드 · Voice ID로 음성 생성</option><option value="qwen" disabled>로컬 · 내 목소리 · 설치 상태 확인 중</option></select><div id="dino-inworld-inputs" class="r5-grid" style="margin-top:12px"><label>인월드 Basic Key<input id="dino-inworld-key" type="password" autocomplete="off" placeholder="내 인월드 Basic Key 입력" style="width:100%;padding:11px"></label><label>인월드 Voice ID · 사용할 목소리<input id="dino-inworld-voice" type="text" autocomplete="off" placeholder="사용할 인월드 Voice ID 입력" style="width:100%;padding:11px"></label></div><p id="dino-voice-help" class="r5-note" role="status"></p><div class="r5-row"><button id="dino-voice-save" type="button" class="fbtn">음성 설정 저장</button><a href="/dino-local" target="_blank" rel="noopener" class="fbtn">로컬 설치·내 목소리 등록</a></div>';
  (E('r5-reference-panel')||E('r5-actions')).before(panel);
  for(const [visible,original] of [['dino-inworld-key','k-iw'],['dino-inworld-voice','vid-inp']])E(visible).addEventListener('input',()=>{const target=E(original);if(target){target.value=E(visible).value;target.dispatchEvent(new Event('input',{bubbles:true}));target.dispatchEvent(new Event('change',{bubbles:true}))}});
  E('dino-voice-source').addEventListener('change',async()=>{voiceSaving=true;const choice=E('dino-voice-source').value;try{await api('voice/settings',{provider:choice});await refreshVoice();E('dino-voice-help').textContent='음성 선택을 저장했습니다.'}catch(error){E('dino-voice-help').textContent=error.message}finally{voiceSaving=false;mountVoicePicker()}});
  E('dino-voice-save').onclick=async()=>{try{if(V.provider==='inworld'){if(!E('dino-inworld-key').value.trim()||!E('dino-inworld-voice').value.trim())throw Error('인월드 Basic Key와 Voice ID를 모두 입력하세요.');if(typeof W.saveApiConfigNow!=='function')throw Error('음성 설정이 준비 중입니다. 잠시 후 다시 저장하세요.');await W.saveApiConfigNow()}await api('voice/settings',{provider:E('dino-voice-source').value});await refreshVoice();E('dino-voice-help').textContent='음성 설정을 저장했습니다.'}catch(error){E('dino-voice-help').textContent=error.message}};
 }
 const select=E('dino-voice-source'),local=select.querySelector('[value=qwen]');local.disabled=!(models.qwen&&voiceReferenceReady);
 const label=local.disabled?'로컬 · 내 목소리 · 설치·목소리 등록 필요':'로컬 · 내 목소리 · '+V.voice;if(local.textContent!==label)local.textContent=label;
 if(!voiceSaving&&document.activeElement!==select)select.value=V.provider;
 E('dino-inworld-inputs').hidden=select.value==='qwen';E('dino-inworld-inputs').style.display=select.value==='qwen'?'none':'grid';
 for(const [visible,original] of [['dino-inworld-key','k-iw'],['dino-inworld-voice','vid-inp']])if(E(original)&&document.activeElement!==E(visible)&&E(visible).value!==E(original).value)E(visible).value=E(original).value;
 const text=select.value==='qwen'?'등록한 내 목소리로 PC에서 생성합니다. 인월드 키와 Voice ID는 필요 없습니다.':'내 인월드 계정의 Basic Key와 Voice ID를 입력하세요. 로컬 음성을 사용하려면 아래에서 설치·등록 후 선택하세요.';
 if(E('dino-voice-help').dataset.provider!==select.value){E('dino-voice-help').textContent=text;E('dino-voice-help').dataset.provider=select.value;}
}
function refreshVoice(){return api('voice/settings').then(d=>{if(V.active.size)return;const changed=V.provider!==d.settings.provider||V.voice!==d.settings.voice||V.revision!==(d.settings.voice_revision||'');V.provider=d.settings.provider;V.voice=d.settings.voice;V.revision=d.settings.voice_revision||'';voiceReferenceReady=!!d.settings.reference_ready;if(changed){W.dino75Speech?.cache?.clear();W.audioBlob=null;W.srtText='';W.timestamps=[];if(W.DINO_R5)W.DINO_R5.audioOwner=null}mountVoicePicker()})}
document.addEventListener('visibilitychange',()=>{if(!document.hidden){refreshModels().catch(()=>{});refreshVoice().catch(()=>{})}});
document.addEventListener('change',event=>{if(['r5-image-provider','r5-image_model','r5-thumbnail_provider'].includes(event.target?.id))mount()});
window.addEventListener('message',event=>{const frame=E('dino-local-settings-frame');if(event.origin!==location.origin||event.source!==frame?.contentWindow||event.data?.type!=='dino-local-settings-changed')return;refreshModels().catch(()=>{});refreshVoice().catch(()=>{})});
mount();document.addEventListener('DOMContentLoaded',mount);let queued=false;new MutationObserver(()=>{if(!queued){queued=true;setTimeout(()=>{queued=false;mount()},200)}}).observe(document.body,{childList:true,subtree:true});init().then(()=>refreshVoice()).catch(e=>console.error('DINO local setup',e.message));
})();
