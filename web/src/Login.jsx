import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from './api.js'

const ROWS = [
  ['RELIANCE', 'LONG', 92, 'CONFIRMED', 'up', '2,841', '2,903'],
  ['TATAMOTORS', 'LONG', 86, 'RETEST', 'up', '978', '1,012'],
  ['HDFCBANK', 'SHORT', 81, 'RETEST', 'down', '1,654', '1,598'],
  ['INFY', 'LONG', 74, 'WATCH', 'up', '1,512', '1,556'],
  ['MARUTI', 'SHORT', 69, 'WATCH', 'down', '12,730', '12,470'],
]

export default function Login({ onDevLogin }) {
  const [cfg, setCfg] = useState({ google: false, dev: false })
  const nav = useNavigate()
  useEffect(() => { api('/auth/config').then(setCfg).catch(() => {}) }, [])

  return (
    <div className="rr-login">
      <style>{CSS}</style>

      {/* ---- left: sign-in ---- */}
      <div className="rl-left">
        <div className="rl-top">
          <div className="rl-brand"><span className="rl-mark">⚡</span><b>Rockstar&nbsp;Radar</b></div>
          <button className="rl-home" onClick={() => nav('/')}>← Home</button>
        </div>

        <div className="rl-signin">
          <div className="rl-eyebrow"><span className="rl-dot" />Intraday · Indian markets</div>
          <h1 className="rl-h1">Welcome back.</h1>
          <p className="rl-sub">Sign in to your NSE opening-range radar — your watchlist, journal and paper P&amp;L, right where you left them.</p>

          {cfg.google ? (
            <a className="rl-gbtn" href="/auth/google/login">
              <svg width="19" height="19" viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.9 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.2C12.4 13.5 17.7 9.5 24 9.5z" /><path fill="#4285F4" d="M46.1 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.4c-.5 2.9-2.1 5.3-4.6 7l7.1 5.5c4.2-3.9 6.6-9.6 6.6-16.5z" /><path fill="#FBBC05" d="M10.5 28.4c-.5-1.5-.8-3-.8-4.4s.3-3 .8-4.4l-7.9-6.2C1 16.7 0 20.2 0 24s1 7.3 2.6 10.6l7.9-6.2z" /><path fill="#34A853" d="M24 48c6.3 0 11.6-2.1 15.5-5.7l-7.1-5.5c-2 1.3-4.6 2.2-8.4 2.2-6.3 0-11.6-4-13.5-9.9l-7.9 6.2C6.5 42.6 14.6 48 24 48z" /></svg>
              Continue with Google
            </a>
          ) : (
            <div className="rl-banner">
              Google sign-in isn't configured yet. Set <code>GOOGLE_CLIENT_ID</code> and <code>GOOGLE_CLIENT_SECRET</code> to enable it.
            </div>
          )}

          {cfg.dev && (
            <>
              <div className="rl-alt"><span>or</span></div>
              <button className="rl-devbtn" onClick={onDevLogin}>Continue as test user (dev)</button>
            </>
          )}

          <div className="rl-trust"><span>🔒 OAuth — password never stored</span><span className="rl-sep">·</span><span>Paper-first</span><span className="rl-sep">·</span><span>Not investment advice</span></div>
        </div>

        <div className="rl-foot">© Rockstar Radar · Your intraday co-pilot for the Indian markets.</div>
      </div>

      {/* ---- right: gradient showcase ---- */}
      <div className="rl-right">
        <div className="rl-rgrid" aria-hidden="true" />
        <div className="rl-rinner">
          <h2 className="rl-rtitle">Ranked NSE breakouts.<br />You confirm every trade.</h2>
          <p className="rl-rsub">Live opening-range setups scored 0–100, each with entry, stop and targets — modelled with real costs.</p>

          <div className="rl-frame">
            <span className="rl-scan" aria-hidden="true" />
            <div className="rl-bar">
              <span className="rl-dots"><i /><i /><i /></span>
              <span className="rl-url">intraday.live/radar</span>
              <span className="rl-livebadge"><i />LIVE</span>
            </div>
            <div className="rl-app">
              <div className="rl-tablehd"><span>Symbol</span><span>Side</span><span className="rl-n">Score</span><span>State</span></div>
              {ROWS.map(([sym, side, score, state, dir], i) => (
                <div className="rl-row" style={{ '--d': (i * 0.5) + 's' }} key={sym}>
                  <span className="rl-sym">{sym}</span>
                  <span className={'rl-side ' + dir}>{side}</span>
                  <span className="rl-n"><span className="rl-score"><i style={{ '--w': score + '%' }} />{score}</span></span>
                  <span><span className={'rl-chip ' + (state === 'CONFIRMED' ? 'ok' : state === 'RETEST' ? 'acc' : 'mut')}>{state}</span></span>
                </div>
              ))}
              <div className="rl-ticker"><span className="rl-tk">+2.4R today</span><span className="rl-tk mut">6 open · paper</span><span className="rl-tk mut">flat by 3:20</span></div>
            </div>
          </div>

          <div className="rl-chips">
            <span className="rl-cchip">NSE 500 scanned live</span>
            <span className="rl-cchip">Bring your own broker</span>
            <span className="rl-cchip">Honest paper P&amp;L</span>
          </div>
        </div>
      </div>
    </div>
  )
}

