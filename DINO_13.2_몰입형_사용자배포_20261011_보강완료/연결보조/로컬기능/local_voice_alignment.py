"""Acoustic word timing mapped back to the exact supplied caption text."""
import difflib,re

class CaptionAlignmentError(ValueError):
    """Only an acoustic/text mismatch is eligible for speech regeneration."""
def read_wav_16k(path):
    import soundfile as sf,numpy as np,math
    from scipy.signal import resample_poly
    data,sr=sf.read(path,dtype='float32')
    if data.ndim>1:data=data.mean(axis=1)
    if sr!=16000:
        divisor=math.gcd(sr,16000);data=resample_poly(data,16000//divisor,sr//divisor)
    return np.asarray(data,dtype=np.float32)

def align_caption_words(text,recognized,duration):
    def norm(value):return ''.join(c.casefold() for c in value if c.isalnum())
    expected=re.findall(r'\S+',text);a=''.join(norm(t) for t in expected)
    b='';times=[]
    for word in recognized:
        value=norm(word['word']);start=max(0,float(word['start']));end=min(duration,float(word['end']))
        for i,c in enumerate(value):b+=c;times.append((start+(end-start)*i/len(value),start+(end-start)*(i+1)/len(value)))
    match=difflib.SequenceMatcher(None,a,b,autojunk=False)
    coverage=match.ratio()
    if not a or not times or coverage<0.65:raise CaptionAlignmentError('낭독 내용과 대본을 충분히 맞추지 못했습니다. 같은 모델로 이 문단을 다시 생성하세요.')
    aligned={}
    for block in match.get_matching_blocks():
        for i in range(block.size):aligned[block.a+i]=times[block.b+i]
    known=sorted(aligned)
    # Number pronunciation and punctuation may differ; interpolate only unmatched spans.
    for i in range(len(a)):
        if i in aligned:continue
        left=max((k for k in known if k<i),default=None);right=min((k for k in known if k>i),default=None)
        start=aligned[left][1] if left is not None else 0;end=aligned[right][0] if right is not None else duration
        count=(right if right is not None else len(a))-(left if left is not None else -1)-1
        step=max(0,end-start)/max(1,count);offset=i-(left if left is not None else -1)-1
        aligned[i]=(start+step*offset,start+step*(offset+1))
    words=[];offset=0;last=0
    for token in expected:
        length=len(norm(token))
        if length:
            start=max(last,aligned[offset][0]);end=min(duration,max(start+0.015,aligned[offset+length-1][1]));offset+=length
        else:start=last;end=min(duration,start+0.015)
        end=max(start,end);words.append({'w':token,'s':round(start,3),'e':round(end,3)});last=end
    if ''.join(w['w'] for w in words)!=''.join(expected):raise ValueError('원문 자막 보존 검증에 실패했습니다.')
    return words,round(coverage,4)
