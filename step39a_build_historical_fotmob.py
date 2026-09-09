
"""
STEP39-A — Large historical FotMob-native xG5 build.

Source:
  step39a_historical_alerts.csv
  (STEP14C frozen GOAL_FT holdout alerts; one alert row per match/target)

Goal:
  Reconstruct provider-native FotMob same-competition xG5 for historical alerts
  and build a large dataset for later chronological calibration/holdout.

No threshold tuning in this step.
"""

import csv, math
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone
import step32_365day_xg5 as x

SOURCE="step39a_historical_alerts.csv"
OUT="step39a_fotmob_native_historical.csv"
MAX_BACK_DAYS=365

ALIASES = {
    "manchesterunited":"manutd","manchestercity":"mancity",
    "tottenhamhotspur":"tottenham","wolverhamptonwanderers":"wolves",
    "brightonandhovealbion":"brighton","westhamunited":"westham",
    "newcastleunited":"newcastle","nottinghamforest":"nottmforest",
    "parissaintgermain":"psg","olympiquedemarseille":"marseille",
    "olympiquelyonnais":"lyon","borussiamonchengladbach":"gladbach",
    "borussiamgladbach":"gladbach","bayernmunich":"bayernmunchen",
    "internazionale":"inter","intermilan":"inter","acmilan":"milan",
    "hellasverona":"verona","athleticclub":"athleticbilbao",
    "realbetisbalompie":"realbetis","rasenballsportleipzig":"rbleipzig",
    "fckoln":"cologne","fccologne":"cologne","bayer04leverkusen":"leverkusen",
    "parmacalcio1913":"parma","stpetersburg":"zenit",
}

def norm(s):
    z="".join(c.lower() for c in str(s) if c.isalnum())
    for junk in ("footballclub","futbolclub","calcio1913","calcio"):
        z=z.replace(junk,"")
    return ALIASES.get(z,z)

def sim(a,b):
    a,b=norm(a),norm(b)
    if a==b:return 1.0
    if a in b or b in a:return 0.96
    return SequenceMatcher(None,a,b).ratio()

def parse_dt(v):
    s=str(v).strip()
    try: dt=datetime.fromisoformat(s.replace("Z","+00:00"))
    except Exception: dt=datetime.fromisoformat(s[:10])
    if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def load_alerts():
    rows=[]
    with open(SOURCE,encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if str(r.get("target","")).strip()!="GOAL_FT":
                continue
            try:
                p=float(r["p"])
                minute=int(float(r["minute"]))
                success=int(float(r["success"]))
            except Exception:
                continue
            if minute < 40 or p < 0.80:
                continue
            r["_dt"]=parse_dt(r["date"])
            r["_p"]=p
            r["_success"]=success
            rows.append(r)
    rows.sort(key=lambda r:(r["_dt"],str(r["match_id"])))
    # First per match defensively
    first={}
    for r in rows:
        first.setdefault(str(r["match_id"]),r)
    return list(first.values())

def find_target(row):
    cands=[]
    for delta in (0,-1,1,-2,2):
        dd=row["_dt"].date()+timedelta(days=delta)
        for m in x.day_matches(dd):
            h,a=x.team_names(m)
            hs,as_=sim(h,row["home"]),sim(a,row["away"])
            score=(hs+as_)/2
            ko=x.match_kickoff(m)
            if ko and score>=0.70:
                cands.append((score,hs,as_,abs((ko-row["_dt"]).total_seconds()),ko,m,h,a))
    if not cands:return None,None,None
    cands.sort(key=lambda z:(-z[0],z[3]))
    b=cands[0]
    if b[1]<0.66 or b[2]<0.66 or b[0]<0.76:
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
                    return sum(vals[:5])/5
    return None

def main():
    alerts=load_alerts()
    print(f"STEP39A frozen GOAL_FT alerts={len(alerts)}")
    if alerts:
        print(f"range={alerts[0]['date']}..{alerts[-1]['date']}")

    out=[]; miss_target=0; miss_xg5=0
    for i,r in enumerate(alerts,1):
        ko,m,ms=find_target(r)
        if not m:
            miss_target+=1
            continue
        hid=x.team_id(m,"home"); aid=x.team_id(m,"away")
        hx=history_xg5(m,ko,hid); ax=history_xg5(m,ko,aid)
        if hx is None or ax is None:
            miss_xg5+=1
            continue
        out.append({
            "match_id":r["match_id"],
            "date":r["date"],"league":r["league"],"season":r.get("season",""),
            "home":r["home"],"away":r["away"],
            "minute":r["minute"],"score_home":r["score_home"],"score_away":r["score_away"],
            "current_total_goals":r["current_total_goals"],
            "p_goal_before_ft":r["p"],
            "goal_before_ft":r["success"],
            "fotmob_home_xg5":round(hx,6),
            "fotmob_away_xg5":round(ax,6),
            "fotmob_sum_xg5":round(hx+ax,6),
            "fotmob_weak_xg5":round(min(hx,ax),6),
            "fotmob_gap_xg5":round(abs(hx-ax),6),
            "target_match_similarity":round(float(ms),4),
            "fotmob_target_kickoff":ko.isoformat(),
        })
        if i%100==0:
            print(f"progress={i}/{len(alerts)} paired={len(out)} target_miss={miss_target} xg5_miss={miss_xg5}",flush=True)

    if out:
        with open(OUT,"w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=list(out[0].keys()))
            w.writeheader(); w.writerows(out)

    n=len(out); total=len(alerts)
    print(f"STEP39A paired={n}/{total} ({n/total:.2%}) target_miss={miss_target} xg5_miss={miss_xg5}")
    if n:
        wins=sum(int(r["goal_before_ft"]) for r in out)
        print(f"paired BASE hit={wins/n:.4%}")
        for lg in sorted(set(r["league"] for r in out)):
            z=[r for r in out if r["league"]==lg]
            print(f"{lg}: N={len(z)} hit={sum(int(q['goal_before_ft']) for q in z)/len(z):.4%}")

    if n < 500:
        raise RuntimeError(f"STEP39A insufficient native historical sample: {n}. Need >=500.")
    print("STEP39A PASS: large historical FotMob-native dataset ready.")
    print("NEXT: merge with STEP38 recent sample and make chronological discovery/holdout split.")

if __name__=="__main__":
    main()
