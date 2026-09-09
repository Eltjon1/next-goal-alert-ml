
import csv, math, statistics
from datetime import datetime, timedelta, timezone
import step32_365day_xg5 as x

REF="step34_understat_reference.csv"
MAX_BACK_DAYS=365

UNDERSTAT_STRONG_SUM=2.90
UNDERSTAT_STRONG_WEAK=1.00
UNDERSTAT_ELITE_SUM=3.45

def norm(s):
    return "".join(c.lower() for c in str(s) if c.isalnum())

def load_ref():
    out=[]
    with open(REF,encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["dt"]=datetime.fromisoformat(r["date"]).replace(tzinfo=timezone.utc)
            for k in ("home_xg5","away_xg5","sum_xg5","weak_xg5"):
                r[k]=float(r[k])
            out.append(r)
    return out

def same_name(a,b):
    a,b=norm(a),norm(b)
    return a==b or a in b or b in a

def find_target(row):
    day=row["dt"].date()
    for delta in (0,-1,1):
        dd=day+timedelta(days=delta)
        for m in x.day_matches(dd):
            h,a=x.team_names(m)
            if same_name(h,row["home_team"]) and same_name(a,row["away_team"]):
                ko=x.match_kickoff(m)
                if ko and abs((ko-row["dt"]).total_seconds()) <= 18*3600:
                    return ko,m
    return None,None

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

def build_same_comp_history(target_m,target_dt,tid):
    target_comp=competition_key(target_m)
    rows=[]
    seen=set()
    start=target_dt.date()-timedelta(days=1)
    for back in range(MAX_BACK_DAYS):
        dd=start-timedelta(days=back)
        for m in x.day_matches(dd):
            st,fin,can=x.s.status_flags(m)
            if not fin or can: continue
            ko=x.match_kickoff(m)
            if not ko or not ko < target_dt: continue
            if target_comp is not None and competition_key(m) != target_comp: continue
            if str(tid) not in (x.team_id(m,"home"),x.team_id(m,"away")): continue
            mid=str(x.s.first(m,"id","matchId"))
            if mid in seen: continue
            seen.add(mid)
            try:
                val=x.xg_for_team(x.get_detail(mid),tid)
            except Exception:
                val=None
            if val is not None:
                rows.append((ko,mid,float(val)))
                if len(rows)>=5:
                    return rows
    return rows

def linfit(xv,yv):
    mx,my=statistics.mean(xv),statistics.mean(yv)
    vx=sum((z-mx)**2 for z in xv)
    if vx<=0:
        return 0.0,my
    b=sum((a-mx)*(b-my) for a,b in zip(xv,yv))/vx
    a=my-b*mx
    return a,b

def predict(a,b,x):
    return a+b*x

def invert(a,b,y):
    if abs(b)<1e-12:
        return float("nan")
    return (y-a)/b

def corr(a,b):
    if len(a)<3:return float("nan")
    ma,mb=statistics.mean(a),statistics.mean(b)
    va=sum((v-ma)**2 for v in a); vb=sum((v-mb)**2 for v in b)
    if va<=0 or vb<=0:return float("nan")
    return sum((u-ma)*(v-mb) for u,v in zip(a,b))/math.sqrt(va*vb)

def cls_under(sumx,weak):
    if sumx>=UNDERSTAT_ELITE_SUM:
        return "ELITE"
    if sumx>=UNDERSTAT_STRONG_SUM and weak>=UNDERSTAT_STRONG_WEAK:
        return "STRONG"
    return "BASE"

def cls_fotmob_raw(sumx,weak):
    if sumx>=UNDERSTAT_ELITE_SUM:
        return "ELITE"
    if sumx>=UNDERSTAT_STRONG_SUM and weak>=UNDERSTAT_STRONG_WEAK:
        return "STRONG"
    return "BASE"

def main():
    refs=load_ref()
    pairs=[]
    matched=0
    print(f"STEP35 reference rows={len(refs)}", flush=True)

    for r in refs:
        ko,m=find_target(r)
        if not m:
            continue
        matched+=1
        hid=x.team_id(m,"home"); aid=x.team_id(m,"away")
        hp=build_same_comp_history(m,ko,hid)
        ap=build_same_comp_history(m,ko,aid)
        if len(hp)<5 or len(ap)<5:
            continue
        fh=sum(v for _,_,v in hp[:5])/5
        fa=sum(v for _,_,v in ap[:5])/5
        fs=fh+fa; fw=min(fh,fa)
        pairs.append({
            "home":r["home_team"],"away":r["away_team"],
            "u_sum":r["sum_xg5"],"u_weak":r["weak_xg5"],
            "f_sum":fs,"f_weak":fw
        })

    print(f"target_match={matched}/{len(refs)} paired_xg5={len(pairs)}/{len(refs)}", flush=True)
    if len(pairs)<12:
        raise RuntimeError(f"Too few paired observations: {len(pairs)}")

    u_sum=[p["u_sum"] for p in pairs]
    u_weak=[p["u_weak"] for p in pairs]
    f_sum=[p["f_sum"] for p in pairs]
    f_weak=[p["f_weak"] for p in pairs]

    a_s,b_s=linfit(f_sum,u_sum)
    a_w,b_w=linfit(f_weak,u_weak)

    strong_sum_f=invert(a_s,b_s,UNDERSTAT_STRONG_SUM)
    elite_sum_f=invert(a_s,b_s,UNDERSTAT_ELITE_SUM)
    strong_weak_f=invert(a_w,b_w,UNDERSTAT_STRONG_WEAK)

    print(f"corr_sum={corr(u_sum,f_sum):.4f} corr_weak={corr(u_weak,f_weak):.4f}", flush=True)
    print(f"Understat_sum ≈ {a_s:.4f} + {b_s:.4f}*FotMob_sum", flush=True)
    print(f"Understat_weak ≈ {a_w:.4f} + {b_w:.4f}*FotMob_weak", flush=True)
    print(f"FotMob-equivalent STRONG sum threshold ≈ {strong_sum_f:.4f}", flush=True)
    print(f"FotMob-equivalent STRONG weak threshold ≈ {strong_weak_f:.4f}", flush=True)
    print(f"FotMob-equivalent ELITE sum threshold ≈ {elite_sum_f:.4f}", flush=True)

    raw_agree=0
    mapped_agree=0
    for p in pairs:
        ucls=cls_under(p["u_sum"],p["u_weak"])
        raw=cls_fotmob_raw(p["f_sum"],p["f_weak"])
        if p["f_sum"]>=elite_sum_f:
            mapped="ELITE"
        elif p["f_sum"]>=strong_sum_f and p["f_weak"]>=strong_weak_f:
            mapped="STRONG"
        else:
            mapped="BASE"
        raw_agree += int(raw==ucls)
        mapped_agree += int(mapped==ucls)
        print(f'{p["home"]}-{p["away"]} | U={ucls} rawF={raw} mappedF={mapped}', flush=True)

    raw_rate=raw_agree/len(pairs)
    mapped_rate=mapped_agree/len(pairs)
    print(f"raw_class_agreement={raw_rate:.4%} ({raw_agree}/{len(pairs)})", flush=True)
    print(f"mapped_class_agreement={mapped_rate:.4%} ({mapped_agree}/{len(pairs)})", flush=True)

    # This is only a calibration transfer study.
    # Gate: mapping should materially improve classification agreement.
    if mapped_rate < raw_rate + 0.10:
        raise RuntimeError("STEP35 mapping did not improve class agreement enough.")
    print("STEP35 PASS: provider calibration mapping is useful.", flush=True)
    print("NEXT: validate mapped FotMob thresholds directly against goal_before_ft before production.", flush=True)

if __name__=="__main__":
    main()
