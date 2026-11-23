import React from 'react'
import { useNavigate } from 'react-router-dom'

const FEATURES = [
  ['📡', 'Opening-range radar', 'Live NSE intraday breakout signals, ranked by strength — each with entry, stop-loss and targets. You review and decide; nothing fires on its own.', 'c3'],
  ['🎯', 'Smart watchlist', 'A daily auto-shortlist of long/short setups with levels and invalidation, built from the live market — not a static list.', 'c3'],
  ['📓', 'Journal & edge in R', 'Every opportunity the radar flagged and every trade you took — win rate, expectancy and your edge measured in R, net of real costs.', 'c2'],
  ['🔗', 'Bring your own broker', 'Connect your own FYERS account (Zerodha & more coming). Your login, your data, your trades — we never see your password.', 'c2'],
  ['🧪', 'Paper-first, cost-true', 'Prove the edge in paper mode with real brokerage, slippage and margin modelled — so a green month actually means something.', 'c2'],
]

const STEPS = [
  ['1', 'Sign in', 'One tap with Google. Your profile is ready in seconds.'],
  ['2', 'Connect your broker', 'Link FYERS once — the step-by-step guide takes ~5 minutes. A quick daily login keeps it live (a SEBI rule for every broker).'],
  ['3', 'Scan & act', 'Watch ranked setups through the session and act with one tap — paper-first, so you prove the edge before risking capital.'],
]

const STATS = [
  ['NSE 500', 'liquid universe scanned live'],
  ['09:15–09:20', 'opening range, every session'],
  ['Paper-first', 'cost-true before real money'],
  ['You confirm', 'every single order'],
]

// a tiny mock of the live radar table for the hero
const ROWS = [
  ['RELIANCE', 'LONG', 92, 'RETEST', 'up'],
  ['TATAMOTORS', 'LONG', 86, 'CONFIRMED', 'up'],
  ['HDFCBANK', 'SHORT', 81, 'RETEST', 'down'],
  ['INFY', 'LONG', 74, 'WATCH', 'up'],
  ['MARUTI', 'SHORT', 69, 'WATCH', 'down'],
]

