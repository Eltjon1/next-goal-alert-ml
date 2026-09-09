import scanner as s

TEAM_XG5_CACHE={}

def team_id(listing, side):
    obj=listing.get(side,{}) if isinstance(listing,dict) else {}
    v=s.first(obj,'id','teamId')
    return str(v) if v is not None else None

def final_xg(detail, tid):
    shots=s.extract_shots(detail)
    home_id=away_id=None
    for d in s.walk(detail):
        teams=d.get('teams') if isinstance(d,dict) else None
        if isinstance(teams,list) and len(teams)>=2 and all(isinstance(x,dict) for x in teams[:2]):
            ids=[s.first(x,'id','teamId') for x in teams[:2]]
            if all(x is not None for x in ids):
                home_id,away_id=str(ids[0]),str(ids[1]); break
    side='home' if str(tid)==home_id else ('away' if str(tid)==away_id else None)
    if side is None:return None
    vals=[float(x['xg']) for x in shots if x.get('side')==side]
    return sum(vals) if vals else 0.0

def fetch_team_xg5(tid,current_mid=None):
    if not tid:return None
    if tid in TEAM_XG5_CACHE:return TEAM_XG5_CACHE[tid]
    payload=None
    for u,p in [
        ('https://www.fotmob.com/api/teams',{'id':tid,'ccode3':'ITA'}),
        ('https://www.fotmob.com/api/data/team',{'id':tid,'ccode3':'ITA'})
    ]:
        try:
            payload=s.get_json(u,p); break
        except Exception: pass
    if payload is None:
        TEAM_XG5_CACHE[tid]=None; return None

    mids=[]
    for d in s.walk(payload):
        mid=s.first(d,'id','matchId')
        if mid is None or str(mid)==str(current_mid):continue
        st=d.get('status') if isinstance(d,dict) else None
        if isinstance(st,dict):
            finished=bool(s.first(st,'finished',default=False))
            reason=str(s.first(st,'reason','status',default='')).lower()
            if finished or reason in ('ft','finished','aet','after penalties'):
                mids.append(str(mid))

    vals=[]
    for mid in list(dict.fromkeys(mids))[:12]:
        try:
            x=final_xg(s.fetch_match_details(mid),tid)
            if x is not None:
                vals.append(float(x))
                if len(vals)>=5:break
        except Exception:pass

    out=sum(vals)/len(vals) if len(vals)>=5 else None
    TEAM_XG5_CACHE[tid]=out
    return out

def prelive(listing):
    mid=str(s.first(listing,'id','matchId',default=''))
    hx=fetch_team_xg5(team_id(listing,'home'),mid)
    ax=fetch_team_xg5(team_id(listing,'away'),mid)
    if hx is None or ax is None:
        return {'home_xg5':hx,'away_xg5':ax,'sum_xg5':None,'weak_xg5':None}
    return {'home_xg5':hx,'away_xg5':ax,'sum_xg5':hx+ax,'weak_xg5':min(hx,ax)}

def level(f,p,pre):
    if f['minute']<40 or p<0.80:return None
    sx,wx=pre.get('sum_xg5'),pre.get('weak_xg5')
    if sx is not None and sx>=3.45:return 'ELITE'
    if sx is not None and wx is not None and sx>=2.90 and wx>=1.00:return 'STRONG'
    return 'BASE'

def one_scan():
    fixtures=s.flatten_match_list(s.fetch_daily_matches())
    live=[]
    for m in fixtures:
        st,fin,can=s.status_flags(m)
        if st and not fin and not can:live.append(m)

    print('STEP27 live fixtures:',len(live),flush=True)
    if not live:
        print('STEP27 API OK: daily FotMob feed reachable; no live fixtures at this instant.',flush=True)

    for m in live:
        mid=str(s.first(m,'id','matchId'))
        home,away=s.team_names({},m)
        try:
            pre=prelive(m)
            print(f'XG5 {home}-{away}: home={pre["home_xg5"]} away={pre["away_xg5"]} sum={pre["sum_xg5"]} weak={pre["weak_xg5"]}',flush=True)
            detail=s.fetch_match_details(mid)
            f=s.features_from_match(detail,m)
            if f:
                p=s.predict_goal_ft(f); lev=level(f,p,pre)
                print(f'LIVE minute={f["minute"]} score={f["score_home"]}-{f["score_away"]} p={p:.3f} level={lev}',flush=True)
        except Exception as e:
            print(f'STEP27 error {home}-{away}: {e!r}',flush=True)

if __name__=='__main__':
    one_scan()
