
import os, time, math, re
from datetime import datetime
from zoneinfo import ZoneInfo
import requests, numpy as np

MODEL_PACK={"features":["minute","remaining_90","score_home","score_away","score_diff","current_total_goals","home_shots","away_shots","total_shots","shot_diff","home_sot","away_sot","total_sot","sot_diff","shots_last5","sot_last5","xg_last5","shots_last10","sot_last10","xg_last10","xg_live_home","xg_live_away","xg_live_total","xg_live_diff"],"scaler_mean":[45.0,45.0,0.6656934550923833,0.49752990772423916,0.16816354736814418,1.1632233628166226,6.50819219374323,5.17021876935364,11.67841096309687,1.3379734243895907,2.151251903979646,1.7176431063383093,3.8688950103179556,0.43360879764133686,1.335669519348259,0.44657259751843004,0.13870721791941817,2.6115092431187725,0.8720131132488289,0.27044368174236144,0.6732461165857774,0.5091311798855169,1.1823772970988597,0.1641149365823211],"scaler_scale":[23.38090388900024,23.38090388900024,0.9175760604520324,0.7799578361606657,1.1414825423114432,1.2639532077590545,4.78395388662296,4.028766454324404,7.382598363141056,4.871507905586946,2.012598744739734,1.7265073741824268,2.963031778503878,2.298522464637804,1.1296295952808353,0.6614471951009604,0.22038644499771812,1.6219646937356726,0.9332907853743133,0.31127688065105813,0.6743036643149128,0.558923905702311,0.9569690411748806,0.786366951772772],"model_coef":[-0.9012289643287659,0.9012289643287659,0.04023432731628418,0.05469736456871033,-0.005015412345528603,0.06285302340984344,0.08362686634063721,0.09276248514652252,0.10483691096305847,0.005389376077800989,-0.026865612715482712,-0.03093494474887848,-0.036273080855607986,-0.00033189443638548255,-0.01183450035750866,-0.0022112801671028137,0.05587688088417053,0.03686065226793289,0.025074802339076996,0.04686042293906212,0.06010506674647331,0.04075343906879425,0.06612110882997513,0.022603241726756096],"model_intercept":1.8552980422973633,"cal_coef":0.6689785195815504,"cal_intercept":0.023451796178657145,"rules":{"base_minute":40,"base_p":0.8,"strong_xg_low":1.26,"strong_xg_high":1.75,"strong_sot_low":4,"strong_sot_high":5,"elite_minute_low":40,"elite_minute_high":44},"validated_reference":{"external_recent_base_hit":0.866929,"external_recent_base_n":1270,"strong_xg_hit":0.870416,"strong_xg_n":409,"minute_xg_hit":0.877238,"minute_xg_n":391,"sot45_hit":0.879418,"sot45_n":481,"xg10_hit":0.880597,"xg10_n":335}}
TZ=ZoneInfo('Europe/Rome')
SCAN_EVERY_SECONDS=int(os.getenv('SCAN_EVERY_SECONDS','60'))
MIN_ALERT_LEVEL=os.getenv('MIN_ALERT_LEVEL','BASE').upper()
BOT_TOKEN=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
CHAT_ID=os.getenv('TELEGRAM_CHAT_ID','').strip()
HEADERS={'User-Agent':'Mozilla/5.0 (Android 13; Mobile) AppleWebKit/537.36 Chrome/140 Safari/537.36','Accept':'application/json,text/plain,*/*','Referer':'https://www.fotmob.com/'}
seen=set()

def get_json(url, params=None, timeout=20):
    r=requests.get(url,params=params,headers=HEADERS,timeout=timeout); r.raise_for_status(); return r.json()

