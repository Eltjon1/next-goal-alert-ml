
import csv, math, statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import step32_365day_xg5 as x

TARGETS="step36_goalft_targets.csv"

# Frozen from STEP35. Do not retune in STEP36.
F_STRONG_SUM=2.6055
F_STRONG_WEAK=0.9638
F_ELITE_SUM=3.1218

MAX_BACK_DAYS=240

def norm(s):
    return "".join(c.lower() for c in str(s) if c.isalnum())

def same_name(a,b):
    a,b=norm(a),norm(b)
    return a==b or a in b or b in a

def load_targets():
    out=[]
    with open(TARGETS,encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["dt"]=datetime.fromisoformat(r["date"]).replace(tzinfo=timezone.utc)
            r["goal_before_ft"]=int(float(r["goal_before_ft"]))
            r["minute"]=int(float(r["minute"]))
            r["p_goal_before_ft"]=float(r["p_goal_before_ft"])
            out.append(r)
    return out

def competition_key(m):
    for k in ("leagueId","tournamentId","competitionId"):
        v=m.get(k) if isinstance(m,dict) else None
        if v is not None:
            return (k,str(v))
    for k in ("leagueName","tournamentName","competitionName"):
        v=m.get(k) if isinstance(m,dict) else None
        if v:
            return (k,norm(v))
    return None

def find_target(row):
    day=row["dt"].date()
    for delta in (0,-1,1):
        dd=day+timedelta(days=delta)
        for m in x.day_matches(dd):
            h,a=x.team_names(m)
            if same_name(h,row["home"]) and same_name(a,row["away"]):
                ko=x.match_kickoff(m)
                if ko and abs((ko-row["dt"]).total_seconds()) <= 18*3600:
                    return ko,m
    return None,None

def history_xg5(target_m,target_dt,tid):
    target_comp=competition_key(target_m)
    vals=[]
    seen=set()
    start=target_dt.date()-timedelta(days=1)
    for back in range(MAX_BACK_DAYS):
        dd=start-timedelta(days=back)
        for m in x.day_matches(dd):
            st,fin,can=x.s.status_flags(m)
            if not fin or can:
                continue
            ko=x.match_kickoff(m)
            if not ko or not ko < target_dt:
                continue
            if target_comp is not None and competition_key(m) != target_comp:
                continue
            if str(tid) not in (x.team_id(m,"home"),x.team_id(m,"away")):
                continue
            mid=str(x.s.first(m,"id","matchId"))
            if mid in seen:
                continue
            seen.add(mid)
            try:
                val=x.xg_for_team(x.get_detail(mid),tid)
            except Exception:
                val=None
            if val is not None:
                vals.append(float(val))
                if len(vals)>=5:
                    return sum(vals[:5])/5
    return None

def level(sumx,weak):
    if sumx >= F_ELITE_SUM:
        return "ELITE"
    if sumx >= F_STRONG_SUM and weak >= F_STRONG_WEAK:
        return "STRONG"
    return "BASE"

def wilson(w,n,z=1.96):
    if n==0:return (float("nan"),float("nan"))
    p=w/n
    d=1+z*z/n
    c=(p+z*z/(2*n))/d
    h=z*math.sqrt((p*(1-p)+z*z/(4*n))/n)/d
    return c-h,c+h

def summarize(name, rows):
    n=len(rows)
    w=sum(r["goal"] for r in rows)
    hit=w/n if n else float("nan")
    lo,hi=wilson(w,n) if n else (float("nan"),float("nan"))
    print(f"{name}: N={n} wins={w} hit={hit:.4%} Wilson95={lo:.4%}-{hi:.4%}")
    return n,w,hit,lo,hi

def main():
    t=load_targets()
    print(f"STEP36 frozen validation targets={len(t)}")
    rows=[]
    miss_target=0
    miss_xg5=0

    for i,r in enumerate(t,1):
        ko,m=find_target(r)
        if not m:
            miss_target+=1
            continue
        hid=x.team_id(m,"home")
        aid=x.team_id(m,"away")
        hx=history_xg5(m,ko,hid)
        ax=history_xg5(m,ko,aid)
        if hx is None or ax is None:
            miss_xg5+=1
            continue
        sx=hx+ax
        wx=min(hx,ax)
        lv=level(sx,wx)
        rows.append({
            "goal":r["goal_before_ft"],
            "level":lv,
            "sum":sx,
            "weak":wx,
            "league":r["league"],
            "home":r["home"],
            "away":r["away"],
            "date":r["date"],
        })
        if i%10==0:
            print(f"progress {i}/{len(t)} paired={len(rows)}", flush=True)

    print(f"target_match_miss={miss_target} xg5_miss={miss_xg5} paired={len(rows)}/{len(t)}")
    if len(rows)<60:
        raise RuntimeError(f"STEP36 insufficient paired validation sample: {len(rows)}")

    base=rows
    strong=[r for r in rows if r["level"] in ("STRONG","ELITE")]
    elite=[r for r in rows if r["level"]=="ELITE"]

    b=summarize("BASE comparator",base)
    s=summarize("STRONG+",strong)
    e=summarize("ELITE",elite)

    print("BY LEAGUE")
    for lg in sorted(set(r["league"] for r in rows)):
        lr=[r for r in rows if r["league"]==lg]
        summarize(f"{lg} BASE",lr)
        summarize(f"{lg} STRONG+",[r for r in lr if r["level"] in ("STRONG","ELITE")])
        summarize(f"{lg} ELITE",[r for r in lr if r["level"]=="ELITE"])

    # Frozen validation decision: require positive lift over BASE and usable volume.
    strong_lift=s[2]-b[2] if s[0] else float("-inf")
    elite_lift=e[2]-b[2] if e[0] else float("-inf")
    print(f"lift_STRONG_pp={100*strong_lift:.3f}")
    print(f"lift_ELITE_pp={100*elite_lift:.3f}")

    passed=(s[0]>=20 and e[0]>=12 and strong_lift>0 and elite_lift>0)
    if passed:
        print("STEP36 PASS: frozen FotMob thresholds show direct goal_before_ft lift.")
        print("NEXT: production integration candidate, with rates labeled STEP36 validation not STEP25.")
    else:
        print("STEP36 GATED: do not promote FotMob STRONG/ELITE yet.")
        raise RuntimeError("Frozen FotMob thresholds did not pass direct goal_before_ft validation gate.")

if __name__=="__main__":
    main()
