import io,json,re,sys
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0,'src')
from jobradar.adapters.base import make_client
from jobradar.sources import load_sources
from jobradar.pipeline.calendar import match_targets
import yaml

doc=yaml.safe_load(io.open('targets/top_companies.yaml',encoding='utf-8'))
comp={s.company for s in load_sources('sources')}
matched=match_targets(doc,comp)
unc={k for k,v in matched.items() if not v}

urls={}
for f in ('work/careers_confirmed.jsonl','work/careers_final.jsonl','work/home_found.jsonl'):
    for line in io.open(f,encoding='utf-8'):
        d=json.loads(line); b=d.get('best') or {}
        u=b.get('url') or d.get('home')
        if u: urls.setdefault(d.get('company',''),u)
todo=[(n,urls[n]) for n in unc if n in urls]
print('todo',len(todo))

SIG=[('beisen',r'\.zhiye\.com'),('hotjob',r'hotjob\.cn'),('feishu',r'\.jobs\.feishu\.cn'),('workday',r'myworkdayjobs'),
     ('moka',r'mokahr'),('gllue',r'gllue\.com'),('tupu360',r'tupu360'),('avature',r'avature'),('radancy',r'radancy'),
     ('dayee',r'wecruit|dayee'),('liepin',r'liepin'),('zhaopin',r'zhaopin'),('51job',r'51job'),('boss',r'zhipin\.com'),
     ('greenhouse',r'greenhouse\.io'),('lever',r'lever\.co'),('smartrecruiters',r'smartrecruiters'),
     ('nextjs',r'__NEXT_DATA__'),('jsonapi',r'"(/api/[^"]{3,60})"')]
cl=make_client(); out=[]
def one(item):
    name,u=item
    try:
        r=cl.get(u,follow_redirects=True)
        t=r.text[:400000]
        hits=[k for k,p in SIG if re.search(p,t,re.I)]
        return {'company':name,'url':u,'status':r.status_code,'size':len(t),'final':str(r.url),'hits':hits}
    except Exception as e:
        return {'company':name,'url':u,'status':0,'size':0,'final':'','hits':[],'err':type(e).__name__}
with ThreadPoolExecutor(max_workers=8) as ex:
    futs=[ex.submit(one,x) for x in todo]
    for i,f in enumerate(as_completed(futs),1):
        out.append(f.result())
        if i%80==0: print('done',i,flush=True)
with io.open('work/self_scan.jsonl','w',encoding='utf-8',newline='\n') as fh:
    for o in out: fh.write(json.dumps(o,ensure_ascii=False)+'\n')
print('saved',len(out))