def fetch_daily_matches(date=None):
    date=date or datetime.now(TZ).strftime('%Y%m%d')
    cand=[('https://www.fotmob.com/api/data/matches',{'date':date,'timezone':'Europe/Rome','ccode3':'ITA'}),('https://www.fotmob.com/api/matches',{'date':date})]
    errs=[]
    for u,p in cand:
        try:return get_json(u,p)
        except Exception as e: errs.append(str(e))
    raise RuntimeError('daily endpoint unavailable: '+' | '.join(errs))

def fetch_match_details(mid):
    cand=[('https://www.fotmob.com/api/data/matchDetails',{'matchId':str(mid)}),('https://www.fotmob.com/api/matchDetails',{'matchId':str(mid)})]
    errs=[]
    for u,p in cand:
        try:return get_json(u,p)
        except Exception as e: errs.append(str(e))
    raise RuntimeError('matchDetails unavailable: '+' | '.join(errs))

def walk(o):
    if isinstance(o,dict):
        yield o
        for v in o.values(): yield from walk(v)
    elif isinstance(o,list):
        for v in o: yield from walk(v)

def first(d,*keys,default=None):
    for k in keys:
        if isinstance(d,dict) and d.get(k) is not None:return d[k]
    return default

def flatten_match_list(payload):
    out={}
    for d in walk(payload):
        mid=first(d,'id','matchId'); home=d.get('home') if isinstance(d,dict) else None; away=d.get('away') if isinstance(d,dict) else None; status=d.get('status') if isinstance(d,dict) else None
        if mid is not None and isinstance(home,dict) and isinstance(away,dict) and isinstance(status,dict):
            if ('name' in home or 'teamName' in home) and ('name' in away or 'teamName' in away): out[str(mid)]=d
    return list(out.values())

def status_flags(m):
    s=m.get('status',{}); started=bool(first(s,'started','ongoing',default=False)); finished=bool(first(s,'finished',default=False)); cancelled=bool(first(s,'cancelled',default=False)); reason=str(first(s,'reason','status',default=''))
    if not started and not finished and ('liveTime' in s or reason in ['1H','2H','HT','ET']):started=True
    return started,finished,cancelled

def current_minute_from_detail(detail):
    vals=[]
    for d in walk(detail):
        if not isinstance(d,dict):continue
        lt=d.get('liveTime')
        if isinstance(lt,dict):
            for k in ('short','long'):
                m=re.search(r'(\d{1,3})',str(lt.get(k,'')))
                if m:return int(m.group(1))
        elif isinstance(lt,str):
            m=re.search(r'(\d{1,3})',lt)
            if m:return int(m.group(1))
        for k in ('currentMinute','minute','min'):
            v=d.get(k)
            if isinstance(v,(int,float)) and 0<=v<=130: vals.append(float(v))
    return int(min(max(vals),90)) if vals else None

def parse_score(detail,listing=None):
    for d in walk(detail):
        teams=d.get('teams') if isinstance(d,dict) else None
        if isinstance(teams,list) and len(teams)>=2 and all(isinstance(x,dict) for x in teams[:2]):
            vals=[]
            for t in teams[:2]:
                sc=first(t,'score','currentScore')
                if isinstance(sc,(int,float)) or (isinstance(sc,str) and sc.isdigit()): vals.append(int(sc))
            if len(vals)==2:return vals[0],vals[1]
    if listing:
        try:return int(first(listing.get('home',{}),'score',default=0) or 0),int(first(listing.get('away',{}),'score',default=0) or 0)
        except:return 0,0
    return 0,0

def team_names(detail,listing=None):
    if listing:return str(first(listing.get('home',{}),'name','teamName',default='HOME')),str(first(listing.get('away',{}),'name','teamName',default='AWAY'))
    return 'HOME','AWAY'

