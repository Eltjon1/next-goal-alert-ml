import scanner as s
import step26_runtime as r
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ=ZoneInfo("Europe/Rome")

def finished_matches_for_date(date_yyyymmdd):
    payload=s.fetch_daily_matches(date_yyyymmdd)
    out=[]
    for m in s.flatten_match_list(payload):
        st,fin,can=s.status_flags(m)
        if fin and not can:
            out.append(m)
    return out

def main():
    # Search backwards until we get enough recently finished matches.
    picked=[]
    today=datetime.now(TZ).date()
    for back in range(1,8):
        day=today-timedelta(days=back)
        ms=finished_matches_for_date(day.strftime("%Y%m%d"))
        for m in ms:
            picked.append((day,m))
            if len(picked)>=6:
                break
        if len(picked)>=6:
            break

    print(f"STEP28 finished matches selected: {len(picked)}", flush=True)
    if not picked:
        raise RuntimeError("No recently finished FotMob matches found in previous 7 days")

    ok=0
    for day,m in picked:
        mid=str(s.first(m,'id','matchId'))
        home,away=s.team_names({},m)
        hx=r.fetch_team_xg5(r.team_id(m,'home'),mid)
        ax=r.fetch_team_xg5(r.team_id(m,'away'),mid)
        sx=None if hx is None or ax is None else hx+ax
        wx=None if hx is None or ax is None else min(hx,ax)
        good=(hx is not None and ax is not None)
        ok+=int(good)
        level=""
        if good:
            level="ELITE-prelive" if sx>=3.45 else ("STRONG-prelive" if sx>=2.90 and wx>=1.00 else "BASE-prelive")
        print(
            f"{day} | {home}-{away} | match_id={mid} | "
            f"home_xG5={hx} away_xG5={ax} sum_xG5={sx} weak_xG5={wx} | "
            f"{level or 'XG5_UNAVAILABLE'}",
            flush=True
        )

    print(f"STEP28 XG5 success: {ok}/{len(picked)}", flush=True)
    if ok==0:
        raise RuntimeError("xG5 reconstruction failed on all sampled finished matches")
    if ok < max(2, len(picked)//2):
        raise RuntimeError(f"xG5 reconstruction too unreliable: {ok}/{len(picked)}")

    print("STEP28 PASS: FotMob rolling xG5 reconstruction works on recent finished matches.", flush=True)

if __name__=="__main__":
    main()
