"""StubFlip poller: MLB The Show 26 market -> sqlite. Run: python3 poller.py [--loop]"""
import json, sqlite3, time, sys, datetime as dt, concurrent.futures as cf, unicodedata, requests
API="https://mlb26.theshow.com/apis"; DB="/workspace/stubflip/stubflip.db"
S=requests.Session(); S.headers["User-Agent"]="stubflip/1.0"
# Quicksell table: NOT exposed by the API; standard community-known values (assumption).
QS=[(92,10000),(91,9000),(90,8000),(89,7000),(88,5500),(87,4500),(86,3750),(85,3000),(84,1500),(83,1200),(82,900),(81,600),(80,400),(75,100),(65,25),(0,5)]
def qs(o): return next(v for t,v in QS if o>=t)
def get(path,**p):
    for i in range(3):
        try:
            r=S.get(f"{API}/{path}",params=p,timeout=20); r.raise_for_status(); return r.json()
        except Exception as e: err=e; time.sleep(1+i)
    raise err
def norm(n): return unicodedata.normalize("NFKD",n).encode("ascii","ignore").decode().lower().replace(".","").strip()
def init(db):
    db.executescript("""create table if not exists runs(ts text, status text, detail text);
    create table if not exists listings(ts text, uuid text, name text, rarity text, ovr int, series text, team text, pos text, buy int, sell int);
    create table if not exists flips(ts text, uuid text, name text, rarity text, ovr int, series text, buy int, sell int, profit real, roi real, sales_per_hr real, score real);
    create table if not exists invest(ts text, uuid text, name text, rarity text, ovr int, team text, pos text, buy int, sell int, quicksell int, qs_gap_pct real, ru_trend int, mlb_stat text, reason text, score real);""")
def detail(uuid):
    try: d=get("listing.json",uuid=uuid)
    except Exception: return None
    co=d.get("completed_orders",[])
    if len(co)<2: return 0.0
    ts=[dt.datetime.strptime(c["date"],"%m/%d/%Y %H:%M:%S") for c in co]
    hrs=max((max(ts)-min(ts)).total_seconds()/3600,1/60)
    return round(len(co)/hrs,1)
def mlb_stats():
    out={}
    try:
        for g in("hitting","pitching"):
            r=requests.get("https://statsapi.mlb.com/api/v1/stats",params=dict(stats="season",group=g,season=2026,sportId=1,playerPool="ALL",limit=3000),timeout=30).json()
            for s in r["stats"][0]["splits"]:
                st=s["stat"];n=norm(s["player"]["fullName"])
                if g=="hitting" and int(st.get("plateAppearances",0))>=150: out[n]=("H",float(st.get("ops") or 0),f"OPS {st.get('ops')} ({st.get('homeRuns')} HR, {st.get('plateAppearances')} PA)")
                if g=="pitching" and float(st.get("inningsPitched","0"))>=40 and n not in out: out[n]=("P",float(st.get("era") or 99),f"ERA {st.get('era')} ({st.get('inningsPitched')} IP, {st.get('strikeOuts')} K)")
    except Exception as e: print("statsapi failed:",e)
    return out
def ru_trends(n=4):
    tr={}
    try:
        ids=[u["id"] for u in get("roster_updates.json")["roster_updates"][:n]]
        for i in ids:
            for a in get("roster_update.json",id=i).get("attribute_changes",[]):
                tr[a["obfuscated_id"]]=tr.get(a["obfuscated_id"],0)+(int(a["current_rank"])-int(a["old_rank"]))
    except Exception as e: print("roster updates failed:",e)
    return tr
def run():
    db=sqlite3.connect(DB); init(db); ts=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    first=get("listings.json",type="mlb_card",page=1); pages=first["total_pages"]; L=first["listings"]
    with cf.ThreadPoolExecutor(8) as ex:
        for d in ex.map(lambda p:get("listings.json",type="mlb_card",page=p),range(2,pages+1)): L+=d["listings"]
    rows=[]
    for l in L:
        it=l["item"]; rows.append((ts,it["uuid"],l["listing_name"],it["rarity"],it["ovr"],it["series"],it["team"],it["display_position"],l["best_buy_price"] or 0,l["best_sell_price"] or 0))
    db.executemany("insert into listings values(?,?,?,?,?,?,?,?,?,?)",rows)
    # flips
    cand=[]
    for r in rows:
        buy,sell=r[8],r[9]
        if buy<=0 or sell<=0: continue
        buy+=1; sell-=1  # outbid/undercut by 1 stub
        p=sell*0.9-buy
        if p>0: cand.append([r,buy,sell,p,p/buy*100])
    cand.sort(key=lambda c:-c[3]); top=cand[:200]
    with cf.ThreadPoolExecutor(4) as ex: vols=list(ex.map(lambda c:detail(c[0][1]),top))
    fl=[]
    for c,v in zip(top,vols):
        if v is None: continue
        score=c[3]*min(v,30)  # est. profit/hr, volume capped at 30 sales/hr per card
        r=c[0]; fl.append((ts,r[1],r[2],r[3],r[4],r[5],c[1],c[2],round(c[3]),round(c[4],1),v,round(score)))
    db.executemany("insert into flips values(?,?,?,?,?,?,?,?,?,?,?,?)",fl)
    # investments
    tr=ru_trends(); st=mlb_stats(); inv=[]
    for r in rows:
        _,u,n,rar,o,ser,team,pos,buy,sell=r
        if ser!="Live" or rar not in("Gold","Silver") or sell<=0: continue
        q=qs(o); gap=(sell-q)/q*100; t=tr.get(u,0); s=st.get(norm(n)); why=[]; sc=0
        if 81<=o<=84: why.append(f"{85-o} OVR from diamond"); sc+=(5-(85-o))*10
        if t>0: why.append(f"+{t} OVR last 4 updates"); sc+=t*8
        if t<0: sc+=t*8
        if s:
            hot=(s[0]=="H" and s[1]>=.800) or (s[0]=="P" and s[1]<=3.30)
            if hot: why.append("strong 2026 season"); sc+=15
        if gap<=25: why.append("near quicksell floor (low risk)"); sc+=15
        if sc<=0: continue
        inv.append((ts,u,n,rar,o,team,pos,buy,sell,q,round(gap,1),t,s[2] if s else "n/a","; ".join(why),sc))
    inv.sort(key=lambda x:-x[-1]); db.executemany("insert into invest values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",inv[:100])
    db.execute("insert into runs values(?,?,?)",(ts,"ok",f"{len(rows)} listings, {len(fl)} flips, {len(inv)} invest, statsapi players {len(st)}"))
    db.execute("delete from listings where ts<datetime('now','localtime','-3 days')"); db.commit()
    print(ts,len(rows),"listings",len(fl),"flips",len(inv),"invest")
if __name__=="__main__":
    while True:
        try: run()
        except Exception as e:
            print("run failed",e); db=sqlite3.connect(DB); init(db); db.execute("insert into runs values(datetime('now','localtime'),'error',?)",(str(e),)); db.commit()
        if "--loop" not in sys.argv: break
        time.sleep(300)
