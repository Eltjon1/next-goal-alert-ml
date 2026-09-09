import scanner as s
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ=ZoneInfo("Europe/Rome")
TEAM_XG5_CACHE={}

def team_id(listing, side):
    obj=listing.get(side,{}) if isinstance(listing,dict) else {}
    v=s.first(obj,'id','teamId')
    return str(v) if v is not None else None

def fetch_team_payload(tid):
    errs=[]
    for url,params in [
        ('https://www.fotmob.com/api/data/teams',{'id':str(tid),'ccode3':'ITA'}),
        ('https://www.fotmob.com/api/teams',{'id':str(tid),'ccode3':'ITA'}),
    ]:
        try:
            return s.get_json(url,params)
        except Exception as e:
            errs.append(f"{url}: {e!r}")
    raise RuntimeError("team endpoint unavailable | "+" | ".join(errs))

def extract_match_date(d):
    st=d.get('status') if isinstance(d,dict) else None
    vals=[]
    if isinstance(st,dict):
        vals += [st.get('utcTime'), st.get('startTime')]
    vals += [d.get('utcTime') if isinstance(d,dict) else None,
             d.get('time') if isinstance(d,dict) else None]
    for v in vals:
        if isinstance(v,str) and len(v)>=10:
            return v
    return ""

def finished_match_nodes(payload,current_mid=None):
    rows=[]
    seen=set()
    for d in s.walk(payload):
        if not isinstance(d,dict): continue
        mid=s.first(d,'id','matchId')
        if mid is None or str(mid)==str(current_mid): continue
        if str(mid) in seen: continue

        st=d.get('status')
        finished=False
        if isinstance(st,dict):
            finished=bool(s.first(st,'finished',default=False))
            reason=str(s.first(st,'reason','status',default='')).lower()
            if reason in ('ft','finished','full-time','aet','after penalties'):
                finished=True

        home=d.get('home'); away=d.get('away')
        looks_match=isinstance(home,dict) and isinstance(away,dict)
        if finished and looks_match:
            seen.add(str(mid))
            rows.append((extract_match_date(d),str(mid),d))
    rows.sort(key=lambda x:x[0], reverse=True)
    return rows

def final_xg_for_team(detail, tid):
    shots=s.extract_shots(detail)
    if not shots:
        return None

    home_id=away_id=None
    for d in s.walk(detail):
        teams=d.get('teams') if isinstance(d,dict) else None
        if isinstance(teams,list) and len(teams)>=2 and all(isinstance(x,dict) for x in teams[:2]):
            ids=[s.first(x,'id','teamId') for x in teams[:2]]
            if all(x is not None for x in ids):
                home_id,away_id=str(ids[0]),str(ids[1]); break

    if str(tid)==home_id: side='home'
    elif str(tid)==away_id: side='away'
    else: return None

    return sum(float(x.get('xg') or 0) for x in shots if x.get('side')==side)

def fetch_team_xg5(tid,current_mid=None):
    key=(str(tid),str(current_mid))
    if key in TEAM_XG5_CACHE:return TEAM_XG5_CACHE[key]

    payload=fetch_team_payload(tid)
    nodes=finished_match_nodes(payload,current_mid=current_mid)

    vals=[]
    provenance=[]
    for dt,mid,_ in nodes[:15]:
        try:
            detail=s.fetch_match_details(mid)
            xg=final_xg_for_team(detail,tid)
            if xg is not None:
                vals.append(float(xg))
                provenance.append((dt,mid,float(xg)))
                if len(vals)>=5:break
        except Exception as e:
            provenance.append((dt,mid,f"ERR:{e!r}"))

    out=None
    if len(vals)>=5:
        out=sum(vals[:5])/5.0
    TEAM_XG5_CACHE[key]=(out,provenance)
    return TEAM_XG5_CACHE[key]

def get_recent_finished_matches(n=6):
    picked=[]
    today=datetime.now(TZ).date()
    for back in range(1,8):
        day=today-timedelta(days=back)
        payload=s.fetch_daily_matches(day.strftime("%Y%m%d"))
        for m in s.flatten_match_list(payload):
            st,fin,can=s.status_flags(m)
            if fin and not can:
                picked.append((day,m))
                if len(picked)>=n:return picked
    return picked

def main():
    picked=get_recent_finished_matches()
    print(f"STEP30 selected={len(picked)}",flush=True)
    if not picked:
        raise RuntimeError("No recent finished matches found")

    ok=0
    for day,m in picked:
        mid=str(s.first(m,'id','matchId'))
        home,away=s.team_names({},m)
        hid,aid=team_id(m,'home'),team_id(m,'away')

        hx,hprov=fetch_team_xg5(hid,mid)
        ax,aprov=fetch_team_xg5(aid,mid)

        sx=None if hx is None or ax is None else hx+ax
        wx=None if hx is None or ax is None else min(hx,ax)
        good=hx is not None and ax is not None
        ok+=int(good)

        level='XG5_UNAVAILABLE'
        if good:
            level='ELITE-prelive' if sx>=3.45 else ('STRONG-prelive' if sx>=2.90 and wx>=1.00 else 'BASE-prelive')

        print(f"\n{day} | {home}-{away} | {mid}",flush=True)
        print(f"home_xG5={hx} away_xG5={ax} sum={sx} weak={wx} | {level}",flush=True)
        print("home provenance:",hprov[:5],flush=True)
        print("away provenance:",aprov[:5],flush=True)

    print(f"\nSTEP30 XG5 success: {ok}/{len(picked)}",flush=True)
    if ok < max(2,len(picked)//2):
        raise RuntimeError(f"STEP30 insufficient xG5 reliability: {ok}/{len(picked)}")
    print("STEP30 PASS",flush=True)

if __name__=="__main__":
    main()
