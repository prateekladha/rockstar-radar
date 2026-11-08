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
    <TradingSettings />
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

function TradingSettings() {
  const [h, setH] = useState(null)
  const [msg, setMsg] = useState('')
  useEffect(() => { api('/api/family/settings').then(setH).catch(() => {}) }, [])
  if (!h) return null
  const patch = async (body) => {
    try { setH(await api('/api/family/settings', { method: 'PATCH', body })); setMsg('Saved') }
    catch (e) { setMsg(e.message) }
  }
  const live = h.trading_mode === 'live'
  return (
    <div className="panel" style={{ marginBottom: 16 }}>
      <div className="panel-h"><h2>Trading</h2>
        <span className="hint">{h.can_manage ? 'Applies to your whole household' : 'Set by your admin'}</span></div>
      <div className="panel-b">
        {msg && <div className="banner ok" style={{ marginBottom: 12 }}>{msg}</div>}
        <div className="field" style={{ marginBottom: 18 }}>
          <label>Order mode (whole household)</label>
          <div className="segmented" style={{ maxWidth: 440 }}>
            <button type="button" disabled={!h.can_manage} className={'seg' + (!live ? ' on' : '')}
              onClick={() => patch({ trading_mode: 'paper' })}>Paper <span className="segsub">simulated</span></button>
            <button type="button" disabled={!h.can_manage} className={'seg' + (live ? ' on' : '')}
              onClick={() => patch({ trading_mode: 'live' })}>Live <span className="segsub">real money</span></button>
          </div>
          {live && <div className="banner warn" style={{ marginTop: 10 }}>⚠️ Live — every member's orders place <strong>real orders</strong> on their own broker. Capital & risk are checked against the broker balance.</div>}
        </div>
        <div className="field">
          <label className="toggle" style={{ opacity: h.can_manage ? 1 : .6 }}>
            <input type="checkbox" checked={!!h.auto_paper_trade} disabled={!h.can_manage}
              onChange={e => patch({ auto_paper_trade: e.target.checked })} />
            <span>Auto paper-trade the algo (RETEST_READY signals)</span>
          </label>
          <p className="note" style={{ marginTop: 6 }}>The system opens paper trades automatically from the algo's confirmed-retest opportunities, exits on target/stop from the live feed, and squares off any open position at 3:15 PM (intraday). Paper only — a risk-free way to see the algo's daily P&L. (Live auto-trading comes later.)</p>
        </div>
      </div>
    </div>
  )
}
