import step32_365day_xg5 as x

def main():
    targets=x.recent_finished_targets(6)
    print(f"STEP33 targets={len(targets)}",flush=True)
    hist,names=x.build_history_index(targets)
    ok=0
    for target_dt,m in targets:
        home,away=x.team_names(m)
        hid,aid=x.team_id(m,"home"),x.team_id(m,"away")
        hx,hp=x.last5_xg(hid,target_dt,hist)
        ax,ap=x.last5_xg(aid,target_dt,hist)
        good=hx is not None and ax is not None
        ok+=int(good)
        if good:
            print(f"{home}-{away}: home={hx:.4f} away={ax:.4f} sum={hx+ax:.4f} weak={min(hx,ax):.4f}",flush=True)
            assert len(hp)==5 and len(ap)==5
            assert all(r["kickoff"] < target_dt for r in hp+ap)
    print(f"FotMob exact-last5 reconstruction coverage: {ok}/{len(targets)}",flush=True)
    if ok != len(targets):
        raise RuntimeError("STEP33 live-side xG5 definition failed")
    print("Frozen STEP22-25 source: BIG5_Understat rolling xG5.",flush=True)
    print("Live STEP32 source: FotMob shotmap expectedGoals rolling xG5.",flush=True)
    print("Definition alignment: PASS.",flush=True)
    print("Provider identity: FAIL (Understat != FotMob).",flush=True)
    print("STEP33 DECISION: GATED. Keep BASE production; paired provider equivalence is required before attaching frozen STRONG/ELITE rates.",flush=True)

if __name__=="__main__":
    main()
