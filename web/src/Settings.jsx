import React, { useEffect, useState } from 'react'
import { api } from './api.js'
import { Select } from './ui.jsx'

const TIME_KEYS = ['open_range_start', 'watch_start', 'new_signals_stop']
const okTime = (t) => /^([01]?\d|2[0-3]):[0-5]\d$/.test(String(t))
const human = (k) => k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()).replace(/Pct/g, '%').replace(/Inr/g, '₹').replace(/Cr/g, '(cr)').replace(/Atr/g, 'ATR').replace(/Rvol/g, 'RVOL').replace(/Or /g, 'OR ')

export default function Settings() {
  const [cfg, setCfg] = useState(null)
  const [uni, setUni] = useState(null)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    api('/api/settings').then(setCfg).catch(e => setMsg(e.message))
    api('/api/universe').then(setUni).catch(() => {})
  }, [])
  const saveUni = async (idx) => {
    const r = await api('/api/universe', { method: 'PUT', body: { universe_index: idx } })
    setUni({ ...uni, current: r.current }); setMsg('Universe set to ' + r.label + ' — applies on next scanner start')
  }
  if (!cfg) return <div className="empty">Loading settings…</div>

  const err = (k, v) => {
    if (TIME_KEYS.includes(k)) return okTime(v) ? '' : 'HH:MM'
    return v === '' || isNaN(Number(v)) ? 'number' : (Number(v) < 0 ? '≥ 0' : '')
  }
  const anyErr = Object.entries(cfg).some(([k, v]) => err(k, v))
  const set = (k, v) => setCfg({ ...cfg, [k]: v })
  const save = async () => {
    try { const r = await api('/api/settings', { method: 'PATCH', body: { ...cfg } }); setCfg(r); setMsg('Settings saved') }
    catch (e) { setMsg(e.message) }
  }

  return (
    <>
    <SimulationSettings />
    <NotificationsSettings />
    {uni && (
      <div className="panel" style={{ marginBottom: 16 }}>
        <div className="panel-h"><h2>Stocks to scan</h2><span className="hint">The group of stocks the radar watches each day</span></div>
        <div className="panel-b">
          <div className="field" style={{ maxWidth: 360 }}><label>Scan this group</label>
            <Select value={uni.current} onChange={saveUni} width={'100%'}
              options={uni.catalog.map(c => ({ value: c.id, label: `${c.cap} — ${c.label}` }))} />
            <p className="note" style={{ marginTop: 8 }}>e.g. large caps (Nifty 100), mid caps (Nifty Midcap 150), small caps, or all (Nifty 500).</p>
          </div>
        </div>
      </div>
    )}
    <div className="panel">
      <div className="panel-h"><h2>Strategy &amp; risk</h2><span className="hint">Your personal settings</span></div>
      <div className="panel-b">
        {msg && <div className="banner ok">{msg}</div>}
        <div className="settings-grid">
          {Object.entries(cfg).map(([k, v]) => {
            const e = err(k, v)
            return (
              <div className="field" key={k}><label>{human(k)}</label>
                <input type={TIME_KEYS.includes(k) ? 'text' : 'number'} value={v ?? ''}
                  className={e ? 'input-bad' : ''}
                  placeholder={TIME_KEYS.includes(k) ? 'HH:MM' : ''}
                  onChange={ev => set(k, ev.target.value)} />
                {e && <div className="err-txt">{e === 'number' ? 'Enter a number' : e === 'HH:MM' ? 'Use 24h HH:MM' : 'Must be ≥ 0'}</div>}
              </div>
            )
          })}
        </div>
        <div style={{ marginTop: 16 }}><button className="btn primary" disabled={anyErr} onClick={save}>Save settings</button></div>
      </div>
    </div>
    </>
  )
}

