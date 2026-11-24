import React, { useEffect, useState } from 'react'
import { api } from './api.js'
import { Select } from './ui.jsx'

const TIME_KEYS = ['open_range_start', 'watch_start', 'new_signals_stop']
// Rendered as switches rather than number boxes, and skipped by the numeric validator.
const BOOL_KEYS = ['use_one_minute_candles']
// Auto-trade & strategy flags live on the user-level "My settings" page (AutoTrade.jsx, open to all
// roles) — along with the per-user pre-requisite / RVOL / EMA blocks. They still arrive in
// /api/settings, so exclude them from this admin page's generic numeric grid — otherwise the
// enums/bools would render as broken number boxes and trip the Save validator.
const STRATEGY_KEYS = [
  'auto_trade_smc', 'auto_trade_smc_min_score', 'auto_trade_smc_atr_stop_mult', 'auto_trade_trigger',
  'smc_runner_target', 'smc_enforce_min_rr', 'smc_block_reentry_after_stop',
  'smc_stop_mode', 'orb_stop_mode', 'max_trades_per_symbol',
]
const STRATEGY_SET = new Set(STRATEGY_KEYS)
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
    if (STRATEGY_SET.has(k)) return ''          // own page (My settings)
    if (BOOL_KEYS.includes(k)) return ''        // switch; can't be out of range
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
      <div className="panel-h"><h2>Strategy &amp; risk</h2><span className="hint">Household defaults for the scanner &amp; risk engine</span></div>
      <div className="panel-b">
        {msg && <div className="banner ok">{msg}</div>}
        <div className="settings-grid">
          {Object.entries(cfg).filter(([k]) => !STRATEGY_SET.has(k)).map(([k, v]) => {
            const e = err(k, v)
            if (BOOL_KEYS.includes(k)) {
              return (
                <div className="field" key={k}><label>{human(k)}</label>
                  <button className={'toggle' + (v ? ' on' : '')} role="switch" aria-checked={!!v}
                    onClick={() => set(k, !v)}><span className="knob" />{v ? 'On' : 'Off'}</button>
                  {k === 'use_one_minute_candles' && (
                    <p className="note" style={{ marginTop: 8 }}>
                      Off (default): breakouts and retests are judged on 5-minute candles.
                      On: 1-minute candles, so setups are spotted sooner and more of them
                      appear — but a stock that doesn't trade for one minute of 09:15–09:20
                      gets no opening range, and no signals, that day. The opening range stays
                      09:15–09:20 either way. Takes effect when the scanner next starts.
                    </p>
                  )}
                </div>
              )
            }
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
