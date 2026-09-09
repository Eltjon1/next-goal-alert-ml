import scanner as s
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TZ=ZoneInfo("Europe/Rome")
DAILY_CACHE={}
DETAIL_CACHE={}

def parse_dt(v):
    if isinstance(v,(int,float)):
        if v > 1e12: v = v/1000
        return datetime.fromtimestamp(v,tz=timezone.utc)
    if isinstance(v,str):
        x=v.strip().replace("Z","+00:00")
        try:
            dt=datetime.fromisoformat(x)
            if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None
    return None

def match_kickoff(m):
    st=m.get("status") if isinstance(m,dict) else None
    vals=[]
    if isinstance(st,dict):
        vals += [st.get("utcTime"),st.get("startTime")]
    vals += [
        m.get("time") if isinstance(m,dict) else None,
        m.get("timeTS") if isinstance(m,dict) else None,
        m.get("utcTime") if isinstance(m,dict) else None,
    ]
    for v in vals:
        dt=parse_dt(v)
        if dt is not None:
            return dt
    return None

def daily(date_obj):
    key=date_obj.strftime("%Y%m%d")
    if key not in DAILY_CACHE:
        DAILY_CACHE[key]=s.fetch_daily_matches(key)
    return DAILY_CACHE[key]

def flattened_day(date_obj):
    return s.flatten_match_list(daily(date_obj))

def team_in_match(m, tid):
    tid=str(tid)
    for side in ("home","away"):
        obj=m.get(side,{}) if isinstance(m,dict) else {}
        mid=s.first(obj,"id","teamId")
        if mid is not None and str(mid)==tid:
            return True
    return False

def team_side(m, tid):
    tid=str(tid)
    for side in ("home","away"):
        obj=m.get(side,{}) if isinstance(m,dict) else {}
        mid=s.first(obj,"id","teamId")
        if mid is not None and str(mid)==tid:
            return side
    return None

def opponent_name(m, tid):
    side=team_side(m,tid)
    other="away" if side=="home" else "home"
    obj=m.get(other,{}) if isinstance(m,dict) else {}
    return s.first(obj,"name","longName",default="?")

def get_detail(mid):
    mid=str(mid)
    if mid not in DETAIL_CACHE:
        DETAIL_CACHE[mid]=s.fetch_match_details(mid)
    return DETAIL_CACHE[mid]

def team_final_xg_from_detail(detail, tid):
    shots=s.extract_shots(detail)
    if not shots:
        return None
    tid=str(tid)
    vals=[]
    for sh in shots:
        sh_tid=sh.get("team_id")
        if sh_tid is not None and str(sh_tid)==tid:
            vals.append(float(sh.get("xg") or 0.0))
    if vals:
        return sum(vals)

    # fallback via header team IDs -> side
    home_id=away_id=None
    for d in s.walk(detail):
        teams=d.get("teams") if isinstance(d,dict) else None
        if isinstance(teams,list) and len(teams)>=2 and all(isinstance(x,dict) for x in teams[:2]):
            ids=[s.first(x,"id","teamId") for x in teams[:2]]
            if all(x is not None for x in ids):
                home_id,away_id=str(ids[0]),str(ids[1]); break
    side="home" if tid==home_id else ("away" if tid==away_id else None)
    if side is None:
        return None
    vals=[float(sh.get("xg") or 0.0) for sh in shots if sh.get("side")==side]
    return sum(vals) if vals else None

def collect_last5_by_daily_scan(tid, target_dt, max_back_days=90):
    found=[]
    seen=set()
    start_date=(target_dt.astimezone(TZ).date()-timedelta(days=1))

    for back in range(max_back_days):
        day=start_date-timedelta(days=back)
        for m in flattened_day(day):
            if not team_in_match(m,tid):
                continue
            mid=s.first(m,"id","matchId")
            if mid is None or str(mid) in seen:
                continue
            ko=match_kickoff(m)
            if ko is None or not (ko < target_dt):
                continue
            st,fin,can=s.status_flags(m)
            if not fin or can:
                continue
            seen.add(str(mid))
            found.append((ko,str(mid),m))
        if len(found)>=8:
            break

    found.sort(key=lambda x:x[0], reverse=True)

    usable=[]
    for ko,mid,m in found:
        try:
            xg=team_final_xg_from_detail(get_detail(mid),tid)
        except Exception as e:
            xg=None
        if xg is not None:
            usable.append({
                "kickoff":ko,
                "match_id":mid,
                "opponent":opponent_name(m,tid),
                "xg":float(xg)
            })
        if len(usable)>=5:
            break

    if len(usable)!=5:
        return None, usable

    avg=sum(x["xg"] for x in usable)/5.0
    return avg, usable

def recent_finished_targets(n=6):
    today=datetime.now(TZ).date()
    out=[]
    for back in range(1,8):
        day=today-timedelta(days=back)
        for m in flattened_day(day):
            st,fin,can=s.status_flags(m)
            if fin and not can:
                ko=match_kickoff(m)
                if ko:
                    out.append((ko,m))
                    if len(out)>=n:
                        return out
    return out

def main():
    targets=recent_finished_targets(6)
    print(f"STEP31 targets={len(targets)}",flush=True)
    if not targets:
        raise RuntimeError("No recent finished targets")

    ok=0
    for target_dt,m in targets:
        mid=str(s.first(m,"id","matchId"))
        home,away=s.team_names({},m)
        hid=str(s.first(m.get("home",{}),"id","teamId"))
        aid=str(s.first(m.get("away",{}),"id","teamId"))

        hx,hprov=collect_last5_by_daily_scan(hid,target_dt)
        ax,aprov=collect_last5_by_daily_scan(aid,target_dt)

        sx=None if hx is None or ax is None else hx+ax
        wx=None if hx is None or ax is None else min(hx,ax)
        good=hx is not None and ax is not None
        ok+=int(good)

        level="XG5_UNAVAILABLE"
        if good:
            level="ELITE-prelive" if sx>=3.45 else ("STRONG-prelive" if sx>=2.90 and wx>=1.00 else "BASE-prelive")

        print(f"\nTARGET {target_dt.isoformat()} | {home}-{away} | {mid}",flush=True)
        print(f"home_xG5={hx} away_xG5={ax} sum={sx} weak={wx} | {level}",flush=True)
        print("HOME LAST5:",flush=True)
        for r in hprov: print(r,flush=True)
        print("AWAY LAST5:",flush=True)
        for r in aprov: print(r,flush=True)

        # strict chronology assertion
        for r in hprov+aprov:
            assert r["kickoff"] < target_dt, f"LEAKAGE {r['match_id']} >= target"
        if hx is not None: assert len(hprov)==5
        if ax is not None: assert len(aprov)==5

    print(f"\nSTEP31 xG5 success={ok}/{len(targets)}",flush=True)
    print(f"daily_feeds_used={len(DAILY_CACHE)} match_details_used={len(DETAIL_CACHE)}",flush=True)
    if ok < max(4, len(targets)-1):
        raise RuntimeError(f"STEP31 insufficient coverage: {ok}/{len(targets)}")
    print("STEP31 PASS: daily-range history resolver is viable.",flush=True)

if __name__=="__main__":
    main()
