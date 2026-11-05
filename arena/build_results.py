#!/usr/bin/env python3
"""Run logs + scores.csv -> metrics.csv and an HTML report.
python3 build_results.py                 baseline run, writes results-charts.html here
python3 build_results.py runs/<id>       writes runs/<id>/report.html"""
import csv, html, math, re, statistics as st, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASELINE = HERE.parent / "results"
PLAYERS = ["rag", "agent", "hybrid"]
NAME = {"rag": "RAG", "agent": "Agent", "hybrid": "Hybrid"}
QS = {
 1:("Fact","Mini-Twitter stream and stack"),2:("Fact","New name for classic Lambda"),3:("Fact","Talanov's childhood music"),
 4:("Rephrased","Parallel AI helpers in a terminal"),5:("Rephrased","Context-saving experiment outcome"),6:("Rephrased","Typical chunking mistake"),
 7:("Multi-hop","Talanov's streams and their link"),8:("Multi-hop","Streams on login security"),9:("Multi-hop","Guest who knows Oleh since 2015"),
 10:("Aggregation","Blazheiko's appearance count"),11:("Aggregation","Streams mentioning LinkedIn"),
 12:("Trap","Installing Plane (never happened)"),13:("Trap","Kubernetes (two passing mentions)"),14:("Trap","GraphQL (ASR: “граф QL”)"),
 15:("Warm-up","AI skills pay premium"),
}
TYPE_ORDER = ["Fact","Rephrased","Multi-hop","Aggregation","Trap","Warm-up"]
FILE = re.compile(r"^Q(\d+)_(rag|agent|hybrid)(?:_r(\d+))?\.txt$")

def parse_log(path):
    t = path.read_text(encoding="utf8", errors="replace")
    lines = [l for l in t.splitlines() if l.startswith("⏱")]
    r = dict(failed=not lines, sec=None, steps=None, tok_in=None, tok_out=None, cost=None)
    r.update(semantic=t.count("🧠 semantic"), grep=t.count("🔧 Grep"), read=t.count("🔧 Read"))
    if not lines: return r
    line = lines[-1]; tok = re.search(r"tokens in (\d+) / out (\d+)", line); cost = re.search(r"~\$([\d.]+)", line)
    m = re.search(r"retrieval (\d+) ms · LLM ([\d.]+) s", line)
    if m: r.update(sec=round(int(m.group(1))/1000+float(m.group(2)),2), steps=1)
    else:
        m = re.search(r"([\d.]+) s · кроків (\d+)", line); r.update(sec=float(m.group(1)), steps=int(m.group(2)))
    r.update(tok_in=int(tok.group(1)), tok_out=int(tok.group(2)), cost=round(float(cost.group(1)),4))
    return r

def read_scores(path):
    out = {}
    if path.exists():
        for r in csv.DictReader(open(path, encoding="utf8")):
            out[(int(r["q"]), r["player"], int(r.get("rep") or 1))] = r
    return out

def load(run_dir, scores_path):
    scores = read_scores(scores_path); rows = []
    for f in sorted(Path(run_dir).glob("Q*_*.txt")):
        m = FILE.match(f.name)
        if not m: continue
        q, pl, rep = int(m.group(1)), m.group(2), int(m.group(3) or 1)
        r = parse_log(f); s = scores.get((q,pl,rep))
        r.update(q=q, player=pl, rep=rep, type=QS[q][0], score=(int(s["score"]) if s and s["score"]!="" else (0 if r["failed"] else None)),
                 contested=bool(s and s.get("contested")=="yes"), by=(s.get("by") or "hand") if s else None)
        rows.append(r)
    return rows

