import json
import scanner as s
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ=ZoneInfo("Europe/Rome")

def compact(obj, depth=0, max_depth=3):
    if depth > max_depth:
        return type(obj).__name__
    if isinstance(obj, dict):
        out={}
        for k,v in list(obj.items())[:40]:
            out[k]=compact(v,depth+1,max_depth)
        return out
    if isinstance(obj, list):
        return [compact(x,depth+1,max_depth) for x in obj[:5]]
    return obj

def team_ids_from_listing(m):
    home=m.get('home',{}) if isinstance(m,dict) else {}
    away=m.get('away',{}) if isinstance(m,dict) else {}
    return s.first(home,'id','teamId'), s.first(away,'id','teamId')

def get_recent_finished_match():
    today=datetime.now(TZ).date()
    for back in range(1,8):
        day=today-timedelta(days=back)
        payload=s.fetch_daily_matches(day.strftime("%Y%m%d"))
        for m in s.flatten_match_list(payload):
            st,fin,can=s.status_flags(m)
            if fin and not can:
                return day,m
    raise RuntimeError("No finished match found in last 7 days")

def probe_team_endpoint(team_id):
    attempts=[]
    candidates=[
        ('https://www.fotmob.com/api/teams',{'id':str(team_id),'ccode3':'ITA'}),
        ('https://www.fotmob.com/api/data/team',{'id':str(team_id),'ccode3':'ITA'})
    ]
    for url,params in candidates:
        try:
            payload=s.get_json(url,params)
            attempts.append({
                'url':url,
                'ok':True,
                'top_type':type(payload).__name__,
                'top_keys':list(payload.keys())[:80] if isinstance(payload,dict) else None,
                'sample':compact(payload)
            })
        except Exception as e:
            attempts.append({'url':url,'ok':False,'error':repr(e)})
    return attempts

def discover_match_like_nodes(payload):
    out=[]
    for d in s.walk(payload):
        if not isinstance(d,dict):
            continue
        keys=set(d.keys())
        if {'id','matchId'} & keys:
            if ({'home','away'} <= keys) or ('status' in keys) or ('time' in keys) or ('utcTime' in keys):
                out.append({
                    'keys':sorted(list(keys))[:50],
                    'id':s.first(d,'id','matchId'),
                    'status':d.get('status'),
                    'home':d.get('home'),
                    'away':d.get('away'),
                    'time':s.first(d,'time','utcTime','startTime')
                })
                if len(out)>=15:
                    break
    return out

def main():
    day,m=get_recent_finished_match()
    mid=str(s.first(m,'id','matchId'))
    home,away=s.team_names({},m)
    hid,aid=team_ids_from_listing(m)

    print(f"STEP29 target match: {day} | {home}-{away} | match_id={mid}",flush=True)
    print(f"listing home_id={hid} away_id={aid}",flush=True)
    print("listing keys:",sorted(m.keys()),flush=True)
    print("listing home object:",json.dumps(m.get('home'),ensure_ascii=False)[:2000],flush=True)
    print("listing away object:",json.dumps(m.get('away'),ensure_ascii=False)[:2000],flush=True)

    for label,tid in [('HOME',hid),('AWAY',aid)]:
        print(f"\n===== {label} TEAM {tid} =====",flush=True)
        attempts=probe_team_endpoint(tid)
        for a in attempts:
            print(json.dumps(a,ensure_ascii=False)[:12000],flush=True)

            if a.get('ok'):
                # refetch full payload for structural scan
                try:
                    payload=s.get_json(a['url'],{'id':str(tid),'ccode3':'ITA'})
                    nodes=discover_match_like_nodes(payload)
                    print("MATCH-LIKE NODES:",json.dumps(nodes,ensure_ascii=False)[:12000],flush=True)
                except Exception as e:
                    print("node scan error:",repr(e),flush=True)

    # Also inspect matchDetails shape and shot container for the target finished match
    print("\n===== MATCH DETAILS =====",flush=True)
    detail=s.fetch_match_details(mid)
    print("detail top keys:", list(detail.keys())[:100] if isinstance(detail,dict) else type(detail).__name__, flush=True)

    shot_lists=[]
    for d in s.walk(detail):
        if isinstance(d,dict) and isinstance(d.get('shots'),list):
            shot_lists.append({
                'parent_keys':sorted(list(d.keys()))[:50],
                'n_shots':len(d['shots']),
                'first_shot':d['shots'][0] if d['shots'] else None
            })
            if len(shot_lists)>=10:
                break
    print("shot containers:",json.dumps(shot_lists,ensure_ascii=False)[:12000],flush=True)
    print("extract_shots_count:",len(s.extract_shots(detail)),flush=True)

    print("\nSTEP29 DIAGNOSTIC COMPLETE",flush=True)

if __name__=="__main__":
    main()
