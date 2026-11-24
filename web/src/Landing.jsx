import React from 'react'
import { useNavigate } from 'react-router-dom'

// ---- live radar mock rows ----
const RADAR_ROWS = [
  ['RELIANCE', 'LONG', 92, 'CONFIRMED', 'up', '2,841', '2,903'],
  ['TATAMOTORS', 'LONG', 86, 'RETEST', 'up', '978', '1,012'],
  ['HDFCBANK', 'SHORT', 81, 'RETEST', 'down', '1,654', '1,598'],
  ['INFY', 'LONG', 74, 'WATCH', 'up', '1,512', '1,556'],
  ['MARUTI', 'SHORT', 69, 'WATCH', 'down', '12,730', '12,470'],
]

// ---- how-it-works flow ----
const FLOW = [
  ['09:15–09:20', 'Opening range', 'The first five-minute high and low on the NSE-500 liquid universe — the level the whole day is measured against.', '📐'],
  ['09:20 →', 'Scan & score', 'Every breakout is scored on confluence — trend, market structure, volume and retest — then ranked 0–100. ~500 symbols, live.', '📡'],
  ['Your call', 'You confirm', 'Nothing fires on its own. You see entry, stop, target and the ₹ risk, and tap to take it — or skip it.', '✋'],
  ['Managed', 'Adaptive exit', 'Once you are in, the trade is managed to its stop and target, with a hard square-off by 3:20 — paper or live, same logic.', '🎯'],
]

// ---- stat band ----
const STATS = [
  ['NSE 500', 'liquid symbols scanned live'],
  ['09:15', 'opening range, every session'],
  ['0 passwords', 'OAuth only — your broker, your data'],
  ['Net of costs', 'brokerage · STT · slippage · margin'],
]

// ---- edge-by-score bars ----
const EDGE = [
  ['90–100', 82, '+0.81R', 'up'],
  ['80–89', 64, '+0.47R', 'up'],
  ['70–79', 41, '+0.18R', 'up'],
  ['< 70', 22, '−0.12R', 'down'],
]

// ---- comparison ----
const CMP = [
  ['Ranked, scored setups', false, false, true],
  ['Entry, stop & target pre-computed', false, 'part', true],
  ['Honest paper P&L, net of real costs', false, false, true],
  ['Your edge measured in R', false, false, true],
  ['You confirm every order', 'na', true, true],
  ['Your broker — password never shared', 'na', true, true],
]

function Cell({ v }) {
  if (v === true) return <span className="rr-y">✓</span>
  if (v === 'part') return <span className="rr-p">partial</span>
  if (v === 'na') return <span className="rr-na">—</span>
  return <span className="rr-n">✕</span>
}

