import React, { useEffect, useState } from 'react'
import { api } from './api.js'

// User-level preferences, available to EVERY user (not just admins): practice simulation + alerts.
export default function Preferences() {
  return (
    <>
      <SimulationSettings />
      <NotificationsSettings />
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
          The session you set plays through the real algo at your chosen speed (e.g. 09:15–15:30 at 30× ≈ 13 min), producing live opening-range breakouts and retest signals, then <strong>replays on a loop</strong> so there's always something to watch. The clock on the Radar is the <strong>simulated session time</strong> (marked “sim-time”, not the real IST clock) — it runs start→end, then restarts. Turn on <strong>Auto paper-trade</strong> (your admin, on the Team page) to watch the algo trade it. Simulation is always <strong>paper</strong> — no broker or money involved.
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
