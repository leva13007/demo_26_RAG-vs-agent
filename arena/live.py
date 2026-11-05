#!/usr/bin/env python3
"""Fast results for stream #026: parallel runs -> LLM draft scores -> table and HTML report.

  ./live.py run 6                  one round, all three players in parallel
  ./live.py run air                the on-air set (8 questions)
  ./live.py run all --reps 3       every question, 3 runs each
  ./live.py show 6                 the answers for a question
  ./live.py score 6 rag 1          host's call overrides the judge, report rebuilds
  ./live.py table                  table again
  ./live.py judge DIR [--compare scores.csv]   score an existing folder of logs

Options for run: --id NAME (default: timestamp; same NAME adds to that folder), --jobs 6, --no-judge
Nothing is ever overwritten: each new run takes the next free run number."""
import argparse, concurrent.futures as cf, csv, json, os, random, re, statistics as st, subprocess, sys, threading, time, urllib.request
from pathlib import Path
import build_results as br

HERE=Path(__file__).resolve().parent; RAG=br.BASELINE.parent; RUNS=HERE/"runs"
AIR=[15,2,5,6,7,10,12,14]; PLAYERS=br.PLAYERS; NAME=br.NAME
QUESTIONS=(RAG/"questions.txt").read_text(encoding="utf8").splitlines()
GOLD=json.loads((HERE/"gold.json").read_text(encoding="utf8"))
FIELDS=["q","player","rep","score","contested","by","note"]
ENV={k:v for k,v in os.environ.items() if not k.startswith("CLAUDE_CODE") and k!="CLAUDECODE"}
JUDGE_MODEL=os.environ.get("JUDGE_MODEL","haiku")
lock=threading.Lock()
def say(*a):
    with lock: print(*a,flush=True)

def index_model():
    # model стоїть на початку chunks.json, увесь файл на 7 МБ читати не треба
    with open(RAG/"rag/index/chunks.json",encoding="utf8") as f: m=re.search(r'"model":"([^"]+)"',f.read(500))
    if not m: sys.exit("Не можу прочитати модель індексу з rag/index/chunks.json")
    return m.group(1)

def preflight():
    norm=lambda m:m.removesuffix(":latest")
    model=index_model(); asked=os.environ.get("EMBED_MODEL",model)
    # інакше RAG упаде, а Hybrid тихо стане агентом на Grep і виглядатиме в таблиці як нормальний прогін
    if norm(asked)!=norm(model): sys.exit(f"EMBED_MODEL={asked}, а rag/index побудований моделлю {model}. Прибери змінну: live.py завжди працює з rag/index.")
    try:
        tags=json.load(urllib.request.urlopen("http://localhost:11434/api/tags",timeout=3))
        if not any(norm(m["name"])==norm(model) for m in tags["models"]): sys.exit(f"Ollama працює, але немає {model}")
        req=urllib.request.Request("http://localhost:11434/api/embed",json.dumps({"model":model,"input":["warm"]}).encode(),{"content-type":"application/json"})
        urllib.request.urlopen(req,timeout=60).read()
    except OSError as ex: sys.exit(f"Ollama недоступна: {ex}")

def cmd(pl,q):
    return {"rag":["node","rag/ask.ts",q],"agent":["./agent/ask.sh",q],"hybrid":["./hybrid/ask.sh",q]}[pl]

def next_rep(d,q,pl):
    n=[int(m.group(1)) for f in d.glob(f"Q{q}_{pl}_r*.txt") if (m:=re.search(r"_r(\d+)\.txt$",f.name))]
    return max(n,default=0)+1

def run_one(d,q,pl,rep):
    f=d/f"Q{q}_{pl}_r{rep}.txt"
    try:
        with open(f,"w",encoding="utf8") as out:
            subprocess.run(cmd(pl,QUESTIONS[q-1]),cwd=RAG,stdout=out,stderr=subprocess.STDOUT,timeout=240,env=ENV)
    except subprocess.TimeoutExpired:
        with open(f,"a",encoding="utf8") as out: out.write("\nTIMEOUT\n")
    r=br.parse_log(f)
    say(f"  {'✗' if r['failed'] else '✓'} Q{q:<2} {NAME[pl]:<6} r{rep} "+("FAILED" if r["failed"] else f"{r['sec']:>5.1f} s  ${r['cost']:.3f}  {r['steps']} кроків"))

