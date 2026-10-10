"""Scan MLB The Show 26 market and write site/data.json (used by GitHub Actions)."""
import json, os, datetime as dt, concurrent.futures as cf
from zoneinfo import ZoneInfo
import stubcore as c
MIN_VOL, MAX_ROI = 10, 60
def main():
    now=dt.datetime.now(ZoneInfo("America/New_York")); first=c.get("listings.json",type="mlb_card",page=1); L=first["listings"]
    with cf.ThreadPoolExecutor(4) as ex:
        for d in ex.map(lambda p:c.get("listings.json",type="mlb_card",page=p),range(2,first["total_pages"]+1)): L+=d["listings"]
    cand=[]
    for l in L:
        it=l["item"]; b,s=l["best_buy_price"] or 0,l["best_sell_price"] or 0
        if b<=0 or s<=0: continue
        b+=1; s-=1; p=s*0.9-b
        if p>0 and p/b*100<=MAX_ROI: cand.append(dict(uuid=it["uuid"],name=l["listing_name"],rarity=it["rarity"],ovr=it["ovr"],series=it["series"],buy=b,sell=s,profit=round(p),roi=round(p/b*100,1)))
    cand.sort(key=lambda x:-x["profit"]); top=cand[:200]
    with cf.ThreadPoolExecutor(4) as ex: vols=list(ex.map(lambda x:c.detail(x["uuid"]),top))
    fl=[]
    for x,v in zip(top,vols):
        if v is None or v<MIN_VOL: continue
        x["sales_per_hr"]=v; x["score"]=round(x["profit"]*min(v,30)); fl.append(x)
    fl.sort(key=lambda x:-x["score"])
    tr=c.ru_trends(); st=c.mlb_stats(); inv=[]
    for l in L:
        it=l["item"]; o=it["ovr"]; s=l["best_sell_price"] or 0
        if it["series"]!="Live" or it["rarity"] not in("Gold","Silver") or s<=0: continue
        q=c.qs(o); gap=(s-q)/q*100; t=tr.get(it["uuid"],0); m=st.get(c.norm(l["listing_name"])); why=[]; sc=0
        if 81<=o<=84: why.append(f"{85-o} OVR from diamond"); sc+=(5-(85-o))*10
        if t>0: why.append(f"+{t} OVR last 4 updates")
        sc+=t*8
        if m and ((m[0]=="H" and m[1]>=.8) or (m[0]=="P" and m[1]<=3.3)): why.append("strong 2026 season"); sc+=15
        if gap<=25: why.append("near quicksell floor (low risk)"); sc+=15
        if sc>0: inv.append(dict(name=l["listing_name"],rarity=it["rarity"],ovr=o,team=it["team"],pos=it["display_position"],sell=s,quicksell=q,qs_gap_pct=round(gap,1),ru_trend=t,mlb_stat=m[2] if m else "n/a",reason="; ".join(why),score=sc))
    inv.sort(key=lambda x:-x["score"])
    ts=now.strftime("%Y-%m-%d %H:%M:%S")
    out=dict(generated_utc=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),scan_ts=ts,run=[ts,"ok",f"{len(L)} listings, {len(fl)} liquid flips, statsapi players {len(st)}"],flips=fl[:10],inv=inv[:5])
    d=os.environ.get("OUT","site"); os.makedirs(d,exist_ok=True); json.dump(out,open(f"{d}/data.json","w")); print(out["run"])
if __name__=="__main__": main()
