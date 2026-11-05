import React, { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from './api.js'
import { Select } from './ui.jsx'

const ERRORS = {
  credentials: 'Save your App ID and Secret first, then click Connect.',
  unsupported: 'Guided login for this platform is coming soon.',
  session: 'Your session expired. Please sign in again and retry.',
  state: 'Login could not be verified (security check). Please try Connect again.',
  manual: 'Your app uses its own redirect URL — use the "existing app" option below to connect.',
  exchange: 'The broker rejected the login. Check your Secret and that the redirect URL matches '
    + 'your app exactly, then retry.',
  no_code: 'The broker did not return an authorization code. Please try again.',
}

export default function Brokers() {
  const [data, setData] = useState(null)
  const [platform, setPlatform] = useState('')
  const [appId, setAppId] = useState('')
  const [secret, setSecret] = useState('')
  const [msg, setMsg] = useState(null)
  const [copied, setCopied] = useState(false)
  // Manual ("existing app") flow state
  const [manual, setManual] = useState(false)
  const [redirect, setRedirect] = useState('')     // the user's own registered redirect URL
  const [pasted, setPasted] = useState('')         // the URL they were redirected to
  const [linkOpened, setLinkOpened] = useState(false)
  const [params, setParams] = useSearchParams()

  const load = async () => {
    const d = await api('/api/brokers'); setData(d)
    if (d.active) {
      setPlatform(d.active.platform); setAppId(d.active.app_id || '')
      if (!d.active.auto) { setManual(true); setRedirect(d.active.redirect_uri || '') }
    } else { setPlatform((d.platforms.find(p => p.status === 'available') || {}).id || '') }
    return d
  }

  useEffect(() => {
    load().then(() => {
      if (params.get('connected')) setMsg({ ok: true, t: 'Connected — your broker is now streaming live data.' })
      else if (params.get('error')) setMsg({ ok: false, t: ERRORS[params.get('error')] || 'Login failed. Please try again.' })
      if (params.get('connected') || params.get('error')) { params.delete('connected'); params.delete('error'); setParams(params, { replace: true }) }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (!data) return <div className="empty">Loading…</div>

  const meta = data.platforms.find(p => p.id === platform) || {}
  const isOauth = (data.platforms.find(p => p.id === platform) || {}).id === 'fyers' // oauth-wired today
  const connected = !!data.active && data.active.has_token

  const putBroker = () => api('/api/brokers', { method: 'PUT', body: { platform, app_id: appId, secret, redirect_uri: manual ? redirect : '' } })

  const save = async () => {
    try { const r = await putBroker(); setMsg({ ok: true, t: 'Broker saved (' + r.status + ')' }); setSecret(''); await load() }
    catch (e) { setMsg({ ok: false, t: e.message }) }
  }
  const test = async () => {
    setMsg({ ok: true, t: 'Testing…' })
    try { const r = await api('/api/brokers/test', { method: 'POST', body: { platform, app_id: appId, secret } }); setMsg({ ok: r.ok, t: r.message }) }
    catch (e) { setMsg({ ok: false, t: e.message }) }
  }
  // Automatic flow — broker redirects back to us.
  const connectAuto = async () => {
    try {
      if (appId.trim() && secret.trim()) await putBroker()
      window.location.href = '/api/brokers/login'
    } catch (e) { setMsg({ ok: false, t: e.message }) }
  }
  // Manual flow — open broker login in a new tab using the user's own redirect.
  const openManualLogin = async () => {
    setMsg(null)
    try {
      if (!redirect.trim()) { setMsg({ ok: false, t: 'Enter your app\'s registered redirect URL first.' }); return }
      await putBroker()
      const r = await api('/api/brokers/login-url', { method: 'POST' })
      setLinkOpened(true)
      window.open(r.url, '_blank', 'noopener')
    } catch (e) { setMsg({ ok: false, t: e.message }) }
  }
  const finishManual = async () => {
    try { await api('/api/brokers/login-finish', { method: 'POST', body: { response_url: pasted } }); setMsg({ ok: true, t: 'Connected — your broker is now streaming live data.' }); setPasted(''); setLinkOpened(false); await load() }
    catch (e) { setMsg({ ok: false, t: e.message }) }
  }
  const copyCallback = async () => {
    try { await navigator.clipboard.writeText(data.callback_uri); setCopied(true); setTimeout(() => setCopied(false), 1500) } catch { /* clipboard blocked */ }
  }

  return (
    <div className="rlayout" style={{ gridTemplateColumns: '1.3fr 1fr' }}>
      <div className="panel">
        <div className="panel-h"><h2>Your broker</h2>
          <span className="hint">One platform powers your data, quotes, history &amp; orders</span></div>
        <div className="panel-b">
          {msg && <div className={'banner ' + (msg.ok ? 'ok' : 'err')}>{msg.t}</div>}
          <div className="field"><label>Platform</label>
            <Select value={platform} onChange={setPlatform} width={'100%'} options={data.platforms.map(p => ({
              value: p.id, label: p.label + (p.status !== 'available' ? ' · coming soon' : ''), disabled: p.status !== 'available' }))} />
          </div>
          <div className="field"><label>App ID</label>
            <input value={appId} onChange={e => setAppId(e.target.value)} placeholder="e.g. ABCD1234-100" /></div>
          <div className="field"><label>Secret {data.active?.has_secret ? '· saved, leave blank to keep' : ''}</label>
            <input type="password" value={secret} onChange={e => setSecret(e.target.value)} autoComplete="off" placeholder="API secret" /></div>

          {/* Connection method */}
          {isOauth && (
            <div className="field">
              <label>How do you want to connect?</label>
              <div className="segmented">
                <button type="button" className={'seg' + (!manual ? ' on' : '')} onClick={() => setManual(false)}>Register our URL <span className="segsub">recommended</span></button>
                <button type="button" className={'seg' + (manual ? ' on' : '')} onClick={() => setManual(true)}>I have an app with its own redirect</button>
              </div>
            </div>
          )}

          {!manual ? (
            <div className="field"><label>Redirect URL — add this to your {meta.label || 'broker'} app</label>
              <div className="copyfield">
                <code>{data.callback_uri}</code>
                <button type="button" className="btn" onClick={copyCallback}>{copied ? 'Copied' : 'Copy'}</button>
              </div>
              <div className="hint" style={{ marginTop: 6 }}>Paste this exact URL as the redirect URI in your app — we never see your password, and the token is captured for you automatically.</div>
            </div>
          ) : (
            <div className="field"><label>Your app's registered redirect URL</label>
              <input value={redirect} onChange={e => setRedirect(e.target.value)} placeholder="http://127.0.0.1:8765/auth/callback" />
              <div className="hint" style={{ marginTop: 6 }}>Use the exact redirect URL already set in your broker app — nothing to change on the broker side. After you sign in, your browser lands on this URL (it may show an error page — that's fine); copy the full URL from the address bar and paste it below.</div>
            </div>
          )}

          <div className="row">
            <button className="btn primary" onClick={save}>Save</button>
            <button className="btn" onClick={test}>Test connection</button>
            {isOauth && !manual && <button className="btn accent" onClick={connectAuto}>{connected ? 'Reconnect' : 'Connect ' + (meta.label || '')}</button>}
            {isOauth && manual && <button className="btn accent" onClick={openManualLogin}>Open {meta.label} login</button>}
          </div>

          {isOauth && manual && linkOpened && (
            <div className="field" style={{ marginTop: 18 }}>
              <label>Paste the URL you were redirected to</label>
              <input value={pasted} onChange={e => setPasted(e.target.value)} placeholder="http://…?auth_code=…&state=…" />
              <div className="row" style={{ marginTop: 10 }}>
                <button className="btn accent" disabled={!pasted.trim()} onClick={finishManual}>Finish connection</button>
              </div>
            </div>
          )}
          {meta.help && <p className="note">{meta.help}</p>}
        </div>
      </div>

      <div className="panel">
        <div className="panel-h"><h2>Status</h2></div>
        <div className="panel-b">
          {data.active ? (
            <>
              <div className="kv"><span className="k">Platform</span><span>{(data.platforms.find(p => p.id === data.active.platform) || {}).label}</span></div>
              <div className="kv"><span className="k">Credentials</span><span className={'chip ' + (data.active.has_secret ? 'CONFIRMED' : 'NONE')}>{data.active.has_secret ? 'saved' : 'missing'}</span></div>
              <div className="kv"><span className="k">Connect mode</span><span className="chip">{data.active.auto ? 'automatic' : 'existing app'}</span></div>
              <div className="kv"><span className="k">Today's login</span>
                <span className={'chip ' + (data.active.fresh_today ? 'CONFIRMED' : 'WATCH')}>{data.active.fresh_today ? 'done' : 'needed'}</span></div>
              <div className="kv"><span className="k">Live token</span><span className={'chip ' + (data.active.has_token ? 'CONFIRMED' : 'NONE')}>{data.active.has_token ? 'present' : 'none'}</span></div>
              {isOauth && !data.active.fresh_today && (
                <div style={{ marginTop: 12 }}>
                  <button className="btn accent" style={{ width: '100%', justifyContent: 'center' }} onClick={manual ? openManualLogin : connectAuto}>{data.active.has_token ? 'Log in for today' : 'Connect ' + (meta.label || '')}</button>
                  <div className="hint" style={{ marginTop: 8 }}>SEBI requires a fresh broker login every trading day — tokens can't be auto-renewed. Log in each morning (ideally before 9:15 IST) to start the scan. It's one tap on {meta.label}'s own page; we never see your password.</div>
                </div>
              )}
              {isOauth && data.active.fresh_today && (
                <div className="hint" style={{ marginTop: 12 }}>You're logged in for today. The scan runs through the session; you'll log in again tomorrow (SEBI requirement).</div>
              )}
            </>
          ) : <div className="empty">No broker connected yet. Fill in the form to get started.</div>}
          <p className="note">More platforms are on the way — Upstox, Angel One, Dhan, Groww, Paytm Money and 5paisa.</p>
        </div>
      </div>
    </div>
  )
}
