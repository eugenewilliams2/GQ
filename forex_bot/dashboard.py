"""
Live paper-trading dashboard — generates a self-contained dashboard.html that
polls paper_state.json and re-renders. Served by the local web server, it shows
balance, P&L, an equity curve, open positions, and closed trades, refreshing on
its own as each paper tick updates the state.
"""

from __future__ import annotations
import os

_HTML = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GQ · Live Paper Trading</title>
<style>
 :root{
  --bg:#070b14; --bg2:#0c1322; --card:rgba(20,28,46,.7); --line:rgba(110,130,170,.14);
  --txt:#e6edf7; --mut:#7e8aa3; --up:#34d399; --down:#fb7185; --acc:#6ea8fe;
 }
 *{box-sizing:border-box} html,body{margin:0;height:100%}
 body{background:radial-gradient(1200px 700px at 80% -10%,#13203a 0%,var(--bg) 55%);
  color:var(--txt);font:14px/1.5 'Inter',system-ui,-apple-system,Segoe UI,sans-serif;
  -webkit-font-smoothing:antialiased;padding:26px;min-height:100%}
 .mono{font-family:'SF Mono',ui-monospace,Menlo,monospace;font-variant-numeric:tabular-nums}
 .wrap{max-width:1100px;margin:0 auto}
 header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:22px}
 .brand{font-weight:700;font-size:18px;letter-spacing:.04em}
 .brand b{color:var(--acc)} .brand .sub{color:var(--mut);font-weight:500;font-size:12px;margin-top:2px}
 .live{display:flex;align-items:center;gap:8px;color:var(--mut);font-size:12px}
 .dot{width:9px;height:9px;border-radius:50%;background:var(--up);box-shadow:0 0 0 0 rgba(52,211,153,.6);
  animation:pulse 2s infinite}
 @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(52,211,153,.5)}70%{box-shadow:0 0 0 10px rgba(52,211,153,0)}100%{box-shadow:0 0 0 0 rgba(52,211,153,0)}}
 .hero{display:grid;grid-template-columns:1.1fr 1fr;gap:16px;margin-bottom:16px}
 .card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:20px;
  backdrop-filter:blur(12px);box-shadow:0 10px 40px rgba(0,0,0,.25)}
 .label{color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.12em;margin-bottom:8px}
 .balance{font-size:42px;font-weight:700;letter-spacing:-.02em}
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
 .up{color:var(--up)} .down{color:var(--down)}
 .empty{color:var(--mut);padding:24px;text-align:center;border:1px dashed var(--line);border-radius:14px}
 .tag{font-size:10px;color:var(--mut);background:rgba(110,130,170,.12);padding:2px 7px;border-radius:6px}
 footer{color:var(--mut);font-size:11px;text-align:center;margin-top:26px;opacity:.7}
</style></head><body><div class="wrap">
 <header>
  <div class="brand">GQ <b>Paper</b> Trading<div class="sub" id="strat">loading…</div></div>
  <div class="live"><span class="dot"></span><span id="updated">connecting…</span></div>
 </header>

 <div class="hero">
  <div class="card">
   <div class="label">Equity</div>
   <div class="balance mono" id="balance">$—</div>
   <div class="pnl mono"><span id="pnl">—</span><span class="tag" id="ddtag"></span></div>
  </div>
  <div class="card">
   <div class="label">Equity curve</div>
   <div class="chart" id="chart"></div>
  </div>
 </div>

 <div class="stats" id="stats"></div>

 <h2>Open positions</h2>
 <div class="grid" id="open"></div>

 <h2>Recent closed trades</h2>
 <div class="card" id="closedWrap"></div>

 <footer>Simulated paper trading — no real orders, no real money. Auto-refreshes every 8s.</footer>
</div>
<script>
const $=id=>document.getElementById(id);
const money=n=>(n<0?'-$':'$')+Math.abs(n).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
const px=n=>Number(n).toFixed(5);