export default function Landing() {
  const nav = useNavigate()
  return (
    <div className="rr-land">
      <style>{CSS}</style>

      <header className="rr-nav">
        <div className="rr-brand"><span className="rr-mark">⚡</span><b>Rockstar&nbsp;Radar</b><span className="rr-navsub">NSE intraday</span></div>
        <span className="rr-sp" />
        <a className="rr-nlink" href="#how">How it works</a>
        <a className="rr-nlink" href="#features">Features</a>
        <a className="rr-nlink" href="#compare">Why it's different</a>
        <a className="rr-nlink" href="/blog/how-to-connect-fyers">Guide</a>
        <button className="rr-btn pri" onClick={() => nav('/login')}>Sign in</button>
      </header>

      {/* ---------- HERO ---------- */}
      <section className="rr-hero">
        <div className="rr-head">
          <div className="rr-eyebrow"><span className="rr-dot" />Intraday · Indian markets · paper-first</div>
          <h1 className="rr-h1">Your intraday co-pilot for the <span className="rr-g">Indian markets</span>.</h1>
          <p className="rr-sub">A real-time NSE opening-range breakout radar. Bring your own broker and get
            ranked setups with entry, stop and targets — modelled with real costs, and with you in control of every single trade.</p>
          <div className="rr-ctas">
            <button className="rr-btn pri lg" onClick={() => nav('/login')}>Get started — it's free</button>
            <a className="rr-btn gh lg" href="#how">See how it works</a>
          </div>
          <div className="rr-foot-note">Paper-trading first · OAuth — no passwords stored · Not investment advice</div>
        </div>

        {/* animated product mock */}
        <div className="rr-shot">
          <div className="rr-frame">
            <span className="rr-scan" aria-hidden="true" />
            <div className="rr-bar">
              <span className="rr-dots"><i /><i /><i /></span>
              <span className="rr-url">intraday.live/radar</span>
              <span className="rr-livebadge"><i />LIVE</span>
            </div>
            <div className="rr-app">
              <div className="rr-scanrow">
                <span className="rr-spin" /> Scanning NSE-500 · opening-range breakouts
                <span className="rr-count">+2.4R today</span>
              </div>
              <div className="rr-tablehd"><span>Symbol</span><span>Side</span><span className="rr-num">Score</span><span>State</span><span className="rr-num">Entry → Target</span></div>
              {RADAR_ROWS.map(([sym, side, score, state, dir, e, t], i) => (
                <div className="rr-row" style={{ '--d': (i * 0.5) + 's' }} key={sym}>
                  <span className="rr-sym">{sym}</span>
                  <span className={'rr-side ' + dir}>{side}</span>
                  <span className="rr-num"><span className="rr-score"><i style={{ '--w': score + '%' }} />{score}</span></span>
                  <span><span className={'rr-chip ' + (state === 'CONFIRMED' ? 'ok' : state === 'RETEST' ? 'acc' : 'mut')}>{state}</span></span>
                  <span className="rr-num rr-lvl">{e} → {t}</span>
                </div>
              ))}
              <div className="rr-ticker">
                <span className="rr-tk">6 open · paper</span>
                <span className="rr-tk mut">feed <i className="rr-live" />live</span>
                <span className="rr-tk mut">flat by 3:20</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ---------- STAT BAND ---------- */}
      <section className="rr-statband">
        {STATS.map(([n, l]) => (<div key={l}><div className="rr-sn">{n}</div><div className="rr-sl">{l}</div></div>))}
      </section>

      {/* ---------- HOW IT WORKS (flow) ---------- */}
      <section className="rr-sec" id="how">
        <div className="rr-head">
          <div className="rr-kick">How it works</div>
          <h2 className="rr-h2">From the opening bell to a confirmed trade.</h2>
          <p className="rr-dek">Four steps, every session. The radar does the watching and the maths; you make the call.</p>
        </div>
        <div className="rr-flow">
          {FLOW.map(([tag, title, body, icon], i) => (
            <React.Fragment key={title}>
              <div className={'rr-node' + (i === 1 ? ' act' : '') + (i === 2 ? ' gate' : '')}>
                <div className="rr-ntag">{tag}</div>
                <div className="rr-nh"><span className="rr-nic">{icon}</span>{title}</div>
                <p>{body}</p>
                {i === 1 && <div className="rr-nlive"><span className="rr-spin sm" />scoring 500 symbols…</div>}
                {i === 2 && <div className="rr-ngate">awaiting your tap</div>}
              </div>
              {i < FLOW.length - 1 && <div className="rr-conn" aria-hidden="true">→</div>}
            </React.Fragment>
          ))}
        </div>
        <div className="rr-loop">↻ repeats live through the session · new signals until 15:00 · square-off by 15:20</div>
      </section>

      {/* ---------- FEATURE ROWS ---------- */}
      <section className="rr-sec" id="features">
        <div className="rr-head">
          <div className="rr-kick">What it does</div>
          <h2 className="rr-h2">A radar, a journal, and an honest paper engine.</h2>
          <p className="rr-dek">Everything you need to find intraday setups, act on them with discipline, and know — with real numbers — whether you actually have an edge.</p>
        </div>

        {/* A — radar */}
        <div className="rr-feat">
          <div className="rr-ftext">
            <div className="rr-ftag">Opening-range radar</div>
            <h3>See every breakout the moment it fires — ranked.</h3>
            <p>Live NSE intraday breakouts across the liquid universe, each scored 0–100 on confluence and sorted so the best setup is always on top.</p>
            <ul className="rr-flist">
              <li><span>✓</span>Entry, stop-loss and targets pre-computed</li>
              <li><span>✓</span>Long and short, with clear invalidation</li>
              <li><span>✓</span>Nothing fires on its own — you review and decide</li>
            </ul>
          </div>
          <div className="rr-fmock">
            <div className="rr-mini">
              <div className="rr-minih"><span className="rr-spin sm" />live radar<span className="rr-live rr-ml" /></div>
              {RADAR_ROWS.slice(0, 4).map(([sym, side, score, , dir], i) => (
                <div className="rr-mrow" style={{ '--d': (i * 0.5) + 's' }} key={sym}>
                  <span className="rr-sym">{sym}</span>
                  <span className={'rr-side ' + dir}>{side}</span>
                  <span className="rr-mbar"><i style={{ '--w': score + '%' }} /></span>
                  <span className="rr-mscore">{score}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* B — edge (reversed) */}
        <div className="rr-feat rev">
          <div className="rr-ftext">
            <div className="rr-ftag">Journal & your edge in R</div>
            <h3>Know if the edge is real — measured in R.</h3>
            <p>Every opportunity the radar flagged and every trade you took, scored net of costs. Win rate, expectancy and your return broken down by setup quality.</p>
            <ul className="rr-flist">
              <li><span>✓</span>Win rate &amp; expectancy, updated each session</li>
              <li><span>✓</span>R returns bucketed by score — see what actually pays</li>
              <li><span>✓</span>Honest: losers counted, costs subtracted</li>
            </ul>
          </div>
          <div className="rr-fmock">
            <div className="rr-mini">
              <div className="rr-minih">your edge · by score bucket</div>
              <div className="rr-kpis">
                <div><b>58%</b><span>win rate</span></div>
                <div><b className="rr-up">+0.42R</b><span>expectancy</span></div>
                <div><b>120</b><span>trades</span></div>
              </div>
              <div className="rr-ebars">
                {EDGE.map(([lbl, h, r, dir]) => (
                  <div className="rr-ecol" key={lbl}>
                    <span className="rr-er">{r}</span>
                    <i className={'rr-ebar ' + dir} style={{ '--h': h + '%' }} />
                    <span className="rr-elbl">{lbl}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* C — paper engine */}
        <div className="rr-feat">
          <div className="rr-ftext">
            <div className="rr-ftag">Paper-first, cost-true</div>
            <h3>Paper trading that behaves like the real thing.</h3>
            <p>Prove the edge in paper mode with real brokerage, STT, slippage and live margin from your own broker — so a green month actually means something before you risk a rupee.</p>
            <ul className="rr-flist">
              <li><span>✓</span>Per-stock MIS margin pulled live from the broker</li>
              <li><span>✓</span>Brokerage, STT, exchange, GST &amp; slippage modelled</li>
              <li><span>✓</span>An exact replica of how the live order would fill</li>
            </ul>
          </div>
          <div className="rr-fmock">
            <div className="rr-receipt">
              <div className="rr-rch"><b>RELIANCE</b><span className="rr-side up">LONG · 70 qty · MIS</span></div>
              <div className="rr-rline"><span>Gross P&amp;L</span><b className="rr-up">+₹2,180</b></div>
              <div className="rr-rline sub"><span>− Brokerage</span><span>₹40</span></div>
              <div className="rr-rline sub"><span>− STT + exchange</span><span>₹83</span></div>
              <div className="rr-rline sub"><span>− Slippage (8 bps)</span><span>₹95</span></div>
              <div className="rr-rfill"><i /></div>
              <div className="rr-rline net"><span>Net P&amp;L</span><b className="rr-up">+₹1,962 · +1.4R</b></div>
              <div className="rr-rnote"><span className="rr-live rr-ml" />margin checked live · ₹1.33L blocked</div>
            </div>
          </div>
        </div>

        {/* D — broker (reversed) */}
        <div className="rr-feat rev">
          <div className="rr-ftext">
            <div className="rr-ftag">Bring your own broker</div>
            <h3>Your broker, your account, your data.</h3>
            <p>Connect FYERS once with OAuth — we never see your password. A quick daily login keeps the live feed running (a SEBI rule for every broker).</p>
            <ul className="rr-flist">
              <li><span>✓</span>OAuth login — credentials never touch our servers</li>
              <li><span>✓</span>Live market data straight from your broker</li>
              <li><span>✓</span>Zerodha &amp; more coming</li>
            </ul>
          </div>
          <div className="rr-fmock">
            <div className="rr-mini rr-broker">
              <div className="rr-bkrow ok"><span className="rr-bklogo">FY</span><div><b>FYERS</b><span>connected</span></div><span className="rr-live rr-ml" /></div>
              <div className="rr-bkstat"><span>feed</span><b className="rr-up">live · streaming</b></div>
              <div className="rr-bkstat"><span>token</span><b>valid today</b></div>
              <div className="rr-bkstat"><span>password stored</span><b className="rr-up">never</b></div>
              <div className="rr-bkrow soon"><span className="rr-bklogo z">Z</span><div><b>Zerodha</b><span>coming soon</span></div></div>
            </div>
          </div>
        </div>
      </section>

      {/* ---------- COMPARISON ---------- */}
      <section className="rr-sec" id="compare">
        <div className="rr-head">
          <div className="rr-kick">Why it's different</div>
          <h2 className="rr-h2">Not a tip group. Not a raw terminal.</h2>
          <p className="rr-dek">A disciplined system that ranks, prices and journals your intraday trades — while you stay in control.</p>
        </div>
        <div className="rr-cmpwrap">
          <table className="rr-cmp">
            <thead><tr><th>Capability</th><th>Tip / Telegram group</th><th>Raw broker terminal</th><th>Rockstar Radar</th></tr></thead>
            <tbody>
              {CMP.map(([label, a, b, c]) => (
                <tr key={label}><td>{label}</td><td><Cell v={a} /></td><td><Cell v={b} /></td><td className="rr-mine"><Cell v={c} /></td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* ---------- CTA ---------- */}
      <section className="rr-cta">
        <h2>Trade with a co-pilot, not on a hunch.</h2>
        <p>Free to start, paper-first, your broker. Prove the edge before you risk a rupee.</p>
        <button className="rr-btn w lg" onClick={() => nav('/login')}>Sign in to Rockstar Radar</button>
      </section>

      <footer className="rr-footer">
        <span className="rr-fbrand"><span className="rr-mark sm">⚡</span>Rockstar Radar — NSE intraday</span>
        <span className="rr-dim">Short-term trading is risky. This is a personal tool, not investment advice.</span>
        <span className="rr-flinks">
          <a href="/blog/how-to-connect-fyers">Connect FYERS guide</a>
          <a href="#how">How it works</a>
        </span>
      </footer>
    </div>
  )
}

const CSS = `
.rr-land{
  --bg:#0a0e16;--surface:#141b2b;--surface2:#0e1420;--surface3:#1a2335;
  --border:#212a3e;--border2:#2c3650;--fg:#e7edf5;--muted:#97a4ba;--faint:#64708a;
  --acc:#3b82f6;--acc2:#60a5fa;--acc-ink:#cfe0ff;--acc-bg:#0f1d3a;--acc-weak:rgba(59,130,246,.12);
  --up:#22c55e;--up-ink:#86efac;--up-weak:rgba(34,197,94,.14);
  --down:#f43f5e;--down-ink:#fda4b4;--down-weak:rgba(244,63,94,.14);
  --warn:#f5b84a;--warn-weak:rgba(245,184,74,.15);
  --fd:"Space Grotesk",Inter,system-ui,-apple-system,"Segoe UI",sans-serif;
  --fm:ui-monospace,"SF Mono","JetBrains Mono",Menlo,monospace;
  background:var(--bg);color:var(--fg);min-height:100vh;
  font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.5;overflow-x:clip}
.rr-land *{box-sizing:border-box}
.rr-land h1,.rr-land h2,.rr-land h3{font-family:var(--fd);font-weight:700;margin:0;letter-spacing:-.02em;text-wrap:balance}
.rr-land a{color:inherit;text-decoration:none}
.rr-up{color:var(--up)}.rr-down{color:var(--down)}

/* keyframes (looping — reads like a live product, not a screenshot) */
@keyframes rr-pulse{0%,100%{box-shadow:0 0 0 0 rgba(59,130,246,.0)}50%{box-shadow:0 0 0 5px rgba(59,130,246,.18)}}
@keyframes rr-pulseg{0%,100%{box-shadow:0 0 0 0 rgba(34,197,94,0)}50%{box-shadow:0 0 0 4px rgba(34,197,94,.22)}}
@keyframes rr-spin{to{transform:rotate(360deg)}}
@keyframes rr-sweep{0%{transform:translateX(-130%)}60%,100%{transform:translateX(560%)}}
@keyframes rr-fill{from{width:0}}
@keyframes rr-rise{from{transform:scaleY(.04);opacity:.4}}
@keyframes rr-glow{0%,100%{opacity:.6;transform:scale(1)}50%{opacity:1;transform:scale(1.05)}}
@keyframes rr-rowscan{0%,14%,100%{background:transparent}4%{background:rgba(59,130,246,.10)}}
@keyframes rr-breathe{0%,100%{box-shadow:0 0 0 0 rgba(59,130,246,0)}50%{box-shadow:0 0 0 4px rgba(59,130,246,.18)}}
@keyframes rr-blink{0%,48%{opacity:1}52%,100%{opacity:0}}
@keyframes rr-progress{0%{width:18%}70%{width:72%}100%{width:72%}}

/* buttons */
.rr-btn{all:unset;cursor:pointer;font-size:14px;font-weight:600;padding:9px 16px;border-radius:10px;border:1px solid var(--border2);background:var(--surface3);color:var(--fg);text-align:center;white-space:nowrap;transition:.15s}
.rr-btn:hover{border-color:var(--acc)}
.rr-btn.pri{background:linear-gradient(180deg,var(--acc2),var(--acc));border-color:transparent;color:#061126;box-shadow:0 8px 24px -8px rgba(59,130,246,.7)}
.rr-btn.pri:hover{filter:brightness(1.07)}
.rr-btn.gh{background:rgba(255,255,255,.04);border-color:rgba(255,255,255,.14);color:var(--fg)}
.rr-btn.gh:hover{border-color:rgba(255,255,255,.4)}
.rr-btn.w{background:#fff;color:var(--acc);border-color:#fff}
.rr-btn.w:hover{background:#eaf1ff}
.rr-btn.lg{padding:13px 24px;font-size:15px}

/* nav */
.rr-nav{position:sticky;top:0;z-index:50;display:flex;align-items:center;gap:8px;height:62px;padding:0 clamp(18px,4vw,40px);
  background:rgba(10,14,22,.74);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border-bottom:1px solid rgba(255,255,255,.06)}
.rr-brand{display:flex;align-items:center;gap:9px;font-family:var(--fd)}
.rr-mark{width:30px;height:30px;border-radius:9px;background:linear-gradient(135deg,var(--acc2),var(--acc));display:grid;place-items:center;font-size:16px;flex:none}
.rr-mark.sm{width:22px;height:22px;font-size:12px;border-radius:7px}
.rr-brand b{font-size:17px}
.rr-navsub{font-size:11px;color:var(--faint);border-left:1px solid var(--border);padding-left:9px;margin-left:3px}
.rr-sp{flex:1}
.rr-nlink{font-size:13.5px;color:var(--muted);font-weight:500;padding:7px 11px;border-radius:8px}
.rr-nlink:hover{color:var(--fg);background:rgba(255,255,255,.05)}
@media(max-width:860px){.rr-nlink{display:none}}

/* shared section head — always centered, bulletproof */
.rr-head{max-width:760px;margin:0 auto;text-align:center;display:flex;flex-direction:column;align-items:center}
.rr-kick,.rr-eyebrow{font-family:var(--fm)}
.rr-kick{font-size:12px;font-weight:700;letter-spacing:.9px;text-transform:uppercase;color:var(--acc-ink)}
.rr-h1,.rr-h2{text-align:center}
.rr-h2{font-size:clamp(26px,4vw,42px);line-height:1.08;margin:12px 0 0}
.rr-dek{color:var(--muted);font-size:clamp(15px,1.6vw,17px);max-width:60ch;margin:14px 0 0;line-height:1.55;text-align:center}

/* hero */
.rr-hero{position:relative;padding:clamp(46px,8vw,88px) clamp(18px,4vw,40px) 0;overflow:clip}
.rr-hero::before{content:"";position:absolute;inset:-170px -10% auto -10%;height:760px;z-index:0;pointer-events:none;transform-origin:50% 16%;animation:rr-glow 7s ease-in-out infinite;
  background:radial-gradient(44% 50% at 50% 0%,rgba(59,130,246,.34),transparent 70%),radial-gradient(36% 44% at 80% 6%,rgba(96,165,250,.24),transparent 72%),radial-gradient(34% 44% at 18% 14%,rgba(34,197,94,.12),transparent 72%)}
.rr-hero::after{content:"";position:absolute;inset:0 0 auto 0;height:800px;z-index:0;pointer-events:none;
  background-image:linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px);background-size:50px 50px;
  -webkit-mask-image:radial-gradient(70% 56% at 50% 0%,#000,transparent 72%);mask-image:radial-gradient(70% 56% at 50% 0%,#000,transparent 72%)}
.rr-hero .rr-head{position:relative;z-index:2}
.rr-eyebrow{display:inline-flex;align-items:center;gap:8px;font-size:12px;font-weight:600;color:var(--acc-ink);background:var(--acc-weak);border:1px solid rgba(59,130,246,.28);padding:6px 14px;border-radius:999px;margin-bottom:22px}
.rr-dot{width:7px;height:7px;border-radius:50%;background:var(--acc2);animation:rr-pulse 2.4s infinite}
.rr-h1{font-size:clamp(34px,6vw,64px);line-height:1.03;letter-spacing:-.03em;max-width:16ch}
.rr-g{background:linear-gradient(110deg,var(--acc2),#bcd3ff 55%,var(--acc2));-webkit-background-clip:text;background-clip:text;color:transparent}
.rr-sub{font-size:clamp(15px,1.7vw,18px);color:var(--muted);max-width:58ch;margin:22px 0 26px;line-height:1.55}
.rr-ctas{display:flex;gap:12px;justify-content:center;flex-wrap:wrap}
.rr-foot-note{margin-top:18px;font-size:12.5px;color:var(--faint)}

/* product mock */
.rr-shot{position:relative;z-index:3;max-width:920px;margin:48px auto 0;padding:0 clamp(8px,2vw,16px)}
.rr-frame{position:relative;background:var(--surface2);border:1px solid var(--border);border-radius:14px 14px 0 0;overflow:hidden;
  box-shadow:0 46px 100px -30px rgba(0,0,0,.85),0 10px 30px rgba(0,0,0,.5)}
.rr-scan{position:absolute;top:0;left:0;width:36%;height:100%;z-index:4;pointer-events:none;background:linear-gradient(90deg,transparent,rgba(96,165,250,.10),transparent);animation:rr-sweep 7s ease-in-out infinite}
.rr-bar{display:flex;align-items:center;gap:12px;padding:11px 14px;background:#0f1522;border-bottom:1px solid var(--border)}
.rr-dots{display:flex;gap:6px}.rr-dots i{width:11px;height:11px;border-radius:50%}
.rr-dots i:nth-child(1){background:#ff5f57}.rr-dots i:nth-child(2){background:#febc2e}.rr-dots i:nth-child(3){background:#28c840}
.rr-url{flex:1;text-align:center;font-family:var(--fm);font-size:11.5px;color:var(--faint);background:var(--bg);border:1px solid var(--border);border-radius:7px;padding:4px 12px;max-width:260px;margin:0 auto}
.rr-livebadge{display:inline-flex;align-items:center;gap:6px;font-size:10.5px;font-weight:700;color:var(--up);font-family:var(--fm)}
.rr-livebadge i,.rr-live{width:7px;height:7px;border-radius:50%;background:var(--up);display:inline-block;animation:rr-pulseg 1.8s infinite}
.rr-app{padding:12px 14px 14px;background:var(--bg);text-align:left}
.rr-scanrow{display:flex;align-items:center;gap:9px;font-family:var(--fm);font-size:11.5px;color:var(--muted);padding:2px 6px 11px}
.rr-count{margin-left:auto;color:var(--up);font-weight:700}
.rr-spin{width:13px;height:13px;border-radius:50%;border:2px solid var(--acc);border-right-color:transparent;display:inline-block;animation:rr-spin .9s linear infinite;flex:none}
.rr-spin.sm{width:11px;height:11px;border-width:1.6px}
.rr-tablehd,.rr-row{display:grid;grid-template-columns:1.4fr .8fr 1.3fr 1fr 1.5fr;gap:10px;align-items:center;padding:9px 10px;border-radius:7px}
.rr-tablehd{font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;color:var(--faint);font-weight:600}
.rr-row{border-top:1px solid rgba(255,255,255,.05);font-size:12.5px;animation:rr-rowscan 5s linear infinite;animation-delay:var(--d)}
.rr-sym{font-weight:700;font-family:var(--fd)}
.rr-side{font-weight:700;font-size:11px;font-family:var(--fm)}.rr-side.up{color:var(--up)}.rr-side.down{color:var(--down)}
.rr-num{text-align:right;font-variant-numeric:tabular-nums}
.rr-lvl{font-family:var(--fm);color:var(--muted);font-size:11px}
.rr-score{display:inline-flex;align-items:center;gap:7px;font-family:var(--fm);font-weight:600;justify-content:flex-end;width:100%}
.rr-score i{height:5px;border-radius:3px;background:linear-gradient(90deg,var(--acc),var(--acc2));max-width:54px;width:var(--w);animation:rr-fill 1.3s ease both}
.rr-chip{font-size:10px;font-weight:700;font-family:var(--fm);padding:3px 8px;border-radius:6px;white-space:nowrap}
.rr-chip.ok{background:var(--up-weak);color:var(--up)}.rr-chip.acc{background:var(--acc-weak);color:var(--acc-ink)}.rr-chip.mut{background:rgba(255,255,255,.06);color:var(--muted)}
.rr-ticker{display:flex;gap:16px;padding:12px 10px 2px;border-top:1px solid rgba(255,255,255,.05);margin-top:4px}
.rr-tk{font-family:var(--fm);font-size:11.5px;font-weight:700;color:var(--up);display:inline-flex;align-items:center;gap:6px}.rr-tk.mut{color:var(--faint);font-weight:400}

/* stat band */
.rr-statband{display:grid;grid-template-columns:repeat(4,1fr);max-width:1000px;margin:clamp(40px,6vw,66px) auto 0;padding:0 clamp(18px,4vw,40px)}
.rr-statband>div{padding:20px;border-left:1px solid var(--border);text-align:center}
.rr-statband>div:first-child{border-left:0}
.rr-sn{font-family:var(--fd);font-size:clamp(20px,2.6vw,28px);font-weight:700;background:linear-gradient(120deg,var(--acc2),#bcd3ff);-webkit-background-clip:text;background-clip:text;color:transparent}
.rr-sl{font-size:12px;color:var(--muted);margin-top:5px}
@media(max-width:680px){.rr-statband{grid-template-columns:1fr 1fr}.rr-statband>div:nth-child(3){border-left:0}.rr-statband>div:nth-child(1),.rr-statband>div:nth-child(2){border-bottom:1px solid var(--border)}}

/* sections */
.rr-sec{max-width:1080px;margin:0 auto;padding:clamp(56px,9vw,104px) clamp(18px,4vw,40px) 0}

/* flow */
.rr-flow{display:grid;grid-template-columns:repeat(4,1fr) ;gap:0;align-items:stretch;margin-top:42px;position:relative}
.rr-node{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:20px;margin:0 7px;display:flex;flex-direction:column}
.rr-node.act{border-color:rgba(59,130,246,.55);animation:rr-breathe 3s infinite}
.rr-node.gate{border-color:rgba(245,184,74,.4)}
.rr-ntag{font-family:var(--fm);font-size:11px;font-weight:700;color:var(--acc-ink);margin-bottom:10px}
.rr-node.gate .rr-ntag{color:var(--warn)}
.rr-nh{display:flex;align-items:center;gap:9px;font-family:var(--fd);font-weight:700;font-size:16px}
.rr-nic{width:30px;height:30px;border-radius:9px;background:var(--acc-weak);display:grid;place-items:center;font-size:15px;flex:none}
.rr-node.gate .rr-nic{background:var(--warn-weak)}
.rr-node p{font-size:13px;color:var(--muted);margin:9px 0 0;line-height:1.5;flex:1}
.rr-nlive{display:inline-flex;align-items:center;gap:7px;margin-top:13px;font-family:var(--fm);font-size:10.5px;color:var(--acc-ink)}
.rr-ngate{display:inline-flex;align-items:center;gap:7px;margin-top:13px;font-family:var(--fm);font-size:10.5px;color:var(--warn);background:var(--warn-weak);border-radius:6px;padding:4px 9px;align-self:flex-start;animation:rr-pulse 2.6s infinite}
.rr-conn{display:none}
.rr-loop{margin:26px auto 0;max-width:620px;border:1px dashed rgba(59,130,246,.4);border-radius:999px;padding:9px 18px;text-align:center;font-family:var(--fm);font-size:11.5px;color:var(--acc-ink);background:var(--acc-weak)}
@media(max-width:860px){.rr-flow{grid-template-columns:1fr 1fr}.rr-node{margin:7px}}
@media(max-width:520px){.rr-flow{grid-template-columns:1fr}}

/* feature rows */
.rr-feat{display:grid;grid-template-columns:1fr 1fr;gap:clamp(28px,5vw,58px);align-items:center;padding:clamp(34px,6vw,58px) 0}
.rr-feat.rev .rr-fmock{order:-1}
.rr-ftag{font-family:var(--fm);font-size:12px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;color:var(--acc-ink);margin-bottom:12px}
.rr-feat h3{font-size:clamp(21px,2.6vw,30px);letter-spacing:-.02em;line-height:1.1;margin:0 0 12px}
.rr-feat p{color:var(--muted);font-size:15px;line-height:1.55;margin:0}
.rr-flist{list-style:none;margin:18px 0 0;padding:0;display:flex;flex-direction:column;gap:11px}
.rr-flist li{display:flex;align-items:flex-start;gap:11px;font-size:14px;color:var(--fg)}
.rr-flist li span{color:var(--acc2);font-weight:700;flex:none;margin-top:1px}
@media(max-width:820px){.rr-feat,.rr-feat.rev{grid-template-columns:1fr;gap:22px}.rr-feat.rev .rr-fmock{order:0}}

/* mock cards */
.rr-fmock{min-width:0}
.rr-mini{background:var(--surface2);border:1px solid var(--border);border-radius:16px;padding:14px;box-shadow:var(--sh-lg,0 24px 60px -24px rgba(0,0,0,.7))}
.rr-minih{display:flex;align-items:center;gap:8px;font-family:var(--fm);font-size:11px;color:var(--muted);padding:2px 4px 12px;text-transform:uppercase;letter-spacing:.4px}
.rr-ml{margin-left:auto}
.rr-mrow{display:grid;grid-template-columns:1.4fr .7fr 2fr .5fr;gap:10px;align-items:center;padding:9px 8px;border-radius:8px;font-size:12.5px;border-top:1px solid rgba(255,255,255,.05);animation:rr-rowscan 5s linear infinite;animation-delay:var(--d)}
.rr-mbar{height:6px;border-radius:4px;background:rgba(255,255,255,.06);overflow:hidden}
.rr-mbar i{display:block;height:100%;width:var(--w);border-radius:4px;background:linear-gradient(90deg,var(--acc),var(--acc2));animation:rr-fill 1.4s ease both}
.rr-mscore{font-family:var(--fm);font-weight:700;text-align:right;color:var(--acc-ink)}

/* edge mock */
.rr-kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;padding:4px 4px 14px}
.rr-kpis div{display:flex;flex-direction:column;gap:2px}
.rr-kpis b{font-family:var(--fd);font-size:18px}
.rr-kpis span{font-size:10.5px;color:var(--faint)}
.rr-ebars{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;align-items:end;height:140px;padding:8px 6px 0;border-top:1px solid rgba(255,255,255,.06)}
.rr-ecol{display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:6px;height:100%}
.rr-er{font-family:var(--fm);font-size:10.5px;font-weight:700;color:var(--muted)}
.rr-ebar{width:100%;max-width:42px;height:var(--h);border-radius:5px 5px 0 0;transform-origin:bottom;animation:rr-rise 1.1s ease both}
.rr-ebar.up{background:linear-gradient(180deg,var(--up),rgba(34,197,94,.4))}
.rr-ebar.down{background:linear-gradient(180deg,var(--down),rgba(244,63,94,.4))}
.rr-elbl{font-family:var(--fm);font-size:10px;color:var(--faint)}

/* receipt mock */
.rr-receipt{background:var(--surface2);border:1px solid var(--border);border-radius:16px;padding:18px 18px 16px;font-family:var(--fm);box-shadow:0 24px 60px -24px rgba(0,0,0,.7)}
.rr-rch{display:flex;align-items:center;justify-content:space-between;padding-bottom:13px;margin-bottom:10px;border-bottom:1px solid var(--border)}
.rr-rch b{font-family:var(--fd);font-size:16px}
.rr-rline{display:flex;align-items:center;justify-content:space-between;font-size:13px;padding:6px 0}
.rr-rline.sub{color:var(--muted);font-size:12px;padding:4px 0}
.rr-rline.net{border-top:1px solid var(--border);margin-top:8px;padding-top:12px;font-size:14px}
.rr-rfill{height:6px;border-radius:4px;background:rgba(255,255,255,.06);overflow:hidden;margin:10px 0 2px}
.rr-rfill i{display:block;height:100%;border-radius:4px;background:linear-gradient(90deg,var(--up),var(--up-ink));animation:rr-progress 2s ease-in-out infinite alternate}
.rr-rnote{display:flex;align-items:center;gap:8px;margin-top:12px;font-size:10.5px;color:var(--acc-ink);background:var(--acc-weak);border-radius:7px;padding:7px 10px}

/* broker mock */
.rr-broker{display:flex;flex-direction:column;gap:9px}
.rr-bkrow{display:flex;align-items:center;gap:11px;background:var(--surface);border:1px solid var(--border);border-radius:11px;padding:11px 13px}
.rr-bkrow.ok{border-color:rgba(34,197,94,.35)}
.rr-bkrow.soon{opacity:.6}
.rr-bkrow>div{display:flex;flex-direction:column}
.rr-bkrow b{font-family:var(--fd);font-size:14px}
.rr-bkrow span{font-size:11px;color:var(--muted)}
.rr-bklogo{width:34px;height:34px;border-radius:9px;background:linear-gradient(135deg,var(--acc2),var(--acc));display:grid;place-items:center;font-family:var(--fd);font-weight:700;font-size:13px;color:#061126;flex:none}
.rr-bklogo.z{background:linear-gradient(135deg,#9aa4b8,#5f6a7e);color:#0a0e16}
.rr-bkstat{display:flex;align-items:center;justify-content:space-between;font-size:12px;color:var(--muted);padding:5px 13px;font-family:var(--fm)}
.rr-bkstat b{color:var(--fg);font-weight:600}

/* comparison */
.rr-cmpwrap{margin-top:40px;overflow-x:auto}
.rr-cmp{width:100%;border-collapse:collapse;font-size:13.5px;background:var(--surface);border:1px solid var(--border);border-radius:16px;overflow:hidden;min-width:620px}
.rr-cmp th,.rr-cmp td{text-align:left;padding:14px 18px;border-bottom:1px solid var(--border)}
.rr-cmp th{font-size:11px;letter-spacing:.4px;text-transform:uppercase;color:var(--faint);font-weight:700;background:var(--surface2)}
.rr-cmp th:last-child{color:var(--acc-ink)}
.rr-cmp td:first-child,.rr-cmp th:first-child{font-weight:600;color:var(--fg)}
.rr-cmp td{color:var(--muted)}
.rr-cmp .rr-mine{background:var(--acc-weak)}
.rr-cmp tr:last-child td{border-bottom:0}
.rr-y{color:var(--up);font-weight:700}.rr-n{color:var(--faint)}.rr-p{color:var(--warn);font-weight:600}.rr-na{color:var(--faint)}

/* cta */
.rr-cta{max-width:1080px;margin:clamp(66px,9vw,104px) auto 0;padding:clamp(42px,6vw,64px) 28px;text-align:center;border-radius:24px;position:relative;overflow:hidden;
  background:linear-gradient(130deg,#0f1d3a,#2563eb 55%,#3b82f6);box-shadow:0 30px 70px -26px rgba(59,130,246,.6)}
.rr-cta::after{content:"";position:absolute;inset:0;background-image:linear-gradient(rgba(255,255,255,.07) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.07) 1px,transparent 1px);background-size:42px 42px;-webkit-mask-image:radial-gradient(75% 100% at 50% 0%,#000,transparent);mask-image:radial-gradient(75% 100% at 50% 0%,#000,transparent)}
.rr-cta h2{position:relative;z-index:1;color:#fff;font-size:clamp(24px,3.6vw,40px);line-height:1.06}
.rr-cta p{position:relative;z-index:1;color:rgba(255,255,255,.88);font-size:15.5px;margin:14px auto 24px;max-width:48ch}
.rr-cta .rr-btn{position:relative;z-index:1}

/* footer */
.rr-footer{max-width:1080px;margin:clamp(56px,8vw,90px) auto 0;padding:34px clamp(18px,4vw,40px) 56px;display:flex;flex-wrap:wrap;gap:12px 24px;align-items:center;border-top:1px solid var(--border);font-size:12.5px;color:var(--faint)}
.rr-fbrand{display:flex;align-items:center;gap:9px;color:var(--muted);font-family:var(--fd);font-weight:600}
.rr-dim{flex:1;min-width:200px}
.rr-flinks{display:flex;gap:18px}
.rr-flinks a:hover{color:var(--acc-ink)}

@media(prefers-reduced-motion:reduce){.rr-land *{animation:none!important}.rr-score i,.rr-mbar i,.rr-ebar{width:var(--w);height:var(--h)}}
`
