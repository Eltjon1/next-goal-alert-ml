import csv, math, statistics
from datetime import datetime, timedelta, timezone
import step32_365day_xg5 as x

REF="step34_understat_reference.csv"
MAX_BACK_DAYS=365

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
    # Daily listing usually carries league/competition identity above or inside match node.
    for k in ("leagueId","tournamentId","competitionId"):
        v=m.get(k) if isinstance(m,dict) else None
        if v is not None: return (k,str(v))
    # Fallback textual league fields.
    for k in ("leagueName","tournamentName","competitionName"):
        v=m.get(k) if isinstance(m,dict) else None
        if v: return (k,norm(v))
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
            try: val=x.xg_for_team(x.get_detail(mid),tid)
            except Exception: val=None
            if val is not None:
                rows.append((ko,mid,float(val)))
                if len(rows)>=5:
                    return rows
    return rows

def corr(a,b):
    if len(a)<3:return float("nan")
    ma,mb=statistics.mean(a),statistics.mean(b)
    va=sum((v-ma)**2 for v in a); vb=sum((v-mb)**2 for v in b)
    if va<=0 or vb<=0:return float("nan")
    return sum((u-ma)*(v-mb) for u,v in zip(a,b))/math.sqrt(va*vb)

def cls(sumx,weak):
    if sumx>=3.45:return "ELITE"
    if sumx>=2.90 and weak>=1.00:return "STRONG"
    return "BASE"

def main():
    refs=load_ref()
    pairs=[]
    matched=0
    print(f"STEP34 reference rows={len(refs)}")
    for r in refs:
        ko,m=find_target(r)
        if not m: continue
        matched+=1
        hid=x.team_id(m,"home"); aid=x.team_id(m,"away")
        hp=build_same_comp_history(m,ko,hid)
        ap=build_same_comp_history(m,ko,aid)
        if len(hp)<5 or len(ap)<5: continue
        fh=sum(v for _,_,v in hp[:5])/5
        fa=sum(v for _,_,v in ap[:5])/5
        fs=fh+fa; fw=min(fh,fa)
        us=r["sum_xg5"]; uw=r["weak_xg5"]
        pairs.append((us,uw,fs,fw,cls(us,uw),cls(fs,fw),r["home_team"],r["away_team"]))
        print(f'{r["home_team"]}-{r["away_team"]} | U sum={us:.3f} weak={uw:.3f} {cls(us,uw)} | F sum={fs:.3f} weak={fw:.3f} {cls(fs,fw)}')

    print(f"target_match={matched}/{len(refs)} paired_xg5={len(pairs)}/{len(refs)}")
    if len(pairs)<12:
        raise RuntimeError(f"Too few paired observations: {len(pairs)}")

    us=[p[0] for p in pairs]; uw=[p[1] for p in pairs]
    fs=[p[2] for p in pairs]; fw=[p[3] for p in pairs]
    mae_sum=statistics.mean(abs(a-b) for a,b in zip(us,fs))
    mae_weak=statistics.mean(abs(a-b) for a,b in zip(uw,fw))
    bias_sum=statistics.mean(b-a for a,b in zip(us,fs))
    agree=sum(p[4]==p[5] for p in pairs)/len(pairs)
    print(f"corr_sum={corr(us,fs):.4f} corr_weak={corr(uw,fw):.4f}")
    print(f"MAE_sum={mae_sum:.4f} MAE_weak={mae_weak:.4f} FotMob_minus_Understat_bias_sum={bias_sum:.4f}")
    print(f"class_agreement={agree:.4%} ({sum(p[4]==p[5] for p in pairs)}/{len(pairs)})")

    # Conservative promotion gate. Passing means provider migration looks sufficiently stable
    # to proceed to a larger frozen validation; it does NOT itself prove STEP25 hit rates.
    passed=(corr(us,fs)>=0.85 and corr(uw,fw)>=0.80 and agree>=0.80 and mae_sum<=0.40)
    print("STEP34 DECISION:", "PASS_TO_LARGER_VALIDATION" if passed else "RECALIBRATE_FOTMOB_THRESHOLDS")
    if not passed:
        raise RuntimeError("Provider migration gate failed; FotMob thresholds require recalibration.")

if __name__=="__main__":
    main()
