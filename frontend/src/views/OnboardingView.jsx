import { useState, useEffect } from 'react'
import { mcpService } from '../services/mcpService'
import { subscribeMcpOAuthEvents } from '../utils/mcpOAuthSync'

export default function OnboardingView({ token, supabaseToken, userEmail, onComplete }) {
  const [connections, setConnections] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // Form states
  const [jiraForm, setJiraForm] = useState({ email: '', domain: '', token: '' })
  const [jiraConnecting, setJiraConnecting] = useState(false)

  // OAuth modal state: null or { provider: 'slack'|'salesforce'|'github', name: '...', scopeDesc: '...' }
  const [oauthModal, setOauthModal] = useState(null)
  const [oauthStep, setOauthStep] = useState(0) // 0 to 4
  const [oauthConnecting, setOauthConnecting] = useState(false)
  const [oauthError, setOauthError] = useState('')

  const [activeForm, setActiveForm] = useState(null) // 'jira' or null

  const openOAuthTab = (loginUrl) => {
    const authWindow = window.open(loginUrl, '_blank')
    if (authWindow) {
      authWindow.focus()
      return true
    }
    return false
  }

  const loadConnections = async () => {
    try {
      setError('')
      const data = await mcpService.getConnections(token, supabaseToken)
      setConnections(data)
    } catch (err) {
      console.error(err)
      setError('Unable to load connection states.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadConnections()

    const handleFocus = () => loadConnections()
    const unsubscribeOAuth = subscribeMcpOAuthEvents((payload) => {
      if (payload?.connected) {
        setError('')
      } else if (payload?.provider) {
        setError(payload.error || `${payload.provider} connection failed.`)
      }
      loadConnections()
    })

    window.addEventListener('focus', handleFocus)
    return () => {
      window.removeEventListener('focus', handleFocus)
      unsubscribeOAuth()
    }
  }, [token, supabaseToken])

  const handleJiraSubmit = async (e) => {
    e.preventDefault()
    setJiraConnecting(true)
    setError('')
    try {
      await mcpService.connectJira(jiraForm.email, jiraForm.domain, jiraForm.token, token, supabaseToken)
      setJiraForm({ email: '', domain: '', token: '' })
      setActiveForm(null)
      await loadConnections()
    } catch (err) {
      setError(err.message || 'Jira connection failed.')
    } finally {
      setJiraConnecting(false)
    }
  }

  const handleOauthAuthorize = async () => {
    if (!oauthModal) return
    setOauthConnecting(true)
    setOauthError('')
    setOauthStep(1)

    const delay = (ms) => new Promise(res => setTimeout(res, ms))

    try {
      await delay(300)
      setOauthStep(2)
      await delay(300)
      setOauthStep(3)
      await delay(300)
      setOauthStep(4)
      await delay(200)

      const provider = oauthModal.provider
      const { state_token: stateToken } = await mcpService.createOAuthContext(token, supabaseToken)
      const loginUrl =
        provider === 'github'
          ? mcpService.getGithubLoginUrl(stateToken)
          : mcpService.getOAuthLoginUrl(provider, stateToken)

      const opened = openOAuthTab(loginUrl)
      if (!opened) {
        setOauthError(`Please allow popups so ${oauthModal.name} can open in a new tab.`)
      }
    } catch (err) {
      setOauthError(err.message || `Failed to complete ${oauthModal.name} OAuth flow.`)
    } finally {
      setOauthConnecting(false)
      setOauthStep(0)
    }
  }

  const handleToggleOutlook = async () => {
    try {
      if (connections?.outlook?.connected) {
        await mcpService.disconnectProvider('outlook', token, supabaseToken)
      } else {
        // Since it relies on Graph token, reconnecting means setting connected=true in DB if it was false
        const fakeSession = { connected: true, provider_user_id: userEmail }
        await fetch(`/api/mcp/connections?on_conflict=user_id,provider`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`,
            'X-Supabase-Token': supabaseToken,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            provider: 'outlook',
            provider_user_id: userEmail,
            connected: true
          })
        })
      }
      await loadConnections()
    } catch (err) {
      setError('Failed to update Outlook state.')
    }
  }

  const handleToggleCalendar = async () => {
    try {
      if (connections?.calendar?.connected) {
        await mcpService.disconnectProvider('calendar', token, supabaseToken)
      } else {
        const fakeSession = { connected: true, provider_user_id: userEmail }
        await fetch(`/api/mcp/connections?on_conflict=user_id,provider`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`,
            'X-Supabase-Token': supabaseToken,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            provider: 'calendar',
            provider_user_id: userEmail,
            connected: true
          })
        })
      }
      await loadConnections()
    } catch (err) {
      setError('Failed to update Calendar state.')
    }
  }

  if (loading) {
    return (
      <div className="onboarding-gate">
        <div className="onboarding-card loading-card">
          <h2>Setting up your workspace...</h2>
          <div className="spinner"></div>
        </div>
      </div>
    )
  }

  return (
    <div className="onboarding-gate">
      <div className="onboarding-card">
        <header className="onboarding-header">
          <div className="brand-mark">M</div>
          <h2>Connect Your Work Tools</h2>
          <p>
            MeetVault AI links meeting discussions with execution systems. Link your tools to search issues, PRs, schedule, emails, and compile work summaries.
          </p>
        </header>

        {error && <p className="onboarding-error-banner">{error}</p>}

        <div className="onboarding-grid">
          {/* Outlook */}
          <div className={`onboarding-item ${connections?.outlook?.connected ? 'connected' : ''}`}>
            <div className="onboarding-item-meta">
              <h4>Outlook Email</h4>
              <p>{connections?.outlook?.connected ? `Linked (${connections.outlook.email || userEmail})` : 'Not linked'}</p>
            </div>
            <button
              onClick={handleToggleOutlook}
              className={`onboarding-action-btn ${connections?.outlook?.connected ? 'disconnect' : 'connect'}`}
            >
              {connections?.outlook?.connected ? 'Disconnect' : 'Connect'}
            </button>
          </div>

          {/* Calendar */}
          <div className={`onboarding-item ${connections?.calendar?.connected ? 'connected' : ''}`}>
            <div className="onboarding-item-meta">
              <h4>Calendar Schedule</h4>
              <p>{connections?.calendar?.connected ? `Linked (${connections.calendar.email || userEmail})` : 'Not linked'}</p>
            </div>
            <button
              onClick={handleToggleCalendar}
              className={`onboarding-action-btn ${connections?.calendar?.connected ? 'disconnect' : 'connect'}`}
            >
              {connections?.calendar?.connected ? 'Disconnect' : 'Connect'}
            </button>
          </div>

          {/* GitHub */}
          <div className={`onboarding-item ${connections?.github?.connected ? 'connected' : ''}`}>
            <div className="onboarding-item-meta">
              <h4>GitHub Repos</h4>
              <p>{connections?.github?.connected ? `Connected as ${connections.github.username}` : 'Not connected'}</p>
            </div>
            <button
              onClick={connections?.github?.connected ? () => mcpService.disconnectProvider('github', token, supabaseToken).then(loadConnections) : () => setOauthModal({
                provider: 'github',
                name: 'GitHub',
                scopeDesc: 'Access code repositories, view public/private pulls, inspect active issues, and retrieve review request metadata.'
              })}
              className={`onboarding-action-btn ${connections?.github?.connected ? 'disconnect' : 'connect'}`}
            >
              {connections?.github?.connected ? 'Disconnect' : 'Connect'}
            </button>
          </div>

          {/* Jira */}
          <div className={`onboarding-item ${connections?.jira?.connected ? 'connected' : ''}`}>
            <div className="onboarding-item-meta">
              <h4>Jira Boards</h4>
              <p>{connections?.jira?.connected ? `Linked to ${connections.jira.domain}` : 'Not connected'}</p>
            </div>
            {connections?.jira?.connected ? (
              <button
                onClick={() => mcpService.disconnectProvider('jira', token, supabaseToken).then(loadConnections)}
                className="onboarding-action-btn disconnect"
              >
                Disconnect
              </button>
            ) : (
              <button
                onClick={() => setActiveForm(activeForm === 'jira' ? null : 'jira')}
                className="onboarding-action-btn connect"
              >
                Connect
              </button>
            )}
          </div>

          {/* Slack */}
          <div className={`onboarding-item ${connections?.slack?.connected ? 'connected' : ''}`}>
            <div className="onboarding-item-meta">
              <h4>Slack Mentions</h4>
              <p>{connections?.slack?.connected ? `Linked account` : 'Not connected'}</p>
            </div>
            {connections?.slack?.connected ? (
              <button
                onClick={() => mcpService.disconnectProvider('slack', token, supabaseToken).then(loadConnections)}
                className="onboarding-action-btn disconnect"
              >
                Disconnect
              </button>
            ) : (
              <button
                onClick={() => setOauthModal({
                  provider: 'slack',
                  name: 'Slack Workspace',
                  scopeDesc: 'Access channel lists, view public thread history, search workspace mentions, and fetch details for @user handles.'
                })}
                className="onboarding-action-btn connect"
              >
                Connect
              </button>
            )}
          </div>

          {/* Salesforce */}
          <div className={`onboarding-item ${connections?.salesforce?.connected ? 'connected' : ''}`}>
            <div className="onboarding-item-meta">
              <h4>Salesforce CRM</h4>
              <p>{connections?.salesforce?.connected ? `Linked account` : 'Not connected'}</p>
            </div>
            {connections?.salesforce?.connected ? (
              <button
                onClick={() => mcpService.disconnectProvider('salesforce', token, supabaseToken).then(loadConnections)}
                className="onboarding-action-btn disconnect"
              >
                Disconnect
              </button>
            ) : (
              <button
                onClick={() => setOauthModal({
                  provider: 'salesforce',
                  name: 'Salesforce CRM',
                  scopeDesc: 'Access client opportunities, read marketing leads, list user pipelines, and inspect customer contact details.'
                })}
                className="onboarding-action-btn connect"
              >
                Connect
              </button>
            )}
          </div>
        </div>

        {/* Dynamic credential forms overlay */}
        {activeForm === 'jira' && (
          <form onSubmit={handleJiraSubmit} className="onboarding-credentials-form">
            <h3>Connect Jira Account</h3>
            <input
              type="email"
              placeholder="Jira Email"
              value={jiraForm.email}
              onChange={(e) => setJiraForm({ ...jiraForm, email: e.target.value })}
              required
            />
            <input
              type="text"
              placeholder="Jira Domain (e.g. company.atlassian.net)"
              value={jiraForm.domain}
              onChange={(e) => setJiraForm({ ...jiraForm, domain: e.target.value })}
              required
            />
            <input
              type="password"
              placeholder="Jira API Token"
              value={jiraForm.token}
              onChange={(e) => setJiraForm({ ...jiraForm, token: e.target.value })}
              required
            />
            <div className="form-actions">
              <button type="button" onClick={() => setActiveForm(null)} className="ghost-button">Cancel</button>
              <button type="submit" className="primary-button" disabled={jiraConnecting}>
                {jiraConnecting ? 'Connecting...' : 'Link Jira'}
              </button>
            </div>
          </form>
        )}

        {/* PREMIUM OAUTH DIALOG OVERLAY */}
        {oauthModal && (
          <div style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.6)',
            backdropFilter: 'blur(8px)',
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            zIndex: 1000,
            padding: '16px'
          }}>
            <div style={{
              backgroundColor: 'var(--bg-card, #ffffff)',
              border: '1px solid var(--border-soft, #e2e8f0)',
              borderRadius: '16px',
              width: '100%',
              maxWidth: '460px',
              padding: '24px',
              boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)',
              display: 'flex',
              flexDirection: 'column',
              gap: '16px',
              color: 'var(--text-main, #2d3748)',
              textAlign: 'left'
            }}>
              <header style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <span style={{ fontSize: '2rem' }}>🔑</span>
                <div>
                  <h3 style={{ fontSize: '1.15rem', fontWeight: 600, margin: 0 }}>
                    Authorize MeetVault AI
                  </h3>
                  <p style={{ fontSize: '0.8rem', color: 'var(--text-muted, #718096)', margin: 0 }}>
                    Connecting to {oauthModal.name}
                  </p>
                </div>
              </header>

              <div style={{
                padding: '14px',
                borderRadius: '10px',
                backgroundColor: 'rgba(59, 130, 246, 0.03)',
                border: '1px solid rgba(59, 130, 246, 0.1)',
                fontSize: '0.85rem',
                lineHeight: 1.4
              }}>
                <p style={{ fontWeight: 600, margin: '0 0 8px 0' }}>Requesting Access Scopes:</p>
                <p style={{ margin: 0, color: 'var(--text-muted, #718096)' }}>{oauthModal.scopeDesc}</p>
              </div>

              {oauthConnecting && (
                <div style={{
                  padding: '12px',
                  borderRadius: '8px',
                  backgroundColor: 'rgba(59, 130, 246, 0.03)',
                  border: '1px solid rgba(59, 130, 246, 0.1)',
                  marginTop: '8px',
                  marginBottom: '8px'
                }}>
                  <p style={{ fontWeight: 600, fontSize: '0.85rem', margin: '0 0 10px 0' }}>OAuth Handshake Checklist:</p>
                  <div style={{
                    fontSize: '0.8rem',
                    color: oauthStep >= 1 ? 'var(--text-main, #2d3748)' : 'var(--text-muted, #a0aec0)',
                    fontWeight: oauthStep >= 1 ? 600 : 400,
                    margin: '4px 0',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px'
                  }}>
                    {oauthStep >= 1 ? '✅' : '⏳'} Step 1: Contacting authorization provider...
                  </div>
                  <div style={{
                    fontSize: '0.8rem',
                    color: oauthStep >= 2 ? 'var(--text-main, #2d3748)' : 'var(--text-muted, #a0aec0)',
                    fontWeight: oauthStep >= 2 ? 600 : 400,
                    margin: '4px 0',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px'
                  }}>
                    {oauthStep >= 2 ? '✅' : '⏳'} Step 2: Exchanging token credentials...
                  </div>
                  <div style={{
                    fontSize: '0.8rem',
                    color: oauthStep >= 3 ? 'var(--text-main, #2d3748)' : 'var(--text-muted, #a0aec0)',
                    fontWeight: oauthStep >= 3 ? 600 : 400,
                    margin: '4px 0',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px'
                  }}>
                    {oauthStep >= 3 ? '✅' : '⏳'} Step 3: Encrypting secret keys...
                  </div>
                  <div style={{
                    fontSize: '0.8rem',
                    color: oauthStep >= 4 ? 'var(--text-main, #2d3748)' : 'var(--text-muted, #a0aec0)',
                    fontWeight: oauthStep >= 4 ? 600 : 400,
                    margin: '4px 0',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px'
                  }}>
                    {oauthStep >= 4 ? '✅' : '⏳'} Step 4: Syncing workspace tools...
                  </div>
                </div>
              )}

              {oauthError && (
                <p style={{ color: '#ef4444', fontSize: '0.8rem', margin: 0 }}>
                  ⚠️ {oauthError}
                </p>
              )}

              <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end', marginTop: '8px' }}>
                <button
                  onClick={() => setOauthModal(null)}
                  className="ghost-button"
                  disabled={oauthConnecting}
                  style={{ padding: '8px 16px' }}
                >
                  Cancel
                </button>
                <button
                  onClick={handleOauthAuthorize}
                  className="primary-button"
                  disabled={oauthConnecting}
                  style={{ padding: '8px 16px' }}
                >
                  {oauthConnecting ? 'Authorizing...' : 'Grant Permission'}
                </button>
              </div>
            </div>
          </div>
        )}

        <footer className="onboarding-footer">
          <button onClick={onComplete} className="skip-onboarding-btn">
            Finish
          </button>
        </footer>
      </div>
    </div>
  )
}
