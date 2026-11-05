import React, { useEffect, useRef, useState } from 'react'
import { BrowserRouter, Routes, Route, NavLink, Navigate, useNavigate, useLocation } from 'react-router-dom'
import { api } from './api.js'
import { Select } from './ui.jsx'
import { initAnalytics, identify, resetIdentity, pageview } from './analytics.js'
import Login from './Login.jsx'
import Radar from './Radar.jsx'
import Watchlist from './Watchlist.jsx'
import Trades from './Trades.jsx'
import Settings from './Settings.jsx'
import Brokers from './Brokers.jsx'
import Alerts from './Alerts.jsx'
import Insights from './Insights.jsx'
import Journal from './Journal.jsx'
import Family from './Family.jsx'
import Landing from './Landing.jsx'
import Support from './Support.jsx'

const NAV = [['/radar', 'Radar'], ['/watchlist', 'Watchlist'], ['/trades', 'Trades'], ['/journal', 'Journal'], ['/insights', 'Insights']]
const ACCOUNT_PATHS = ['/brokers', '/alerts', '/family', '/settings']

export default function App() {
  const [user, setUser] = useState(undefined)
  const loadMe = async () => {
    try {
      const r = await api('/api/me')
      const u = r.__unauth ? null : r
      setUser(u)
      if (u) identify(u)
    } catch { setUser(null) }
  }
  useEffect(() => { initAnalytics(); loadMe() }, [])

  if (user === undefined) return <div className="center">Loading…</div>

  return (
    <BrowserRouter>
      <RouteTracker />
      {user === null ? (
        <Routes>
          <Route path="/login" element={<Login onDevLogin={async () => { await api('/auth/dev-login', { method: 'POST' }); loadMe() }} />} />
          <Route path="/" element={<Landing />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      ) : !user.onboarded ? (
        <Onboarding onDone={loadMe} />
      ) : (
        <Shell user={user} onLogout={async () => { await api('/auth/logout', { method: 'POST' }); resetIdentity(); setUser(null) }} />
      )}
    </BrowserRouter>
  )
}

// Fires a PostHog $pageview on every SPA route change (no-op without an analytics key).
function RouteTracker() {
  const loc = useLocation()
  useEffect(() => { pageview() }, [loc.pathname])
  return null
}

function Shell({ user, onLogout }) {
  const [menu, setMenu] = useState(false)
  const [support, setSupport] = useState(false)
  const menuRef = useRef(null)
  const nav = useNavigate()
  const loc = useLocation()
  useEffect(() => {
    const close = (e) => { if (menuRef.current && !menuRef.current.contains(e.target)) setMenu(false) }
    document.addEventListener('click', close); return () => document.removeEventListener('click', close)
  }, [])
  const onAccount = ACCOUNT_PATHS.includes(loc.pathname)
  const menuItems = user.is_admin
    ? [['/brokers', 'Broker', '🔗'], ['/alerts', 'Alerts', '🔔'], ['/family', 'Team', '👥'], ['/settings', 'Strategy settings', '⚙️']]
    : [['/brokers', 'Broker', '🔗'], ['/alerts', 'Alerts', '🔔']]
  const go = (p) => { setMenu(false); nav(p) }

  return (
    <>
      <div className="appbar">
        <div className="brand" style={{ cursor: 'pointer' }} onClick={() => nav('/radar')}>
          <span className="mark">⚡</span><div>Rockstar&nbsp;Radar<small>NSE intraday</small></div></div>
        <span className="spring" />
        <div ref={menuRef} style={{ position: 'relative' }}>
          <div className="user" onClick={() => setMenu(!menu)}>
            <span className="avatar">{user.picture ? <img src={user.picture} alt="" /> : user.initials}</span>
            <span style={{ fontSize: 13, fontWeight: 600 }}>{user.name}</span>
          </div>
          {menu && (
            <div className="menu">
              <div className="mhead"><div className="nm">{user.name}<span className="rolechip">{user.role}</span></div><div className="em">{user.email}</div></div>
              {menuItems.map(([p, lbl, icon]) => (
                <button key={p} className="mitem" onClick={() => go(p)}><span>{icon}</span>{lbl}</button>
              ))}
              <div className="msep" />
              <button className="mitem" onClick={() => { setMenu(false); setSupport(true) }}><span>💬</span>Contact &amp; support</button>
              <button className="mitem danger" onClick={onLogout}><span>⎋</span>Log out</button>
            </div>
          )}
        </div>
      </div>

      {support && <Support onClose={() => setSupport(false)} />}

      <div className="wrap">
        {onAccount ? (
          <div className="tabs" style={{ gap: 14 }}>
            <button className="tab" onClick={() => nav('/radar')}>← Back</button>
            <span className="tab active" style={{ cursor: 'default' }}>{menuItems.find(m => m[0] === loc.pathname)?.[1] || 'Account'}</span>
          </div>
        ) : (
          <div className="tabs">
            {NAV.map(([p, lbl]) => (
              <NavLink key={p} to={p} className={({ isActive }) => 'tab' + (isActive ? ' active' : '')}>{lbl}</NavLink>
            ))}
          </div>
        )}

        <Routes>
          <Route path="/radar" element={<Radar />} />
          <Route path="/watchlist" element={<Watchlist />} />
          <Route path="/trades" element={<Trades />} />
          <Route path="/journal" element={<Journal />} />
          <Route path="/insights" element={<Insights />} />
          <Route path="/brokers" element={<Brokers />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/family" element={user.is_admin ? <Family /> : <Navigate to="/radar" />} />
          <Route path="/settings" element={user.is_admin ? <Settings /> : <Navigate to="/radar" />} />
          <Route path="*" element={<Navigate to="/radar" />} />
        </Routes>
      </div>
    </>
  )
}

function Onboarding({ onDone }) {
  const [step, setStep] = useState(1)
  const [first, setFirst] = useState('')
  const [last, setLast] = useState('')
  const [platforms, setPlatforms] = useState([])
  const [callback, setCallback] = useState('')
  const [copied, setCopied] = useState(false)
  const [b, setB] = useState({ platform: 'fyers', app_id: '', secret: '' })
  const [manual, setManual] = useState(false)
  const [redirect, setRedirect] = useState('')
  const [testMsg, setTestMsg] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    api('/api/brokers').then(d => {
      setPlatforms(d.platforms || [])
      setCallback(d.callback_uri || '')
      const avail = (d.platforms || []).find(p => p.status === 'available')
      if (avail) setB(x => ({ ...x, platform: avail.id }))
    }).catch(() => {})
  }, [])

  const metaLabel = (platforms.find(p => p.id === b.platform) || {}).label || 'your broker'
  const isOauth = b.platform === 'fyers'
  const copyCallback = async () => {
    try { await navigator.clipboard.writeText(callback); setCopied(true); setTimeout(() => setCopied(false), 1500) } catch { /* blocked */ }
  }
  const test = async () => {
    setTestMsg({ ok: true, t: 'Testing…' })
    try { const r = await api('/api/brokers/test', { method: 'POST', body: { platform: b.platform, app_id: b.app_id, secret: b.secret } }); setTestMsg({ ok: r.ok, t: r.message }) }
    catch (e) { setTestMsg({ ok: false, t: e.message }) }
  }

  // withBroker: save creds (+ redirect for an existing app), mark onboarded, then connect.
  // Auto mode -> hand off to the FYERS login (returns to /brokers?connected=1). Manual mode (user's
  // own redirect) -> land in the app; the login is completed from the Broker page (open + paste).
  const finish = async (withBroker) => {
    setErr('')
    if (withBroker && (!b.app_id.trim() || !b.secret.trim())) {
      setErr('Enter your App ID and Secret, or skip for now.'); return
    }
    if (withBroker && manual && !redirect.trim()) {
      setErr('Enter your app\'s registered redirect URL (or switch to "Register our URL").'); return
    }
    setBusy(true)
    try {
      if (withBroker) await api('/api/brokers', { method: 'PUT', body: { ...b, redirect_uri: manual ? redirect : '' } })
      await api('/api/onboarding', { method: 'POST', body: { first_name: first, last_name: last } })
      if (withBroker && !manual) { window.location.href = '/api/brokers/login'; return }
      onDone()
    } catch (e) { setErr(e.message); setBusy(false) }
  }

  return (
    <div className="login">
      <div className="card" style={{ maxWidth: 440 }}>
        <div className="mark">{step === 1 ? '👋' : '🔗'}</div>
        <h1>{step === 1 ? 'Welcome' : 'Connect your broker'}</h1>
        <p>{step === 1 ? "Let's set up your profile." : 'Connect a broker so the radar can load live market data. You can also do this later.'}</p>
        <div className="steps">Step {step} of 2</div>
        {err && <div className="banner err" style={{ textAlign: 'left' }}>{err}</div>}

        {step === 1 ? (
          <div style={{ textAlign: 'left' }}>
            <div className="field"><label>First name</label><input autoFocus value={first} onChange={e => setFirst(e.target.value)} placeholder="Your first name" /></div>
            <div className="field"><label>Last name</label><input value={last} onChange={e => setLast(e.target.value)} placeholder="Your last name" /></div>
            <button className="btn primary btn-lg" style={{ width: '100%', justifyContent: 'center' }}
              disabled={!first.trim()} onClick={() => setStep(2)}>Continue</button>
          </div>
        ) : (
          <div style={{ textAlign: 'left' }}>
            <div className="field"><label>Platform</label>
              <Select value={b.platform} onChange={v => setB({ ...b, platform: v })} width={'100%'}
                options={platforms.map(p => ({ value: p.id, label: p.label, disabled: p.status !== 'available' }))} /></div>
            <div className="field"><label>App ID</label><input value={b.app_id} onChange={e => setB({ ...b, app_id: e.target.value })} placeholder="e.g. ABCD1234-100" /></div>
            <div className="field"><label>Secret</label><input type="password" value={b.secret} onChange={e => setB({ ...b, secret: e.target.value })} autoComplete="off" placeholder="API secret" /></div>

            {isOauth && (
              <div className="field"><label>How do you want to connect?</label>
                <div className="segmented">
                  <button type="button" className={'seg' + (!manual ? ' on' : '')} onClick={() => setManual(false)}>Register our URL <span className="segsub">recommended</span></button>
                  <button type="button" className={'seg' + (manual ? ' on' : '')} onClick={() => setManual(true)}>I have an app with its own redirect</button>
                </div>
              </div>
            )}

            {!manual ? (
              callback && (
                <div className="field"><label>Redirect URL — add this to your {metaLabel} app</label>
                  <div className="copyfield"><code>{callback}</code>
                    <button type="button" className="btn" onClick={copyCallback}>{copied ? 'Copied' : 'Copy'}</button></div>
                  <div className="hint" style={{ marginTop: 6 }}>We fill this in for you — paste it as the redirect URI in your API app.</div>
                </div>
              )
            ) : (
              <div className="field"><label>Your app's registered redirect URL</label>
                <input value={redirect} onChange={e => setRedirect(e.target.value)} placeholder="http://127.0.0.1:8765/auth/callback" />
                <div className="hint" style={{ marginTop: 6 }}>Use the redirect already set in your app — nothing to change on the broker side. You'll complete the one-time login from the Broker page after this.</div>
              </div>
            )}

            {testMsg && <div className={'banner ' + (testMsg.ok ? 'ok' : 'err')} style={{ textAlign: 'left' }}>{testMsg.t}</div>}

            <div className="row" style={{ gap: 10, flexWrap: 'nowrap' }}>
              <button className="btn outline" style={{ flex: 'none' }} disabled={busy} onClick={test}>Test connection</button>
              <button className="btn primary btn-lg" style={{ flex: 1, justifyContent: 'center' }}
                disabled={busy} onClick={() => finish(true)}>{busy ? 'Working…' : (manual ? 'Save & finish' : 'Connect & finish')}</button>
            </div>
            <div className="row" style={{ marginTop: 10, justifyContent: 'space-between' }}>
              <button className="btn" disabled={busy} onClick={() => setStep(1)}>← Back</button>
              <button className="btn" disabled={busy} onClick={() => finish(false)}>Skip for now</button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
