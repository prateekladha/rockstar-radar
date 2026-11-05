import React from 'react'
import { useNavigate } from 'react-router-dom'

const FEATURES = [
  ['📡', 'Opening-range radar', 'Live NSE intraday breakout signals, ranked by strength — each with entry, stop-loss and targets. You review and decide; nothing fires on its own.'],
  ['🎯', 'Smart watchlist', 'A daily auto-shortlist of long/short setups with levels and invalidation, built from the live market — not a static list.'],
  ['📓', 'Trade journal & insights', 'Every opportunity the radar flagged and every trade you took, saved and auditable — win rate, expectancy and your edge in R.'],
  ['🔗', 'Bring your own broker', 'Connect your own FYERS account (Zerodha & more coming). Your login, your data, your trades — we never see your password.'],
]

const STEPS = [
  ['1', 'Sign in', 'One tap with Google. Set up your profile in seconds.'],
  ['2', 'Connect your broker', 'Link your FYERS account once. A quick daily login keeps it live (a SEBI requirement for all brokers).'],
  ['3', 'Scan & act', 'Watch ranked setups through the session and act with one tap — in paper mode first, so you prove the edge before risking capital.'],
]

export default function Landing() {
  const nav = useNavigate()
  return (
    <div className="mktg">
      <header className="mktg-nav">
        <div className="brand"><span className="mark">⚡</span><div>Rockstar&nbsp;Radar<small>NSE intraday</small></div></div>
        <span className="spring" />
        <button className="btn primary" onClick={() => nav('/login')}>Sign in</button>
      </header>

      <section className="hero">
        <div className="pill">Intraday · Indian markets</div>
        <h1>Your intraday co-pilot for the Indian markets.</h1>
        <p className="lede">A real-time NSE opening-range breakout radar. Bring your own broker and get
          ranked intraday setups with entry, stop and targets — you stay in control of every trade.</p>
        <div className="hero-cta">
          <button className="btn primary btn-lg" onClick={() => nav('/login')}>Get started — sign in</button>
          <a className="btn btn-lg" href="https://github.com/prateekladha/rockstar-radar" target="_blank" rel="noreferrer">View on GitHub</a>
        </div>
        <div className="hero-note">Paper-trading first · No credentials stored in plain text · Not investment advice</div>
      </section>

      <section className="feat-grid">
        {FEATURES.map(([icon, title, body]) => (
          <div className="feat" key={title}>
            <div className="feat-ic">{icon}</div>
            <h3>{title}</h3><p>{body}</p>
          </div>
        ))}
      </section>

      <section className="steps-sec">
        <h2>How it works</h2>
        <div className="steps-grid">
          {STEPS.map(([n, title, body]) => (
            <div className="step" key={n}><div className="step-n">{n}</div>
              <div><h3>{title}</h3><p>{body}</p></div></div>
          ))}
        </div>
      </section>

      <section className="cta-band">
        <h2>Ready to trade with a co-pilot?</h2>
        <button className="btn primary btn-lg" onClick={() => nav('/login')}>Sign in to Rockstar Radar</button>
      </section>

      <footer className="mktg-foot">
        <span>⚡ Rockstar Radar</span>
        <span className="dim">Short-term trading is risky. This is a personal tool, not investment advice.</span>
        <a href="https://github.com/prateekladha/rockstar-radar" target="_blank" rel="noreferrer">GitHub</a>
      </footer>
    </div>
  )
}
