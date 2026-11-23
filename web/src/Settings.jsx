import React, { useEffect, useState } from 'react'
import { api } from './api.js'
import { Select } from './ui.jsx'

const TIME_KEYS = ['open_range_start', 'watch_start', 'new_signals_stop']
// Rendered as switches rather than number boxes, and skipped by the numeric validator.
const BOOL_KEYS = ['use_one_minute_candles']
// Auto-trade & strategy flags — rendered in their own panel below with proper toggles/dropdowns,
// so excluded from the generic numeric grid (the way auto_trade_trigger always has been). These
// are all per-user overrides of the config.json defaults.
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
  const [prereq, setPrereq] = useState(null)
  const [rvolSettings, setRvolSettings] = useState(null)
  const [emaSettings, setEmaSettings] = useState(null)
  const [msg, setMsg] = useState('')
  const [prereqMsg, setPrereqMsg] = useState('')
  const [rvolMsg, setRvolMsg] = useState('')
  const [emaMsg, setEmaMsg] = useState('')

  useEffect(() => {
    api('/api/settings').then(setCfg).catch(e => setMsg(e.message))
    api('/api/universe').then(setUni).catch(() => {})
    api('/api/prerequisites').then(setPrereq).catch(e => console.error('Failed to load prerequisites:', e))
    api('/api/rvol-settings').then(setRvolSettings).catch(e => console.error('Failed to load RVOL settings:', e))
    api('/api/ema-settings').then(setEmaSettings).catch(e => console.error('Failed to load EMA settings:', e))
  }, [])
  const saveUni = async (idx) => {
    const r = await api('/api/universe', { method: 'PUT', body: { universe_index: idx } })
    setUni({ ...uni, current: r.current }); setMsg('Universe set to ' + r.label + ' — applies on next scanner start')
  }
  if (!cfg) return <div className="empty">Loading settings…</div>

  const err = (k, v) => {
    if (STRATEGY_SET.has(k)) return ''          // own panel below (toggles/dropdowns/ints)
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
      <div className="panel-h"><h2>Strategy &amp; risk</h2><span className="hint">Your personal settings</span></div>
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

    {'auto_trade_smc' in cfg && (
      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-h">
          <h2>Auto-trade &amp; strategy flags</h2>
          <span className="hint">How the automated paper trader enters and exits (ORB + SMC)</span>
        </div>
        <div className="panel-b">
          <p className="note" style={{ marginBottom: 16 }}>
            These control the automated <b>paper</b> trader only — live never auto-fires. Each is your
            personal override of the platform default; changes apply on the next engine pass.
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
          <div style={{ marginTop: 16 }}><button className="btn primary" disabled={anyErr} onClick={save}>Save auto-trade settings</button></div>
        </div>
      </div>
    )}

    {prereq && (
      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-h">
          <h2>Pre-requisite Checks</h2>
          <span className="hint">Mandatory checks before strategy evaluation (applies to both ORB and SMC)</span>
        </div>
        <div className="panel-b">
          {prereqMsg && <div className="banner ok">{prereqMsg}</div>}
          <p className="note" style={{ marginBottom: 16 }}>
            All checks are mandatory (AND logic). If any check fails, the stock will not be evaluated by the selected strategy and will not appear in opportunities.
          </p>

          <div className="settings-grid">
            {/* RVOL Check */}
            <div className="field">
              <label>Enable RVOL Check</label>
              <button className={'toggle' + (prereq.rvol_enabled ? ' on' : '')} role="switch" aria-checked={!!prereq.rvol_enabled}
                onClick={() => setPrereq({ ...prereq, rvol_enabled: !prereq.rvol_enabled })}>
                <span className="knob" />{prereq.rvol_enabled ? 'On' : 'Off'}
              </button>
            </div>

            {prereq.rvol_enabled && (
              <div className="field">
                <label>Minimum RVOL</label>
                <input type="number" step="0.1" min="0" value={prereq.min_rvol ?? 1.0}
                  onChange={ev => setPrereq({ ...prereq, min_rvol: ev.target.value })} />
                <p className="note" style={{ marginTop: 8 }}>
                  Stocks with RVOL below this threshold will be rejected. Default: 1.0 (100% of normal volume)
                </p>
              </div>
            )}

            {/* Future: Liquidity Check (disabled for now) */}
            {false && (
              <>
                <div className="field">
                  <label>Min Liquidity (₹Cr)</label>
                  <input type="number" step="1" min="0" value={prereq.min_liquidity_cr ?? ''}
                    placeholder="Optional"
                    onChange={ev => setPrereq({ ...prereq, min_liquidity_cr: ev.target.value || null })} />
                </div>

                <div className="field">
                  <label>Min Price (₹)</label>
                  <input type="number" step="1" min="0" value={prereq.min_price ?? ''}
                    placeholder="Optional"
                    onChange={ev => setPrereq({ ...prereq, min_price: ev.target.value || null })} />
                </div>

                <div className="field">
                  <label>Max Price (₹)</label>
                  <input type="number" step="1" min="0" value={prereq.max_price ?? ''}
                    placeholder="Optional"
                    onChange={ev => setPrereq({ ...prereq, max_price: ev.target.value || null })} />
                </div>
              </>
            )}
          </div>

          <div style={{ marginTop: 16 }}>
            <button className="btn primary" onClick={async () => {
              try {
                const result = await api('/api/prerequisites', { method: 'PUT', body: prereq })
                setPrereq(result)
                setPrereqMsg('Pre-requisite settings saved')
                setTimeout(() => setPrereqMsg(''), 3000)
              } catch (e) {
                setPrereqMsg('Error: ' + e.message)
              }
            }}>Save prerequisite settings</button>
          </div>
        </div>
      </div>
    )}

    {rvolSettings && (
      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-h">
          <h2>RVOL Calculation Settings</h2>
          <span className="hint">Configure how Relative Volume is calculated</span>
        </div>
        <div className="panel-b">
          {rvolMsg && <div className="banner ok">{rvolMsg}</div>}
          <p className="note" style={{ marginBottom: 16 }}>
            These settings control how RVOL (Relative Volume) is calculated for opportunities.
            Changes apply to both ORB and SMC scanners on next restart.
          </p>

          <div className="settings-grid">
            {/* Anchor Timeframe */}
            <div className="field">
              <label>Anchor Timeframe</label>
              <Select
                value={rvolSettings.anchor_timeframe || 'day'}
                onChange={(val) => setRvolSettings({ ...rvolSettings, anchor_timeframe: val })}
                width={'100%'}
                options={[
                  { value: 'day', label: 'Day (Default)' }
                ]}
              />
              <p className="note" style={{ marginTop: 8 }}>
                Time period for volume comparison. "Day" compares to the same time on previous days.
                (Session/Week/Month anchors are coming soon.)
              </p>
            </div>

            {/* Length */}
            <div className="field">
              <label>Length (Lookback Period)</label>
              <input
                type="number"
                min="1"
                max="100"
                value={rvolSettings.length ?? 10}
                onChange={ev => setRvolSettings({ ...rvolSettings, length: parseInt(ev.target.value) || 10 })}
              />
              <p className="note" style={{ marginTop: 8 }}>
                Number of previous periods to compare against. Default: 10 days.
              </p>
            </div>

            {/* Calculation Mode */}
            <div className="field">
              <label>Calculation Mode</label>
              <Select
                value={rvolSettings.calculation_mode || 'cumulative'}
                onChange={(val) => setRvolSettings({ ...rvolSettings, calculation_mode: val })}
                width={'100%'}
                options={[
                  { value: 'cumulative', label: 'Cumulative (Default)' },
                  { value: 'per_bar', label: 'Per Bar (Spot)' }
                ]}
              />
              <p className="note" style={{ marginTop: 8 }}>
                How to aggregate volume. "Cumulative" compares total volume from the session open
                (smooth); "Per Bar" compares each bar to its same-time median (spiky). This one metric
                now drives every strategy — the radar, SMC and the Debug tab all read it.
                (Mean/Median modes are coming soon.)
              </p>
            </div>
          </div>

          <div style={{ marginTop: 16 }}>
            <button className="btn primary" onClick={async () => {
              try {
                const result = await api('/api/rvol-settings', { method: 'PUT', body: rvolSettings })
                setRvolSettings(result)
                setRvolMsg('RVOL settings saved. Restart scanner to apply changes.')
                setTimeout(() => setRvolMsg(''), 5000)
              } catch (e) {
                setRvolMsg('Error: ' + e.message)
              }
            }}>Save RVOL settings</button>
            <span style={{ marginLeft: 12, color: '#888', fontSize: 13 }}>
              Scanner restart required for changes to take effect
            </span>
          </div>
        </div>
      </div>
    )}

    {emaSettings && (
      <div className="panel" style={{ marginTop: 20 }}>
        <div className="panel-h"><h2>EMA Crossover Settings</h2></div>
        <div className="panel-b" style={{ padding: 20 }}>
          {emaMsg && <div className="banner ok">{emaMsg}</div>}
          <p className="note" style={{ marginBottom: 16 }}>
            Two EMAs on the Debug tab (and EMA trend). EMA fast crossing above the slow is bullish;
            below is bearish. Defaults: 5 / 20, Close, offset 0.
          </p>
          <div className="settings-grid">
            <div className="field">
              <label>Fast EMA Length</label>
              <input type="number" min="1" max="200" value={emaSettings.fast_length ?? 5}
                onChange={ev => setEmaSettings({ ...emaSettings, fast_length: parseInt(ev.target.value) || 5 })} />
              <p className="note" style={{ marginTop: 8 }}>Shorter EMA (default 5).</p>
            </div>
            <div className="field">
              <label>Slow EMA Length</label>
              <input type="number" min="1" max="200" value={emaSettings.slow_length ?? 20}
                onChange={ev => setEmaSettings({ ...emaSettings, slow_length: parseInt(ev.target.value) || 20 })} />
              <p className="note" style={{ marginTop: 8 }}>Longer EMA (default 20).</p>
            </div>
            <div className="field">
              <label>Source</label>
              <Select value={emaSettings.source || 'close'} width={'100%'}
                onChange={(val) => setEmaSettings({ ...emaSettings, source: val })}
                options={[
                  { value: 'close', label: 'Close (Default)' },
                  { value: 'open', label: 'Open' },
                  { value: 'high', label: 'High' },
                  { value: 'low', label: 'Low' },
                  { value: 'hl2', label: 'HL2 (median)' },
                  { value: 'hlc3', label: 'HLC3 (typical)' },
                  { value: 'ohlc4', label: 'OHLC4 (average)' },
                ]} />
              <p className="note" style={{ marginTop: 8 }}>Price the EMA is computed on.</p>
            </div>
            <div className="field">
              <label>Offset</label>
              <input type="number" min="0" max="100" value={emaSettings.offset ?? 0}
                onChange={ev => setEmaSettings({ ...emaSettings, offset: parseInt(ev.target.value) || 0 })} />
              <p className="note" style={{ marginTop: 8 }}>Shift the EMA back by N bars (default 0).</p>
            </div>
          </div>
          <div style={{ marginTop: 16 }}>
            <button className="btn primary" onClick={async () => {
              try {
                const result = await api('/api/ema-settings', { method: 'PUT', body: emaSettings })
                setEmaSettings(result)
                setEmaMsg('EMA settings saved.')
                setTimeout(() => setEmaMsg(''), 5000)
              } catch (e) {
                setEmaMsg('Error: ' + e.message)
              }
            }}>Save EMA settings</button>
          </div>
        </div>
      </div>
    )}
    </>
  )
}

