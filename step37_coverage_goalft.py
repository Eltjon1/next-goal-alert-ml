
import csv, math
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone
import step32_365day_xg5 as x

TARGETS="step36_goalft_targets.csv"

# Still frozen from STEP35: STEP37 does NOT tune thresholds.
F_STRONG_SUM=2.6055
F_STRONG_WEAK=0.9638
F_ELITE_SUM=3.1218
MAX_BACK_DAYS=365

ALIASES = {
    "manchesterunited":"manutd",
    "manchestercity":"mancity",
    "tottenhamhotspur":"tottenham",
    "wolverhamptonwanderers":"wolves",
    "brightonandhovealbion":"brighton",
    "westhamunited":"westham",
    "newcastleunited":"newcastle",
    "nottinghamforest":"nottmforest",
    "parissaintgermain":"psg",
    "olympiquedemarseille":"marseille",
    "olympiquelyonnais":"lyon",
    "borussiamonchengladbach":"gladbach",
    "bayernmunich":"bayernmunchen",
    "internazionale":"inter",
    "intermilan":"inter",
    "acmilan":"milan",
    "hellasverona":"verona",
    "atleticomadrid":"atleticomadrid",
    "athleticclub":"athleticbilbao",
    "realbetisbalompie":"realbetis",
}

def norm(s):
    z="".join(c.lower() for c in str(s) if c.isalnum())
    for junk in ("footballclub","futbolclub","calcio","cf","fc"):
        if len(z)>8 and z.endswith(junk):
            z=z[:-len(junk)]
    return ALIASES.get(z,z)

def sim(a,b):
    a,b=norm(a),norm(b)
    if a==b:return 1.0
    if a in b or b in a:return 0.96
    return SequenceMatcher(None,a,b).ratio()

def load_targets():
    out=[]
    with open(TARGETS,encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["dt"]=datetime.fromisoformat(r["date"]).replace(tzinfo=timezone.utc)
            r["goal_before_ft"]=int(float(r["goal_before_ft"]))
            out.append(r)
    return out

def find_target(row):
    # Search +/- 2 days and score every candidate by home+away similarity.
    candidates=[]
    for delta in (0,-1,1,-2,2):
        dd=row["dt"].date()+timedelta(days=delta)
        for m in x.day_matches(dd):
            h,a=x.team_names(m)
            hs,as_=sim(h,row["home"]),sim(a,row["away"])
            score=(hs+as_)/2
            ko=x.match_kickoff(m)
            if ko and score>=0.72:
                candidates.append((score,hs,as_,abs((ko-row["dt"]).total_seconds()),ko,m,h,a))
    if not candidates:return None,None,None
    candidates.sort(key=lambda z:(-z[0],z[3]))
    best=candidates[0]
    # Require convincing two-sided identity.
    if best[1] < 0.68 or best[2] < 0.68 or best[0] < 0.78:
        return None,None,(best[0],best[6],best[7])
    return best[4],best[5],(best[0],best[6],best[7])

def competition_key(m):
    for k in ("leagueId","tournamentId","competitionId"):
        v=m.get(k) if isinstance(m,dict) else None
        if v is not None:return (k,str(v))
    for k in ("leagueName","tournamentName","competitionName"):
        v=m.get(k) if isinstance(m,dict) else None
        if v:return (k,norm(v))
    return None

def history_xg5(target_m,target_dt,tid):
    target_comp=competition_key(target_m)
    vals=[]; seen=set()
    start=target_dt.date()-timedelta(days=1)
    for back in range(MAX_BACK_DAYS):
        dd=start-timedelta(days=back)
        for m in x.day_matches(dd):
            st,fin,can=x.s.status_flags(m)
            if not fin or can:continue
            ko=x.match_kickoff(m)
            if not ko or not ko<target_dt:continue
            if target_comp is not None and competition_key(m)!=target_comp:continue
            if str(tid) not in (x.team_id(m,"home"),x.team_id(m,"away")):continue
            mid=str(x.s.first(m,"id","matchId"))
            if mid in seen:continue
            seen.add(mid)
            try:val=x.xg_for_team(x.get_detail(mid),tid)
            except Exception:val=None
            if val is not None:
                vals.append(float(val))
                if len(vals)>=5:return sum(vals[:5])/5
    return None

def level(s,w):
    if s>=F_ELITE_SUM:return "ELITE"
    if s>=F_STRONG_SUM and w>=F_STRONG_WEAK:return "STRONG"
    return "BASE"

def wilson(w,n,z=1.96):
    if not n:return (float("nan"),float("nan"))
    p=w/n; d=1+z*z/n
    c=(p+z*z/(2*n))/d
    h=z*math.sqrt((p*(1-p)+z*z/(4*n))/n)/d
    return c-h,c+h

def summary(name,rows):
    n=len(rows); w=sum(r["goal"] for r in rows)
    p=w/n if n else float("nan"); lo,hi=wilson(w,n)
    print(f"{name}: N={n} wins={w} hit={p:.4%} Wilson95={lo:.4%}-{hi:.4%}")
    return n,w,p

def main():
    t=load_targets()
    rows=[]; misses=[]
    print(f"STEP37 targets={len(t)} frozen thresholds, improved target matcher")
    for i,r in enumerate(t,1):
        ko,m,diag=find_target(r)
        if not m:
            misses.append((r["date"],r["home"],r["away"],diag))
            continue
        hid=x.team_id(m,"home"); aid=x.team_id(m,"away")
        hx=history_xg5(m,ko,hid); ax=history_xg5(m,ko,aid)
        if hx is None or ax is None:
            continue
        sx=hx+ax; wx=min(hx,ax)
        rows.append({"goal":r["goal_before_ft"],"level":level(sx,wx),"league":r["league"]})
        if i%10==0:print(f"progress {i}/{len(t)} paired={len(rows)}",flush=True)

    print(f"paired={len(rows)}/{len(t)} target_misses={len(misses)}")
    print("FIRST MISSES")
    for q in misses[:15]:print(q)

    if len(rows)<85:
        raise RuntimeError(f"STEP37 coverage gate failed: only {len(rows)} paired; need >=85")

    b=summary("BASE comparator",rows)
    s=summary("STRONG+",[r for r in rows if r["level"] in ("STRONG","ELITE")])
    e=summary("ELITE",[r for r in rows if r["level"]=="ELITE"])
    print(f"lift_STRONG_pp={(s[2]-b[2])*100:.3f}")
    print(f"lift_ELITE_pp={(e[2]-b[2])*100:.3f}")

    print("BY LEAGUE")
    for lg in sorted(set(r["league"] for r in rows)):
        lr=[r for r in rows if r["league"]==lg]
        summary(f"{lg} BASE",lr)
        summary(f"{lg} STRONG+",[r for r in lr if r["level"] in ("STRONG","ELITE")])
        summary(f"{lg} ELITE",[r for r in lr if r["level"]=="ELITE"])

    print("STEP37 COMPLETE: coverage-expanded frozen evaluation. No threshold tuning performed.")

if __name__=="__main__":
    main()
