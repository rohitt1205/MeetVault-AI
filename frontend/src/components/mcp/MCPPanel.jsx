import { useEffect, useState } from 'react'
import { mcpService } from '../../services/mcpService'

export default function MCPPanel({ token, userEmail }) {
  const [connections, setConnections] = useState(null)
  const [loading, setLoading] = useState(true)
  const [connectionError, setConnectionError] = useState('')
  const [jiraForm, setJiraForm] = useState({ email: '', domain: '', token: '' })
  const [jiraConnecting, setJiraConnecting] = useState(false)
  const [jiraError, setJiraError] = useState('')

  const loadConnections = async () => {
    try {
      setConnectionError('')
      const data = await mcpService.getConnections(token)
      setConnections(data)
    } catch (err) {
      console.error(err)
      setConnectionError(err.message || 'Unable to load MCP connections.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadConnections()

    const params = new URLSearchParams(window.location.search)
    if (params.get('github_connected')) {
      if (params.get('github_connected') === 'false') {
        setConnectionError(params.get('mcp_error') || 'GitHub connection failed.')
      }
      window.history.replaceState({}, document.title, window.location.pathname)
    }

    const handleFocus = () => loadConnections()
    window.addEventListener('focus', handleFocus)
    return () => window.removeEventListener('focus', handleFocus)
  }, [token])

  const handleJiraConnect = async (event) => {
    event.preventDefault()
    setJiraConnecting(true)
    setJiraError('')

    try {
      await mcpService.connectJira(jiraForm.email, jiraForm.domain, jiraForm.token, token)
      await loadConnections()
      setJiraForm({ email: '', domain: '', token: '' })
    } catch (err) {
      setJiraError(err.message || 'Invalid Jira credentials or domain')
    } finally {
      setJiraConnecting(false)
    }
  }

  const handleGithubConnect = () => {
    window.location.href = mcpService.getGithubLoginUrl(userEmail)
  }

  if (loading) {
    return (
      <div className="mcp-panel">
        <p>Loading connections...</p>
      </div>
    )
  }

  return (
    <div className="mcp-panel" style={{ maxHeight: '350px', overflowY: 'auto', paddingRight: '8px' }}>
      <div className="mcp-section">
        <h4 style={{ marginBottom: '16px', fontSize: '1.1rem', fontWeight: 600 }}>
          Connected Enterprise Tools
        </h4>

        {connectionError ? (
          <p style={{ color: '#d14343', fontSize: '0.9rem', marginBottom: '12px' }}>
            {connectionError}
          </p>
        ) : null}

        <div className="server-list">
          <article className="server-row">
            <div>
              <p style={{ fontWeight: 600, fontSize: '0.95rem' }}>Outlook / Email / Calendar</p>
              {connections?.outlook?.connected ? (
                <p style={{ color: 'var(--brand-accent)', fontSize: '0.9rem' }}>
                  Connected via Microsoft session
                  {connections?.outlook?.email ? ` (${connections.outlook.email})` : ''}
                </p>
              ) : (
                <p style={{ fontSize: '0.9rem' }}>
                  Not connected. Sign in with Microsoft Graph access.
                </p>
              )}
            </div>
          </article>

          <article className="server-row">
            <div>
              <p style={{ fontWeight: 600, fontSize: '0.95rem' }}>GitHub Code Repository</p>
              {connections?.github?.connected ? (
                <p style={{ color: 'var(--brand-accent)', fontSize: '0.9rem' }}>
                  Connected as <strong style={{ color: 'inherit' }}>{connections.github.username}</strong>
                </p>
              ) : (
                <div>
                  <p style={{ fontSize: '0.9rem', marginBottom: '8px' }}>Not connected</p>
                  <button
                    onClick={handleGithubConnect}
                    className="auth-button"
                    style={{ padding: '6px 12px', fontSize: '0.85rem' }}
                    type="button"
                  >
                    Connect GitHub
                  </button>
                </div>
              )}
            </div>
          </article>

          <article className="server-row" style={{ flexWrap: 'wrap' }}>
            <div style={{ width: '100%' }}>
              <p style={{ fontWeight: 600, fontSize: '0.95rem' }}>Jira Issues & Boards</p>
              {connections?.jira?.connected ? (
                <p style={{ color: 'var(--brand-accent)', fontSize: '0.9rem' }}>
                  Connected to <strong style={{ color: 'inherit' }}>{connections.jira.domain}</strong> as{' '}
                  <strong style={{ color: 'inherit' }}>{connections.jira.email}</strong>
                </p>
              ) : (
                <div>
                  <p style={{ fontSize: '0.9rem', marginBottom: '8px' }}>Not connected</p>
                  <form
                    onSubmit={handleJiraConnect}
                    style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '12px' }}
                  >
                    <input
                      type="email"
                      placeholder="Jira Email"
                      value={jiraForm.email}
                      onChange={(event) => setJiraForm({ ...jiraForm, email: event.target.value })}
                      required
                      style={{ padding: '8px', borderRadius: '8px', border: '1px solid var(--border-soft)' }}
                    />
                    <input
                      type="text"
                      placeholder="Jira Domain (e.g. company.atlassian.net)"
                      value={jiraForm.domain}
                      onChange={(event) => setJiraForm({ ...jiraForm, domain: event.target.value })}
                      required
                      style={{ padding: '8px', borderRadius: '8px', border: '1px solid var(--border-soft)' }}
                    />
                    <input
                      type="password"
                      placeholder="Jira API Token"
                      value={jiraForm.token}
                      onChange={(event) => setJiraForm({ ...jiraForm, token: event.target.value })}
                      required
                      style={{ padding: '8px', borderRadius: '8px', border: '1px solid var(--border-soft)' }}
                    />
                    {jiraError ? (
                      <p style={{ color: '#d14343', fontSize: '0.85rem' }}>{jiraError}</p>
                    ) : null}
                    <button
                      type="submit"
                      className="send-button"
                      disabled={jiraConnecting}
                      style={{ alignSelf: 'flex-start', padding: '6px 12px' }}
                    >
                      {jiraConnecting ? 'Connecting...' : 'Connect Jira'}
                    </button>
                  </form>
                </div>
              )}
            </div>
          </article>
        </div>
      </div>
    </div>
  )
}
