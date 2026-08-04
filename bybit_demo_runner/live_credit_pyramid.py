#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, hashlib, hmac, json, os, time, uuid, urllib.parse
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from pathlib import Path
from typing import Any

import requests

DEMO_BASE = "https://api-demo.bybit.com"
PUBLIC_BASES = ("https://api.bybit.com", "https://api.bytick.com")
RECV_WINDOW = "10000"

class BybitError(RuntimeError): pass

def D(v: Any, default="0") -> Decimal:
    try: return Decimal(str(v)) if v not in (None, "") else Decimal(default)
    except Exception: return Decimal(default)

def F(v: Decimal) -> str: return format(v, "f")
def ms() -> int: return int(time.time() * 1000)
def stamp() -> str: return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

def dump(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

class Client:
    def __init__(self, key: str, secret: str):
        if not key or not secret: raise BybitError("Empty demo credentials")
        self.key, self.secret = key, secret
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "SINERGY-Bybit-Demo-Credit-Test/2.0"

    def headers(self, payload: str) -> dict[str,str]:
        ts = str(ms())
        raw = ts + self.key + RECV_WINDOW + payload
        sig = hmac.new(self.secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
        return {"X-BAPI-API-KEY": self.key, "X-BAPI-TIMESTAMP": ts,
                "X-BAPI-RECV-WINDOW": RECV_WINDOW, "X-BAPI-SIGN": sig,
                "Content-Type": "application/json"}

    @staticmethod
    def decode(r: requests.Response, path: str) -> dict:
        try: data = r.json()
        except Exception as e: raise BybitError(f"{path}: HTTP {r.status_code}, non-JSON") from e
        if r.status_code >= 400 or data.get("retCode") not in (0, None):
            raise BybitError(f"{path}: HTTP {r.status_code}; {data.get('retCode')} {data.get('retMsg')}")
        return data

    def get(self, path: str, params: dict | None = None) -> dict:
        params = {k:v for k,v in (params or {}).items() if v is not None}
        q = urllib.parse.urlencode(params)
        r = self.s.get(DEMO_BASE + path, params=params, headers=self.headers(q), timeout=25)
        return self.decode(r, path)

    def post(self, path: str, body: dict | None = None) -> dict:
        body = body or {}; raw = json.dumps(body, separators=(",", ":"))
        r = self.s.post(DEMO_BASE + path, data=raw, headers=self.headers(raw), timeout=25)
        return self.decode(r, path)

    def public(self, path: str, params: dict | None = None) -> dict:
        last = None
        for base in PUBLIC_BASES:
            try:
                return self.decode(self.s.get(base + path, params=params or {}, timeout=25), path)
            except Exception as e: last = e
        raise BybitError(f"Public endpoints unavailable: {last}")

@dataclass(frozen=True)
class Inst:
    symbol: str; expiry: int; strike: Decimal; typ: str; settle: str
    min_qty: Decimal; step: Decimal; tick: Decimal

@dataclass(frozen=True)
class Quote:
    bid: Decimal; ask: Decimal; bid_size: Decimal; ask_size: Decimal; mark: Decimal

@dataclass(frozen=True)
class Candidate:
    cid: str; expiry: int; settle: str; k1: Decimal; k2: Decimal
    lc: Inst; hc: Inst; lp: Inst; hp: Inst
    credit: Decimal; protective_debit: Decimal; width: Decimal; multiplier: Decimal
    max_qty: Decimal; step: Decimal; min_qty: Decimal

FIELDS = ("accountIMRate","accountMMRate","totalEquity","totalWalletBalance",
          "totalMarginBalance","totalAvailableBalance","totalInitialMargin",
          "totalMaintenanceMargin","totalPerpUPL")

def snapshot(c: Client) -> dict:
    info = c.get("/v5/account/info").get("result", {})
    rows = c.get("/v5/account/wallet-balance", {"accountType":"UNIFIED"}).get("result",{}).get("list",[])
    if not rows: raise BybitError("No UNIFIED wallet row")
    row = rows[0]
    out = {"timestamp_ms":ms(), "marginMode":info.get("marginMode"),
           "unifiedMarginStatus":info.get("unifiedMarginStatus")}
    for f in FIELDS: out[f] = row.get(f, "")
    out["coins"] = [{k:x.get(k) for k in ("coin","walletBalance","equity","usdValue","spotBorrow")}
                    for x in row.get("coin",[]) if D(x.get("walletBalance")) != 0 or D(x.get("equity")) != 0]
    return out

def delta(a: dict, b: dict, f: str) -> Decimal: return D(a.get(f)) - D(b.get(f))

def instruments(c: Client, base_coin: str) -> list[Inst]:
    out=[]; cursor=""
    while True:
        p={"category":"option","baseCoin":base_coin,"limit":1000}
        if cursor: p["cursor"] = cursor
        res=c.public("/v5/market/instruments-info",p).get("result",{})
        for x in res.get("list",[]):
            typ=x.get("optionsType") or x.get("optionType")
            if x.get("status")!="Trading" or typ not in ("Call","Put"): continue
            lot=x.get("lotSizeFilter",{}); pf=x.get("priceFilter",{})
            out.append(Inst(x["symbol"],int(x.get("deliveryTime") or 0),D(x.get("strike")),typ,
                            x.get("settleCoin") or x.get("quoteCoin") or "",
                            D(lot.get("minOrderQty"),"0.01"),D(lot.get("qtyStep"),"0.01"),
                            D(pf.get("tickSize"),"0.1")))
        cursor=res.get("nextPageCursor") or ""
        if not cursor: break
    return out

def quotes(c: Client, base_coin: str) -> dict[str,Quote]:
    xs=c.public("/v5/market/tickers",{"category":"option","baseCoin":base_coin}).get("result",{}).get("list",[])
    out={}
    for x in xs:
        bid,ask=D(x.get("bid1Price")),D(x.get("ask1Price"))
        if bid>0 and ask>0 and ask>=bid:
            out[x["symbol"]]=Quote(bid,ask,D(x.get("bid1Size")),D(x.get("ask1Size")),D(x.get("markPrice")))
    return out

def build(insts: list[Inst], qs: dict[str,Quote]) -> list[Candidate]:
    g={}
    for i in insts:
        if i.symbol in qs: g.setdefault((i.expiry,i.settle,i.strike),{})[i.typ]=i
    by={}
    for e,s,k in g:
        if "Call" in g[(e,s,k)] and "Put" in g[(e,s,k)]: by.setdefault((e,s),[]).append(k)
    out=[]
    for (e,s), raw in by.items():
        ks=sorted(set(raw))
        for n,k1 in enumerate(ks):
            for k2 in ks[n+1:min(len(ks),n+31)]:
                lc,lp=g[(e,s,k1)]["Call"],g[(e,s,k1)]["Put"]
                hc,hp=g[(e,s,k2)]["Call"],g[(e,s,k2)]["Put"]
                a,b,d,z=qs[lc.symbol],qs[hc.symbol],qs[lp.symbol],qs[hp.symbol]
                credit=a.bid+z.bid-b.ask-d.ask
                debit=b.ask+d.ask
                top=min(a.bid_size,z.bid_size,b.ask_size,d.ask_size)
                if credit<=0 or debit<=0 or top<=0: continue
                st=max(lc.step,lp.step,hc.step,hp.step); mn=max(lc.min_qty,lp.min_qty,hc.min_qty,hp.min_qty)
                out.append(Candidate(f"{e}:{s}:{F(k1)}:{F(k2)}",e,s,k1,k2,lc,hc,lp,hp,
                                     credit,debit,k2-k1,credit/debit,top,st,mn))
    return out

def percentile(v: list[Decimal], p: Decimal) -> Decimal:
    s=sorted(v); x=Decimal(len(s)-1)*p; lo=int(x.to_integral_value(rounding=ROUND_DOWN)); hi=min(lo+1,len(s)-1)
    return s[lo]*(1-(x-lo))+s[hi]*(x-lo)

def floor_step(v: Decimal, st: Decimal) -> Decimal:
    return (v/st).to_integral_value(rounding=ROUND_DOWN)*st if st>0 else v

def tick(v: Decimal, t: Decimal, up: bool) -> Decimal:
    return (v/t).to_integral_value(rounding=ROUND_UP if up else ROUND_DOWN)*t

def one_quote(c: Client, sym: str) -> Quote:
    xs=c.public("/v5/market/tickers",{"category":"option","symbol":sym}).get("result",{}).get("list",[])
    if not xs: raise BybitError(f"No ticker {sym}")
    x=xs[0]; return Quote(D(x.get("bid1Price")),D(x.get("ask1Price")),D(x.get("bid1Size")),D(x.get("ask1Size")),D(x.get("markPrice")))

def wait_order(c: Client, oid: str, timeout=25) -> dict:
    end=time.time()+timeout; last={}
    while time.time()<end:
        xs=c.get("/v5/order/realtime",{"category":"option","orderId":oid}).get("result",{}).get("list",[])
        if xs:
            last=xs[0]
            if last.get("orderStatus") in ("Filled","Cancelled","Rejected","PartiallyFilledCanceled","Deactivated"): return last
        time.sleep(.6)
    return last

def place(c: Client, i: Inst, side: str, qty: Decimal, bps: Decimal, tag: str) -> dict:
    q=one_quote(c,i.symbol)
    px=tick((q.ask*(1+bps/10000) if side=="Buy" else q.bid*(1-bps/10000)),i.tick,side=="Buy")
    if px<=0: raise BybitError(f"Bad price {i.symbol}")
    req={"category":"option","symbol":i.symbol,"side":side,"orderType":"Limit","qty":F(qty),
         "price":F(px),"timeInForce":"IOC","orderLinkId":f"syn-{tag}-{uuid.uuid4().hex[:10]}"[:36]}
    ack=c.post("/v5/order/create",req); oid=ack.get("result",{}).get("orderId")
    if not oid: raise BybitError(f"No order id {i.symbol}")
    final=wait_order(c,oid); final["request"]=req
    if D(final.get("cumExecQty"))<qty: raise BybitError(f"Not filled {i.symbol} {side}: {final.get('orderStatus')} {final.get('cumExecQty')}/{qty}")
    return final

def inst_for(c: Client, sym: str) -> Inst:
    xs=c.public("/v5/market/instruments-info",{"category":"option","symbol":sym}).get("result",{}).get("list",[])
    if not xs: raise BybitError(f"No instrument {sym}")
    x=xs[0]; lot=x.get("lotSizeFilter",{}); pf=x.get("priceFilter",{})
    return Inst(sym,int(x.get("deliveryTime") or 0),D(x.get("strike")),x.get("optionsType") or x.get("optionType"),
                x.get("settleCoin") or x.get("quoteCoin") or "",D(lot.get("minOrderQty"),"0.01"),
                D(lot.get("qtyStep"),"0.01"),D(pf.get("tickSize"),"0.1"))

def reverse(c: Client, orders: list[dict], bps: Decimal) -> list[dict]:
    out=[]
    for o in reversed(orders):
        r=o.get("request",{}); sym=r.get("symbol"); qty=D(o.get("cumExecQty"))
        if not sym or qty<=0: continue
        try: out.append(place(c,inst_for(c,sym),"Sell" if r.get("side")=="Buy" else "Buy",qty,bps,"close"))
        except Exception as e: out.append({"symbol":sym,"qty":F(qty),"error":str(e)})
    return out

def choose(cs: list[Candidate], used: set[str], budget: Decimal, threshold: Decimal) -> tuple[Candidate,Decimal]:
    pool=[]
    for x in cs:
        if x.cid in used: continue
        qty=min(floor_step(budget/x.protective_debit,x.step),floor_step(x.max_qty,x.step))
        if qty>=x.min_qty and x.multiplier>=threshold: pool.append((x,qty))
    if not pool:
        for x in cs:
            if x.cid in used: continue
            qty=min(floor_step(budget/x.protective_debit,x.step),floor_step(x.max_qty,x.step))
            if qty>=x.min_qty: pool.append((x,qty))
    if not pool: raise BybitError(f"No candidate fits recursive budget {budget}")
    return max(pool,key=lambda y:(y[0].multiplier,y[0].credit,y[0].max_qty))

def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows: return
    keys=[]
    for r in rows:
        for k in r:
            if k not in keys: keys.append(k)
    with path.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=keys); w.writeheader(); w.writerows(rows)

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--capital",type=Decimal,default=Decimal("30")); ap.add_argument("--steps",type=int,default=30)
    ap.add_argument("--quantile",type=Decimal,default=Decimal(".99")); ap.add_argument("--base-coin",default="ETH")
    ap.add_argument("--slippage-bps",type=Decimal,default=Decimal("50")); ap.add_argument("--max-im-rate",type=Decimal,default=Decimal(".90"))
    ap.add_argument("--execute",action="store_true"); ap.add_argument("--force-cross",action="store_true"); ap.add_argument("--close-after",action="store_true")
    ap.add_argument("--output",type=Path,default=Path("bybit_demo_results")); a=ap.parse_args()
    if not 1<=a.steps<=30 or a.capital<=0: raise SystemExit("Invalid steps/capital")
    c=Client(os.environ.get("BYBIT_DEMO_API_KEY",""),os.environ.get("BYBIT_DEMO_API_SECRET",""))
    run=a.output/f"run_{stamp()}"; run.mkdir(parents=True,exist_ok=True)
    opened=[]; rows=[]; verdict="NOT_STARTED"; budget=a.capital
    try:
        keyinfo=c.get("/v5/user/query-api").get("result",{})
        dump(run/"api_key_info_redacted.json",{k:v for k,v in keyinfo.items() if "secret" not in k.lower() and "key" not in k.lower()})
        base=snapshot(c); dump(run/"account_before.json",base)
        if base.get("marginMode")!="REGULAR_MARGIN":
            if not a.force_cross: raise BybitError(f"marginMode={base.get('marginMode')}")
            pos=c.get("/v5/position/list",{"category":"option","baseCoin":a.base_coin}).get("result",{}).get("list",[])
            if any(D(x.get("size"))>0 for x in pos): raise BybitError("Existing option positions prevent safe mode switch")
            c.post("/v5/account/set-margin-mode",{"setMarginMode":"REGULAR_MARGIN"}); time.sleep(2)
            base=snapshot(c); dump(run/"after_margin_mode_switch.json",base)
            if base.get("marginMode")!="REGULAR_MARGIN": raise BybitError("Cross-margin switch not confirmed")
        ins=instruments(c,a.base_coin.upper()); qs=quotes(c,a.base_coin.upper()); cs=build(ins,qs)
        if not cs: raise BybitError("No executable short boxes")
        threshold=percentile([x.multiplier for x in cs],a.quantile)
        dump(run/"market_summary.json",{"instruments":len(ins),"quotes":len(qs),"candidates":len(cs),"quantile":F(a.quantile),"threshold":F(threshold),"max":F(max(x.multiplier for x in cs))})
        if not a.execute: return 0
        used=set()
        for n in range(1,a.steps+1):
            before=snapshot(c)
            if D(before.get("accountIMRate"))>=a.max_im_rate: verdict=f"STOP_IM_RATE_STEP_{n}"; break
            cs=build(ins,quotes(c,a.base_coin.upper())); x,qty=choose(cs,used,budget,threshold); used.add(x.cid)
            sd=run/f"step_{n:02d}"; sd.mkdir(); dump(sd/"before.json",before); dump(sd/"candidate.json",{**asdict(x),"qty":F(qty),"budget":F(budget)})
            pack=[]
            try:
                pack.append(place(c,x.hc,"Buy",qty,a.slippage_bps,f"{n}-hc"))
                pack.append(place(c,x.lp,"Buy",qty,a.slippage_bps,f"{n}-lp"))
                dump(sd/"after_protection.json",snapshot(c))
                pack.append(place(c,x.lc,"Sell",qty,a.slippage_bps,f"{n}-lc"))
                pack.append(place(c,x.hp,"Sell",qty,a.slippage_bps,f"{n}-hp"))
                time.sleep(2); after=snapshot(c); dump(sd/"after_package.json",after); dump(sd/"orders.json",pack); opened.extend(pack)
                da=delta(after,before,"totalAvailableBalance")
                row={"step":n,"candidate":x.cid,"k1":F(x.k1),"k2":F(x.k2),"qty":F(qty),"quoted_multiplier":F(x.multiplier),
                     "recursive_budget_before":F(budget),"delta_wallet":F(delta(after,before,"totalWalletBalance")),
                     "delta_margin_balance":F(delta(after,before,"totalMarginBalance")),"delta_initial_margin":F(delta(after,before,"totalInitialMargin")),
                     "delta_available_balance":F(da),"delta_equity":F(delta(after,before,"totalEquity")),
                     "available_before":before.get("totalAvailableBalance"),"available_after":after.get("totalAvailableBalance"),
                     "im_rate_after":after.get("accountIMRate")}
                rows.append(row); write_csv(run/"steps.csv",rows)
                if da<=0: verdict=f"NOT_CONFIRMED_STEP_{n}: deltaAvailable={F(da)}"; break
                budget=da; verdict=f"CONFIRMED_THROUGH_STEP_{n}"
            except Exception as e:
                dump(sd/"error.json",{"error":str(e)})
                if pack: dump(sd/"rollback.json",reverse(c,pack,a.slippage_bps))
                verdict=f"EXECUTION_ERROR_STEP_{n}: {e}"; break
        dump(run/"account_after_test.json",snapshot(c))
    finally:
        if a.close_after and opened:
            dump(run/"close_orders.json",reverse(c,opened,a.slippage_bps)); time.sleep(2)
            try: dump(run/"account_after_close.json",snapshot(c))
            except Exception as e: dump(run/"close_snapshot_error.json",{"error":str(e)})
        summary={"verdict":verdict,"completed_steps":len(rows),"requested_steps":a.steps,"starting_budget":F(a.capital),"last_recursive_budget":F(budget),"closed_after":a.close_after}
        dump(run/"summary.json",summary)
        (run/"VERDICT.md").write_text("# Bybit Demo live verdict\n\n"+"\n".join(f"- {k}: **{v}**" for k,v in summary.items())+"\n",encoding="utf-8")
        print(json.dumps(summary,ensure_ascii=False,indent=2)); print(run)
    return 0

if __name__=="__main__":
    try: raise SystemExit(main())
    except Exception as e: raise SystemExit(f"FATAL: {e}")