export default function Landing() {
  const nav = useNavigate()
  return (
    <div className="rr-land">
      <style>{CSS}</style>

      <header className="rr-nav">
        <div className="rr-brand"><span className="rr-mark">⚡</span><b>Rockstar&nbsp;Radar</b><span className="rr-navsub">NSE intraday</span></div>
        <span className="rr-sp" />
        <a className="rr-nlink" href="#features">Features</a>
        <a className="rr-nlink" href="#how">How it works</a>
        <a className="rr-nlink" href="/blog/how-to-connect-fyers">Guide</a>
        <button className="rr-btn pri" onClick={() => nav('/login')}>Sign in</button>
      </header>

      <section className="rr-hero">
        <div className="rr-hero-in">
          <div className="rr-eyebrow"><span className="rr-dot" />Intraday · Indian markets · paper-first</div>
          <h1 className="rr-h1">Your intraday co-pilot for the <span className="rr-g">Indian markets</span>.</h1>
          <p className="rr-sub">A real-time NSE opening-range breakout radar. Bring your own broker and get
            ranked setups with entry, stop and targets — modelled with real costs, with you in control of every trade.</p>
          <div className="rr-ctas">
            <button className="rr-btn pri lg" onClick={() => nav('/login')}>Get started — it's free</button>
            <a className="rr-btn gh lg" href="https://github.com/prateekladha/rockstar-radar" target="_blank" rel="noreferrer">★ View on GitHub</a>
          </div>
          <div className="rr-foot-note">Paper-trading first · OAuth — no passwords stored · Not investment advice</div>
        </div>

        {/* product mock */}
        <div className="rr-shot">
          <div className="rr-frame">
            <div className="rr-bar"><span className="rr-dots"><i /><i /><i /></span>
              <span className="rr-url">intraday.live/radar</span><span className="rr-live"><i />LIVE</span></div>
            <div className="rr-app">
              <div className="rr-tablehd"><span>Symbol</span><span>Side</span><span className="rr-num">Score</span><span>State</span><span className="rr-num">Entry→Target</span></div>
              {ROWS.map(([sym, side, score, state, dir]) => (
                <div className="rr-row" key={sym}>
                  <span className="rr-sym">{sym}</span>
                  <span className={'rr-side ' + dir}>{side}</span>
                  <span className="rr-num"><span className="rr-score"><i style={{ width: score + '%' }} />{score}</span></span>
                  <span><span className={'rr-chip ' + (state === 'CONFIRMED' ? 'ok' : state === 'RETEST' ? 'acc' : 'mut')}>{state}</span></span>
                  <span className="rr-num rr-lvl">2,841 → 2,903</span>
                </div>
              ))}
              <div className="rr-ticker"><span className="rr-tk">+2.4R today</span><span className="rr-tk mut">6 open · paper</span><span className="rr-tk mut">feed: live</span></div>
            </div>
          </div>
        </div>
      </section>

      <section className="rr-statband">
        {STATS.map(([n, l]) => (<div key={l}><div className="rr-sn">{n}</div><div className="rr-sl">{l}</div></div>))}
      </section>

      <section className="rr-sec" id="features">
        <div className="rr-kick">What it does</div>
        <h2 className="rr-h2">A radar, a journal, and an honest paper engine.</h2>
        <p className="rr-dek">Everything you need to find intraday setups, act on them with discipline, and know — with real numbers — whether you actually have an edge.</p>
        <div className="rr-bento">
          {FEATURES.map(([icon, title, body, span]) => (
            <div className={'rr-b ' + span} key={title}>
              <div className="rr-bic">{icon}</div>
              <h3>{title}</h3><p>{body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="rr-sec" id="how">
        <div className="rr-kick">Getting started</div>
        <h2 className="rr-h2">Live in about five minutes.</h2>
        <div className="rr-steps">
          {STEPS.map(([n, title, body]) => (
            <div className="rr-step" key={n}><div className="rr-stepn">{n}</div>
              <div><h3>{title}</h3><p>{body}</p></div></div>
          ))}
        </div>
      </section>

      <section className="rr-cta">
        <h2>Trade with a co-pilot, not on a hunch.</h2>
        <p>Free to start, paper-first, your broker. Prove the edge before you risk a rupee.</p>
        <button className="rr-btn w lg" onClick={() => nav('/login')}>Sign in to Rockstar Radar</button>
      </section>

      <footer className="rr-footer">
        <span>⚡ Rockstar Radar — NSE intraday</span>
        <span className="rr-dim">Short-term trading is risky. This is a personal tool, not investment advice.</span>
        <span className="rr-flinks">
          <a href="/blog/how-to-connect-fyers">Connect FYERS guide</a>
          <a href="https://github.com/prateekladha/rockstar-radar" target="_blank" rel="noreferrer">GitHub</a>
        </span>
      </footer>
    </div>
  )
}

const CSS = `
.rr-land{--bg:#0a0e16;--surface:#121826;--surface2:#0e1420;--border:#202a3c;--fg:#e9edf5;--muted:#99a3b5;--faint:#5f6a7e;
  --acc:#ffbe4d;--acc2:#ff9a3d;--acc-weak:rgba(255,190,77,.12);--acc-ink:#ffd58a;--up:#34d399;--down:#f87171;
  --fd:"Space Grotesk",system-ui,-apple-system,"Segoe UI",sans-serif;--fm:ui-monospace,"SF Mono","JetBrains Mono",monospace;
  background:var(--bg);color:var(--fg);min-height:100vh;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.5;overflow-x:clip}
.rr-land *{box-sizing:border-box}
.rr-land h1,.rr-land h2,.rr-land h3{font-family:var(--fd);font-weight:700;margin:0;letter-spacing:-.02em;text-wrap:balance}
.rr-land a{color:inherit;text-decoration:none}
.rr-btn{all:unset;cursor:pointer;font-size:14px;font-weight:600;padding:9px 16px;border-radius:10px;border:1px solid var(--border);background:var(--surface);color:var(--fg);text-align:center;white-space:nowrap;transition:.15s}
.rr-btn:hover{border-color:var(--acc)}
.rr-btn.pri{background:linear-gradient(180deg,var(--acc),var(--acc2));border-color:transparent;color:#2a1a00;box-shadow:0 8px 24px -8px rgba(255,160,60,.7)}
.rr-btn.pri:hover{filter:brightness(1.06)}
.rr-btn.gh{background:rgba(255,255,255,.04);border-color:rgba(255,255,255,.14)}
.rr-btn.gh:hover{border-color:rgba(255,255,255,.4)}
.rr-btn.w{background:#1a1205;color:var(--acc-ink);border-color:#3a2a08}
.rr-btn.lg{padding:13px 24px;font-size:15px}
/* nav */
.rr-nav{position:sticky;top:0;z-index:50;display:flex;align-items:center;gap:8px;height:62px;padding:0 clamp(18px,4vw,40px);
  background:rgba(10,14,22,.72);backdrop-filter:blur(14px);border-bottom:1px solid rgba(255,255,255,.06)}
.rr-brand{display:flex;align-items:center;gap:9px;font-family:var(--fd)}
.rr-mark{width:30px;height:30px;border-radius:9px;background:linear-gradient(135deg,var(--acc),var(--acc2));display:grid;place-items:center;font-size:16px}
.rr-brand b{font-size:17px}
.rr-navsub{font-size:11px;color:var(--faint);border-left:1px solid var(--border);padding-left:9px;margin-left:3px}
.rr-sp{flex:1}
.rr-nlink{font-size:13.5px;color:var(--muted);font-weight:500;padding:7px 11px;border-radius:8px}
.rr-nlink:hover{color:var(--fg);background:rgba(255,255,255,.05)}
@media(max-width:720px){.rr-nlink{display:none}}
/* hero */
.rr-hero{position:relative;text-align:center;padding:clamp(48px,8vw,92px) clamp(18px,4vw,40px) 0;overflow:clip}
.rr-hero::before{content:"";position:absolute;inset:-160px -10% auto -10%;height:720px;z-index:0;pointer-events:none;
  background:radial-gradient(42% 48% at 50% 0%,rgba(255,190,77,.28),transparent 70%),radial-gradient(34% 42% at 80% 8%,rgba(255,120,60,.2),transparent 72%),radial-gradient(34% 44% at 18% 14%,rgba(255,200,90,.14),transparent 72%)}
.rr-hero::after{content:"";position:absolute;inset:0 0 auto 0;height:760px;z-index:0;pointer-events:none;
  background-image:linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px);background-size:50px 50px;
  -webkit-mask-image:radial-gradient(70% 56% at 50% 0%,#000,transparent 72%);mask-image:radial-gradient(70% 56% at 50% 0%,#000,transparent 72%)}
.rr-hero-in{position:relative;z-index:2;max-width:860px;margin:0 auto}
.rr-eyebrow{display:inline-flex;align-items:center;gap:8px;font-size:12.5px;font-weight:600;color:var(--acc-ink);background:var(--acc-weak);border:1px solid rgba(255,190,77,.25);padding:6px 14px;border-radius:999px;margin-bottom:22px}
.rr-dot{width:6px;height:6px;border-radius:50%;background:var(--acc);box-shadow:0 0 0 0 rgba(255,190,77,.5);animation:rrp 2.4s infinite}
@keyframes rrp{50%{box-shadow:0 0 0 5px rgba(255,190,77,.14)}}
.rr-h1{font-size:clamp(34px,6vw,64px);line-height:1.03;letter-spacing:-.03em;max-width:16ch;margin:0 auto}
.rr-g{background:linear-gradient(110deg,var(--acc),#ffe0a3 55%,var(--acc));-webkit-background-clip:text;background-clip:text;color:transparent}
.rr-sub{font-size:clamp(15px,1.7vw,18px);color:var(--muted);max-width:56ch;margin:22px auto 26px;line-height:1.55}
.rr-ctas{display:flex;gap:12px;justify-content:center;flex-wrap:wrap}
.rr-foot-note{margin-top:18px;font-size:12.5px;color:var(--faint)}
/* product mock */
.rr-shot{position:relative;z-index:3;max-width:900px;margin:46px auto 0;padding:0 clamp(8px,2vw,16px)}
.rr-frame{background:var(--surface2);border:1px solid var(--border);border-radius:14px 14px 0 0;overflow:hidden;
  box-shadow:0 44px 100px -30px rgba(0,0,0,.8),0 10px 30px rgba(0,0,0,.5)}
.rr-bar{display:flex;align-items:center;gap:12px;padding:11px 14px;background:#0f1522;border-bottom:1px solid var(--border)}
.rr-dots{display:flex;gap:6px}.rr-dots i{width:11px;height:11px;border-radius:50%;background:#2a3346}
.rr-dots i:nth-child(1){background:#ff5f57}.rr-dots i:nth-child(2){background:#febc2e}.rr-dots i:nth-child(3){background:#28c840}
.rr-url{flex:1;text-align:center;font-family:var(--fm);font-size:11.5px;color:var(--faint);background:var(--bg);border:1px solid var(--border);border-radius:7px;padding:4px 12px;max-width:260px;margin:0 auto}
.rr-live{display:inline-flex;align-items:center;gap:6px;font-size:10.5px;font-weight:700;color:var(--up);font-family:var(--fm)}
.rr-live i{width:6px;height:6px;border-radius:50%;background:var(--up);animation:rrp 1.8s infinite}
.rr-app{padding:12px 14px 14px;background:var(--bg);text-align:left}
.rr-tablehd,.rr-row{display:grid;grid-template-columns:1.4fr .8fr 1.3fr 1fr 1.4fr;gap:10px;align-items:center;padding:9px 10px}
.rr-tablehd{font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;color:var(--faint);font-weight:600}
.rr-row{border-top:1px solid rgba(255,255,255,.05);font-size:12.5px}
.rr-sym{font-weight:700;font-family:var(--fd)}
.rr-side{font-weight:700;font-size:11px;font-family:var(--fm)}.rr-side.up{color:var(--up)}.rr-side.down{color:var(--down)}
.rr-num{text-align:right;font-variant-numeric:tabular-nums}
.rr-lvl{font-family:var(--fm);color:var(--muted);font-size:11px}
.rr-score{display:inline-flex;align-items:center;gap:7px;font-family:var(--fm);font-weight:600;justify-content:flex-end;width:100%}
.rr-score i{height:5px;border-radius:3px;background:linear-gradient(90deg,var(--acc2),var(--acc));max-width:54px;min-width:14px}
.rr-chip{font-size:10px;font-weight:700;font-family:var(--fm);padding:3px 8px;border-radius:6px}
.rr-chip.ok{background:rgba(52,211,153,.14);color:var(--up)}.rr-chip.acc{background:var(--acc-weak);color:var(--acc-ink)}.rr-chip.mut{background:rgba(255,255,255,.06);color:var(--muted)}
.rr-ticker{display:flex;gap:16px;padding:12px 10px 2px;border-top:1px solid rgba(255,255,255,.05);margin-top:4px}
.rr-tk{font-family:var(--fm);font-size:11.5px;font-weight:700;color:var(--up)}.rr-tk.mut{color:var(--faint);font-weight:400}
/* stat band */
.rr-statband{display:grid;grid-template-columns:repeat(4,1fr);max-width:980px;margin:clamp(40px,6vw,64px) auto 0;padding:0 clamp(18px,4vw,40px)}
.rr-statband>div{padding:20px;border-left:1px solid var(--border);text-align:center}
.rr-statband>div:first-child{border-left:0}
.rr-sn{font-family:var(--fd);font-size:clamp(20px,2.6vw,28px);font-weight:700;background:linear-gradient(120deg,var(--acc),#ffe0a3);-webkit-background-clip:text;background-clip:text;color:transparent}
.rr-sl{font-size:12px;color:var(--muted);margin-top:5px}
@media(max-width:680px){.rr-statband{grid-template-columns:1fr 1fr}.rr-statband>div:nth-child(3){border-left:0}.rr-statband>div:nth-child(1),.rr-statband>div:nth-child(2){border-bottom:1px solid var(--border)}}
/* sections */
.rr-sec{max-width:1080px;margin:0 auto;padding:clamp(56px,9vw,104px) clamp(18px,4vw,40px) 0;text-align:center}
.rr-kick{font-size:12px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:var(--acc-ink);font-family:var(--fm)}
.rr-h2{font-size:clamp(26px,4vw,42px);line-height:1.08;margin:12px auto 0;max-width:20ch}
.rr-dek{color:var(--muted);font-size:clamp(15px,1.6vw,17px);max-width:58ch;margin:14px auto 0;line-height:1.55}
/* bento */
.rr-bento{display:grid;grid-template-columns:repeat(6,1fr);gap:14px;margin-top:38px;text-align:left}
.rr-b{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:22px;transition:.2s}
.rr-b:hover{border-color:rgba(255,190,77,.4);transform:translateY(-3px)}
.rr-b.c3{grid-column:span 3}.rr-b.c2{grid-column:span 2}
.rr-bic{width:40px;height:40px;border-radius:11px;background:var(--acc-weak);display:grid;place-items:center;font-size:19px;margin-bottom:13px}
.rr-b h3{font-size:16.5px;margin-bottom:7px}
.rr-b p{font-size:13.5px;color:var(--muted);margin:0;line-height:1.55}
@media(max-width:880px){.rr-bento{grid-template-columns:repeat(2,1fr)}.rr-b.c3,.rr-b.c2{grid-column:span 1}}
@media(max-width:520px){.rr-bento{grid-template-columns:1fr}}
/* steps */
.rr-steps{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-top:38px;text-align:left}
.rr-step{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:22px;display:flex;gap:14px}
.rr-stepn{width:34px;height:34px;flex:none;border-radius:10px;background:linear-gradient(135deg,var(--acc),var(--acc2));color:#2a1a00;font-family:var(--fd);font-weight:700;display:grid;place-items:center;font-size:16px}
.rr-step h3{font-size:16px;margin-bottom:6px}
.rr-step p{font-size:13px;color:var(--muted);margin:0;line-height:1.5}
@media(max-width:780px){.rr-steps{grid-template-columns:1fr}}
/* cta */
.rr-cta{max-width:1080px;margin:clamp(64px,9vw,104px) auto 0;padding:clamp(40px,6vw,64px) 28px;text-align:center;border-radius:24px;position:relative;overflow:hidden;
  background:linear-gradient(135deg,#1c1203,#ffbe4d 55%,#ffd58a)}
.rr-cta::after{content:"";position:absolute;inset:0;background-image:linear-gradient(rgba(0,0,0,.07) 1px,transparent 1px),linear-gradient(90deg,rgba(0,0,0,.07) 1px,transparent 1px);background-size:40px 40px;-webkit-mask-image:radial-gradient(70% 100% at 50% 130%,#000,transparent);mask-image:radial-gradient(70% 100% at 50% 130%,#000,transparent)}
.rr-cta h2{position:relative;z-index:1;color:#2a1a00;font-size:clamp(24px,3.6vw,40px);line-height:1.05}
.rr-cta p{position:relative;z-index:1;color:rgba(42,26,0,.82);font-size:15.5px;margin:14px auto 24px;max-width:46ch}
.rr-cta .rr-btn{position:relative;z-index:1;background:#2a1a00;color:var(--acc-ink);border-color:#2a1a00}
/* footer */
.rr-footer{max-width:1080px;margin:0 auto;padding:40px clamp(18px,4vw,40px) 56px;display:flex;flex-wrap:wrap;gap:12px 24px;align-items:center;border-top:1px solid var(--border);margin-top:clamp(56px,8vw,90px);font-size:12.5px;color:var(--faint)}
.rr-footer b,.rr-footer>span:first-child{color:var(--muted);font-family:var(--fd)}
.rr-dim{flex:1;min-width:200px}
.rr-flinks{display:flex;gap:18px}
.rr-flinks a:hover{color:var(--acc-ink)}
@media(prefers-reduced-motion:reduce){.rr-land *{animation:none!important}}
`
