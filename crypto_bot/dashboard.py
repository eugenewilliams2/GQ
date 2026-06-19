"""
Live paper-trading dashboard — multi-session. Generates a self-contained
dashboard.html that lets you switch between paper sessions (FVG, NN-aggressive,
Crypto-NN), each polling its own state JSON and re-rendering live.
"""

from __future__ import annotations
import os

# (tab label, servable json file) — only those that exist render as tabs.
SESSIONS = [
    ("Crypto NN", "paper_state.json"),
    ("Crypto momentum", "paper_state_mom.json"),
]

_HTML = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GQ · Live Paper Trading</title>
<style>
 :root{
  --bg:#070b14; --card:rgba(20,28,46,.7); --line:rgba(110,130,170,.14);
  --txt:#e6edf7; --mut:#7e8aa3; --up:#34d399; --down:#fb7185; --acc:#6ea8fe;
 }
 *{box-sizing:border-box} html,body{margin:0;height:100%}
 body{background:radial-gradient(1200px 700px at 80% -10%,#13203a 0%,var(--bg) 55%);
  color:var(--txt);font:14px/1.5 'Inter',system-ui,-apple-system,Segoe UI,sans-serif;
  -webkit-font-smoothing:antialiased;padding:26px;min-height:100%}
 .mono{font-family:'SF Mono',ui-monospace,Menlo,monospace;font-variant-numeric:tabular-nums}
 .wrap{max-width:1100px;margin:0 auto}
 header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:16px}
 .brand{font-weight:700;font-size:18px;letter-spacing:.04em}
 .brand b{color:var(--acc)} .brand .sub{color:var(--mut);font-weight:500;font-size:12px;margin-top:2px}
 .live{display:flex;align-items:center;gap:8px;color:var(--mut);font-size:12px}
 .dot{width:9px;height:9px;border-radius:50%;background:var(--up);animation:pulse 2s infinite}
 @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(52,211,153,.5)}70%{box-shadow:0 0 0 10px rgba(52,211,153,0)}100%{box-shadow:0 0 0 0 rgba(52,211,153,0)}}
 .tabs{display:flex;gap:8px;margin-bottom:18px;flex-wrap:wrap}
 .tab{padding:8px 14px;border-radius:10px;background:var(--card);border:1px solid var(--line);
  color:var(--mut);cursor:pointer;font-size:13px;font-weight:600;transition:.15s}
 .tab:hover{color:var(--txt)} .tab.on{background:rgba(110,168,254,.16);color:var(--acc);border-color:rgba(110,168,254,.4)}
 .hero{display:grid;grid-template-columns:1.1fr 1fr;gap:16px;margin-bottom:16px}
 .card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:20px;
  backdrop-filter:blur(12px);box-shadow:0 10px 40px rgba(0,0,0,.25)}
 .label{color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.12em;margin-bottom:8px}
 .balance{font-size:40px;font-weight:700;letter-spacing:-.02em}
 .pnl{font-size:16px;font-weight:600;margin-top:6px;display:flex;gap:10px;align-items:baseline}
 .chart{position:relative;height:128px;margin-top:6px}
 .chart svg{width:100%;height:100%}
 .stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}
 .stat{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
 .stat .v{font-size:22px;font-weight:700;margin-top:4px}
 h2{font-size:13px;text-transform:uppercase;letter-spacing:.1em;color:var(--mut);margin:22px 4px 12px}
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
 .pos{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px}
 .pos .top{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
 .pair{font-weight:700;font-size:16px;letter-spacing:.02em}
 .pill{font-size:11px;font-weight:700;padding:4px 10px;border-radius:999px}
 .pill.buy{background:rgba(52,211,153,.15);color:var(--up)} .pill.sell{background:rgba(251,113,133,.15);color:var(--down)}
 .gauge{height:6px;border-radius:3px;background:linear-gradient(90deg,var(--down),#475569 50%,var(--up));position:relative;margin:14px 0 8px}
 .gauge .mk{position:absolute;top:-4px;width:2px;height:14px;background:var(--txt);border-radius:2px;transform:translateX(-50%)}
 .legs{display:flex;justify-content:space-between;color:var(--mut);font-size:11px}
 .meta{display:flex;justify-content:space-between;margin-top:12px;color:var(--mut);font-size:12px}
 .meta b{color:var(--txt);font-weight:600}
 table{width:100%;border-collapse:collapse;font-size:13px}
 th{text-align:left;color:var(--mut);font-weight:500;font-size:11px;text-transform:uppercase;
  letter-spacing:.08em;padding:8px 10px;border-bottom:1px solid var(--line)}
 td{padding:9px 10px;border-bottom:1px solid rgba(110,130,170,.07)}
 .up{color:var(--up)} .down{color:var(--down)} .mut{color:var(--mut)}
 .empty{color:var(--mut);padding:24px;text-align:center;border:1px dashed var(--line);border-radius:14px}
 .tag{font-size:10px;color:var(--mut);background:rgba(110,130,170,.12);padding:2px 7px;border-radius:6px}
 footer{color:var(--mut);font-size:11px;text-align:center;margin-top:26px;opacity:.7}
</style></head><body><div class="wrap">
 <header>
  <div class="brand">GQ <b>Paper</b> Trading<div class="sub" id="strat">loading…</div></div>
  <div class="live"><span class="dot"></span><span id="updated">connecting…</span></div>
 </header>
 <div class="tabs" id="tabs"></div>

 <div class="hero">
  <div class="card"><div class="label">Equity</div>
   <div class="balance mono" id="balance">$—</div>
   <div class="pnl mono"><span id="pnl">—</span><span class="tag" id="ddtag"></span></div></div>
  <div class="card"><div class="label">Equity curve</div><div class="chart" id="chart"></div></div>
 </div>
 <div class="stats" id="stats"></div>
 <div class="card" id="costbar" style="margin-bottom:8px"></div>
 <h2>Open positions</h2><div class="grid" id="open"></div>
 <h2>Recent closed trades</h2><div class="card" id="closedWrap"></div>
 <footer>Simulated paper trading — no real orders, no real money. Auto-refreshes every 8s.</footer>
</div>
<script>
const SESSIONS = __SESSIONS__;
const $=id=>document.getElementById(id);
let active = 0, available = [];
const money=n=>(n<0?'-$':'$')+Math.abs(n).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
const px=n=>{n=Number(n);const d=Math.abs(n)>=100?2:Math.abs(n)>=1?4:5;return n.toFixed(d);};

function sparkline(hist){
 const pts=hist.map(h=>h.equity).filter(v=>v!=null);
 if(pts.length<2) return '<div class="empty">no ticks yet</div>';
 const w=520,h=120,lo=Math.min(...pts),hi=Math.max(...pts),rng=(hi-lo)||1;
 const X=i=>i/(pts.length-1)*w, Y=v=>h-(v-lo)/rng*(h-12)-6;
 const d=pts.map((v,i)=>`${i?'L':'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(' ');
 const up=pts[pts.length-1]>=pts[0], col=up?'#34d399':'#fb7185';
 const base=(lo<=10000&&10000<=hi)?`<line x1="0" y1="${Y(10000).toFixed(1)}" x2="${w}" y2="${Y(10000).toFixed(1)}" stroke="#475569" stroke-dasharray="4 5" stroke-width="1"/>`:'';
 return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><defs><linearGradient id="g" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${col}" stop-opacity=".28"/><stop offset="1" stop-color="${col}" stop-opacity="0"/></linearGradient></defs>${base}<path d="${d} L${w},${h} L0,${h} Z" fill="url(#g)"/><path d="${d}" fill="none" stroke="${col}" stroke-width="2" stroke-linejoin="round"/></svg>`;
}
function statTile(l,v,cls){return `<div class="stat"><div class="label">${l}</div><div class="v mono ${cls||''}">${v}</div></div>`;}
function posCard(p){
 const buy=p.dir===1, side=buy?'buy':'sell';
 const lo=Math.min(p.stop,p.target),hi=Math.max(p.stop,p.target);
 let f=(p.entry-lo)/((hi-lo)||1); f=Math.max(0,Math.min(1,f));
 const risk=Math.abs(p.entry-p.stop)*p.units;
 return `<div class="pos"><div class="top"><span class="pair">${p.pair.replace('=X','').replace('-USD','')}</span>
  <span class="pill ${side}">${buy?'▲ BUY':'▼ SELL'}</span></div>
  <div class="mono" style="font-size:20px;font-weight:700">${px(p.entry)}</div>
  <div class="gauge"><span class="mk" style="left:${(f*100).toFixed(0)}%"></span></div>
  <div class="legs"><span>SL ${px(p.stop)}</span><span>entry</span><span>TP ${px(p.target)}</span></div>
  <div class="meta"><span>units <b class="mono">${p.units.toLocaleString()}</b></span><span>risk <b class="mono">${money(risk)}</b></span></div></div>`;
}
function renderTabs(){
 $('tabs').innerHTML=available.map((s,k)=>`<div class="tab ${k===active?'on':''}" onclick="pick(${k})">${s.label}</div>`).join('');
}
window.pick=k=>{active=k;renderTabs();load();};

function render(s){
 const start=10000,pnl=s.balance-start,pct=pnl/start*100,cls=pnl>=0?'up':'down';
 const asset=s.asset||'forex';
 $('strat').textContent=`${s.strategy}${s.aggressive?' aggressive':''} · ${asset} · ${s.interval} · ${(s.source||'')}`;
 $('balance').textContent=money(s.balance);
 $('pnl').innerHTML=`<span class="${cls}">${pnl>=0?'▲':'▼'} ${money(pnl)} (${pct>=0?'+':''}${pct.toFixed(2)}%)</span>`;
 const peak=s.peak||start,dd=peak>0?(peak-s.balance)/peak*100:0;
 $('ddtag').textContent=`drawdown ${dd.toFixed(1)}%`;
 $('chart').innerHTML=sparkline(s.history||[]);
 const closed=s.closed||[],pnls=closed.map(c=>c.pnl),wins=pnls.filter(p=>p>0);
 const wr=pnls.length?(wins.length/pnls.length*100):0;
 const gw=wins.reduce((a,b)=>a+b,0),gl=Math.abs(pnls.filter(p=>p<=0).reduce((a,b)=>a+b,0));
 const pf=gl>0?(gw/gl).toFixed(2):'—';
 $('stats').innerHTML=[statTile('Open',Object.keys(s.open||{}).length),statTile('Closed trades',closed.length),
  statTile('Win rate',wr.toFixed(0)+'%'),statTile('Profit factor',pf,pf!=='—'&&pf>1?'up':(pf!=='—'?'down':''))].join('');
 // cost-bleed analysis
 const costs=s.costs_paid||0, gross=pnl+costs, perTr=closed.length?costs/closed.length:0;
 const eaten=gross>0?costs/gross*100:null, bleed=eaten!=null&&eaten>50;
 $('costbar').innerHTML=`<div class="label">Cost bleed — fees + spread + slippage</div>
  <div style="display:flex;gap:26px;flex-wrap:wrap;align-items:baseline;margin-top:8px;font-size:13px">
   <span class="mut">fees paid <b class="mono down">${money(costs)}</b></span>
   <span class="mut">per trade <b class="mono">${money(perTr)}</b></span>
   <span class="mut">gross P&L <b class="mono ${gross>=0?'up':'down'}">${money(gross)}</b></span>
   <span class="mut">net P&L <b class="mono ${pnl>=0?'up':'down'}">${money(pnl)}</b></span>
   ${eaten!=null?`<span class="mut">fees ate <b class="mono ${bleed?'down':'up'}">${eaten.toFixed(0)}%</b> of gross</span>`
     :(closed.length?'<span class="mut down">strategy is net-negative before fees too</span>':'<span class="mut">no closed trades yet</span>')}
  </div>`;
 const open=Object.values(s.open||{});
 $('open').innerHTML=open.length?open.map(posCard).join(''):'<div class="empty">no open positions</div>';
 const rows=[...closed].slice(-12).reverse().map(c=>`<tr><td><b>${c.pair.replace('=X','').replace('-USD','')}</b></td>
  <td><span class="pill ${c.dir===1?'buy':'sell'}">${c.dir===1?'BUY':'SELL'}</span></td>
  <td class="mono">${px(c.entry)} → ${px(c.exit)}</td><td><span class="tag">${c.reason||''}</span></td>
  <td class="mono ${c.pnl>=0?'up':'down'}" style="text-align:right">${money(c.pnl)}</td>
  <td class="mono" style="color:var(--mut)">${(c.closed_at||'').slice(0,16).replace('T',' ')}</td></tr>`).join('');
 $('closedWrap').innerHTML=closed.length?`<table><thead><tr><th>Pair</th><th>Side</th><th>Entry → Exit</th><th>Exit</th><th style="text-align:right">P&L</th><th>When</th></tr></thead><tbody>${rows}</tbody></table>`:'<div class="empty">no closed trades yet</div>';
}
async function probe(){
 available=[];
 for(const s of SESSIONS){
  try{const r=await fetch(s.file+'?t='+Date.now(),{cache:'no-store'});if(r.ok){await r.json();available.push(s);}}catch(e){}
 }
 if(active>=available.length) active=0;
 renderTabs();
}
async function load(){
 if(!available.length){await probe();}
 if(!available.length){$('updated').textContent='waiting for paper sessions…';return;}
 try{
  const r=await fetch(available[active].file+'?t='+Date.now(),{cache:'no-store'});
  render(await r.json());
  $('updated').textContent='updated '+new Date().toLocaleTimeString();
 }catch(e){$('updated').textContent='session unavailable';}
}
(async()=>{await probe();await load();setInterval(load,8000);setInterval(probe,30000);})();
</script></body></html>"""


def write(path: str = "dashboard.html") -> str:
    import json
    sessions = [{"label": lbl, "file": f} for lbl, f in SESSIONS]
    html = _HTML.replace("__SESSIONS__", json.dumps(sessions))
    with open(path, "w") as f:
        f.write(html)
    return path
