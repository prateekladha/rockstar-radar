import React, { useEffect, useState } from 'react'
import { api } from './api.js'
import { Select } from './ui.jsx'

// The auto-trade / SMC strategy flags — per-user overrides of the config.json defaults, resolved by
// the order engine as sdata.get(key, cfg.get(key)). This page is available to ALL household roles
// (each member edits their own); the admin-only Strategy settings page keeps universe / scan filters
// / prereq / RVOL / EMA. Only these keys are PATCHed so this page never rewrites those other settings.
const STRATEGY_KEYS = [
  'auto_trade_smc', 'auto_trade_smc_min_score', 'auto_trade_smc_atr_stop_mult', 'auto_trade_trigger',
  'smc_runner_target', 'smc_enforce_min_rr', 'smc_block_reentry_after_stop',
  'smc_stop_mode', 'orb_stop_mode', 'max_trades_per_symbol',
]

export default function AutoTrade() {
  const [cfg, setCfg] = useState(null)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    api('/api/settings').then(setCfg).catch(e => setMsg('Error: ' + e.message))
  }, [])
  if (!cfg) return <div className="empty">Loading auto-trade settings…</div>

  const set = (k, v) => setCfg({ ...cfg, [k]: v })
  const save = async () => {
    const body = {}
    STRATEGY_KEYS.forEach(k => { if (k in cfg) body[k] = cfg[k] })
    try {
      const r = await api('/api/settings', { method: 'PATCH', body })
      setCfg(r)
      setMsg('Auto-trade settings saved')
      setTimeout(() => setMsg(''), 3000)
    } catch (e) {
      setMsg('Error: ' + e.message)
    }
  }

  return (
    <div className="panel">
      <div className="panel-h">
        <h2>Auto-trade &amp; strategy flags</h2>
        <span className="hint">How the automated paper trader enters and exits (ORB + SMC)</span>
      </div>
      <div className="panel-b">
        {msg && <div className={'banner ' + (msg.startsWith('Error') ? 'err' : 'ok')}>{msg}</div>}
        <p className="note" style={{ marginBottom: 16 }}>
          These control the automated <b>paper</b> trader only — live never auto-fires. Each is your
          personal setting; changes apply on the next engine pass.
        </p>
        <div className="settings-grid">
          <div className="field"><label>Auto-trade SMC setups</label>
            <button className={'toggle' + (cfg.auto_trade_smc ? ' on' : '')} role="switch" aria-checked={!!cfg.auto_trade_smc}
              onClick={() => set('auto_trade_smc', !cfg.auto_trade_smc)}><span className="knob" />{cfg.auto_trade_smc ? 'On' : 'Off'}</button>
            <p className="note" style={{ marginTop: 8 }}>Auto-enter high-conviction SMC opportunities (separate strategy from the ORB auto-trade).</p>
          </div>
          <div className="field"><label>Min SMC score to auto-trade</label>
            <input type="number" min="50" max="100" value={cfg.auto_trade_smc_min_score ?? 80}
              onChange={ev => set('auto_trade_smc_min_score', ev.target.value)} />
            <p className="note" style={{ marginTop: 8 }}>Only SMC setups scoring at least this (50–100) auto-trade. Default 80.</p>
          </div>
          <div className="field"><label>Let winners run (no fixed target)</label>
            <button className={'toggle' + (cfg.smc_runner_target ? ' on' : '')} role="switch" aria-checked={!!cfg.smc_runner_target}
              onClick={() => set('smc_runner_target', !cfg.smc_runner_target)}><span className="knob" />{cfg.smc_runner_target ? 'On' : 'Off'}</button>
            <p className="note" style={{ marginTop: 8 }}>On: SMC positions ride to the stop or the session square-off instead of a fixed target — the profit engine from the 23-Nov run.</p>
          </div>
          <div className="field"><label>Enforce 2:1 reward:risk gate</label>
            <button className={'toggle' + (cfg.smc_enforce_min_rr ? ' on' : '')} role="switch" aria-checked={!!cfg.smc_enforce_min_rr}
              onClick={() => set('smc_enforce_min_rr', !cfg.smc_enforce_min_rr)}><span className="knob" />{cfg.smc_enforce_min_rr ? 'On' : 'Off'}</button>
            <p className="note" style={{ marginTop: 8 }}>On: reject SMC entries whose net R:R is below 2:1. Off: take them anyway (R:R still shown on the ticket).</p>
          </div>
          <div className="field"><label>Block re-entry after a stop-out</label>
            <button className={'toggle' + (cfg.smc_block_reentry_after_stop ? ' on' : '')} role="switch" aria-checked={!!cfg.smc_block_reentry_after_stop}
              onClick={() => set('smc_block_reentry_after_stop', !cfg.smc_block_reentry_after_stop)}><span className="knob" />{cfg.smc_block_reentry_after_stop ? 'On' : 'Off'}</button>
            <p className="note" style={{ marginTop: 8 }}>On: once a symbol takes a stop today, don't re-enter it — cuts the same-symbol churn that bled the 23-Nov run.</p>
          </div>
          <div className="field"><label>Max trades per symbol / day</label>
            <input type="number" min="1" max="20" value={cfg.max_trades_per_symbol ?? 2}
              onChange={ev => set('max_trades_per_symbol', ev.target.value)} />
            <p className="note" style={{ marginTop: 8 }}>Cap on auto entries per stock per day (both strategies share the count). Default 2.</p>
          </div>
          <div className="field"><label>SMC stop placement</label>
            <Select value={cfg.smc_stop_mode || 'ob_atr'} width={'100%'}
              onChange={(val) => set('smc_stop_mode', val)}
              options={[
                { value: 'ob_atr', label: 'Order block → ATR (default)' },
                { value: 'structure', label: 'Structure (nearest swing)' },
              ]} />
            <p className="note" style={{ marginTop: 8 }}>Where the SMC stop sits when price isn't inside a fresh order block.</p>
          </div>
          <div className="field"><label>ORB retest stop placement</label>
            <Select value={cfg.orb_stop_mode || 'atr_floor'} width={'100%'}
              onChange={(val) => set('orb_stop_mode', val)}
              options={[
                { value: 'atr_floor', label: 'ATR floor (wider, safer)' },
                { value: 'structure', label: 'Structure (tighter, better R:R)' },
              ]} />
            <p className="note" style={{ marginTop: 8 }}>'Structure' stops the radar hiding valid retests behind the 2:1 gate; 'ATR floor' widens the stop to at least ATR.</p>
          </div>
          <div className="field"><label>ORB auto-trade trigger</label>
            <Select value={cfg.auto_trade_trigger || 'RETEST_READY'} width={'100%'}
              onChange={(val) => set('auto_trade_trigger', val)}
              options={[
                { value: 'RETEST_READY', label: 'Retest ready (safer, default)' },
                { value: 'CONFIRMED', label: 'Confirmed breakout (earlier, riskier)' },
              ]} />
            <p className="note" style={{ marginTop: 8 }}>Which ORB signal state fires an auto entry.</p>
          </div>
          <div className="field"><label>SMC ATR stop multiple (fallback)</label>
            <input type="number" step="0.1" min="0.5" max="5" value={cfg.auto_trade_smc_atr_stop_mult ?? 1.5}
              onChange={ev => set('auto_trade_smc_atr_stop_mult', ev.target.value)} />
            <p className="note" style={{ marginTop: 8 }}>ATR multiple for the SMC stop when there's no order block or swing to anchor to. Default 1.5.</p>
          </div>
        </div>
        <div style={{ marginTop: 16 }}><button className="btn primary" onClick={save}>Save auto-trade settings</button></div>
      </div>
    </div>
  )
}
