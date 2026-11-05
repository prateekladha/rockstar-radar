import React, { useEffect, useState } from 'react'
import { api } from './api.js'
import { label } from './ui.jsx'

const okTime = (t) => !t || /^([01]?\d|2[0-3]):[0-5]\d$/.test(t)

export default function Alerts() {
  const [a, setA] = useState(null)
  const [token, setToken] = useState('')
  const [msg, setMsg] = useState('')
  const load = async () => { setA(await api('/api/alerts')); setToken('') }
  useEffect(() => { load() }, [])
  if (!a) return <div className="empty">Loading alerts…</div>

  const states = a.available_states || ['CONFIRMED', 'RETEST_READY', 'BREAKOUT_PENDING', 'READY']
  const payload = (over = {}) => ({
    enabled: a.enabled, states: a.states, min_score: a.min_score, channels: a.channels,
    telegram_chat_id: a.telegram_chat_id, telegram_token: token || undefined,
    quiet_from: a.quiet_from, quiet_to: a.quiet_to, ...over,
  })
  const toggleState = (s) => {
    const has = (a.states || []).includes(s)
    setA({ ...a, states: has ? a.states.filter(x => x !== s) : [...(a.states || []), s] })
  }
  // Master on/off — instant enable/disable of your alert (post-setup control).
  const setEnabled = async (val) => {
    setA({ ...a, enabled: val })
    try { await api('/api/alerts', { method: 'PUT', body: payload({ enabled: val }) }); setMsg(val ? 'Alerts turned on' : 'Alerts paused') }
    catch (e) { setMsg(e.message); load() }
  }
  const save = async () => {
    try { await api('/api/alerts', { method: 'PUT', body: payload() }); setMsg('Alert rule saved'); load() }
    catch (e) { setMsg(e.message) }
  }
  const test = async () => {
    const r = await api('/api/alerts/test', { method: 'POST' })
    setMsg(r.ok ? 'Test alert sent ✓' : 'Failed: ' + r.message)
  }

  return (
    <div className="rlayout rl-even">
      <div className="panel">
        <div className="panel-h"><h2>Your alert</h2><span className="spring" />
          <button className={'toggle' + (a.enabled ? ' on' : '')} role="switch" aria-checked={a.enabled}
            onClick={() => setEnabled(!a.enabled)}><span className="knob" />{a.enabled ? 'On' : 'Off'}</button>
        </div>
        <div className="panel-b">
          {msg && <div className="banner ok">{msg}</div>}
          <p className="note" style={{ marginTop: 0 }}>Set up the rule below and save it. Use the switch above to pause or resume alerts anytime.</p>
          <div className="field"><label>Notify me on these signals</label>
            <div className="row" style={{ gap: 8 }}>
              {states.map(s => (
                <button key={s} className={'chip ' + ((a.states || []).includes(s) ? s : '')}
                  style={{ cursor: 'pointer' }} onClick={() => toggleState(s)}>{label(s)}</button>
              ))}
            </div>
          </div>
          <div className="field"><label>Minimum score</label>
            <input type="number" min="0" max="100" value={a.min_score}
              onChange={e => setA({ ...a, min_score: e.target.value })} /></div>
          <div className="row">
            <div className="field" style={{ flex: 1 }}><label>Quiet from</label>
              <input placeholder="HH:MM" className={okTime(a.quiet_from) ? '' : 'input-bad'}
                value={a.quiet_from} onChange={e => setA({ ...a, quiet_from: e.target.value })} />
              {!okTime(a.quiet_from) && <div className="err-txt">Use 24h HH:MM</div>}</div>
            <div className="field" style={{ flex: 1 }}><label>Quiet to</label>
              <input placeholder="HH:MM" className={okTime(a.quiet_to) ? '' : 'input-bad'}
                value={a.quiet_to} onChange={e => setA({ ...a, quiet_to: e.target.value })} />
              {!okTime(a.quiet_to) && <div className="err-txt">Use 24h HH:MM</div>}</div>
          </div>
          <button className="btn primary" disabled={!okTime(a.quiet_from) || !okTime(a.quiet_to)} onClick={save}>Save alert rule</button>
        </div>
      </div>

      <div className="panel">
        <div className="panel-h"><h2>Telegram</h2>
          <span className={'chip ' + (a.has_telegram_token ? 'CONFIRMED' : 'NONE')}>{a.has_telegram_token ? 'connected' : 'not set'}</span></div>
        <div className="panel-b">
          <div className="field"><label>Bot token (@BotFather) {a.has_telegram_token ? '(saved — blank keeps it)' : ''}</label>
            <input type="password" value={token} onChange={e => setToken(e.target.value)} placeholder="123456:ABC-…" autoComplete="off" /></div>
          <div className="field"><label>Chat ID</label>
            <input value={a.telegram_chat_id} onChange={e => setA({ ...a, telegram_chat_id: e.target.value })} placeholder="e.g. 83729104" /></div>
          <div className="row"><button className="btn primary" onClick={save}>Save Telegram</button>
            <button className="btn" onClick={test}>Send test</button></div>
          <p className="note">Full tickets (entry/stop/target, qty, ₹ risk) push to your phone when a signal fires.</p>
        </div>
      </div>
    </div>
  )
}