def answer_text(f):
    t=f.read_text(encoding="utf8",errors="replace"); i=t.rfind("💬")
    if i<0: return ""
    a=t[i+1:]; return a.split("\n⏱")[0].strip()

def judge_one(f,q):
    g=GOLD[str(q)]
    system=("Ти суддя експерименту. Оціни відповідь строго за критерієм. Транскрипти мають помилки розпізнавання, тому написання термінів не карай. "
            'Поверни лише JSON без markdown: {"score":0|1|2,"why":"одне коротке речення українською"}')
    prompt=f"Питання: {QUESTIONS[q-1]}\n\nЕталон: {g['gold']}\n\nКритерій: {g['rubric']}\n\nВідповідь гравця:\n{answer_text(f)}"
    p=subprocess.run(["claude","-p","--model",JUDGE_MODEL,"--output-format","json","--tools","","--system-prompt",system,"--disable-slash-commands","--strict-mcp-config","--setting-sources","","--no-session-persistence"],
                     input=prompt,capture_output=True,text=True,timeout=120,env=ENV)
    out=json.loads(p.stdout); m=re.search(r"\{.*\}",out["result"],re.S); v=json.loads(m.group(0))
    return int(v["score"]),v.get("why",""),out.get("total_cost_usd",0)

def read(d):
    p=Path(d)/"scores.csv"
    return {(int(r["q"]),r["player"],int(r.get("rep") or 1)):r for r in csv.DictReader(open(p,encoding="utf8"))} if p.exists() else {}
def write(d,s,path=None):
    with open(path or Path(d)/"scores.csv","w",newline="",encoding="utf8") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS,extrasaction="ignore"); w.writeheader()
        for k in sorted(s): w.writerow(s[k])

def judge_dir(d,jobs=8,out=None):
    d=Path(d); s=read(out.parent if out else d) if not out else {}
    todo=[]
    for f in sorted(d.glob("Q*_*.txt")):
        m=br.FILE.match(f.name)
        if not m: continue
        key=(int(m.group(1)),m.group(2),int(m.group(3) or 1))
        if key not in s and not br.parse_log(f)["failed"]: todo.append((key,f))
    t0=time.time(); total=[0.0]
    def work(item):
        key,f=item
        try:
            sc,why,c=judge_one(f,key[0]); total[0]+=c
            return key,dict(q=key[0],player=key[1],rep=key[2],score=sc,by="judge",note=why)
        except Exception as ex:
            say(f"  ! суддя не впорався з Q{key[0]} {key[1]}: {ex}"); return key,None
    with cf.ThreadPoolExecutor(jobs) as ex:
        for key,v in ex.map(work,todo):
            if v: s[key]=v
    write(d,s,out)
    say(f"  суддя: {len(todo)} відповідей за {time.time()-t0:.0f} с, ~${total[0]:.3f}")
    return s

def table(d):
    rows,sm,out=br.build(d); S=sm["S"]; M=sm["M"]
    print(f"\n{'':<5}{'':<36}"+"".join(f"{NAME[p]:^10}" for p in PLAYERS))
    for q in sm["qs"]:
        print(f"Q{q:<4}{br.QS[q][1][:34]:<36}"+"".join(f"{br.G[M[(q,p)]]:^10}" for p in PLAYERS))
    print(f"{'':<5}{'РАЗОМ з '+str(sm['maxpts']):<36}"+"".join(f"{S[p]['score']:^10}" for p in PLAYERS))
    print(f"{'':<5}{'Ціна відповіді':<36}"+"".join(f"{'$'+format(S[p]['mean'],'.3f'):^10}" for p in PLAYERS))
    print(f"{'':<5}{'Медіанний час':<36}"+"".join(f"{format(S[p]['tmed'],'.1f')+' с':^10}" for p in PLAYERS))
    print(f"\n📊 {out}")

def latest():
    ds=sorted((p for p in RUNS.glob("*") if p.is_dir()),key=lambda p:p.stat().st_mtime)
    if not ds: sys.exit("Ще немає прогонів")
    return ds[-1]