def summarize(rows):
    qs = sorted({r["q"] for r in rows}); types = [t for t in TYPE_ORDER if any(QS[q][0]==t for q in qs)]
    def med(q,pl):
        v=[r["score"] for r in rows if r["q"]==q and r["player"]==pl and r["score"] is not None]
        return st.median_low(v) if v else None
    M={(q,pl):med(q,pl) for q in qs for pl in PLAYERS}
    S={}
    for pl in PLAYERS:
        R=[r for r in rows if r["player"]==pl and not r["failed"]]
        c=[r["cost"] for r in R]; t=[r["sec"] for r in R]
        S[pl]=dict(score=sum(M[(q,pl)] or 0 for q in qs),mean=st.mean(c) if c else 0,tmed=st.median(t) if t else 0,tmin=min(t,default=0),tmax=max(t,default=0),
                   cmed=st.median(c) if c else 0,failed=sum(1 for r in rows if r["player"]==pl and r["failed"]))
    T={t:{pl:sum(M[(q,pl)] or 0 for q in qs if QS[q][0]==t) for pl in PLAYERS} for t in types}
    MAX={t:2*sum(1 for q in qs if QS[q][0]==t) for t in types}
    pick={}
    for t in types:
        cost={pl:st.mean([r["cost"] for r in rows if r["player"]==pl and r["type"]==t and not r["failed"]] or [0]) for pl in PLAYERS}
        best=max(T[t].values()); ok=[pl for pl in PLAYERS if T[t][pl]>=0.9*best]
        pick[t]=(min(ok,key=lambda p:cost[p]),cost)
    reps=max((r["rep"] for r in rows),default=1)
    return dict(qs=qs,types=types,M=M,S=S,T=T,MAX=MAX,pick=pick,reps=reps,maxpts=2*len(qs),pending=sum(1 for r in rows if r["score"] is None))

e=html.escape
def tip(*l): return e(" · ".join(l),quote=True)
G={2:"●●",1:"●○",0:"○○",None:"?"}
def nice(v,step): return max(step,math.ceil(v/step)*step)

