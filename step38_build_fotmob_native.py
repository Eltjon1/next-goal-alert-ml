
"""
STEP38 — Native FotMob xG5 dataset builder.

Purpose
-------
Build a substantially larger, provider-native dataset:
    FotMob prelive xG5 + frozen live BASE alert state -> goal_before_ft

No Understat->FotMob threshold transfer is used here.
The script reads step36_holdout_predictions.csv for the frozen live alert/target
labels, matches those matches to FotMob, reconstructs same-competition prior-5
FotMob xG with strict chronology, and writes an artifact CSV for later
chronological calibration/holdout analysis.

This step BUILDS the dataset only. It does not tune thresholds.
"""
import csv, os, math
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone
import step32_365day_xg5 as x

SOURCE = "step36_holdout_predictions.csv"
OUT = "step38_fotmob_native_dataset.csv"
MAX_BACK_DAYS = 365
MINUTE = 40
P_BASE = 0.80

ALIASES = {
    "manchesterunited":"manutd","manchestercity":"mancity",
    "tottenhamhotspur":"tottenham","wolverhamptonwanderers":"wolves",
    "brightonandhovealbion":"brighton","westhamunited":"westham",
    "newcastleunited":"newcastle","nottinghamforest":"nottmforest",
    "parissaintgermain":"psg","olympiquedemarseille":"marseille",
    "olympiquelyonnais":"lyon","borussiamonchengladbach":"gladbach",
    "bayernmunich":"bayernmunchen","internazionale":"inter",
    "intermilan":"inter","acmilan":"milan","hellasverona":"verona",
    "athleticclub":"athleticbilbao","realbetisbalompie":"realbetis",
    "rasenballsportleipzig":"rbleipzig","fckoln":"cologne",
    "fccologne":"cologne","bayer04leverkusen":"leverkusen",
}

def norm(s):
    z="".join(c.lower() for c in str(s) if c.isalnum())
    for junk in ("footballclub","futbolclub","calcio"):
        z=z.replace(junk,"")
    return ALIASES.get(z,z)

def sim(a,b):
    a,b=norm(a),norm(b)
    if a==b:return 1.0
    if a in b or b in a:return 0.96
    return SequenceMatcher(None,a,b).ratio()

