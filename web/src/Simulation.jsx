import React, { useEffect, useState } from 'react'
import { api } from './api.js'
import { Select, Chip, label } from './ui.jsx'

export default function Simulation() {
  const [view, setView] = useState('list')  // 'list', 'create', 'details', 'compare'
  const [selectedRun, setSelectedRun] = useState(null)
  const [compareIds, setCompareIds] = useState([])

  return (
    <div>
      {view === 'list' && <SimRunList onView={(id) => { setSelectedRun(id); setView('details') }} onCreate={() => setView('create')} onCompare={(ids) => { setCompareIds(ids); setView('compare') }} />}
      {view === 'create' && <CreateSimRunForm onCancel={() => setView('list')} onCreated={() => setView('list')} />}
      {view === 'details' && <SimRunDetails runId={selectedRun} onBack={() => setView('list')} />}
      {view === 'compare' && <SimComparison runIds={compareIds} onBack={() => setView('list')} />}
    </div>
  )
}

// ============================================================================
// Create Sim Run Form
// ============================================================================

function CreateSimRunForm({ onCancel, onCreated }) {
  const [form, setForm] = useState({
    name: '',
    description: '',
    start_date: new Date().toISOString().split('T')[0],
    start_time: '09:15',
    end_time: '15:30',
    bar_interval: '1',
    // Config
    strategy: 'ORB',
    retest_tolerance_pct: 0.16,
    min_net_reward_risk: 2.0,
    prereq_min_rvol: 1.0,
    prereq_rvol_enabled: true,
    auto_paper_trade: true,
    auto_trade_trigger: 'RETEST_READY',
    // SMC-specific
    auto_trade_smc_min_score: 80,
    smc_stop_mode: 'ob_atr',
    smc_enforce_min_rr: true,
    smc_runner_target: false,
    smc_atr_stop_floor: false,
    smc_atr_stop_floor_mult: 0.5,
    smc_require_confirmation: false,
    capital_inr: 100000,
    risk_pct: 1.0
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError(null)

    try {
      // Build config object
      const config = {
        strategy: form.strategy,
        retest_tolerance_pct: parseFloat(form.retest_tolerance_pct),
        retest_expiry_minutes: 20,
        min_net_reward_risk: Number.isFinite(parseFloat(form.min_net_reward_risk)) ? parseFloat(form.min_net_reward_risk) : 2.0,
        orb_stop_mode: 'structure',
        prereq_min_rvol: parseFloat(form.prereq_min_rvol),
        prereq_rvol_enabled: form.prereq_rvol_enabled ? 1 : 0,
        auto_paper_trade: form.auto_paper_trade ? 1 : 0,
        auto_trade_trigger: form.auto_trade_trigger,
        // SMC strategy params (ignored by the ORB engine)
        auto_trade_smc_min_score: parseInt(form.auto_trade_smc_min_score) || 80,
        smc_stop_mode: form.smc_stop_mode,
        smc_enforce_min_rr: form.smc_enforce_min_rr ? 1 : 0,
        smc_runner_target: form.smc_runner_target ? 1 : 0,
        smc_atr_stop_floor: form.smc_atr_stop_floor ? 1 : 0,
        smc_atr_stop_floor_mult: Number.isFinite(parseFloat(form.smc_atr_stop_floor_mult)) ? parseFloat(form.smc_atr_stop_floor_mult) : 0.5,
        smc_require_confirmation: form.smc_require_confirmation ? 1 : 0,
        capital_inr: parseFloat(form.capital_inr),
        risk_pct: parseFloat(form.risk_pct),
        use_one_minute_candles: form.bar_interval === '1' ? 1 : 0
      }

      await api('/api/sim/runs', {
        method: 'POST',
        body: {
          name: form.name,
          description: form.description,
          start_date: form.start_date,
          start_time: form.start_time,
          end_date: form.start_date,  // Single day for now
          end_time: form.end_time,
          bar_interval: form.bar_interval,
          config: config
        }
      })

      onCreated()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="panel">
      <div className="panel-h">
        <h2>Create Simulation Run</h2>
        <span className="hint">Test your strategy on historical data</span>
      </div>
      <div className="panel-b">
        {error && <div className="banner err">{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className="settings-grid">
            {/* Basic Info */}
            <div className="field">
              <label>Name *</label>
              <input type="text" value={form.name} onChange={e => setForm({...form, name: e.target.value})} required placeholder="e.g., Nov 15 - Aggressive Setup" />
            </div>

            <div className="field">
              <label>Description</label>
              <textarea value={form.description} onChange={e => setForm({...form, description: e.target.value})} placeholder="Optional notes about this simulation" rows={2} />
            </div>

            {/* Date & Time */}
            <div className="field">
              <label>Date *</label>
              <input type="date" value={form.start_date} onChange={e => setForm({...form, start_date: e.target.value})} required />
            </div>

            <div className="field">
              <label>Time Range</label>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input type="time" value={form.start_time} onChange={e => setForm({...form, start_time: e.target.value})} style={{ flex: 1 }} />
                <span>to</span>
                <input type="time" value={form.end_time} onChange={e => setForm({...form, end_time: e.target.value})} style={{ flex: 1 }} />
              </div>
            </div>

            <div className="field">
              <label>Bar Interval</label>
              <Select
                value={form.bar_interval}
                onChange={v => setForm({...form, bar_interval: v})}
                options={[
                  { value: '1', label: '1 minute (more accurate)' },
                  { value: '5', label: '5 minutes (faster)' }
                ]}
                width={'100%'}
              />
            </div>

            {/* Strategy Config */}
            <div className="field" style={{ gridColumn: '1 / -1' }}>
              <h3 style={{ marginTop: 16, marginBottom: 8 }}>Strategy Configuration</h3>
            </div>

            <div className="field" style={{ gridColumn: '1 / -1' }}>
              <label>Strategy</label>
              <Select
                value={form.strategy}
                onChange={v => setForm({...form, strategy: v})}
                options={[
                  { value: 'ORB', label: 'ORB — Opening Range Breakout' },
                  { value: 'SMC', label: 'SMC — Smart Money Concepts' }
                ]}
                width={'100%'}
              />
              <p className="note">{form.strategy === 'SMC'
                ? 'Replays the SMC engine: premium/discount zones, order blocks, FVGs. Longs in discount, shorts in premium.'
                : 'Replays the ORB engine: opening-range breakout, confirmation, then entry on the retest.'}</p>
            </div>

            <div className="field">
              <label>Min Reward:Risk</label>
              <input type="number" step="0.1" min="0" value={form.min_net_reward_risk} onChange={e => setForm({...form, min_net_reward_risk: e.target.value})} />
              <p className="note">Net R:R gate (default 2.0). Below this a setup isn't traded. Lower it (e.g. 1.5) for more trades; raise it for fewer, higher-quality ones. Applies to both strategies.</p>
            </div>

            {form.strategy === 'ORB' && (
              <>
                <div className="field">
                  <label>Retest Tolerance %</label>
                  <input type="number" step="0.01" value={form.retest_tolerance_pct} onChange={e => setForm({...form, retest_tolerance_pct: e.target.value})} />
                  <p className="note">Default: 0.16%. Test 0.18% or 0.20% for more opportunities.</p>
                </div>

                <div className="field">
                  <label>Min RVOL</label>
                  <input type="number" step="0.1" value={form.prereq_min_rvol} onChange={e => setForm({...form, prereq_min_rvol: e.target.value})} />
                  <p className="note">Minimum relative volume threshold (default: 1.0)</p>
                </div>

                <div className="field">
                  <label>Enable RVOL Check</label>
                  <button type="button" className={'toggle' + (form.prereq_rvol_enabled ? ' on' : '')} onClick={() => setForm({...form, prereq_rvol_enabled: !form.prereq_rvol_enabled})}>
                    <span className="knob" />{form.prereq_rvol_enabled ? 'On' : 'Off'}
                  </button>
                </div>
              </>
            )}

            {form.strategy === 'SMC' && (
              <>
                <div className="field">
                  <label>Min SMC Score</label>
                  <input type="number" step="1" min="0" max="100" value={form.auto_trade_smc_min_score} onChange={e => setForm({...form, auto_trade_smc_min_score: e.target.value})} />
                  <p className="note">Only trade setups scoring at least this (default 80). Lower → more trades; raise for A+ setups only.</p>
                </div>

                <div className="field">
                  <label>SMC Stop Mode</label>
                  <Select
                    value={form.smc_stop_mode}
                    onChange={v => setForm({...form, smc_stop_mode: v})}
                    options={[
                      { value: 'ob_atr', label: 'Order block / ATR (default)' },
                      { value: 'structure', label: 'Structure (tighter, swing-based)' }
                    ]}
                    width={'100%'}
                  />
                  <p className="note">Where the stop sits: the order-block edge (ATR fallback), or just beyond the nearest swing.</p>
                </div>

                <div className="field">
                  <label>Enforce Min R:R</label>
                  <button type="button" className={'toggle' + (form.smc_enforce_min_rr ? ' on' : '')} onClick={() => setForm({...form, smc_enforce_min_rr: !form.smc_enforce_min_rr})}>
                    <span className="knob" />{form.smc_enforce_min_rr ? 'On' : 'Off'}
                  </button>
                  <p className="note">When on, reject SMC setups below the Min Reward:Risk above.</p>
                </div>

                <div className="field">
                  <label>Let Winners Run</label>
                  <button type="button" className={'toggle' + (form.smc_runner_target ? ' on' : '')} onClick={() => setForm({...form, smc_runner_target: !form.smc_runner_target})}>
                    <span className="knob" />{form.smc_runner_target ? 'On' : 'Off'}
                  </button>
                  <p className="note">When on, no fixed target — ride until the stop or end-of-day square-off.</p>
                </div>

                <div className="field">
                  <label>Require Entry Confirmation</label>
                  <button type="button" className={'toggle' + (form.smc_require_confirmation ? ' on' : '')} onClick={() => setForm({...form, smc_require_confirmation: !form.smc_require_confirmation})}>
                    <span className="knob" />{form.smc_require_confirmation ? 'On' : 'Off'}
                  </button>
                  <p className="note">Only enter after a candle rejects the zone in the trade's direction (bullish close off the lows for longs, bearish close off the highs for shorts) — instead of firing the moment price is in the zone. Avoids catching knives.</p>
                </div>

                <div className="field">
                  <label>ATR Stop Floor</label>
                  <button type="button" className={'toggle' + (form.smc_atr_stop_floor ? ' on' : '')} onClick={() => setForm({...form, smc_atr_stop_floor: !form.smc_atr_stop_floor})}>
                    <span className="knob" />{form.smc_atr_stop_floor ? 'On' : 'Off'}
                  </button>
                  <p className="note">Widen the stop to clear intraday noise. Default SMC stops sit ~0.2–0.5% away (inside the wiggle) → nearly everything stops out. When on, the stop is at least the multiple below of the symbol's daily ATR.</p>
                </div>

                {form.smc_atr_stop_floor && (
                  <div className="field">
                    <label>ATR Floor × (of daily ATR)</label>
                    <input type="number" step="0.1" min="0" value={form.smc_atr_stop_floor_mult} onChange={e => setForm({...form, smc_atr_stop_floor_mult: e.target.value})} />
                    <p className="note">Minimum stop = this × daily ATR. 0.5 ≈ a ~1–1.5% stop on a typical name. Higher = wider stop, smaller size, fewer noise stop-outs.</p>
                  </div>
                )}
              </>
            )}

            {/* Auto-Trade */}
            <div className="field">
              <label>Auto-Trade</label>
              <button type="button" className={'toggle' + (form.auto_paper_trade ? ' on' : '')} onClick={() => setForm({...form, auto_paper_trade: !form.auto_paper_trade})}>
                <span className="knob" />{form.auto_paper_trade ? 'On' : 'Off'}
              </button>
              <p className="note">Simulate automatic trade execution</p>
            </div>

            {form.auto_paper_trade && (
              <>
                {form.strategy === 'ORB' && (
                  <div className="field">
                    <label>Auto-Trade Trigger</label>
                    <Select
                      value={form.auto_trade_trigger}
                      onChange={v => setForm({...form, auto_trade_trigger: v})}
                      options={[
                        { value: 'RETEST_READY', label: 'Retest Ready (conservative)' },
                        { value: 'CONFIRMED', label: 'Confirmed (aggressive)' }
                      ]}
                      width={'100%'}
                    />
                  </div>
                )}

                <div className="field">
                  <label>Capital (₹)</label>
                  <input type="number" value={form.capital_inr} onChange={e => setForm({...form, capital_inr: e.target.value})} />
                </div>

                <div className="field">
                  <label>Risk per Trade (%)</label>
                  <input type="number" step="0.1" value={form.risk_pct} onChange={e => setForm({...form, risk_pct: e.target.value})} />
                </div>
              </>
            )}
          </div>

          <div style={{ marginTop: 24, display: 'flex', gap: 12 }}>
            <button type="submit" className="btn primary" disabled={loading}>
              {loading ? 'Creating...' : 'Create & Run Simulation'}
            </button>
            <button type="button" className="btn" onClick={onCancel} disabled={loading}>Cancel</button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ============================================================================
// Sim Run List
// ============================================================================

function SimRunList({ onView, onCreate, onCompare }) {
  const [runs, setRuns] = useState([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState(new Set())

  useEffect(() => {
    loadRuns()
    const interval = setInterval(loadRuns, 5000)  // Poll every 5s for status updates
    return () => clearInterval(interval)
  }, [])

  const loadRuns = async () => {
    try {
      const data = await api('/api/sim/runs')
      setRuns(data)
    } catch (err) {
      console.error('Failed to load sim runs:', err)
    } finally {
      setLoading(false)
    }
  }

  const toggleSelect = (id) => {
    const newSelected = new Set(selected)
    if (newSelected.has(id)) {
      newSelected.delete(id)
    } else {
      newSelected.add(id)
    }
    setSelected(newSelected)
  }

  const handleCompare = () => {
    if (selected.size >= 2) {
      onCompare(Array.from(selected))
    }
  }

  if (loading) return <div className="empty">Loading...</div>

  return (
    <div className="panel">
      <div className="panel-h">
        <h2>Simulation Runs</h2>
        <span className="hint">Test strategies on historical data</span>
        <span className="spring" />
        {selected.size >= 2 && (
          <button className="btn" onClick={handleCompare} style={{ marginRight: 12 }}>
            Compare Selected ({selected.size})
          </button>
        )}
        <button className="btn primary" onClick={onCreate}>+ New Simulation</button>
      </div>
      <div className="panel-b">
        {runs.length === 0 ? (
          <div className="empty">No simulation runs yet. Create one to get started!</div>
        ) : (
          <div className="tbl-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 40 }}></th>
                  <th>Name</th>
                  <th>Date</th>
                  <th>Interval</th>
                  <th>Status</th>
                  <th className="num">Progress</th>
                  <th className="num">Opportunities</th>
                  <th className="num">Trades</th>
                  <th className="num">Total R</th>
                  <th className="num">Win Rate</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {runs.map(run => (
                  <tr key={run.id} style={{ cursor: 'pointer' }}>
                    <td onClick={(e) => { e.stopPropagation(); toggleSelect(run.id) }}>
                      <input type="checkbox" checked={selected.has(run.id)} readOnly />
                    </td>
                    <td onClick={() => onView(run.id)}>{run.name}</td>
                    <td onClick={() => onView(run.id)}>{run.start_date}</td>
                    <td onClick={() => onView(run.id)}>{run.bar_interval} min</td>
                    <td onClick={() => onView(run.id)}>
                      <Chip state={run.status.toUpperCase()} />
                    </td>
                    <td className="num" onClick={() => onView(run.id)}>
                      {run.status === 'running' || run.status === 'fetching_data' ? `${run.progress_pct}%` : '—'}
                    </td>
                    <td className="num" onClick={() => onView(run.id)}>{run.total_opportunities ?? '—'}</td>
                    <td className="num" onClick={() => onView(run.id)}>{run.total_trades ?? '—'}</td>
                    <td className="num" onClick={() => onView(run.id)}>
                      {run.total_r != null ? (
                        <span className={run.total_r >= 0 ? 'up' : 'down'}>
                          {run.total_r >= 0 ? '+' : ''}{run.total_r.toFixed(2)}R
                        </span>
                      ) : '—'}
                    </td>
                    <td className="num" onClick={() => onView(run.id)}>
                      {run.win_rate != null ? `${run.win_rate.toFixed(1)}%` : '—'}
                    </td>
                    <td className="num">
                      <button className="btn" onClick={(e) => { e.stopPropagation(); onView(run.id) }}>View</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// ============================================================================
// Sim Run Details
// ============================================================================

function SimRunDetails({ runId, onBack }) {
  const [run, setRun] = useState(null)
  const [journal, setJournal] = useState([])
  const [trades, setTrades] = useState([])
  const [tab, setTab] = useState('metrics')  // 'metrics', 'journal', 'trades'
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (runId) {
      loadData()
    }
  }, [runId])

  const loadData = async () => {
    try {
      const [runData, journalData, tradesData] = await Promise.all([
        api(`/api/sim/runs/${runId}`),
        api(`/api/sim/runs/${runId}/journal`),
        api(`/api/sim/runs/${runId}/trades`)
      ])
      setRun(runData)
      setJournal(journalData.items)
      setTrades(tradesData.items)
    } catch (err) {
      console.error('Failed to load sim run:', err)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className="empty">Loading...</div>
  if (!run) return <div className="empty">Simulation run not found</div>

  return (
    <div>
      {/* Header */}
      <div className="panel">
        <div className="panel-h">
          <button className="btn" onClick={onBack} style={{ marginRight: 12 }}>← Back</button>
          <h2>{run.name}</h2>
          <span className="hint">{run.start_date} · {run.bar_interval} min bars</span>
          <span className="spring" />
          <Chip state={run.status.toUpperCase()} />
        </div>
        {run.description && (
          <div className="panel-b">
            <p>{run.description}</p>
          </div>
        )}
      </div>

      {/* Tabs */}
      <div style={{ marginTop: 16, marginBottom: 16, borderBottom: '1px solid var(--border)' }}>
        <button className={'tab-btn' + (tab === 'metrics' ? ' active' : '')} onClick={() => setTab('metrics')}>Metrics</button>
        <button className={'tab-btn' + (tab === 'journal' ? ' active' : '')} onClick={() => setTab('journal')}>Journal ({journal.length})</button>
        <button className={'tab-btn' + (tab === 'trades' ? ' active' : '')} onClick={() => setTab('trades')}>Trades ({trades.length})</button>
      </div>

      {/* Content */}
      {tab === 'metrics' && <MetricsView run={run} />}
      {tab === 'journal' && <JournalView journal={journal} />}
      {tab === 'trades' && <TradesView trades={trades} />}
    </div>
  )
}

function MetricsView({ run }) {
  if (run.status !== 'completed') {
    return (
      <div className="panel">
        <div className="panel-b">
          <div className="empty">
            {run.status === 'pending' && 'Simulation pending...'}
            {run.status === 'fetching_data' && `Fetching historical data... ${run.progress_pct}%`}
            {run.status === 'running' && `Running simulation... ${run.progress_pct}%`}
            {run.status === 'failed' && `Simulation failed: ${run.error_message}`}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div>
      <div className="kpis">
        <Tile label="Total R" val={run.total_r != null ? `${run.total_r >= 0 ? '+' : ''}${run.total_r.toFixed(2)}R` : '—'} cls={run.total_r >= 0 ? 'accent' : 'down'} sub={`${run.total_trades} trades`} />
        <Tile label="Win Rate" val={run.win_rate != null ? `${run.win_rate.toFixed(1)}%` : '—'} sub={`${run.total_opportunities} opportunities`} />
        <Tile label="Expectancy" val={run.expectancy_r != null ? `${run.expectancy_r.toFixed(2)}R` : '—'} sub="per trade" />
        <Tile label="Max Drawdown" val={run.max_drawdown_r != null ? `${run.max_drawdown_r.toFixed(2)}R` : '—'} cls="down" sub="peak to trough" />
        <Tile label="Total P&L" val={run.total_pnl != null ? `₹${Math.round(run.total_pnl).toLocaleString()}` : '—'} cls={run.total_pnl >= 0 ? 'up' : 'down'} sub="simulated" />
      </div>
    </div>
  )
}

function JournalView({ journal }) {
  return (
    <div className="panel">
      <div className="panel-b">
        {journal.length === 0 ? (
          <div className="empty">No opportunities recorded</div>
        ) : (
          <div className="tbl-wrap">
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th>State</th>
                  <th className="num">Score</th>
                  <th className="num">Entry/Stop/Target</th>
                  <th className="num">R:R</th>
                  <th className="num">RVOL</th>
                </tr>
              </thead>
              <tbody>
                {journal.map(j => (
                  <tr key={j.id}>
                    <td>{j.sim_time ? new Date(j.sim_time).toLocaleTimeString() : '—'}</td>
                    <td>{j.symbol?.split(':').pop().replace('-EQ', '') ?? '—'}</td>
                    <td><span className={'chip ' + (j.side === 'LONG' ? 'CONFIRMED' : 'WATCH')}>{label(j.side)}</span></td>
                    <td><Chip state={j.state} /></td>
                    <td className="num">{j.score}</td>
                    <td className="num">{j.entry || '—'} / {j.stop || '—'} / {j.target || '—'}</td>
                    <td className="num">{j.net_rr || '—'}</td>
                    <td className="num">{j.rvol || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

function TradesView({ trades }) {
  return (
    <div className="panel">
      <div className="panel-b">
        {trades.length === 0 ? (
          <div className="empty">No trades executed</div>
        ) : (
          <div className="tbl-wrap">
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th className="num">Qty</th>
                  <th className="num">Entry</th>
                  <th className="num">Exit</th>
                  <th>Reason</th>
                  <th className="num">P&L</th>
                  <th className="num">Result R</th>
                </tr>
              </thead>
              <tbody>
                {trades.map(t => (
                  <tr key={t.id}>
                    <td>{t.created_at ? new Date(t.created_at).toLocaleTimeString() : '—'}</td>
                    <td>{t.symbol?.split(':').pop().replace('-EQ', '') ?? '—'}</td>
                    <td><span className={'chip ' + (t.side === 'LONG' ? 'CONFIRMED' : 'WATCH')}>{label(t.side)}</span></td>
                    <td className="num">{t.qty}</td>
                    <td className="num">{t.entry.toFixed(2)}</td>
                    <td className="num">{t.close_price ? t.close_price.toFixed(2) : '—'}</td>
                    <td>{label(t.close_reason) || '—'}</td>
                    <td className="num">
                      {t.pnl != null ? (
                        <span className={t.pnl >= 0 ? 'up' : 'down'}>
                          ₹{Math.round(t.pnl).toLocaleString()}
                        </span>
                      ) : '—'}
                    </td>
                    <td className="num">
                      {t.result_r != null ? (
                        <span className={t.result_r >= 0 ? 'up' : 'down'}>
                          {t.result_r >= 0 ? '+' : ''}{t.result_r.toFixed(2)}R
                        </span>
                      ) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// ============================================================================
// Comparison View
// ============================================================================

function SimComparison({ runIds, onBack }) {
  const [runs, setRuns] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadComparison()
  }, [runIds])

  const loadComparison = async () => {
    try {
      const data = await api(`/api/sim/compare?run_ids=${runIds.join(',')}`)
      setRuns(data.runs)
    } catch (err) {
      console.error('Failed to load comparison:', err)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className="empty">Loading comparison...</div>

  return (
    <div className="panel">
      <div className="panel-h">
        <button className="btn" onClick={onBack} style={{ marginRight: 12 }}>← Back</button>
        <h2>Compare Simulations</h2>
        <span className="hint">{runs.length} runs</span>
      </div>
      <div className="panel-b">
        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                <th>Metric</th>
                {runs.map(r => (
                  <th key={r.id} className="num">{r.name}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>Date</strong></td>
                {runs.map(r => <td key={r.id} className="num">{r.date}</td>)}
              </tr>
              <tr>
                <td><strong>Bar Interval</strong></td>
                {runs.map(r => <td key={r.id} className="num">{r.bar_interval} min</td>)}
              </tr>
              <tr>
                <td><strong>Opportunities</strong></td>
                {runs.map(r => <td key={r.id} className="num">{r.metrics.total_opportunities ?? '—'}</td>)}
              </tr>
              <tr>
                <td><strong>Trades</strong></td>
                {runs.map(r => <td key={r.id} className="num">{r.metrics.total_trades ?? '—'}</td>)}
              </tr>
              <tr>
                <td><strong>Total R</strong></td>
                {runs.map(r => (
                  <td key={r.id} className="num">
                    {r.metrics.total_r != null ? (
                      <span className={r.metrics.total_r >= 0 ? 'up' : 'down'}>
                        {r.metrics.total_r >= 0 ? '+' : ''}{r.metrics.total_r.toFixed(2)}R
                      </span>
                    ) : '—'}
                  </td>
                ))}
              </tr>
              <tr>
                <td><strong>Win Rate</strong></td>
                {runs.map(r => <td key={r.id} className="num">{r.metrics.win_rate != null ? `${r.metrics.win_rate.toFixed(1)}%` : '—'}</td>)}
              </tr>
              <tr>
                <td><strong>Expectancy R</strong></td>
                {runs.map(r => <td key={r.id} className="num">{r.metrics.expectancy_r != null ? `${r.metrics.expectancy_r.toFixed(2)}R` : '—'}</td>)}
              </tr>
              <tr>
                <td><strong>Max Drawdown R</strong></td>
                {runs.map(r => <td key={r.id} className="num">{r.metrics.max_drawdown_r != null ? `${r.metrics.max_drawdown_r.toFixed(2)}R` : '—'}</td>)}
              </tr>
              <tr>
                <td><strong>Total P&L</strong></td>
                {runs.map(r => (
                  <td key={r.id} className="num">
                    {r.metrics.total_pnl != null ? (
                      <span className={r.metrics.total_pnl >= 0 ? 'up' : 'down'}>
                        ₹{Math.round(r.metrics.total_pnl).toLocaleString()}
                      </span>
                    ) : '—'}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>

        <h3 style={{ marginTop: 24, marginBottom: 12 }}>Configuration Differences</h3>
        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                <th>Parameter</th>
                {runs.map(r => <th key={r.id} className="num">{r.name}</th>)}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Strategy</td>
                {runs.map(r => <td key={r.id} className="num">{(r.config.strategy || 'ORB')}</td>)}
              </tr>
              <tr>
                <td>Retest Tolerance %</td>
                {runs.map(r => <td key={r.id} className="num">{r.config.strategy === 'SMC' ? '—' : (r.config.retest_tolerance_pct ?? '—')}</td>)}
              </tr>
              <tr>
                <td>Min SMC Score</td>
                {runs.map(r => <td key={r.id} className="num">{r.config.strategy === 'SMC' ? (r.config.auto_trade_smc_min_score ?? '—') : '—'}</td>)}
              </tr>
              <tr>
                <td>Min Reward:Risk</td>
                {runs.map(r => <td key={r.id} className="num">{r.config.min_net_reward_risk ?? '—'}</td>)}
              </tr>
              <tr>
                <td>Min RVOL</td>
                {runs.map(r => <td key={r.id} className="num">{r.config.prereq_min_rvol ?? '—'}</td>)}
              </tr>
              <tr>
                <td>Auto-Trade</td>
                {runs.map(r => <td key={r.id} className="num">{r.config.auto_paper_trade ? 'On' : 'Off'}</td>)}
              </tr>
              <tr>
                <td>Capital (₹)</td>
                {runs.map(r => <td key={r.id} className="num">{r.config.capital_inr ? `₹${r.config.capital_inr.toLocaleString()}` : '—'}</td>)}
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

const Tile = ({ label, val, sub, cls }) => (
  <div className={'kpi ' + (cls || '')}><div className="label">{label}</div><div className="val">{val}</div><div className="sub">{sub}</div></div>
)