def extract_shots(detail):
    home_id=away_id=None
    for d in walk(detail):
        teams=d.get('teams') if isinstance(d,dict) else None
        if isinstance(teams,list) and len(teams)>=2 and all(isinstance(x,dict) for x in teams[:2]):
            ids=[first(x,'id','teamId') for x in teams[:2]]
            if all(x is not None for x in ids): home_id,away_id=str(ids[0]),str(ids[1]); break
    raw=[]
    for d in walk(detail):
        if isinstance(d,dict) and isinstance(d.get('shots'),list) and d['shots'] and isinstance(d['shots'][0],dict):
            keys=set().union(*(x.keys() for x in d['shots'][:5] if isinstance(x,dict)))
            if {'xG','expectedGoals','eventType','shotType','min','minute'} & keys: raw.extend(d['shots'])
    shots=[]; dedupe=set()
    for s in raw:
        try: minute=float(first(s,'min','minute','time'))
        except: continue
        try:xg=float(first(s,'xG','expectedGoals','expected_goals',default=0) or 0)
        except:xg=0.0
        team=first(s,'teamId','team_id'); event=str(first(s,'eventType','shotType','result','type',default='')).lower(); is_goal=('goal' in event) or bool(first(s,'isGoal',default=False)); is_sot=is_goal or ('save' in event)
        sid=first(s,'id','shotId'); key=(sid,minute,team,round(xg,5),event)
        if key in dedupe:continue
        dedupe.add(key); side=None
        if team is not None and home_id is not None: side='home' if str(team)==home_id else ('away' if str(team)==away_id else None)
        if side is None:
            ih=first(s,'isHome'); side='home' if ih is True else ('away' if ih is False else None)
        shots.append({'minute':minute,'xg':xg,'side':side,'is_goal':is_goal,'is_sot':is_sot})
    return shots

def features_from_match(detail,listing=None):
    minute=current_minute_from_detail(detail)
    if minute is None:return None
    sh,sa=parse_score(detail,listing); shots=extract_shots(detail)
    def side_count(side,attr,lo=None):
        total=0.0
        for x in shots:
            if x['side']!=side:continue
            if lo is not None and not (lo < x['minute'] <= minute):continue
            total += 1 if attr=='shot' else (int(x['is_sot']) if attr=='sot' else x['xg'])
        return total
    def both(attr,w):
        lo=max(0,minute-w); return side_count('home',attr,lo)+side_count('away',attr,lo)
    hs=side_count('home','shot'); ass=side_count('away','shot'); hso=side_count('home','sot'); aso=side_count('away','sot'); hx=side_count('home','xg'); ax=side_count('away','xg')
    return {'minute':minute,'remaining_90':90-minute,'score_home':sh,'score_away':sa,'score_diff':sh-sa,'current_total_goals':sh+sa,'home_shots':hs,'away_shots':ass,'total_shots':hs+ass,'shot_diff':hs-ass,'home_sot':hso,'away_sot':aso,'total_sot':hso+aso,'sot_diff':hso-aso,'shots_last5':both('shot',5),'sot_last5':both('sot',5),'xg_last5':both('xg',5),'shots_last10':both('shot',10),'sot_last10':both('sot',10),'xg_last10':both('xg',10),'xg_live_home':hx,'xg_live_away':ax,'xg_live_total':hx+ax,'xg_live_diff':hx-ax}

def sigmoid(x):return 1/(1+math.exp(-max(min(x,40),-40)))
def predict_goal_ft(f):
    vals=np.array([float(f.get(k,0) or 0) for k in MODEL_PACK['features']]); mu=np.array(MODEL_PACK['scaler_mean']); sd=np.array(MODEL_PACK['scaler_scale']); z=(vals-mu)/np.where(sd==0,1,sd); raw=float(np.dot(z,np.array(MODEL_PACK['model_coef']))+MODEL_PACK['model_intercept']); return sigmoid(MODEL_PACK['cal_coef']*raw+MODEL_PACK['cal_intercept'])
def alert_level(f,p):
    if f['minute']<40 or p<0.80:return None
    xg=f['xg_live_total']; elite=(40<=f['minute']<=44 and 1.26<=xg<=1.75) or (4<=f['total_sot']<=5) or (0.11<=f['xg_last10']<=0.30); strong=(1.26<=xg<=1.75)
    return 'ELITE' if elite else ('STRONG' if strong else 'BASE')