def parse_dt(v):
    s=str(v).strip()
    try:
        dt=datetime.fromisoformat(s.replace("Z","+00:00"))
    except Exception:
        dt=datetime.fromisoformat(s[:10])
    if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def first_base_rows():
    rows=[]
    with open(SOURCE,encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                minute=int(float(r["minute"]))
                p=float(r["p_goal_before_ft"])
            except Exception:
                continue
            if minute < MINUTE or p < P_BASE:
                continue
            r["_dt"]=parse_dt(r["date"])
            r["_minute"]=minute
            r["_p"]=p
            rows.append(r)

    # one first BASE alert per Understat match, preserving STEP20+ convention
    rows.sort(key=lambda r:(r["_dt"], str(r["understat_id"]), r["_minute"]))
    first={}
    for r in rows:
        first.setdefault(str(r["understat_id"]), r)
    return list(first.values())

def find_target(row):
    candidates=[]
    for delta in (0,-1,1,-2,2):
        dd=row["_dt"].date()+timedelta(days=delta)
        for m in x.day_matches(dd):
            h,a=x.team_names(m)
            hs,as_=sim(h,row["home"]),sim(a,row["away"])
            score=(hs+as_)/2
            ko=x.match_kickoff(m)
            if ko and score>=0.72:
                candidates.append((score,hs,as_,abs((ko-row["_dt"]).total_seconds()),ko,m,h,a))
    if not candidates:return None,None,None
    candidates.sort(key=lambda z:(-z[0],z[3]))
    b=candidates[0]
    if b[1]<0.68 or b[2]<0.68 or b[0]<0.78:
        return None,None,(b[0],b[6],b[7])
    return b[4],b[5],b[0]

def competition_key(m):
    for k in ("leagueId","tournamentId","competitionId"):
        v=m.get(k) if isinstance(m,dict) else None
        if v is not None:return (k,str(v))
    for k in ("leagueName","tournamentName","competitionName"):
        v=m.get(k) if isinstance(m,dict) else None
        if v:return (k,norm(v))
    return None

def history_xg5(target_m,target_dt,tid):
    comp=competition_key(target_m)
    vals=[]; seen=set()
    start=target_dt.date()-timedelta(days=1)
    for back in range(MAX_BACK_DAYS):
        dd=start-timedelta(days=back)
        for m in x.day_matches(dd):
            st,fin,can=x.s.status_flags(m)
            if not fin or can: continue
            ko=x.match_kickoff(m)
            if not ko or not ko < target_dt: continue
            if comp is not None and competition_key(m)!=comp: continue
            if str(tid) not in (x.team_id(m,"home"),x.team_id(m,"away")): continue
            mid=str(x.s.first(m,"id","matchId"))
            if mid in seen: continue
            seen.add(mid)
            try: val=x.xg_for_team(x.get_detail(mid),tid)
            except Exception: val=None
            if val is not None:
                vals.append(float(val))
                if len(vals)>=5:
                    return sum(vals[:5])/5, vals[:5]
    return None, vals

def main():
    targets=first_base_rows()
    targets.sort(key=lambda r:r["_dt"])
    print(f"STEP38 BASE targets={len(targets)} date={targets[0]['date']}..{targets[-1]['date']}", flush=True)

    out=[]; miss_target=0; miss_xg5=0
    for i,r in enumerate(targets,1):
        ko,m,match_score=find_target(r)
        if not m:
            miss_target+=1
            continue
        hid=x.team_id(m,"home"); aid=x.team_id(m,"away")
        hx,hist_h=history_xg5(m,ko,hid)
        ax,hist_a=history_xg5(m,ko,aid)
        if hx is None or ax is None:
            miss_xg5+=1
            continue
        sx=hx+ax; wx=min(hx,ax)
        out.append({
            "understat_id":r["understat_id"],
            "date":r["date"],"league":r["league"],
            "home":r["home"],"away":r["away"],
            "minute":r["minute"],
            "score_home":r.get("score_home",""),
            "score_away":r.get("score_away",""),
            "current_total_goals":r.get("current_total_goals",""),
            "p_goal_before_ft":r["p_goal_before_ft"],
            "goal_before_ft":int(float(r["goal_before_ft"])),
            "fotmob_home_xg5":round(hx,6),
            "fotmob_away_xg5":round(ax,6),
            "fotmob_sum_xg5":round(sx,6),
            "fotmob_weak_xg5":round(wx,6),
            "fotmob_gap_xg5":round(abs(hx-ax),6),
            "target_match_similarity":round(float(match_score),4),
            "fotmob_target_kickoff":ko.isoformat(),
        })
        if i%50==0:
            print(f"progress={i}/{len(targets)} paired={len(out)} target_miss={miss_target} xg5_miss={miss_xg5}",flush=True)

    fields=list(out[0].keys()) if out else []
    with open(OUT,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(out)

    n=len(out); wins=sum(r["goal_before_ft"] for r in out)
    print(f"STEP38 paired={n}/{len(targets)} ({n/len(targets):.2%}) target_miss={miss_target} xg5_miss={miss_xg5}")
    print(f"STEP38 paired BASE hit={wins/n:.4%}" if n else "STEP38 no rows")
    if n:
        dates=sorted(r["date"] for r in out)
        print(f"STEP38 paired range={dates[0]}..{dates[-1]}")
        print("STEP38 by league")
        for lg in sorted(set(r["league"] for r in out)):
            z=[r for r in out if r["league"]==lg]
            print(f"{lg}: N={len(z)} hit={sum(r['goal_before_ft'] for r in z)/len(z):.4%}")

    # Need a genuinely larger provider-native dataset before tuning.
    if n < 500:
        raise RuntimeError(f"STEP38 sample too small for native calibration: {n}. Need >=500 paired BASE alerts.")
    print("STEP38 PASS: native FotMob dataset large enough for STEP39 chronological calibration/holdout.")

if __name__=="__main__":
    main()