def render(rows,sm,scorer,key_note):
    S,T,MAX,M,qs,types,pick=sm["S"],sm["T"],sm["MAX"],sm["M"],sm["qs"],sm["types"],sm["pick"]; maxpts=sm["maxpts"]
    ok=lambda pl:[r for r in rows if r["player"]==pl and not r["failed"]]
    def bars():
        W,H=1120,410; L,R_,T_,B=50,10,28,44; pw=W-L-R_; ph=H-T_-B; g=pw/len(types); bw=min(44,(g-20)/3); gap=2
        o=[f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Share of available points by question type">']
        for v in (0,25,50,75,100):
            y=T_+ph*(1-v/100); o.append(f'<line class="grid" x1="{L}" x2="{W-R_}" y1="{y}" y2="{y}"/><text class="ax" x="{L-8}" y="{y+4}" text-anchor="end">{v}%</text>')
        for i,ty in enumerate(types):
            x0=L+g*i+(g-3*bw-2*gap)/2
            for j,pl in enumerate(PLAYERS):
                val=T[ty][pl]; h=ph*val/MAX[ty]; x=x0+j*(bw+gap); y=T_+ph-h; rd=4 if h>=4 else 0
                o.append(f'<path class="s-{pl}" data-tip="{tip(ty,NAME[pl],f"{val}/{MAX[ty]} points")}" d="M{x},{T_+ph}V{y+rd}Q{x},{y} {x+rd},{y}H{x+bw-rd}Q{x+bw},{y} {x+bw},{y+rd}V{T_+ph}Z"/>')
                o.append(f'<text class="val" x="{x+bw/2}" y="{y-6}" text-anchor="middle">{val}/{MAX[ty]}</text>')
            o.append(f'<text class="cat" x="{L+g*i+g/2}" y="{H-14}" text-anchor="middle">{ty}</text>')
        o.append('</svg>'); return "".join(o)
    def strip(metric,fmt,mfmt,unit,step):
        vals=[r[metric] for r in rows if not r["failed"]] or [step]
        hi=nice(max(vals)*1.05,step*5 if max(vals)>step*5 else step); n=5; ticks=[hi*i/n for i in range(n+1)]
        W,H=1120,270; L,R_,T_,B=90,30,10,34; pw=W-L-R_; row=(H-T_-B)/3; X=lambda v:L+pw*v/hi
        o=[f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{unit} for every run by player">']
        for v in ticks: o.append(f'<line class="grid" x1="{X(v)}" x2="{X(v)}" y1="{T_}" y2="{H-B}"/><text class="ax" x="{X(v)}" y="{H-12}" text-anchor="middle">{fmt(v)}</text>')
        for j,pl in enumerate(PLAYERS):
            y=T_+row*j+row/2; R=ok(pl)
            o.append(f'<text class="cat" x="{L-14}" y="{y+5}" text-anchor="end">{NAME[pl]}</text>')
            for r in R: o.append(f'<circle class="s-{pl} ring" cx="{X(r[metric]):.1f}" cy="{y}" r="8" data-tip="{tip("Q"+str(r["q"]),QS[r["q"]][1],NAME[pl],mfmt(r[metric]))}"/>')
            if R:
                m=st.median(r[metric] for r in R); o.append(f'<line class="med" x1="{X(m)}" x2="{X(m)}" y1="{y-24}" y2="{y+24}"/><text class="val" x="{X(m)}" y="{y-29}" text-anchor="middle">median {mfmt(m)}</text>')
        o.append('</svg>'); return "".join(o)
    def scatter():
        W,H=1120,430; L,R_,T_,B=64,30,20,52; pw=W-L-R_; ph=H-T_-B
        xhi=nice(max(S[p]["mean"] for p in PLAYERS)*1.3,0.01); low=min(S[p]["score"] for p in PLAYERS); ylo=max(0,int(low*0.8)//2*2); step=max(1,(maxpts-ylo)//5)
        X=lambda v:L+pw*v/xhi; Y=lambda v:T_+ph*(1-(v-ylo)/max(1,maxpts-ylo))
        o=[f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Total score against mean cost per answer">']
        for v in range(ylo,maxpts+1,step): o.append(f'<line class="grid" x1="{L}" x2="{W-R_}" y1="{Y(v)}" y2="{Y(v)}"/><text class="ax" x="{L-10}" y="{Y(v)+4}" text-anchor="end">{v}</text>')
        for i in range(7): o.append(f'<text class="ax" x="{X(xhi*i/6)}" y="{H-B+22}" text-anchor="middle">${xhi*i/6:.3f}</text>')
        o.append(f'<text class="ax" x="{L+pw/2}" y="{H-6}" text-anchor="middle">Mean cost per answer</text><text class="ax" transform="translate(16 {T_+ph/2}) rotate(-90)" text-anchor="middle">Score out of {maxpts}'+(f' (axis starts at {ylo})' if ylo else '')+'</text>')
        off={"rag":(0,-22,"middle"),"agent":(18,6,"start"),"hybrid":(-18,6,"end")}
        for pl in PLAYERS:
            s=S[pl]; x,y=X(s["mean"]),Y(s["score"]); dx,dy,a=off[pl]
            o.append(f'<circle class="s-{pl} ring" cx="{x:.1f}" cy="{y:.1f}" r="12" data-tip="{tip(NAME[pl],f"{s["score"]}/{maxpts}",f"${s["mean"]:.3f} per answer")}"/><text class="big" x="{x+dx:.1f}" y="{y+dy:.1f}" text-anchor="{a}">{NAME[pl]} · {s["score"]}/{maxpts} · ${s["mean"]:.3f}</text>')
        o.append('</svg>'); return "".join(o)
    def board():
        o=['<table class="board"><thead><tr><th>#</th><th>Type</th><th>Question</th>'+"".join(f'<th class="c">{NAME[p]}</th>' for p in PLAYERS)+'</tr></thead><tbody>']
        for q in qs:
            o.append(f'<tr><td class="m">Q{q}</td><td class="mut">{QS[q][0]}</td><td>{e(QS[q][1])}</td>')
            for p in PLAYERS:
                v=M[(q,p)]; star=any(r["contested"] for r in rows if r["q"]==q and r["player"]==p)
                o.append(f'<td class="c m{" lo" if v==0 else ""}">{G[v]}{"*" if star else ""}</td>')
            o.append('</tr>')
        o.append(f'<tr class="tot"><td colspan="3">Total, out of {maxpts}</td>'+"".join(f'<td class="c m">{S[p]["score"]}</td>' for p in PLAYERS)+'</tr></tbody></table>'); return "".join(o)
    legend='<div class="legend">'+"".join(f'<span><i class="k-{p}"></i>{NAME[p]}</span>' for p in PLAYERS)+'</div>'
    def rule():
        o=['<table class="board"><thead><tr><th>Question type</th>'+"".join(f'<th class="c">{NAME[p]}</th>' for p in PLAYERS)+'<th>Rule picks</th></tr></thead><tbody>']
        for t in types: o.append(f'<tr><td>{t}</td>'+"".join(f'<td class="c m">{T[t][p]}/{MAX[t]}<small>${pick[t][1][p]:.3f}</small></td>' for p in PLAYERS)+f'<td class="pick">{NAME[pick[t][0]]}</td></tr>')
        o.append('</tbody></table>'); return "".join(o)
    def scale():
        o=['<table class="board"><thead><tr><th>Questions per month</th>'+"".join(f'<th class="c">{NAME[p]}</th>' for p in PLAYERS)+'</tr></thead><tbody>']
        for n in (1000,10000,100000): o.append(f'<tr><td class="m">{n:,}</td>'+"".join(f'<td class="c m">${S[p]["mean"]*n:,.0f}</td>' for p in PLAYERS)+'</tr>')
        o.append('</tbody></table>'); return "".join(o)
    def data():
        o=['<details><summary>Data table: every run</summary><table class="board small"><thead><tr><th>Q</th><th>Player</th><th>Run</th><th>Score</th><th>Time, s</th><th>Steps</th><th>Tokens in</th><th>Tokens out</th><th>Cost, $</th></tr></thead><tbody>']
        for r in rows: o.append(f'<tr><td>Q{r["q"]}</td><td>{NAME[r["player"]]}</td><td>{r["rep"]}</td><td>{"?" if r["score"] is None else r["score"]}</td>'+("<td colspan=5>failed</td>" if r["failed"] else f'<td>{r["sec"]}</td><td>{r["steps"]}</td><td>{r["tok_in"]:,}</td><td>{r["tok_out"]:,}</td><td>{r["cost"]:.4f}</td>')+'</tr>')
        o.append('</tbody></table></details>'); return "".join(o)
    tiles="".join(f'<div class="tile"><div class="tn"><i class="k-{p}"></i>{NAME[p]}</div><div class="hero">{S[p]["score"]}<span>/{maxpts}</span></div><div class="sub">${S[p]["mean"]:.3f} per answer · median {S[p]["tmed"]:.1f} s'+(f' · {S[p]["failed"]} failed' if S[p]["failed"] else '')+'</div></div>' for p in PLAYERS)
    runs_txt=f'{sm["reps"]} run{"s" if sm["reps"]>1 else ""} per question and player'
    caveat=f'{runs_txt}, scored {scorer}. Differences of a point or two are not meaningful.'
    rc,ac,hc=S["rag"]["mean"],S["agent"]["mean"],S["hybrid"]["mean"]
    costline=f"RAG costs {rc/ac:.0%} of Agent and {rc/hc:.0%} of Hybrid per answer" if ac and hc else "Cost per answer"
    timeline=f'Median answer: RAG {S["rag"]["tmed"]:.1f} s, Agent {S["agent"]["tmed"]:.1f} s, Hybrid {S["hybrid"]["tmed"]:.1f} s'
    dq=len(qs)
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>IT Friday #026: RAG vs AI agent, results</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{{color-scheme:light;--bg:#fcfcfb;--ink:#0b0b0b;--mut:#52514e;--line:#e4e3df;--accent:#ff5a1f;--rag:#2a78d6;--agent:#eb6834;--hybrid:#1baf7a;--tipb:#0b0b0b;--tipf:#fff}}
@media (prefers-color-scheme:dark){{:root{{color-scheme:dark;--bg:#1a1a19;--ink:#f0efec;--mut:#c3c2b7;--line:#3a3a37;--rag:#3987e5;--agent:#d95926;--hybrid:#199e70;--tipb:#f0efec;--tipf:#111}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:18px/1.45 Inter,system-ui,sans-serif}}
section{{min-height:100vh;max-width:1200px;margin:auto;padding:40px 40px 32px;display:flex;flex-direction:column;justify-content:center}}
.kick{{font:600 14px ui-monospace,Menlo,monospace;color:var(--accent);letter-spacing:.08em;text-transform:uppercase;margin-bottom:8px}}
h1{{font-size:44px;line-height:1.1;letter-spacing:-.02em;margin:0 0 8px}}h2{{font-size:34px;line-height:1.15;letter-spacing:-.02em;margin:0 0 8px}}
.lead{{color:var(--mut);margin:0 0 18px;font-size:19px}}.note{{color:var(--mut);font-size:15px;margin-top:12px}}
.tiles{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin:18px 0}}.tile{{border:1px solid var(--line);border-radius:12px;padding:22px}}
.tn{{font-weight:600;display:flex;gap:8px;align-items:center}}.hero{{font-size:76px;font-weight:700;letter-spacing:-.03em;line-height:1.1}}.hero span{{font-size:28px;color:var(--mut);font-weight:500}}.sub{{color:var(--mut);font-size:16px}}
i[class^=k-]{{display:inline-block;width:12px;height:12px;border-radius:50%}}.k-rag{{background:var(--rag)}}.k-agent{{background:var(--agent)}}.k-hybrid{{background:var(--hybrid)}}
.legend{{display:flex;gap:20px;margin-bottom:6px;font-size:16px}}.legend span{{display:flex;gap:7px;align-items:center}}
svg{{width:100%;height:auto;display:block}}.grid{{stroke:var(--line);stroke-width:1}}.ax{{fill:var(--mut);font-size:14px}}.cat{{fill:var(--ink);font-size:17px;font-weight:600}}.val{{fill:var(--ink);font-size:14px;font-family:ui-monospace,Menlo,monospace}}.big{{fill:var(--ink);font-size:19px;font-weight:600}}
.s-rag{{fill:var(--rag)}}.s-agent{{fill:var(--agent)}}.s-hybrid{{fill:var(--hybrid)}}.ring{{stroke:var(--bg);stroke-width:2}}.med{{stroke:var(--ink);stroke-width:2}}
[data-tip]{{cursor:default}}[data-tip]:hover{{opacity:.8}}
table.board{{width:100%;border-collapse:collapse;font-size:17px}}.board th{{text-align:left;color:var(--mut);font-weight:500;font-size:14px;border-bottom:1px solid var(--line);padding:5px 10px}}.board td{{padding:5px 10px;border-bottom:1px solid var(--line)}}
.c{{text-align:center!important}}.m{{font-family:ui-monospace,Menlo,monospace}}.mut{{color:var(--mut);font-size:15px}}.lo{{color:var(--accent);font-weight:700}}.tot td{{font-weight:700;font-size:21px;border-bottom:0}}.pick{{font-weight:700}}
.board small{{display:block;color:var(--mut);font-size:13px}}.small{{font-size:14px}}details{{margin-top:18px}}summary{{cursor:pointer;color:var(--mut)}}
#tip{{position:fixed;pointer-events:none;background:var(--tipb);color:var(--tipf);padding:6px 10px;border-radius:6px;font-size:14px;display:none;max-width:420px;z-index:9}}
@media (max-width:800px){{.tiles{{grid-template-columns:1fr}}section{{padding:24px 16px}}}}
</style></head><body>
<section><div class="kick">IT Friday #026 · results</div><h1>RAG vs AI agent: {dq} question{"s" if dq!=1 else ""}, 25 streams, 58 hours</h1><p class="lead">{costline}.</p><div class="tiles">{tiles}</div><p class="note">{caveat} Cost is Claude Code's own estimate: RAG runs without prompt caching, and its figure excludes local embeddings and index building.</p></section>
<section><div class="kick">Scoreboard</div><h2>Who answered what</h2><div>{board()}</div><p class="note">●● correct with a source · ●○ partial · ○○ wrong · ? not scored yet · * contested call.{key_note}</p></section>
<section><div class="kick">By question type</div><h2>Score by question type</h2>{legend}{bars()}<p class="note">Share of available points. One point can move a bar a lot.</p></section>
<section><div class="kick">Cost</div><h2>{costline}</h2><p class="lead">Every dot is one answer.</p>{strip("cost",lambda v:f"${v:.3f}",lambda v:f"${v:.3f}","Cost per answer",0.02)}</section>
<section><div class="kick">Speed</div><h2>{timeline}</h2><p class="lead">Every dot is one answer.</p>{strip("sec",lambda v:f"{v:.0f} s",lambda v:f"{v:.1f} s","Time per answer",5)}</section>
<section><div class="kick">Quality vs cost</div><h2>What the extra spend bought</h2>{scatter()}</section>
<section><div class="kick">So what do I pick?</div><h2>Apply the rule we wrote before the runs</h2><p class="lead">The cheapest player scoring at least 90% of the best on that question type. Small print is mean cost per answer.</p>{rule()}<p class="note">{caveat}</p></section>
<section><div class="kick">At scale</div><h2>What the bill could look like</h2><p class="lead">Mean cost per answer multiplied by volume. A straight-line estimate, not a quote.</p>{scale()}<p class="note">Model usage only. Excludes hosting, index rebuilds, caching across users and engineering time. Question mix is ours and deliberately hard.</p>{data()}</section>
<div id="tip"></div>
<script>const t=document.getElementById('tip');document.addEventListener('mousemove',e=>{{const m=e.target.closest&&e.target.closest('[data-tip]');if(!m){{t.style.display='none';return}}t.textContent=m.dataset.tip;t.style.display='block';t.style.left=Math.min(e.clientX+14,innerWidth-430)+'px';t.style.top=(e.clientY+14)+'px'}});</script>
</body></html>'''

def build(run_dir=None):
    if run_dir is None:
        logs,scores,out,metrics,baseline=BASELINE,HERE/"scores.csv",HERE/"results-charts.html",HERE/"metrics.csv",True
    else:
        d=Path(run_dir); logs,scores,out,metrics,baseline=d,d/"scores.csv",d/"report.html",d/"metrics.csv",False
    rows=load(logs,scores); sm=summarize(rows)
    with open(metrics,"w",newline="",encoding="utf8") as f:
        w=csv.DictWriter(f,fieldnames=["q","rep","type","player","score","sec","steps","tok_in","tok_out","cost","semantic","grep","read"],extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    bys={r["by"] for r in rows if r["by"]}
    scorer="by hand" if bys<={"hand"} else ("by an LLM judge against the answer key" if bys=={"judge"} else "by an LLM judge, reviewed by the host")
    out.write_text(render(rows,sm,scorer," Q13 and Q5 answer keys were corrected after the runs." if baseline else ""),encoding="utf8")
    return rows,sm,out

if __name__=="__main__":
    _,sm,out=build(sys.argv[1] if len(sys.argv)>1 else None)
    print(out," · ".join(f'{NAME[p]} {sm["S"][p]["score"]}/{sm["maxpts"]}' for p in PLAYERS))
