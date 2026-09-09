import scanner as s
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from collections import defaultdict

TZ = ZoneInfo("Europe/Rome")
DAILY_CACHE = {}
DETAIL_CACHE = {}

MAX_BACK_DAYS = 365
CANDIDATES_PER_TEAM = 10

def parse_dt(v):
    if isinstance(v, (int, float)):
        if v > 1e12:
            v = v / 1000
        try:
            return datetime.fromtimestamp(v, tz=timezone.utc)
        except Exception:
            return None
    if isinstance(v, str):
        x = v.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(x)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None
    return None

def match_kickoff(m):
    st = m.get("status") if isinstance(m, dict) else None
    vals = []
    if isinstance(st, dict):
        vals += [st.get("utcTime"), st.get("startTime")]
    if isinstance(m, dict):
        vals += [m.get("time"), m.get("timeTS"), m.get("utcTime")]
    for v in vals:
        dt = parse_dt(v)
        if dt is not None:
            return dt
    return None

def daily(day):
    key = day.strftime("%Y%m%d")
    if key not in DAILY_CACHE:
        DAILY_CACHE[key] = s.fetch_daily_matches(key)
    return DAILY_CACHE[key]

def day_matches(day):
    return s.flatten_match_list(daily(day))

def team_id(m, side):
    obj = m.get(side, {}) if isinstance(m, dict) else {}
    v = s.first(obj, "id", "teamId")
    return str(v) if v is not None else None

def team_names(m):
    h = m.get("home", {}) if isinstance(m, dict) else {}
    a = m.get("away", {}) if isinstance(m, dict) else {}
    return (
        s.first(h, "name", "longName", default="?"),
        s.first(a, "name", "longName", default="?"),
    )

def get_detail(mid):
    mid = str(mid)
    if mid not in DETAIL_CACHE:
        DETAIL_CACHE[mid] = s.fetch_match_details(mid)
    return DETAIL_CACHE[mid]

def xg_for_team(detail, tid):
    tid = str(tid)
    shots = s.extract_shots(detail)
    if not shots:
        return None

    # Preferred: explicit team id on normalized shots
    vals = []
    for sh in shots:
        sh_tid = sh.get("team_id")
        if sh_tid is not None and str(sh_tid) == tid:
            vals.append(float(sh.get("xg") or 0.0))
    if vals:
        return sum(vals)

    # Fallback: resolve side from detail team ids
    home_id = away_id = None
    for d in s.walk(detail):
        if not isinstance(d, dict):
            continue
        teams = d.get("teams")
        if isinstance(teams, list) and len(teams) >= 2 and all(isinstance(x, dict) for x in teams[:2]):
            ids = [s.first(x, "id", "teamId") for x in teams[:2]]
            if all(x is not None for x in ids):
                home_id, away_id = str(ids[0]), str(ids[1])
                break

    side = "home" if tid == home_id else ("away" if tid == away_id else None)
    if side is None:
        return None
    vals = [float(sh.get("xg") or 0.0) for sh in shots if sh.get("side") == side]
    return sum(vals) if vals else None

def recent_finished_targets(n=6):
    out = []
    today = datetime.now(TZ).date()
    for back in range(1, 8):
        day = today - timedelta(days=back)
        for m in day_matches(day):
            st, fin, can = s.status_flags(m)
            if fin and not can:
                ko = match_kickoff(m)
                if ko is not None:
                    out.append((ko, m))
                    if len(out) >= n:
                        return out
    return out