function sparkline(hist){
 const pts=hist.map(h=>h.equity).filter(v=>v!=null);
 if(pts.length<2) return '<div class="empty">no ticks yet</div>';
 const w=520,h=120,lo=Math.min(...pts),hi=Math.max(...pts),rng=(hi-lo)||1;
 const X=i=>i/(pts.length-1)*w, Y=v=>h-(v-lo)/rng*(h-12)-6;
 const d=pts.map((v,i)=>`${i?'L':'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(' ');
 const up=pts[pts.length-1]>=pts[0], col=up?'#34d399':'#fb7185';
 const area=`${d} L${w},${h} L0,${h} Z`;
 const base=(lo<=10000&&10000<=hi)?`<line x1="0" y1="${Y(10000).toFixed(1)}" x2="${w}" y2="${Y(10000).toFixed(1)}" stroke="#475569" stroke-dasharray="4 5" stroke-width="1"/>`:'';
 return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
  <defs><linearGradient id="g" x1="0" x2="0" y1="0" y2="1">
   <stop offset="0" stop-color="${col}" stop-opacity=".28"/><stop offset="1" stop-color="${col}" stop-opacity="0"/></linearGradient></defs>
  ${base}<path d="${area}" fill="url(#g)"/><path d="${d}" fill="none" stroke="${col}" stroke-width="2" stroke-linejoin="round"/></svg>`;
}

function statTile(l,v,cls){return `<div class="stat"><div class="label">${l}</div><div class="v mono ${cls||''}">${v}</div></div>`;}

function posCard(p){
 const buy=p.dir===1, side=buy?'buy':'sell';
 // marker position of entry between stop(0%) and target(100%)
 const lo=Math.min(p.stop,p.target), hi=Math.max(p.stop,p.target);
 let frac=(p.entry-lo)/((hi-lo)||1); frac=Math.max(0,Math.min(1,frac));
 const risk=Math.abs(p.entry-p.stop)*p.units;
 return `<div class="pos">
  <div class="top"><span class="pair">${p.pair.replace('=X','')}</span>
   <span class="pill ${side}">${buy?'▲ BUY':'▼ SELL'}</span></div>
  <div class="mono" style="font-size:20px;font-weight:700">${px(p.entry)}</div>
  <div class="gauge"><span class="mk" style="left:${(frac*100).toFixed(0)}%"></span></div>
  <div class="legs"><span>SL ${px(p.stop)}</span><span>entry</span><span>TP ${px(p.target)}</span></div>
  <div class="meta"><span>units <b class="mono">${p.units.toLocaleString()}</b></span>
   <span>risk <b class="mono">${money(risk)}</b></span></div>
 </div>`;
}

async function load(){
 try{
  const r=await fetch('paper_state.json?t='+Date.now(),{cache:'no-store'});
  if(!r.ok) throw 0;
  const s=await r.json();
  render(s);
  $('updated').textContent='updated '+new Date().toLocaleTimeString();
 }catch(e){ $('updated').textContent='waiting for paper_state.json…'; }
}

function render(s){
 const start=10000, pnl=s.balance-start, pct=pnl/start*100;
 const cls=pnl>=0?'up':'down';
 $('strat').textContent=`${s.strategy} · ${s.interval} · since ${(s.created||'').slice(0,10)}`;
 $('balance').textContent=money(s.balance);
 $('pnl').innerHTML=`<span class="${cls}">${pnl>=0?'▲':'▼'} ${money(pnl)} (${pct>=0?'+':''}${pct.toFixed(2)}%)</span>`;
 const peak=s.peak||start, dd=peak>0?(peak-s.balance)/peak*100:0;
 $('ddtag').textContent=`drawdown ${dd.toFixed(1)}%`;
 $('chart').innerHTML=sparkline(s.history||[]);

 const closed=s.closed||[], pnls=closed.map(c=>c.pnl), wins=pnls.filter(p=>p>0);
 const wr=pnls.length?(wins.length/pnls.length*100):0;
 const gw=wins.reduce((a,b)=>a+b,0), gl=Math.abs(pnls.filter(p=>p<=0).reduce((a,b)=>a+b,0));
 const pf=gl>0?(gw/gl).toFixed(2):'—';
 $('stats').innerHTML=[
  statTile('Open positions',Object.keys(s.open||{}).length),
  statTile('Closed trades',closed.length),
  statTile('Win rate',wr.toFixed(0)+'%'),
  statTile('Profit factor',pf,pf!=='—'&&pf>1?'up':(pf!=='—'?'down':'')),
 ].join('');

 const open=Object.values(s.open||{});
 $('open').innerHTML=open.length?open.map(posCard).join(''):'<div class="empty">no open positions</div>';

 const rows=[...closed].slice(-12).reverse().map(c=>`<tr>
  <td><b>${c.pair.replace('=X','')}</b></td>
  <td><span class="pill ${c.dir===1?'buy':'sell'}">${c.dir===1?'BUY':'SELL'}</span></td>
  <td class="mono">${px(c.entry)} → ${px(c.exit)}</td>
  <td><span class="tag">${c.reason||''}</span></td>
  <td class="mono ${c.pnl>=0?'up':'down'}" style="text-align:right">${money(c.pnl)}</td>
  <td class="mono" style="color:var(--mut)">${(c.closed_at||'').slice(0,10)}</td></tr>`).join('');
 $('closedWrap').innerHTML=closed.length?
  `<table><thead><tr><th>Pair</th><th>Side</th><th>Entry → Exit</th><th>Exit</th><th style="text-align:right">P&L</th><th>Date</th></tr></thead><tbody>${rows}</tbody></table>`
  :'<div class="empty">no closed trades yet</div>';
}
load(); setInterval(load,8000);
</script></body></html>"""


def write(path: str = "dashboard.html") -> str:
    with open(path, "w") as f:
        f.write(_HTML)
    return path