const CSS = `
.rr-login{
  --bg:#090d14;--panel:#0d131f;--border:#1e2740;--border2:#2a3550;
  --fg:#eef2f8;--muted:#9aa6bd;--faint:#67728a;
  --acc:#3b82f6;--acc2:#60a5fa;--acc-ink:#cfe0ff;--acc-bg:#0f1d3a;--acc-weak:rgba(59,130,246,.12);
  --up:#22c55e;--down:#f43f5e;
  --fd:"Space Grotesk",Inter,system-ui,-apple-system,"Segoe UI",sans-serif;
  --fm:ui-monospace,"SF Mono","JetBrains Mono",Menlo,monospace;
  min-height:100vh;min-height:100dvh;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.08fr);
  background:var(--bg);color:var(--fg);font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.5;overflow:hidden}
.rr-login *{box-sizing:border-box}
.rr-login h1,.rr-login h2{font-family:var(--fd);font-weight:700;margin:0;letter-spacing:-.025em}
@keyframes rl-pulse{0%,100%{box-shadow:0 0 0 0 rgba(59,130,246,0)}50%{box-shadow:0 0 0 5px rgba(59,130,246,.18)}}
@keyframes rl-pulseg{0%,100%{box-shadow:0 0 0 0 rgba(255,255,255,0)}50%{box-shadow:0 0 0 4px rgba(255,255,255,.25)}}
@keyframes rl-spin{to{transform:rotate(360deg)}}
@keyframes rl-fill{from{width:0}}
@keyframes rl-rowscan{0%,14%,100%{background:transparent}4%{background:rgba(59,130,246,.10)}}
@keyframes rl-sweep{0%{transform:translateX(-130%)}60%,100%{transform:translateX(560%)}}

/* ---------- LEFT ---------- */
.rl-left{position:relative;display:flex;flex-direction:column;padding:clamp(26px,3.5vw,46px);min-width:0}
.rl-left::before{content:"";position:absolute;inset:-180px -40% auto -20%;height:520px;z-index:0;pointer-events:none;
  background:radial-gradient(45% 55% at 30% 0%,rgba(59,130,246,.18),transparent 70%)}
.rl-top{position:relative;z-index:1;display:flex;align-items:center;justify-content:space-between}
.rl-brand{display:flex;align-items:center;gap:10px;font-family:var(--fd);font-size:16px;font-weight:700}
.rl-mark{width:30px;height:30px;border-radius:9px;background:linear-gradient(135deg,var(--acc2),var(--acc));display:grid;place-items:center;font-size:16px;flex:none;box-shadow:0 8px 20px -8px rgba(59,130,246,.8)}
.rl-home{all:unset;cursor:pointer;font-size:13px;font-weight:600;color:var(--muted);padding:7px 13px;border-radius:9px}
.rl-home:hover{color:var(--fg);background:rgba(255,255,255,.05)}
.rl-signin{position:relative;z-index:1;flex:1;display:flex;flex-direction:column;justify-content:center;max-width:400px;width:100%;margin:0 auto;padding:30px 0}
.rl-eyebrow{align-self:flex-start;display:inline-flex;align-items:center;gap:8px;font-size:12px;font-weight:600;font-family:var(--fm);color:var(--acc-ink);background:var(--acc-weak);border:1px solid rgba(59,130,246,.28);padding:5px 12px;border-radius:999px;margin-bottom:20px}
.rl-dot{width:7px;height:7px;border-radius:50%;background:var(--acc2);animation:rl-pulse 2.4s infinite}
.rl-h1{font-size:clamp(30px,4.4vw,40px);line-height:1.02}
.rl-sub{color:var(--muted);font-size:15px;line-height:1.6;margin:14px 0 30px}
.rl-gbtn{display:flex;align-items:center;justify-content:center;gap:12px;width:100%;padding:14px 16px;border-radius:13px;background:#fff;color:#16181d;font-size:15.5px;font-weight:600;cursor:pointer;transition:.15s;border:1px solid #fff;box-shadow:0 12px 30px -12px rgba(255,255,255,.25)}
.rl-gbtn:hover{filter:brightness(.97);transform:translateY(-1px)}
.rl-banner{font-size:13px;line-height:1.5;color:#ffd98a;background:rgba(245,184,74,.1);border:1px solid rgba(245,184,74,.3);border-radius:12px;padding:13px 15px}
.rl-banner code{font-family:var(--fm);font-size:12px;background:rgba(0,0,0,.3);padding:1px 5px;border-radius:4px;color:#ffe0a3}
.rl-alt{display:flex;align-items:center;gap:12px;margin:16px 0;color:var(--faint);font-size:12px;text-transform:uppercase;letter-spacing:.5px}
.rl-alt::before,.rl-alt::after{content:"";flex:1;height:1px;background:var(--border)}
.rl-devbtn{all:unset;cursor:pointer;display:block;width:100%;text-align:center;padding:12px 16px;border-radius:13px;border:1px solid var(--border2);background:rgba(255,255,255,.03);color:var(--fg);font-size:14px;font-weight:600}
.rl-devbtn:hover{border-color:var(--acc);color:var(--acc-ink)}
.rl-trust{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin-top:26px;font-size:12px;color:var(--faint)}
.rl-sep{opacity:.5}
.rl-foot{position:relative;z-index:1;font-size:12px;color:var(--faint)}

/* ---------- RIGHT (gradient showcase) ---------- */
.rl-right{position:relative;overflow:hidden;display:flex;align-items:center;justify-content:center;padding:clamp(28px,4vw,56px);
  background:linear-gradient(145deg,#0b1730 0%,#15337a 42%,#2563eb 78%,#3b82f6 100%)}
.rl-right::before{content:"";position:absolute;inset:-30% -20% auto -20%;height:70%;pointer-events:none;
  background:radial-gradient(50% 60% at 70% 0%,rgba(255,255,255,.22),transparent 70%)}
.rl-rgrid{position:absolute;inset:0;pointer-events:none;
  background-image:linear-gradient(rgba(255,255,255,.07) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.07) 1px,transparent 1px);background-size:46px 46px;
  -webkit-mask-image:radial-gradient(80% 80% at 60% 20%,#000,transparent 85%);mask-image:radial-gradient(80% 80% at 60% 20%,#000,transparent 85%)}
.rl-rinner{position:relative;z-index:1;width:100%;max-width:470px}
.rl-rtitle{color:#fff;font-size:clamp(24px,2.6vw,33px);line-height:1.1}
.rl-rsub{color:rgba(255,255,255,.82);font-size:15px;line-height:1.55;margin:14px 0 26px;max-width:42ch}
/* browser-framed radar mock */
.rl-frame{position:relative;background:#0a0f1a;border:1px solid rgba(255,255,255,.1);border-radius:15px;overflow:hidden;box-shadow:0 50px 100px -30px rgba(0,0,0,.7),0 10px 30px rgba(0,0,0,.4)}
.rl-scan{position:absolute;top:0;left:0;width:36%;height:100%;z-index:4;pointer-events:none;background:linear-gradient(90deg,transparent,rgba(96,165,250,.12),transparent);animation:rl-sweep 7s ease-in-out infinite}
.rl-bar{display:flex;align-items:center;gap:11px;padding:11px 14px;background:#0e1420;border-bottom:1px solid rgba(255,255,255,.07)}
.rl-dots{display:flex;gap:6px}.rl-dots i{width:10px;height:10px;border-radius:50%}
.rl-dots i:nth-child(1){background:#ff5f57}.rl-dots i:nth-child(2){background:#febc2e}.rl-dots i:nth-child(3){background:#28c840}
.rl-url{flex:1;text-align:center;font-family:var(--fm);font-size:11px;color:rgba(255,255,255,.4);background:rgba(0,0,0,.3);border:1px solid rgba(255,255,255,.08);border-radius:7px;padding:4px 10px;max-width:220px;margin:0 auto}
.rl-livebadge{display:inline-flex;align-items:center;gap:6px;font-size:10px;font-weight:700;color:var(--up);font-family:var(--fm)}
.rl-livebadge i{width:7px;height:7px;border-radius:50%;background:var(--up);display:inline-block;animation:rl-pulse 1.8s infinite}
.rl-app{padding:10px 12px 12px}
.rl-tablehd,.rl-row{display:grid;grid-template-columns:1.5fr .9fr 1.5fr 1.1fr;gap:10px;align-items:center;padding:9px 9px;border-radius:7px}
.rl-tablehd{font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:rgba(255,255,255,.35);font-weight:600}
.rl-row{border-top:1px solid rgba(255,255,255,.05);font-size:12.5px;animation:rl-rowscan 5s linear infinite;animation-delay:var(--d)}
.rl-sym{font-weight:700;font-family:var(--fd);color:#fff}
.rl-side{font-weight:700;font-size:11px;font-family:var(--fm)}.rl-side.up{color:var(--up)}.rl-side.down{color:var(--down)}
.rl-n{text-align:right}
.rl-score{display:inline-flex;align-items:center;gap:8px;font-family:var(--fm);font-weight:700;justify-content:flex-end;width:100%;color:#fff}
.rl-score i{height:5px;border-radius:3px;background:linear-gradient(90deg,var(--acc),var(--acc2));max-width:60px;width:var(--w);animation:rl-fill 1.3s ease both}
.rl-chip{font-size:9.5px;font-weight:700;font-family:var(--fm);padding:3px 8px;border-radius:6px;white-space:nowrap}
.rl-chip.ok{background:rgba(34,197,94,.16);color:#4ade80}.rl-chip.acc{background:rgba(59,130,246,.2);color:#93b4ff}.rl-chip.mut{background:rgba(255,255,255,.08);color:rgba(255,255,255,.5)}
.rl-ticker{display:flex;gap:15px;padding:12px 9px 2px;border-top:1px solid rgba(255,255,255,.05);margin-top:4px}
.rl-tk{font-family:var(--fm);font-size:11.5px;font-weight:700;color:var(--up)}.rl-tk.mut{color:rgba(255,255,255,.4);font-weight:400}
.rl-chips{display:flex;gap:9px;flex-wrap:wrap;margin-top:24px}
.rl-cchip{font-size:12px;font-weight:600;color:#fff;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.16);border-radius:999px;padding:6px 13px;backdrop-filter:blur(4px)}

@media(max-width:900px){
  .rr-login{display:block;overflow-x:hidden}
  .rl-right{display:none}
  .rl-left{width:100%;min-width:0;min-height:100dvh;padding:22px 20px}
  .rl-signin{max-width:420px;width:100%;min-width:0;margin:0 auto;padding:10px 0 40px}
  .rl-gbtn{font-size:15px}
}
@media(prefers-reduced-motion:reduce){.rr-login *{animation:none!important}.rl-score i{width:var(--w)}}
`
