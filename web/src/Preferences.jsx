import React, { useEffect, useState } from 'react'
import { api } from './api.js'
import { Select, Checkbox } from './ui.jsx'

// User-level preferences, available to EVERY user (not just admins): practice simulation + alerts.
export default function Preferences() {
  return (
    <>
      <SimulationSettings />
      <AutoTradeSettings />
      <NotificationsSettings />
    </>
  )
}

// Per-user auto-trade trigger. Available to every trader (saved via /api/settings, which is not
// admin-gated). Your admin turns auto paper-trading on/off (Team page); this is YOUR choice of which
// signal status opens a trade when it's on.
function AutoTradeSettings() {
  const [trig, setTrig] = useState(null)
  const [smc, setSmc] = useState(false)
  const [smcScore, setSmcScore] = useState(80)
  const [msg, setMsg] = useState('')
  useEffect(() => {
    api('/api/settings').then(s => {
      setTrig(s.auto_trade_trigger || 'RETEST_READY')
      setSmc(!!s.auto_trade_smc)
      setSmcScore(Number(s.auto_trade_smc_min_score ?? 80))
    }).catch(() => {})
  }, [])
  if (trig === null) return null
  const patch = async (body, optimistic) => {
    if (optimistic) optimistic()
    try { await api('/api/settings', { method: 'PATCH', body }); setMsg('Saved') }
    catch (e) { setMsg(e.message) }
  }
  const saveTrig = (v) => patch({ auto_trade_trigger: v }, () => setTrig(v))
  const saveSmc = (v) => patch({ auto_trade_smc: v }, () => setSmc(v))
  const saveScore = (raw) => {
    const n = Math.max(50, Math.min(100, parseInt(raw, 10) || 80))
    patch({ auto_trade_smc_min_score: n }, () => setSmcScore(n))
  }
  return (
    <div className="panel" style={{ marginBottom: 16 }}>
      <div className="panel-h"><h2>⚡ Auto-trading</h2>
        <span className="hint">What fires an automatic paper entry</span></div>
      <div className="panel-b">
        {msg && <div className="banner ok" style={{ marginBottom: 12 }}>{msg}</div>}
        <div className="field" style={{ maxWidth: 440 }}>
          <label>ORB signal trigger</label>
          <Select value={trig} width={'100%'} onChange={saveTrig}
            options={[
              { value: 'RETEST_READY', label: 'Retest Ready — safer (double-confirmed)' },
              { value: 'CONFIRMED', label: 'Confirmed — aggressive (enter on breakout)' },
            ]} />
          <p className="note" style={{ marginTop: 8 }}>
            When auto paper-trading is on for you (your admin enables it on the Team page), this picks
            which signal opens a paper trade. <strong>Retest Ready</strong> waits for price to pull back
            and re-confirm the breakout — fewer, higher-quality trades. <strong>Confirmed</strong> enters
            the moment a breakout is validated — earlier and many more trades, but riskier (no second
            confirmation). Paper only — real orders always need your tap to confirm.
          </p>
        </div>

        <div className="field" style={{ maxWidth: 440, marginTop: 22 }}>
          <label>Smart Money (SMC) auto-trade</label>
          <Checkbox checked={smc} onChange={saveSmc}>
            Also auto-trade high-conviction SMC setups
          </Checkbox>
          {smc && (
            <div style={{ marginTop: 12 }}>
              <label>Minimum SMC score to enter (50–100)</label>
              <input type="number" min={50} max={100} step={1} value={smcScore}
                className="input"
                onChange={e => setSmcScore(e.target.value)}
                onBlur={e => saveScore(e.target.value)}
                style={{ width: 110 }} />
            </div>
          )}
          <p className="note" style={{ marginTop: 8 }}>
            A separate strategy from the ORB trigger above. When on (and your admin has enabled auto
            paper-trading), the algo also enters <strong>long in a discount zone / short in a premium
            zone</strong> — but <em>only</em> when price sits inside a fresh order block and the setup's
            net reward:risk clears 2:1. A higher score demands stronger confluence (default 80; fewer,
            better setups). One entry per stock per day, shared with the ORB strategy.
            <strong> Paper only</strong> — real orders always need your tap to confirm.
          </p>
        </div>
      </div>
    </div>
  )
}

function SimulationSettings() {
  const [m, setM] = useState(null)
  const [msg, setMsg] = useState('')
  useEffect(() => { api('/api/me').then(setM).catch(() => {}) }, [])
  if (!m) return null
  const okTime = (t) => /^([01]?\d|2[0-3]):[0-5]\d$/.test(String(t))
  const patch = async (body) => {
    try {
      setM(await api('/api/me', { method: 'PATCH', body })); setMsg('Saved')
      window.dispatchEvent(new Event('rr-me-changed'))   // update the Paper/Actual toggle instantly
    } catch (e) { setMsg(e.message) }
  }
  const reset = async () => {
    if (!window.confirm('Reset the practice simulation? This deletes ALL your simulation trades and P&L and starts a fresh session. Your real paper/live trades are not affected.')) return
    try { const r = await api('/api/sim/reset', { method: 'POST' }); setMsg(`Simulation reset — cleared ${r.deleted} practice trades.`) }
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
              onBlur={e => patch({ sim_speed: e.target.value })} placeholder="10" />
          </div>
        </div>
        <p className="note" style={{ marginTop: 8 }}>
          The session you set plays through the real algo once at your chosen speed (e.g. 09:15–15:30 at 10× ≈ 40 min), producing live opening-range breakouts and retest signals. When it reaches the end time it <strong>ends like a real intraday session</strong> — open positions are squared off and the Radar shows “Complete”. Toggle simulation off then on (or hit Reset) to run another session. Turn on <strong>Auto paper-trade</strong> (your admin, on the Team page) to watch the algo trade it. Simulation is always <strong>paper</strong> — no broker or money involved.
        </p>
        <div style={{ marginTop: 14, borderTop: '1px solid var(--border)', paddingTop: 14 }}>
          <button className="btn danger" onClick={reset}>↻ Reset simulation</button>
          <p className="note" style={{ marginTop: 6 }}>Clears all your practice trades &amp; P&L and restarts a fresh session. Your real paper/live trades are never touched.</p>
        </div>
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