function SimulationSettings() {
  const [m, setM] = useState(null)
  const [msg, setMsg] = useState('')
  useEffect(() => { api('/api/me').then(setM).catch(() => {}) }, [])
  if (!m) return null
  const okTime = (t) => /^([01]?\d|2[0-3]):[0-5]\d$/.test(String(t))
  const patch = async (body) => {
    try { setM(await api('/api/me', { method: 'PATCH', body })); setMsg('Saved') }
    catch (e) { setMsg(e.message) }
  }
  const on = !!m.sim_enabled
  return (
    <div className="panel" style={{ marginBottom: 16 }}>
      <div className="panel-h"><h2>🎓 Practice simulation</h2>
        <span className="hint">A synthetic market to learn + test — no broker, no live wait</span></div>
      <div className="panel-b">
        {msg && <div className="banner ok" style={{ marginBottom: 12 }}>{msg}</div>}
        <label className="toggle" style={{ marginBottom: 14 }}>
          <input type="checkbox" checked={on} onChange={e => patch({ sim_enabled: e.target.checked })} />
          <span><strong>Simulation feed</strong> — replaces your radar with an accelerated synthetic session</span>
        </label>
        <div className="row" style={{ alignItems: 'flex-start', opacity: on ? 1 : .55 }}>
          <div className="field" style={{ flex: 1 }}><label>Session start</label>
            <input value={m.sim_start} disabled={!on}
              onChange={e => setM({ ...m, sim_start: e.target.value })}
              onBlur={e => okTime(e.target.value) && patch({ sim_start: e.target.value })} placeholder="09:15" />
          </div>
          <div className="field" style={{ flex: 1 }}><label>Session end</label>
            <input value={m.sim_end} disabled={!on}
              onChange={e => setM({ ...m, sim_end: e.target.value })}
              onBlur={e => okTime(e.target.value) && patch({ sim_end: e.target.value })} placeholder="15:30" />
          </div>
          <div className="field" style={{ flex: 1 }}><label>Speed (× real-time)</label>
            <input inputMode="numeric" value={m.sim_speed} disabled={!on}
              onChange={e => setM({ ...m, sim_speed: e.target.value.replace(/[^\d]/g, '') })}
              onBlur={e => patch({ sim_speed: e.target.value })} placeholder="30" />
          </div>
        </div>
        <p className="note" style={{ marginTop: 8 }}>
          The session you set plays through the real algo at your chosen speed (e.g. 09:15–15:30 at 30× ≈ 13 min), producing live opening-range breakouts and retest signals. Turn on <strong>Auto paper-trade</strong> (Team page) to watch the algo trade it. Simulation is always <strong>paper</strong> — no broker or money involved. Toggle off then on to replay.
        </p>
      </div>
    </div>
  )
}

function NotificationsSettings() {
  const [chat, setChat] = useState(null)
  const [msg, setMsg] = useState('')
  useEffect(() => { api('/api/me').then(m => setChat(m.telegram_chat_id || '')).catch(() => {}) }, [])
  if (chat === null) return null
  const save = async () => {
    try { const m = await api('/api/me', { method: 'PATCH', body: { telegram_chat_id: chat } }); setChat(m.telegram_chat_id || ''); setMsg('Saved') }
    catch (e) { setMsg(e.message) }
  }
  return (
    <div className="panel" style={{ marginBottom: 16 }}>
      <div className="panel-h"><h2>Notifications</h2><span className="hint">Daily reconnect reminder on Telegram</span></div>
      <div className="panel-b">
        {msg && <div className="banner ok" style={{ marginBottom: 12 }}>{msg}</div>}
        <div className="field" style={{ maxWidth: 360 }}>
          <label>Your Telegram chat ID (optional)</label>
          <input value={chat} onChange={e => setChat(e.target.value.replace(/[^\d-]/g, ''))} placeholder="e.g. 123456789" />
          <p className="note" style={{ marginTop: 8 }}>Get a daily reminder to log in to your broker before the market opens. Message our Telegram bot, send <code>/start</code>, and it replies with your chat ID. Leave blank to turn off.</p>
        </div>
        <div style={{ marginTop: 12 }}><button className="btn primary" onClick={save}>Save</button></div>
      </div>
    </div>
  )
}

