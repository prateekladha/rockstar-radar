import React, { useEffect, useState } from 'react'
import { api, bare } from './api.js'
import { label } from './ui.jsx'

const okTime = (t) => !t || /^([01]?\d|2[0-3]):[0-5]\d$/.test(t)

export default function Alerts() {
  const [a, setA] = useState(null)
  const [token, setToken] = useState('')
  const [msg, setMsg] = useState('')
  const [chats, setChats] = useState(null)
  const [finding, setFinding] = useState(false)
  const load = async () => { setA(await api('/api/alerts')); setToken('') }
  useEffect(() => { load() }, [])
  useEffect(() => {
    const id = setInterval(() => api('/api/alerts').then(setA).catch(() => {}), 15000)
    return () => clearInterval(id)
  }, [])
  if (!a) return <div className="empty">Loading alerts…</div>

  const states = a.available_states || ['CONFIRMED', 'RETEST_READY', 'BREAKOUT_PENDING', 'READY']
  const payload = (over = {}) => ({
    enabled: a.enabled, states: a.states, min_score: a.min_score, channels: a.channels,
    telegram_chat_id: a.telegram_chat_id, telegram_token: token || undefined,
    quiet_from: a.quiet_from, quiet_to: a.quiet_to,
    smc_alerts_enabled: a.smc_alerts_enabled, smc_min_score: a.smc_min_score,
    ...over,
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
  // Telegram never tells a bot which groups it is in; it only reports chats it has seen activity
  // in. So this is a lookup, not a list — hence the explicit button and the retry guidance.
  const findChats = async () => {
    setFinding(true); setMsg('')
    try {
      const r = await api('/api/alerts/chats')
      setChats(r.chats || [])
      if (!r.ok || !(r.chats || []).length) setMsg(r.message || 'No chats found yet.')
    } catch (e) { setMsg(e.message) } finally { setFinding(false) }
  }
  const pickChat = async (c) => {
    setA({ ...a, telegram_chat_id: c.id })
    try {
      await api('/api/alerts', { method: 'PUT', body: payload({ telegram_chat_id: c.id }) })
      setMsg(`Alerts will go to “${c.title}”`); setChats(null); load()
    } catch (e) { setMsg(e.message) }
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
        <div className="panel-h">
          <h2>SMC Alerts</h2>
          <span className="spring" />
          <button className={'toggle' + (a.smc_alerts_enabled ? ' on' : '')} role="switch" aria-checked={a.smc_alerts_enabled}
            onClick={() => setA({ ...a, smc_alerts_enabled: !a.smc_alerts_enabled })}><span className="knob" />{a.smc_alerts_enabled ? 'On' : 'Off'}</button>
        </div>
        <div className="panel-b">
          <p className="note" style={{ marginTop: 0 }}>
            Get alerts for Smart Money Concepts (SMC) opportunities from the SMC Radar tab.
            These are separate from ORB breakout alerts and use the same Telegram channel.
          </p>
          <div className="field">
            <label>Minimum SMC score</label>
            <input
              type="number"
              min="35"
              max="100"
              value={a.smc_min_score || 70}
              onChange={e => setA({ ...a, smc_min_score: parseInt(e.target.value) || 70 })}
            />
            <div className="hint" style={{ fontSize: 11, color: 'var(--faint)', marginTop: 4 }}>
              Alert when SMC score ≥ this value (recommended: 70-85)
            </div>
          </div>
          <button className="btn primary" onClick={save}>Save SMC alerts</button>
        </div>
      </div>

      <div className="panel">
        <div className="panel-h"><h2>Telegram</h2>
          <span className={'chip ' + (a.has_telegram_token ? 'CONFIRMED' : 'NONE')}>{a.has_telegram_token ? 'connected' : 'not set'}</span></div>
        <div className="panel-b">
          <div className="field"><label>Bot token (@BotFather) {a.has_telegram_token ? '(saved — blank keeps it)' : ''}</label>
            <input type="password" value={token} onChange={e => setToken(e.target.value)} placeholder="123456:ABC-…" autoComplete="off" /></div>
          <div className="field"><label>Destination chat or group</label>
            <input value={a.telegram_chat_id} onChange={e => setA({ ...a, telegram_chat_id: e.target.value })}
              placeholder="e.g. -1001234567890 for a group" /></div>
          <div className="row"><button className="btn primary" onClick={save}>Save Telegram</button>
            <button className="btn" onClick={findChats} disabled={finding || !a.has_telegram_token}>
              {finding ? 'Looking…' : 'Find my groups'}</button>
            <button className="btn" onClick={test}>Send test</button></div>

          {chats && (chats.length
            ? <div style={{ marginTop: 12 }}>
              <div className="hint" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--faint)', marginBottom: 6 }}>
                Pick a destination
              </div>
              {chats.map(c => (
                <button key={c.id} className="rp-step" onClick={() => pickChat(c)}>
                  <span style={{ flex: 1 }}>{c.title}</span>
                  <span className="faint mono" style={{ fontSize: 11 }}>{c.type} · {c.id}</span>
                </button>
              ))}
            </div>
            : <p className="note" style={{ marginTop: 10 }}>Nothing found yet — see the steps below.</p>)}

          <div className="note" style={{ marginTop: 14 }}>
            <b>Sending to a group</b>
            <ol style={{ margin: '6px 0 0', paddingLeft: 18, lineHeight: 1.7 }}>
              <li>Create the bot with <b>@BotFather</b> and paste its token above, then Save.</li>
              <li>Add that bot to your group as a member.</li>
              <li>Send any message in the group — <code>/start</code> works.</li>
              <li>Press <b>Find my groups</b> and pick it. A group id is negative.</li>
            </ol>
            <p style={{ margin: '8px 0 0' }}>Telegram hides ordinary group chatter from bots by
              default, so if the group doesn’t appear, remove and re-add the bot — being added is
              always visible to it.</p>
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-h"><h2>Recently sent</h2><span className="spring" />
          <span className="hint">one alert per stock, side and state each day</span></div>
        <div className="panel-b">
          {(a.recent || []).length
            ? (a.recent || []).map((d, i) => (
              <div key={i} className="rp-kv">
                <span>{d.ok ? '✓' : '✕'} {bare(d.symbol)} {d.side}</span>
                <span className="mono">{label(d.state)} · {d.at}</span>
              </div>
            ))
            : <div className="empty"><div className="big">Nothing sent yet</div>
              Alerts fire on their own while a scan is running — you don’t need this page
              (or any page) open.</div>}
          {(a.recent || []).some(d => !d.ok) && (
            <p className="note" style={{ marginTop: 10 }}>
              ✕ means Telegram refused it: {(a.recent.find(d => !d.ok) || {}).detail}
            </p>)}
        </div>
      </div>
    </div>
  )
}