def icon(l):return {'BASE':'🟡','STRONG':'🟢','ELITE':'🔥'}.get(l,'⚪')
def market_for_score(f):return f"Over {f['current_total_goals']+0.5:.1f} FT"
def format_alert(row):
    f=row['features']; p=row['p']; fair=1/p; target=1.05/p
    return f"{icon(row['level'])} NEXT GOAL — {row['level']}\n{row['home']}–{row['away']} | {f['score_home']}-{f['score_away']} | {f['minute']}'\nP(gol→FT): {p*100:.1f}%\nxG live: {f['xg_live_total']:.2f} | SOT: {int(f['total_sot'])} | ultimi10': {int(f['shots_last10'])} tiri / {int(f['sot_last10'])} SOT / {f['xg_last10']:.2f} xG\nMercato: {market_for_score(f)}\nFair: @{fair:.2f} | Target +5%: @{target:.2f}\nBET solo se quota live ≥ target."

def discover_chat_id():
    global CHAT_ID
    if CHAT_ID or not BOT_TOKEN:return CHAT_ID
    try:
        d=requests.get(f'https://api.telegram.org/bot{BOT_TOKEN}/getUpdates',timeout=20).json()
        c=[]
        for u in d.get('result',[]):
            for k in ('message','edited_message','channel_post','my_chat_member'):
                o=u.get(k)
                if isinstance(o,dict) and isinstance(o.get('chat'),dict) and o['chat'].get('id') is not None:c.append(str(o['chat']['id']))
        if c: CHAT_ID=c[-1]
    except:pass
    return CHAT_ID

def send_telegram(text):
    cid=discover_chat_id()
    if not BOT_TOKEN or not cid:return False
    r=requests.post(f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',json={'chat_id':cid,'text':text},timeout=20); r.raise_for_status(); return True

RANK={'BASE':1,'STRONG':2,'ELITE':3}
def scan_once():
    payload=fetch_daily_matches(); fixtures=flatten_match_list(payload); live=[]
    for m in fixtures:
        st,fin,can=status_flags(m)
        if st and not fin and not can:live.append(m)
    found=[]
    for m in live:
        mid=str(first(m,'id','matchId'))
        try:
            detail=fetch_match_details(mid); f=features_from_match(detail,m)
            if not f:continue
            p=predict_goal_ft(f); lev=alert_level(f,p); home,away=team_names(detail,m)
            if lev and RANK.get(lev,0)>=RANK.get(MIN_ALERT_LEVEL,1):
                row={'match_id':mid,'home':home,'away':away,'features':f,'p':p,'level':lev}; found.append(row); episode=(mid,f['current_total_goals'],lev)
                if episode not in seen: send_telegram(format_alert(row)); seen.add(episode)
        except Exception: continue
    print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] live={len(live)} alerts={len(found)}")
    return found



def run_monitor():
    max_runtime=int(os.getenv('MAX_RUNTIME_SECONDS','20700'))  # 5h45m
    deadline=time.time()+max_runtime
    print('NEXT GOAL ALERT ML — GitHub Actions runner started')
    print('scan every',SCAN_EVERY_SECONDS,'seconds | min level',MIN_ALERT_LEVEL)
    print('telegram configured:', bool(BOT_TOKEN), '| chat id explicit:', bool(CHAT_ID))
    while time.time() < deadline:
        try:
            scan_once()
        except Exception as e:
            print('scan error:',repr(e),flush=True)
        remaining=deadline-time.time()
        if remaining<=0: break
        time.sleep(min(SCAN_EVERY_SECONDS,max(1,int(remaining))))
    print('Runner window completed; next scheduled job will take over.')

if __name__=='__main__':
    run_monitor()