def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter); sub=ap.add_subparsers(dest="c",required=True)
    r=sub.add_parser("run"); r.add_argument("what",nargs="+"); r.add_argument("--reps",type=int,default=1); r.add_argument("--jobs",type=int,default=6); r.add_argument("--id"); r.add_argument("--no-judge",action="store_true")
    s=sub.add_parser("show"); s.add_argument("q",type=int); s.add_argument("--id")
    c=sub.add_parser("score"); c.add_argument("q",type=int); c.add_argument("player",choices=PLAYERS); c.add_argument("value",type=int,choices=[0,1,2]); c.add_argument("--id"); c.add_argument("--rep",type=int); c.add_argument("--note",default="")
    t=sub.add_parser("table"); t.add_argument("--id")
    j=sub.add_parser("judge"); j.add_argument("dir"); j.add_argument("--compare"); j.add_argument("--jobs",type=int,default=8)
    a=ap.parse_args()
    pick=lambda i:(RUNS/i if i else latest())
    if a.c=="run":
        qs=AIR if a.what==["air"] else list(range(1,len(QUESTIONS)+1)) if a.what==["all"] else [int(x) for x in a.what]
        preflight()   # до створення папки: порожня папка стала б «найновішим прогоном» для show і table
        d=RUNS/(a.id or time.strftime("%H%M%S")); d.mkdir(parents=True,exist_ok=True)
        tasks=[]
        for q in qs:
            for pl in PLAYERS:
                base=next_rep(d,q,pl); tasks+=[(d,q,pl,base+i) for i in range(a.reps)]
        random.shuffle(tasks)
        print(f"{len(tasks)} прогонів, паралельно {a.jobs} → {d.name}"); t0=time.time()
        for t_ in tasks: (t_[0]/f"Q{t_[1]}_{t_[2]}_r{t_[3]}.txt").touch()
        with cf.ThreadPoolExecutor(a.jobs) as ex: list(ex.map(lambda x:run_one(*x),tasks))
        print(f"  прогони: {time.time()-t0:.0f} с")
        if not a.no_judge: judge_dir(d)
        table(d)
    elif a.c=="show":
        d=pick(a.id); print(f"\n❓ Q{a.q}: {QUESTIONS[a.q-1]}\n🎯 {GOLD[str(a.q)]['gold']}")
        sc=read(d)
        for pl in PLAYERS:
            for f in sorted(d.glob(f"Q{a.q}_{pl}_r*.txt")):
                rep=int(re.search(r"_r(\d+)\.txt$",f.name).group(1)); v=sc.get((a.q,pl,rep),{})
                print(f"\n──── {NAME[pl]} r{rep}  бал {v.get('score','?')}  {v.get('note','')}\n{answer_text(f)}")
    elif a.c=="score":
        d=pick(a.id); sc=read(d); reps=[a.rep] if a.rep else sorted({k[2] for k in sc if k[0]==a.q and k[1]==a.player}) or [1]
        for rep in reps: sc[(a.q,a.player,rep)]=dict(q=a.q,player=a.player,rep=rep,score=a.value,by="host",note=a.note or sc.get((a.q,a.player,rep),{}).get("note",""))
        write(d,sc); table(d)
    elif a.c=="table": table(pick(a.id))
    elif a.c=="judge":
        import tempfile
        tmp=Path(tempfile.mkdtemp())/"scores.csv"; s=judge_dir(a.dir,a.jobs,out=tmp); print(tmp)
        if a.compare:
            base={(int(r["q"]),r["player"]):int(r["score"]) for r in csv.DictReader(open(a.compare,encoding="utf8"))}
            same=0
            for k,v in sorted(s.items()):
                b=base.get(k[:2])
                if b==int(v["score"]): same+=1
                else: print(f"  Q{k[0]} {NAME[k[1]]}: рука {b}, суддя {v['score']} — {v['note']}")
            tot={p:sum(int(v["score"]) for k,v in s.items() if k[1]==p) for p in PLAYERS}
            print(f"Збіг {same}/{len(s)} · суддя: "+", ".join(f"{NAME[p]} {tot[p]}" for p in PLAYERS))
main()
