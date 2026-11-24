import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from './api.js'

const ROWS = [
  ['RELIANCE', 'LONG', 92, 'up'],
  ['TATAMOTORS', 'LONG', 86, 'up'],
  ['HDFCBANK', 'SHORT', 81, 'down'],
  ['INFY', 'LONG', 74, 'up'],
]

export default function Login({ onDevLogin }) {
  const [cfg, setCfg] = useState({ google: false, dev: false })
  const nav = useNavigate()
  useEffect(() => { api('/auth/config').then(setCfg).catch(() => {}) }, [])

  return (
    <div className="rr-login">
      <style>{CSS}</style>
      <div className="rl-glow" aria-hidden="true" />
      <div className="rl-grid-mask" aria-hidden="true" />

      <button className="rl-back" onClick={() => nav('/')}>← Back to home</button>

      <div className="rl-wrap">
        {/* sign-in card */}
        <div className="rl-card">
          <div className="rl-brand"><span className="rl-mark">⚡</span><b>Rockstar&nbsp;Radar</b></div>
          <div className="rl-eyebrow"><span className="rl-dot" />Intraday · Indian markets</div>
          <h1 className="rl-h1">Welcome back.</h1>
          <p className="rl-sub">Sign in to your NSE opening-range radar — your watchlist, journal and paper P&amp;L, right where you left them.</p>

          {cfg.google ? (
            <a className="rl-gbtn" href="/auth/google/login">
              <svg width="18" height="18" viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.9 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.2C12.4 13.5 17.7 9.5 24 9.5z" /><path fill="#4285F4" d="M46.1 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.4c-.5 2.9-2.1 5.3-4.6 7l7.1 5.5c4.2-3.9 6.6-9.6 6.6-16.5z" /><path fill="#FBBC05" d="M10.5 28.4c-.5-1.5-.8-3-.8-4.4s.3-3 .8-4.4l-7.9-6.2C1 16.7 0 20.2 0 24s1 7.3 2.6 10.6l7.9-6.2z" /><path fill="#34A853" d="M24 48c6.3 0 11.6-2.1 15.5-5.7l-7.1-5.5c-2 1.3-4.6 2.2-8.4 2.2-6.3 0-11.6-4-13.5-9.9l-7.9 6.2C6.5 42.6 14.6 48 24 48z" /></svg>
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

          <div className="rl-trust">🔒 OAuth — we never see or store your password</div>
          <div className="rl-foot">Your intraday co-pilot for the Indian markets.</div>
        </div>

        {/* live radar mock */}
        <div className="rl-aside">
          <div className="rl-mini">
            <div className="rl-minih"><span className="rl-spin" />live radar<span className="rl-live rl-ml" /></div>
            {ROWS.map(([sym, side, score, dir], i) => (
              <div className="rl-mrow" style={{ '--d': (i * 0.5) + 's' }} key={sym}>
                <span className="rl-sym">{sym}</span>
                <span className={'rl-side ' + dir}>{side}</span>
                <span className="rl-mbar"><i style={{ '--w': score + '%' }} /></span>
                <span className="rl-mscore">{score}</span>
              </div>
            ))}
            <div className="rl-ticker"><span className="rl-tk">+2.4R today</span><span className="rl-tk mut">6 open · paper</span></div>
          </div>
          <div className="rl-asidenote">Ranked intraday breakouts with entry, stop &amp; targets — you confirm every trade.</div>
        </div>
      </div>
    </div>
  )
}

const CSS = `
.rr-login{
  --bg:#0a0e16;--surface:#141b2b;--surface2:#0e1420;--border:#212a3e;--border2:#2c3650;
  --fg:#e7edf5;--muted:#97a4ba;--faint:#64708a;
  --acc:#3b82f6;--acc2:#60a5fa;--acc-ink:#cfe0ff;--acc-bg:#0f1d3a;--acc-weak:rgba(59,130,246,.12);
  --up:#22c55e;--down:#f43f5e;
  --fd:"Space Grotesk",Inter,system-ui,-apple-system,"Segoe UI",sans-serif;
  --fm:ui-monospace,"SF Mono","JetBrains Mono",Menlo,monospace;
  position:relative;min-height:100vh;min-height:100dvh;display:flex;align-items:center;justify-content:center;
  padding:clamp(20px,5vw,48px);overflow:clip;background:var(--bg);color:var(--fg);
  font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.5}
.rr-login *{box-sizing:border-box}
.rr-login h1{font-family:var(--fd);font-weight:700;margin:0;letter-spacing:-.02em}
@keyframes rl-pulse{0%,100%{box-shadow:0 0 0 0 rgba(59,130,246,0)}50%{box-shadow:0 0 0 5px rgba(59,130,246,.18)}}
@keyframes rl-pulseg{0%,100%{box-shadow:0 0 0 0 rgba(34,197,94,0)}50%{box-shadow:0 0 0 4px rgba(34,197,94,.22)}}
@keyframes rl-spin{to{transform:rotate(360deg)}}
@keyframes rl-fill{from{width:0}}
@keyframes rl-rowscan{0%,14%,100%{background:transparent}4%{background:rgba(59,130,246,.10)}}
@keyframes rl-glow{0%,100%{opacity:.65;transform:scale(1)}50%{opacity:1;transform:scale(1.05)}}

.rl-glow{position:absolute;inset:-25% -10% auto -10%;height:720px;z-index:0;pointer-events:none;transform-origin:50% 20%;animation:rl-glow 7s ease-in-out infinite;
  background:radial-gradient(42% 48% at 30% 0%,rgba(59,130,246,.32),transparent 70%),radial-gradient(38% 46% at 82% 8%,rgba(96,165,250,.22),transparent 72%),radial-gradient(34% 44% at 60% 26%,rgba(34,197,94,.1),transparent 72%)}
.rl-grid-mask{position:absolute;inset:0;z-index:0;pointer-events:none;
  background-image:linear-gradient(rgba(255,255,255,.03) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.03) 1px,transparent 1px);background-size:50px 50px;
  -webkit-mask-image:radial-gradient(70% 60% at 50% 0%,#000,transparent 72%);mask-image:radial-gradient(70% 60% at 50% 0%,#000,transparent 72%)}
.rl-back{position:absolute;top:22px;left:22px;z-index:3;all:unset;cursor:pointer;font-size:13px;font-weight:600;color:var(--muted);padding:8px 13px;border-radius:9px;border:1px solid var(--border2);background:rgba(255,255,255,.03)}
.rl-back:hover{color:var(--fg);border-color:var(--acc)}

.rl-wrap{position:relative;z-index:2;display:grid;grid-template-columns:minmax(0,420px) minmax(0,360px);gap:26px;align-items:center;width:100%;max-width:840px}
@media(max-width:800px){.rl-wrap{grid-template-columns:1fr;max-width:440px}.rl-aside{display:none}}

.rl-card{background:linear-gradient(180deg,rgba(20,27,43,.92),rgba(14,20,32,.92));border:1px solid var(--border2);border-radius:20px;padding:clamp(26px,4vw,38px);box-shadow:0 40px 90px -30px rgba(0,0,0,.85),0 2px 0 rgba(255,255,255,.03) inset;backdrop-filter:blur(8px)}
.rl-brand{display:flex;align-items:center;gap:10px;font-family:var(--fd);font-size:17px;font-weight:700;margin-bottom:22px}
.rl-mark{width:32px;height:32px;border-radius:9px;background:linear-gradient(135deg,var(--acc2),var(--acc));display:grid;place-items:center;font-size:17px;flex:none;box-shadow:0 8px 20px -8px rgba(59,130,246,.8)}
.rl-eyebrow{display:inline-flex;align-items:center;gap:8px;font-size:12px;font-weight:600;font-family:var(--fm);color:var(--acc-ink);background:var(--acc-weak);border:1px solid rgba(59,130,246,.28);padding:5px 12px;border-radius:999px;margin-bottom:16px}
.rl-dot{width:7px;height:7px;border-radius:50%;background:var(--acc2);animation:rl-pulse 2.4s infinite}
.rl-h1{font-size:clamp(26px,4vw,34px);line-height:1.05}
.rl-sub{color:var(--muted);font-size:14.5px;line-height:1.55;margin:12px 0 26px;max-width:42ch}

.rl-gbtn{display:flex;align-items:center;justify-content:center;gap:11px;width:100%;padding:13px 16px;border-radius:12px;background:#fff;color:#1a1f2b;font-size:15px;font-weight:600;cursor:pointer;transition:.15s;border:1px solid #fff}
.rl-gbtn:hover{filter:brightness(.97);transform:translateY(-1px)}
.rl-banner{font-size:13px;line-height:1.5;color:#ffd98a;background:rgba(245,184,74,.1);border:1px solid rgba(245,184,74,.3);border-radius:11px;padding:12px 14px;text-align:left}
.rl-banner code{font-family:var(--fm);font-size:12px;background:rgba(0,0,0,.3);padding:1px 5px;border-radius:4px;color:#ffe0a3}
.rl-alt{display:flex;align-items:center;gap:12px;margin:16px 0;color:var(--faint);font-size:12px}
.rl-alt::before,.rl-alt::after{content:"";flex:1;height:1px;background:var(--border)}
.rl-devbtn{all:unset;cursor:pointer;display:block;width:100%;text-align:center;padding:11px 16px;border-radius:12px;border:1px solid var(--border2);background:rgba(255,255,255,.03);color:var(--fg);font-size:14px;font-weight:600}
.rl-devbtn:hover{border-color:var(--acc);color:var(--acc-ink)}
.rl-trust{margin-top:22px;font-size:12px;color:var(--faint);display:flex;align-items:center;gap:7px}
.rl-foot{margin-top:8px;font-size:12px;color:var(--faint);font-family:var(--fd)}

/* aside radar mock */
.rl-aside{display:flex;flex-direction:column;gap:14px}
.rl-mini{background:var(--surface2);border:1px solid var(--border);border-radius:18px;padding:16px;box-shadow:0 30px 70px -28px rgba(0,0,0,.8)}
.rl-minih{display:flex;align-items:center;gap:8px;font-family:var(--fm);font-size:11px;color:var(--muted);padding:2px 4px 13px;text-transform:uppercase;letter-spacing:.4px}
.rl-spin{width:11px;height:11px;border-radius:50%;border:1.6px solid var(--acc);border-right-color:transparent;display:inline-block;animation:rl-spin .9s linear infinite;flex:none}
.rl-live{width:7px;height:7px;border-radius:50%;background:var(--up);display:inline-block;animation:rl-pulseg 1.8s infinite}
.rl-ml{margin-left:auto}
.rl-mrow{display:grid;grid-template-columns:1.4fr .7fr 2fr .5fr;gap:10px;align-items:center;padding:10px 8px;border-radius:9px;font-size:12.5px;border-top:1px solid rgba(255,255,255,.05);animation:rl-rowscan 5s linear infinite;animation-delay:var(--d)}
.rl-sym{font-weight:700;font-family:var(--fd)}
.rl-side{font-weight:700;font-size:11px;font-family:var(--fm)}.rl-side.up{color:var(--up)}.rl-side.down{color:var(--down)}
.rl-mbar{height:6px;border-radius:4px;background:rgba(255,255,255,.06);overflow:hidden}
.rl-mbar i{display:block;height:100%;width:var(--w);border-radius:4px;background:linear-gradient(90deg,var(--acc),var(--acc2));animation:rl-fill 1.4s ease both}
.rl-mscore{font-family:var(--fm);font-weight:700;text-align:right;color:var(--acc-ink)}
.rl-ticker{display:flex;gap:14px;padding:13px 8px 2px;border-top:1px solid rgba(255,255,255,.05);margin-top:4px}
.rl-tk{font-family:var(--fm);font-size:11.5px;font-weight:700;color:var(--up)}.rl-tk.mut{color:var(--faint);font-weight:400}
.rl-asidenote{font-size:12.5px;color:var(--muted);line-height:1.5;padding:0 6px}

@media(prefers-reduced-motion:reduce){.rr-login *{animation:none!important}.rl-mbar i{width:var(--w)}}
`
