"""Local-only, dependency-free browser dashboard. No credentials are returned to browser."""
from __future__ import annotations
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .engine import RadarEngine

PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Rockstar Live Radar | FYERS pilot</title>
<style>
:root{color-scheme:dark;font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;--bg:#0b1020;--panel:#131b2e;--border:#2a3650;--muted:#93a0b6;--text:#f2f6ff;--green:#48d3a4;--gold:#e9c46a;--blue:#8bbaff;--red:#ff8797}
*{box-sizing:border-box}body{background:var(--bg);color:var(--text);margin:0;font-size:14px} main{max-width:1460px;margin:auto;padding:24px}
header{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:22px}h1{margin:3px 0;font-size:29px;letter-spacing:-1px}small,.muted{color:var(--muted)}.eyebrow{font-size:11px;letter-spacing:2px;color:var(--green);font-weight:750}
.chip{border:1px solid var(--border);background:#1b263a;padding:8px 11px;border-radius:9px;color:var(--muted)}.chip strong{color:var(--text)}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.card,.section{border:1px solid var(--border);border-radius:13px;background:var(--panel);padding:17px}.card .number{font-size:31px;font-weight:750;margin:7px 0}.card label{font-size:12px;color:var(--muted)}.layout{display:grid;grid-template-columns:2.1fr 1fr;gap:15px;margin-top:18px}.section{overflow:hidden}.section h2{font-size:16px;margin:0 0 14px}.sub{color:var(--muted);font-size:12px;margin-top:-7px;margin-bottom:13px}
table{border-collapse:collapse;width:100%;text-align:left}td,th{padding:11px 8px;border-bottom:1px solid #243149;white-space:nowrap}th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.7px}td{font-size:12px;font-variant-numeric:tabular-nums}.symbol{font-weight:750;font-size:13px}a{color:#a7c8ff;text-decoration:none}a:hover{text-decoration:underline}.pill{border:1px solid #44506b;border-radius:7px;padding:4px 8px;font-size:11px;font-weight:700;display:inline-block}.pill.CONFIRMED,.pill.RETEST_READY{color:var(--green);border-color:#337c71;background:#10382f}.pill.READY,.pill.BREAKOUT_PENDING{color:var(--blue);border-color:#406092;background:#182c51}.pill.WATCH{color:var(--gold);border-color:#66572e;background:#352c18}.pill.RISK_FAIL,.pill.FAILED,.pill.STALE,.pill.SIGNAL_AGED{color:var(--red);border-color:#7b4154}.pill.NONE,.pill.WAIT_OR,.pill.NO_SETUP,.pill.WAIT_VOLUME,.pill.RECOVERING,.pill.SESSION_CLOSED{color:var(--muted)}.pill.RETRACTED{color:var(--red);border-color:#7b4154;background:#2e1620}.prov{display:inline-block;margin-left:6px;font-size:9px;font-weight:800;letter-spacing:.5px;color:#ffcf8f;border:1px solid #7a5a2b;background:#3a2b14;border-radius:5px;padding:2px 5px;vertical-align:middle}
.src{display:inline-block;font-size:10px;border-radius:5px;border:1px solid #3a5b78;color:#b4d8ff;background:#162b42;padding:3px 6px}.src.AUTO{color:var(--muted);border-color:#43506a;background:#1b263a}.tiny{font-size:11px;color:var(--muted)}.good{color:var(--green)}.bad{color:var(--red)}.feed{font-size:11px;max-width:390px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:12px}button,select{color:var(--text);border:1px solid var(--border);background:#22304a;border-radius:9px;padding:8px 11px;cursor:pointer;font:inherit}input{accent-color:var(--green)}.scroll{overflow:auto;max-height:480px}.alerts{max-height:470px;overflow:auto}.alert{border-bottom:1px solid #29344b;padding:11px 0}.alert-head{display:flex;justify-content:space-between;align-items:center;gap:8px}.alert p{color:var(--muted);line-height:1.35;font-size:12px;margin:5px 0 0}.score{font-weight:750;font-size:15px}.notice{padding:14px;border:1px solid #6b5435;background:#33291e;color:#f4dab0;border-radius:10px;margin-top:16px;font-size:12px;line-height:1.5}footer{color:var(--muted);margin-top:16px;font-size:11px}
@media(max-width:1000px){.layout{grid-template-columns:1fr}.cards{grid-template-columns:repeat(2,1fr)}}@media(max-width:520px){main{padding:12px}h1{font-size:25px}.card{padding:10px}.card .number{font-size:25px}}
</style></head><body><main>
<header><div><div class="eyebrow">NSE • INTRADAY • 5-MIN OPENING RANGE</div><h1>Rockstar Live Radar</h1><small>Automatic discovery and evidence logging — not automatic order placement.</small></div>
<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center"><span class="chip" id="mode">MODE: ...</span><span class="chip" id="clock">--:--:-- IST</span><span class="chip feed" id="feed">FEED ...</span></div></header>
<div id="sessionNotice" class="notice" style="display:none;margin-bottom:16px"></div>
<div class="cards"><div class="card"><label>Universe tracked</label><div class="number" id="monitored">—</div><small><span id="morningcount">0</span> morning picks · FYERS cap 100</small></div><div class="card"><label>OR levels ready</label><div class="number" id="anchors">—</div><small>First candle 09:15–09:20</small></div><div class="card"><label>Volume baselines ready</label><div class="number" id="baseline">—</div><small>Prior 20 sessions, same 5-min slot</small></div><div class="card"><label>Active setups</label><div class="number" id="candidates">—</div><small>Not trade recommendations</small></div></div>
<div class="notice"><b>Execution gate:</b> WATCH / READY / BREAKOUT_PENDING = monitoring only. CONFIRMED means a completed FYERS 5-minute candle met the scanner rules, <b>not an entry signal</b>. RETEST_READY only suggests an estimated 2R opportunity against prior-session levels; verify actual MIS eligibility, spread, costs, resistance, market trend and fills independently. Live mode has a strict stale-feed gate. A <b>LIVE·PROV</b> badge means the signal was built from the live tick feed and is awaiting the authoritative FYERS candle — it may be <b>validated</b> or <b>RETRACTED</b> seconds later; treat provisional signals as early warnings, not confirmed entries.</div>
<div class="layout"><div class="section"><h2>Top five watch candidates</h2><div class="sub">Priority: retest-ready → confirmed → pending → ready → watch. Within a state, sorted by heuristic score.</div>
<div class="scroll"><table><thead><tr><th>Symbol</th><th>Source</th><th>Side</th><th>State</th><th>Last</th><th>OR H / L</th><th>RVOL</th><th>Score</th></tr></thead><tbody id="top"><tr><td colspan="8">No qualifying setups yet.</td></tr></tbody></table></div></div>
<div class="section"><h2>Signal journal</h2><div class="sub">Events persisted to CSV; high-risk candidates may still fail.</div><div class="controls"><button id="sound" onclick="toggleSound()">Enable sound</button><button onclick="copyAlerts()">Copy recent alerts</button></div><div id="alerts" class="alerts"><div class="tiny">No signals yet</div></div></div></div>
<div class="section" style="margin-top:16px"><h2>All monitored stocks</h2><div class="controls"><select id="source"><option value="">All sources</option><option value="MORNING">Morning Rockstar picks</option><option value="AUTO">Auto selected</option></select><select id="side"><option value="">All directions</option><option value="LONG">Long</option><option value="SHORT">Short</option></select><select id="status"><option value="">All states</option><option value="active">Only active setups</option><option value="RETEST_READY">Retest ready</option><option value="RISK_FAIL">Risk rejected</option></select><span class="tiny" id="updated">Updating...</span></div>
<div class="scroll"><table><thead><tr><th>Symbol</th><th>Source</th><th>Direction</th><th>Status</th><th>Price</th><th>ORH</th><th>ORL</th><th>VWAP*</th><th>RVOL</th><th>Score</th><th>Comment</th></tr></thead><tbody id="all"></tbody></table></div></div>
<footer>* VWAP: FYERS daily average trade price during live tick updates; otherwise an OHLC-typical-price weighted approximation from completed candles. Scoring is heuristic, not a win probability. No auto-orders, margin/MIS verification, or investment advice. Data source in the current run is shown above.</footer>
</main><script>
let latest=null, sound=false, lastSeen='';
const el=id=>document.getElementById(id);
const td=(row,text,cls='')=>{let t=document.createElement('td');t.textContent=text??'—';if(cls)t.className=cls;row.appendChild(t);return t;};
const pill=(row,text,provisional=false)=>{let t=document.createElement('td');const s=document.createElement('span');s.className='pill '+text;s.textContent=text||'—';t.appendChild(s);if(provisional){const p=document.createElement('span');p.className='prov';p.textContent='LIVE·PROV';p.title='Provisional: built from the live tick feed; awaiting authoritative FYERS candle. May be validated or retracted.';t.appendChild(p);}row.appendChild(t)};
const fmt=x=>typeof x==='number'?x.toLocaleString('en-IN',{maximumFractionDigits:2}):'—';
function link(row,sym){let c=document.createElement('td');const a=document.createElement('a');let bare=sym.replace('NSE:','').replace(/-EQ$/,'');a.textContent=bare;a.href='https://www.tradingview.com/chart/?symbol='+encodeURIComponent('NSE:'+bare);a.target='_blank';a.rel='noreferrer';a.className='symbol';c.appendChild(a);row.appendChild(c);}
function renderTable(id,rows,full=false){let dest=el(id);dest.textContent=''; if(!rows.length){let r=dest.insertRow();td(r,'No qualifying setups yet.');return;} rows.forEach(s=>{let r=dest.insertRow();link(r,s.symbol);let sc=document.createElement('td');let sb=document.createElement('span');sb.className='src '+(s.source||'AUTO');sb.textContent=s.source||'AUTO';sc.appendChild(sb);r.appendChild(sc);td(r,s.side||'—');pill(r,s.state,s.provisional);td(r,fmt(s.price));if(full){td(r,fmt(s.orh));td(r,fmt(s.orl));td(r,fmt(s.vwap_proxy));td(r,s.rvol===null?'—':s.rvol.toFixed(2)+'×');td(r,s.score+'/100','score');let msg=td(r,s.reason||'');msg.title=s.reason||'';msg.style.maxWidth='300px';msg.style.overflow='hidden';msg.style.textOverflow='ellipsis';}else{td(r,fmt(s.orh)+' / '+fmt(s.orl));td(r,s.rvol===null?'—':s.rvol.toFixed(2)+'×');td(r,s.score+'/100','score');}});}
function render(){if(!latest)return;const j=latest;el('mode').textContent=j.mode+' • '+j.session;el('clock').textContent=j.server_time_ist+' IST';el('feed').textContent='FEED: '+j.feed_health;el('feed').title=j.feed_health;
const notice=el('sessionNotice');notice.style.display=j.session_closed?'block':'none';notice.textContent=j.session_closed?'REVIEW ONLY: Today\'s new-signal scan ended at '+j.new_signals_stop+' IST. Top 5 is intentionally empty. Historical signals below are NOT current trade ideas.':'';
el('monitored').textContent=j.monitored;el('morningcount').textContent=j.morning_monitored||0;el('anchors').textContent=j.anchors_ready;el('baseline').textContent=j.baselines_ready;el('candidates').textContent=j.active_candidates;el('updated').textContent='Updated '+j.server_time_ist+' IST';renderTable('top',j.top5);
const fSource=el('source').value,fSide=el('side').value,fStatus=el('status').value;renderTable('all',j.all.filter(s=>(!fSource||s.source===fSource)&&(!fSide||s.side===fSide)&&(!fStatus||(fStatus==='active'?['WATCH','READY','BREAKOUT_PENDING','CONFIRMED','RETEST_READY'].includes(s.state):s.state===fStatus))),true);
const dest=el('alerts');dest.textContent='';if(!j.events.length){dest.textContent='No signals yet';return;}j.events.slice(0,40).forEach(e=>{let d=document.createElement('div');d.className='alert';let h=document.createElement('div');h.className='alert-head';let t=document.createElement('strong');t.textContent=e.symbol.replace('NSE:','').replace('-EQ','')+' · '+e.side;let c=document.createElement('span');c.className='pill '+e.state;c.textContent=e.state;h.append(t,c);if(e.provisional){let p=document.createElement('span');p.className='prov';p.textContent='LIVE·PROV';h.append(p);}d.appendChild(h);let n=document.createElement('p');n.textContent=e.time+' IST · Score '+e.score+' · '+e.note;d.appendChild(n);dest.appendChild(d)});
if(sound&&j.events.length&&lastSeen&&j.events[0].time+j.events[0].symbol+j.events[0].state!==lastSeen){try{let ctx=new (window.AudioContext||window.webkitAudioContext)();let o=ctx.createOscillator(),g=ctx.createGain();o.connect(g);g.connect(ctx.destination);o.frequency.value=730;g.gain.value=.07;o.start();o.stop(ctx.currentTime+.13)}catch(e){}}
if(j.events.length)lastSeen=j.events[0].time+j.events[0].symbol+j.events[0].state;}
async function fetchData(){try{let response=await fetch('/api/state',{cache:'no-store'});if(!response.ok)throw new Error('HTTP '+response.status);latest=await response.json();render();}catch(e){el('feed').textContent='Dashboard fetch failed: '+e.message;}}
function toggleSound(){sound=!sound;el('sound').textContent=sound?'Disable sound':'Enable sound'}
function copyAlerts(){if(!latest)return;const value=latest.events.map(x=>x.time+' '+x.symbol+' '+x.side+' '+x.state+' '+x.note).join('\n');navigator.clipboard?.writeText(value)}
el('source').addEventListener('change',render);el('side').addEventListener('change',render);el('status').addEventListener('change',render);fetchData();setInterval(fetchData,2000);
</script></body></html>'''


def serve(engine: RadarEngine, port: int = 8765, mode: str = 'LIVE'):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/api/state':
                content = json.dumps(engine.snapshot(), allow_nan=False).encode('utf-8')
                mime = 'application/json; charset=utf-8'
            elif self.path in ('/', '/index.html'):
                content = PAGE.encode('utf-8')
                mime = 'text/html; charset=utf-8'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(content)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, fmt, *args):
            pass  # don't put app-specific or token information into console logs

    httpd = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'{mode} dashboard: http://127.0.0.1:{port} (only accessible on this computer)')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\nShutting down dashboard.')
    finally:
        httpd.server_close()
