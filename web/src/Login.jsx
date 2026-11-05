import React, { useEffect, useState } from 'react'
import { api } from './api.js'

export default function Login({ onDevLogin }) {
  const [cfg, setCfg] = useState({ google: false, dev: false })
  useEffect(() => { api('/auth/config').then(setCfg).catch(() => {}) }, [])

  return (
    <div className="login">
      <div className="card">
        <div className="mark">⚡</div>
        <h1>Rockstar Radar</h1>
        <p>NSE intraday opening-range radar. Sign in to continue.</p>

        {cfg.google ? (
          <a className="gbtn" href="/auth/google/login">
            <svg width="18" height="18" viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.9 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.2C12.4 13.5 17.7 9.5 24 9.5z"/><path fill="#4285F4" d="M46.1 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.4c-.5 2.9-2.1 5.3-4.6 7l7.1 5.5c4.2-3.9 6.6-9.6 6.6-16.5z"/><path fill="#FBBC05" d="M10.5 28.4c-.5-1.5-.8-3-.8-4.4s.3-3 .8-4.4l-7.9-6.2C1 16.7 0 20.2 0 24s1 7.3 2.6 10.6l7.9-6.2z"/><path fill="#34A853" d="M24 48c6.3 0 11.6-2.1 15.5-5.7l-7.1-5.5c-2 1.3-4.6 2.2-8.4 2.2-6.3 0-11.6-4-13.5-9.9l-7.9 6.2C6.5 42.6 14.6 48 24 48z"/></svg>
            Continue with Google
          </a>
        ) : (
          <div className="banner warn" style={{ textAlign: 'left' }}>
            Google sign-in isn't configured yet. Set <code>GOOGLE_CLIENT_ID</code> and
            <code> GOOGLE_CLIENT_SECRET</code> to enable it.
          </div>
        )}

        {cfg.dev && (
          <>
            <div className="alt">— or —</div>
            <button className="btn" style={{ width: '100%', marginTop: 10, justifyContent: 'center' }}
              onClick={onDevLogin}>Continue as test user (dev)</button>
          </>
        )}

        <div className="foot">
          Your intraday co-pilot for the Indian markets.
        </div>
      </div>
    </div>
  )
}