def build_history_index(targets):
    # target team -> latest target kickoff for which chronology must be respected
    cutoff = {}
    team_names_map = {}
    for ko, m in targets:
        for side in ("home", "away"):
            tid = team_id(m, side)
            if tid:
                cutoff[tid] = min(cutoff.get(tid, ko), ko)
                obj = m.get(side, {})
                team_names_map[tid] = s.first(obj, "name", "longName", default=tid)

    hist = defaultdict(list)
    seen = defaultdict(set)

    start = min(ko.astimezone(TZ).date() for ko, _ in targets) - timedelta(days=1)

    for back in range(MAX_BACK_DAYS):
        day = start - timedelta(days=back)
        for m in day_matches(day):
            st, fin, can = s.status_flags(m)
            if not fin or can:
                continue

            ko = match_kickoff(m)
            if ko is None:
                continue

            mid = s.first(m, "id", "matchId")
            if mid is None:
                continue
            mid = str(mid)

            for side in ("home", "away"):
                tid = team_id(m, side)
                if tid not in cutoff:
                    continue
                if not (ko < cutoff[tid]):
                    continue
                if mid in seen[tid]:
                    continue
                seen[tid].add(mid)

                opp_side = "away" if side == "home" else "home"
                opp_obj = m.get(opp_side, {})
                opp = s.first(opp_obj, "name", "longName", default="?")
                hist[tid].append((ko, mid, opp))

        # Stop once every target team has enough candidate finished matches.
        if cutoff and all(len(hist[tid]) >= CANDIDATES_PER_TEAM for tid in cutoff):
            print(f"History candidate scan complete after {back+1} days.", flush=True)
            break

    for tid in hist:
        hist[tid].sort(key=lambda x: x[0], reverse=True)

    return hist, team_names_map

def last5_xg(tid, target_dt, hist):
    usable = []
    for ko, mid, opp in hist.get(str(tid), []):
        if not (ko < target_dt):
            continue
        try:
            xg = xg_for_team(get_detail(mid), tid)
        except Exception as e:
            xg = None
        if xg is not None:
            usable.append({
                "kickoff": ko,
                "match_id": mid,
                "opponent": opp,
                "xg": float(xg),
            })
        if len(usable) >= 5:
            break

    if len(usable) < 5:
        return None, usable
    return sum(r["xg"] for r in usable[:5]) / 5.0, usable[:5]

def main():
    targets = recent_finished_targets(6)
    print(f"STEP32 targets={len(targets)}", flush=True)
    if not targets:
        raise RuntimeError("No recent finished targets")

    hist, team_names_map = build_history_index(targets)

    print("\nCandidate history counts:", flush=True)
    for tid, name in team_names_map.items():
        print(f"{name} ({tid}): {len(hist.get(tid, []))}", flush=True)

    ok = 0
    for target_dt, m in targets:
        mid = str(s.first(m, "id", "matchId"))
        home, away = team_names(m)
        hid, aid = team_id(m, "home"), team_id(m, "away")

        hx, hp = last5_xg(hid, target_dt, hist)
        ax, ap = last5_xg(aid, target_dt, hist)

        sx = None if hx is None or ax is None else hx + ax
        wx = None if hx is None or ax is None else min(hx, ax)
        good = hx is not None and ax is not None
        ok += int(good)

        level = "XG5_UNAVAILABLE"
        if good:
            if sx >= 3.45:
                level = "ELITE-prelive"
            elif sx >= 2.90 and wx >= 1.00:
                level = "STRONG-prelive"
            else:
                level = "BASE-prelive"

        print(f"\nTARGET {target_dt.isoformat()} | {home}-{away} | {mid}", flush=True)
        print(f"home_xG5={hx} away_xG5={ax} sum={sx} weak={wx} | {level}", flush=True)
        print("HOME LAST5:", flush=True)
        for r in hp:
            print(r, flush=True)
            assert r["kickoff"] < target_dt, f"LEAKAGE home {r['match_id']}"
        print("AWAY LAST5:", flush=True)
        for r in ap:
            print(r, flush=True)
            assert r["kickoff"] < target_dt, f"LEAKAGE away {r['match_id']}"

        if hx is not None:
            assert len(hp) == 5
        if ax is not None:
            assert len(ap) == 5

    print(f"\nSTEP32 xG5 success={ok}/{len(targets)}", flush=True)
    print(f"daily_feeds_used={len(DAILY_CACHE)} match_details_used={len(DETAIL_CACHE)}", flush=True)

    if ok < max(5, len(targets)-1):
        raise RuntimeError(f"STEP32 insufficient coverage: {ok}/{len(targets)}")

    print("STEP32 PASS: 365-day xG5 resolver is viable.", flush=True)

if __name__ == "__main__":
    main()
