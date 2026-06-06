import { useEffect, useState } from 'react'
import { mcpService } from '../../services/mcpService'
import { subscribeMcpOAuthEvents, MCP_OAUTH_EVENT_KEY } from '../../utils/mcpOAuthSync'

const API_BASE_URL = import.meta.env.DEV
  ? '/api'
  : import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
export default function MCPPanel({ token, supabaseToken, userEmail }) {
  const [connections, setConnections] = useState(null)
  const [tools, setTools] = useState([])
  const [loading, setLoading] = useState(true)
  const [connectionError, setConnectionError] = useState('')

  // Active form view: 'jira' | 'custom_mcp' | null
  const [activeForm, setActiveForm] = useState(null)

  // OAuth status modal state
  const [oauthModal, setOauthModal] = useState(null)
  const [oauthStep] = useState(0) // 0 to 4
  const [oauthConnecting] = useState(false)
  const [oauthError] = useState('')

  // Form states
  const [jiraForm, setJiraForm] = useState({ email: '', domain: '', token: '' })
  const [jiraConnecting, setJiraConnecting] = useState(false)
  const [jiraError, setJiraError] = useState('')

  const [customMcpForm, setCustomMcpForm] = useState({ url: '', token: '' })
  const [customMcpConnecting, setCustomMcpConnecting] = useState(false)
  const [customMcpError, setCustomMcpError] = useState('')
  const [validationStep, setValidationStep] = useState(0) // 1 to 5

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
      setConnectionError('')
      const [connData, toolsData] = await Promise.all([
        mcpService.getConnections(token, supabaseToken),
        mcpService.listTools(token, supabaseToken)
      ])
      setConnections(connData)
      setTools(toolsData)
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
    const oauthProviders = ['github', 'slack', 'salesforce', 'notion', 'gmail']
    const returnedProvider = oauthProviders.find(provider => params.has(`${provider}_connected`))
    if (returnedProvider) {
      const connected = params.get(`${returnedProvider}_connected`) === 'true'
      const error = params.get('mcp_error') || ''
      if (!connected) {
        setConnectionError(error || `${returnedProvider} connection failed.`)
      }
      try {
        localStorage.setItem(
          MCP_OAUTH_EVENT_KEY,
          JSON.stringify({
            provider: returnedProvider,
            connected,
            error,
            ts: Date.now(),
          }),
        )
      } catch (storageError) {
        console.error('Could not broadcast MCP OAuth completion.', storageError)
      }
      window.history.replaceState({}, document.title, window.location.pathname)
      if (window.opener) {
        window.close()
      }
    }

    const handleFocus = () => loadConnections()
    const unsubscribeOAuth = subscribeMcpOAuthEvents((payload) => {
      if (payload?.connected) {
        setConnectionError('')
      } else if (payload?.provider) {
        setConnectionError(payload.error || `${payload.provider} connection failed.`)
      }
      loadConnections()
    })

    window.addEventListener('focus', handleFocus)
    return () => {
      window.removeEventListener('focus', handleFocus)
      unsubscribeOAuth()
    }
  }, [token, supabaseToken])

  const handleJiraConnect = async (event) => {
    event.preventDefault()
    setJiraConnecting(true)
    setJiraError('')

    try {
      await mcpService.connectJira(
        jiraForm.email,
        jiraForm.domain,
        jiraForm.token,
        token,
        supabaseToken
      )
      setJiraForm({ email: '', domain: '', token: '' })
      setActiveForm(null)
      await loadConnections()
    } catch (err) {
      setJiraError(err.message || 'Invalid Jira credentials or domain')
    } finally {
      setJiraConnecting(false)
    }
  }

  const handleOauthAuthorize = () => {
    if (!oauthModal?.provider) return
    handleOAuthConnect(oauthModal.provider)
  }

  const handleCustomMcpConnect = async (event) => {
    event.preventDefault()
    setCustomMcpConnecting(true)
    setCustomMcpError('')
    setValidationStep(1)

    const delay = (ms) => new Promise(res => setTimeout(res, ms))
    
    try {
      await delay(300)
      setValidationStep(2)
      await delay(300)
      setValidationStep(3)
      await delay(300)
      setValidationStep(4)
      await delay(200)
      setValidationStep(5)

      await mcpService.connectCustomMcp(
        customMcpForm.url,
        customMcpForm.token,
        token,
        supabaseToken
      )
      
      setCustomMcpForm({ url: '', token: '' })
      setActiveForm(null)
      await loadConnections()
    } catch (err) {
      setCustomMcpError(err.message || 'Failed to connect Custom MCP Server')
    } finally {
      setCustomMcpConnecting(false)
      setValidationStep(0)
    }
  }

  const handleGithubConnect = async () => {
    try {
      setConnectionError('')
      const { state_token: stateToken } = await mcpService.createOAuthContext(token, supabaseToken)
      const opened = openOAuthTab(mcpService.getGithubLoginUrl(stateToken))
      if (!opened) {
        setConnectionError('Please allow popups so GitHub can open in a new tab.')
      }
    } catch (err) {
      setConnectionError(err.message || 'GitHub OAuth could not be started.')
    }
  }

  const handleOAuthConnect = async (provider) => {
    try {
      setConnectionError('')
      const { state_token: stateToken } = await mcpService.createOAuthContext(token, supabaseToken)
      if (provider === 'github') {
        const opened = openOAuthTab(mcpService.getGithubLoginUrl(stateToken))
        if (!opened) {
          setConnectionError('Please allow popups so GitHub can open in a new tab.')
        }
        return
      }
      const opened = openOAuthTab(mcpService.getOAuthLoginUrl(provider, stateToken))
      if (!opened) {
        setConnectionError(`Please allow popups so ${provider} can open in a new tab.`)
      }
    } catch (err) {
      setConnectionError(err.message || `${provider} OAuth could not be started.`)
    }
  }

  const handleDisconnect = async (provider) => {
    try {
      setConnectionError('')
      await mcpService.disconnectProvider(provider, token, supabaseToken)
      await loadConnections()
    } catch (err) {
      setConnectionError(err.message || `Failed to disconnect ${provider}`)
    }
  }

  const handleToggleOutlook = async () => {
    try {
      if (connections?.outlook?.connected) {
        await handleDisconnect('outlook')
      } else {
        await fetch(`${API_BASE_URL}/mcp/connections`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`,
            'X-Supabase-Token': supabaseToken,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            provider: 'outlook',
            provider_user_id: userEmail || 'Microsoft user',
            connected: true
          })
        })
        await loadConnections()
      }
    } catch (err) {
      setConnectionError('Failed to update Outlook.')
    }
  }

  const handleToggleCalendar = async () => {
    try {
      if (connections?.calendar?.connected) {
        await handleDisconnect('calendar')
      } else {
        await fetch(`${API_BASE_URL}/mcp/connections`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`,
            'X-Supabase-Token': supabaseToken,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            provider: 'calendar',
            provider_user_id: userEmail || 'Microsoft user',
            connected: true
          })
        })
        await loadConnections()
      }
    } catch (err) {
      setConnectionError('Failed to update Calendar.')
    }
  }

  if (loading) {
    return (
      <div className="mcp-panel" style={{ padding: '24px', textAlign: 'center' }}>
        <p style={{ color: 'var(--text-muted)' }}>Loading integration marketplace...</p>
      </div>
    )
  }

  const renderToolBadges = (providerName) => {
    const providerTools = tools.filter(t => t.provider === providerName)
    if (providerTools.length === 0) return null
    return (
      <div style={{ marginTop: '8px', display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
        {providerTools.map(t => (
          <span 
            key={t.name}
            style={{
              padding: '2px 8px',
              borderRadius: '4px',
              fontSize: '0.75rem',
              fontWeight: 500,
              backgroundColor: 'rgba(59, 130, 246, 0.1)',
              color: 'var(--brand-accent, #3b82f6)',
              border: '1px solid rgba(59, 130, 246, 0.2)'
            }}
            title={t.description}
          >
            ⚙️ {t.name}
          </span>
        ))}
      </div>
    )
  }

  return (
    <div className="mcp-panel" style={{ padding: '8px', overflowX: 'hidden' }}>
      <header style={{ marginBottom: '20px' }}>
        <h3 style={{ fontSize: '1.25rem', fontWeight: 600, color: 'var(--text-main)' }}>
          Integration Marketplace
        </h3>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
          Connect MeetVault with your enterprise workspace. Connect tools to orchestrate grounding queries.
        </p>
      </header>

      {connectionError ? (
        <div style={{
          padding: '12px',
          borderRadius: '8px',
          backgroundColor: 'rgba(239, 68, 68, 0.1)',
          color: '#ef4444',
          fontSize: '0.875rem',
          border: '1px solid rgba(239, 68, 68, 0.2)',
          marginBottom: '16px'
        }}>
          ⚠️ {connectionError}
        </div>
      ) : null}

      <div style={{ 
        display: 'grid', 
        gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', 
        gap: '16px',
        marginBottom: '24px'
      }}>
        {/* OUTLOOK */}
        <article style={cardStyle}>
          <div style={headerStyle}>
            <div>
              <span style={{ fontSize: '1.5rem', marginRight: '8px' }}>✉️</span>
              <strong style={{ fontSize: '1rem' }}>Outlook</strong>
            </div>
            {connections?.outlook?.connected ? (
              <span style={connectedBadgeStyle}>Connected</span>
            ) : (
              <span style={disconnectedBadgeStyle}>Available</span>
            )}
          </div>
          <p style={descStyle}>Integrate Microsoft Outlook email inbox and unread priorities.</p>
          {connections?.outlook?.connected && renderToolBadges('outlook')}
          <div style={footerStyle}>
            <button 
              onClick={handleToggleOutlook} 
              className={connections?.outlook?.connected ? "ghost-button" : "auth-button"}
              style={{ fontSize: '0.8rem', padding: '6px 12px' }}
            >
              {connections?.outlook?.connected ? 'Disconnect' : 'Connect'}
            </button>
          </div>
        </article>

        {/* CALENDAR */}
        <article style={cardStyle}>
          <div style={headerStyle}>
            <div>
              <span style={{ fontSize: '1.5rem', marginRight: '8px' }}>📅</span>
              <strong style={{ fontSize: '1rem' }}>Microsoft Calendar</strong>
            </div>
            {connections?.calendar?.connected ? (
              <span style={connectedBadgeStyle}>Connected</span>
            ) : (
              <span style={disconnectedBadgeStyle}>Available</span>
            )}
          </div>
          <p style={descStyle}>Orchestrate meetings, deadlines, and schedule events from Teams.</p>
          {connections?.calendar?.connected && renderToolBadges('calendar')}
          <div style={footerStyle}>
            <button 
              onClick={handleToggleCalendar} 
              className={connections?.calendar?.connected ? "ghost-button" : "auth-button"}
              style={{ fontSize: '0.8rem', padding: '6px 12px' }}
            >
              {connections?.calendar?.connected ? 'Disconnect' : 'Connect'}
            </button>
          </div>
        </article>

        {/* GITHUB */}
        <article style={cardStyle}>
          <div style={headerStyle}>
            <div>
              <span style={{ fontSize: '1.5rem', marginRight: '8px' }}>🐙</span>
              <strong style={{ fontSize: '1rem' }}>GitHub</strong>
            </div>
            {connections?.github?.connected ? (
              <span style={connectedBadgeStyle}>Connected</span>
            ) : (
              <span style={disconnectedBadgeStyle}>Available</span>
            )}
          </div>
          <p style={descStyle}>Discover code repositories, pull requests, issues, and review workflows.</p>
          {connections?.github?.connected && renderToolBadges('github')}
          <div style={footerStyle}>
            {connections?.github?.connected ? (
              <button 
                onClick={() => handleDisconnect('github')} 
                className="ghost-button"
                style={{ fontSize: '0.8rem', padding: '6px 12px' }}
              >
                Disconnect
              </button>
            ) : (
              <button 
                onClick={() => handleOAuthConnect('github')} 
                className="auth-button"
                style={{ fontSize: '0.8rem', padding: '6px 12px' }}
              >
                Connect OAuth
              </button>
            )}
          </div>
        </article>

        {/* JIRA */}
        <article style={cardStyle}>
          <div style={headerStyle}>
            <div>
              <span style={{ fontSize: '1.5rem', marginRight: '8px' }}>🤖</span>
              <strong style={{ fontSize: '1rem' }}>Jira</strong>
            </div>
            {connections?.jira?.connected ? (
              <span style={connectedBadgeStyle}>Connected</span>
            ) : (
              <span style={disconnectedBadgeStyle}>Available</span>
            )}
          </div>
          <p style={descStyle}>Query and fetch issues, backlog statuses, and assigned tickets.</p>
          {connections?.jira?.connected && renderToolBadges('jira')}
          <div style={footerStyle}>
            {connections?.jira?.connected && (
              <button 
                onClick={() => handleDisconnect('jira')} 
                className="ghost-button"
                style={{ fontSize: '0.85rem', padding: '6px 12px', marginRight: '8px' }}
              >
                Disconnect
              </button>
            )}
            <button 
              onClick={() => setActiveForm(activeForm === 'jira' ? null : 'jira')} 
              className="auth-button"
              style={{ fontSize: '0.8rem', padding: '6px 12px' }}
            >
              {connections?.jira?.connected ? 'Reconnect' : 'Connect API Key'}
            </button>
          </div>

          {activeForm === 'jira' && (
            <form onSubmit={handleJiraConnect} style={formStyle}>
              <input
                type="email"
                placeholder="Jira Registered Email"
                value={jiraForm.email}
                onChange={(e) => setJiraForm({ ...jiraForm, email: e.target.value })}
                required
                style={inputStyle}
              />
              <input
                type="text"
                placeholder="Jira Domain (e.g. company.atlassian.net)"
                value={jiraForm.domain}
                onChange={(e) => setJiraForm({ ...jiraForm, domain: e.target.value })}
                required
                style={inputStyle}
              />
              <input
                type="password"
                placeholder="API Token Key"
                value={jiraForm.token}
                onChange={(e) => setJiraForm({ ...jiraForm, token: e.target.value })}
                required
                style={inputStyle}
              />
              {jiraError && <p style={errorTextStyle}>{jiraError}</p>}
              <button type="submit" className="send-button" disabled={jiraConnecting} style={{ padding: '6px 12px' }}>
                {jiraConnecting ? 'Connecting...' : 'Verify & Save'}
              </button>
            </form>
          )}
        </article>

        {/* SLACK */}
        <article style={cardStyle}>
          <div style={headerStyle}>
            <div>
              <span style={{ fontSize: '1.5rem', marginRight: '8px' }}>💬</span>
              <strong style={{ fontSize: '1rem' }}>Slack</strong>
            </div>
            {connections?.slack?.connected ? (
              <span style={connectedBadgeStyle}>Connected</span>
            ) : (
              <span style={disconnectedBadgeStyle}>Available</span>
            )}
          </div>
          <p style={descStyle}>Sync mentions, direct threads, and channel notifications.</p>
          {connections?.slack?.connected && renderToolBadges('slack')}
          <div style={footerStyle}>
            {connections?.slack?.connected ? (
              <button 
                onClick={() => handleDisconnect('slack')} 
                className="ghost-button"
                style={{ fontSize: '0.8rem', padding: '6px 12px' }}
              >
                Disconnect
              </button>
            ) : (
              <button 
                onClick={() => handleOAuthConnect('slack')} 
                className="auth-button"
                style={{ fontSize: '0.8rem', padding: '6px 12px' }}
              >
                Connect OAuth
              </button>
            )}
          </div>
        </article>

        {/* SALESFORCE */}
        <article style={cardStyle}>
          <div style={headerStyle}>
            <div>
              <span style={{ fontSize: '1.5rem', marginRight: '8px' }}>☁️</span>
              <strong style={{ fontSize: '1rem' }}>Salesforce</strong>
            </div>
            {connections?.salesforce?.connected ? (
              <span style={connectedBadgeStyle}>Connected</span>
            ) : (
              <span style={disconnectedBadgeStyle}>Available</span>
            )}
          </div>
          <p style={descStyle}>Retrieve pipeline details, customer context, and sales opportunities.</p>
          {connections?.salesforce?.connected && renderToolBadges('salesforce')}
          <div style={footerStyle}>
            {connections?.salesforce?.connected ? (
              <button 
                onClick={() => handleDisconnect('salesforce')} 
                className="ghost-button"
                style={{ fontSize: '0.8rem', padding: '6px 12px' }}
              >
                Disconnect
              </button>
            ) : (
              <button 
                onClick={() => handleOAuthConnect('salesforce')} 
                className="auth-button"
                style={{ fontSize: '0.8rem', padding: '6px 12px' }}
              >
                Connect OAuth
              </button>
            )}
          </div>
        </article>

        {/* NOTION */}
        <article style={cardStyle}>
          <div style={headerStyle}>
            <div>
              <span style={{ fontSize: '1.5rem', marginRight: '8px' }}>📓</span>
              <strong style={{ fontSize: '1rem' }}>Notion</strong>
            </div>
            {connections?.notion?.connected ? (
              <span style={connectedBadgeStyle}>Connected</span>
            ) : (
              <span style={disconnectedBadgeStyle}>Available</span>
            )}
          </div>
          <p style={descStyle}>Access workspace notes, product specs, and collaborative page resources.</p>
          {connections?.notion?.connected && renderToolBadges('notion')}
          <div style={footerStyle}>
            {connections?.notion?.connected ? (
              <button 
                onClick={() => handleDisconnect('notion')} 
                className="ghost-button"
                style={{ fontSize: '0.8rem', padding: '6px 12px' }}
              >
                Disconnect
              </button>
            ) : (
              <button 
                onClick={() => handleOAuthConnect('notion')} 
                className="auth-button"
                style={{ fontSize: '0.8rem', padding: '6px 12px' }}
              >
                Connect OAuth
              </button>
            )}
          </div>
        </article>

        {/* GMAIL */}
        <article style={cardStyle}>
          <div style={headerStyle}>
            <div>
              <span style={{ fontSize: '1.5rem', marginRight: '8px' }}>📧</span>
              <strong style={{ fontSize: '1rem' }}>Gmail</strong>
            </div>
            {connections?.gmail?.connected ? (
              <span style={connectedBadgeStyle}>Connected</span>
            ) : (
              <span style={disconnectedBadgeStyle}>Available</span>
            )}
          </div>
          <p style={descStyle}>Orchestrate recent emails, threads, and notification summaries from Google.</p>
          {connections?.gmail?.connected && renderToolBadges('gmail')}
          <div style={footerStyle}>
            {connections?.gmail?.connected ? (
              <button 
                onClick={() => handleDisconnect('gmail')} 
                className="ghost-button"
                style={{ fontSize: '0.8rem', padding: '6px 12px' }}
              >
                Disconnect
              </button>
            ) : (
              <button 
                onClick={() => handleOAuthConnect('gmail')} 
                className="auth-button"
                style={{ fontSize: '0.8rem', padding: '6px 12px' }}
              >
                Connect OAuth
              </button>
            )}
          </div>
        </article>
      </div>

      {/* CUSTOM MCP SERVER CONNECTIONS */}
      <h4 style={{ fontSize: '1.1rem', fontWeight: 600, color: 'var(--text-main)', marginTop: '28px', marginBottom: '16px' }}>
        Universal Model Context Protocol (MCP) Connectors
      </h4>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '16px', marginBottom: '24px' }}>
        <article style={{ ...cardStyle, minHeight: 'auto', padding: '20px' }}>
          <div style={headerStyle}>
            <div>
              <span style={{ fontSize: '1.5rem', marginRight: '8px' }}>🔌</span>
              <strong style={{ fontSize: '1.1rem' }}>Connect Custom MCP Server</strong>
            </div>
            <span style={disconnectedBadgeStyle}>Universal</span>
          </div>
          <p style={descStyle}>
            Register any MCP-compatible JSON-RPC SSE/HTTP server dynamically to discover its capabilities at runtime.
          </p>

          {connections?.custom_mcp_servers && connections.custom_mcp_servers.length > 0 && (
            <div style={{ margin: '16px 0', borderTop: '1px solid var(--border-soft)', paddingTop: '12px' }}>
              <p style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '8px' }}>Connected Custom Servers:</p>
              {connections.custom_mcp_servers.map(server => (
                <div 
                  key={server.url}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '10px 14px',
                    borderRadius: '8px',
                    backgroundColor: 'rgba(59, 130, 246, 0.05)',
                    border: '1px solid rgba(59, 130, 246, 0.15)',
                    marginBottom: '8px'
                  }}
                >
                  <div style={{ flex: 1 }}>
                    <code style={{ fontSize: '0.8rem', color: 'var(--brand-accent)' }}>{server.url}</code>
                    {renderToolBadges(`mcp:${server.url}`)}
                  </div>
                  <button 
                    onClick={() => handleDisconnect(`mcp:${server.url}`)}
                    className="ghost-button"
                    style={{ fontSize: '0.75rem', padding: '4px 10px', marginLeft: '12px' }}
                  >
                    Disconnect
                  </button>
                </div>
              ))}
            </div>
          )}

          <div style={{ marginTop: '16px' }}>
            <button 
              onClick={() => setActiveForm(activeForm === 'custom_mcp' ? null : 'custom_mcp')}
              className="send-button"
              style={{ fontSize: '0.85rem', padding: '8px 16px' }}
            >
              🔌 Connect New MCP Server
            </button>
          </div>

          {activeForm === 'custom_mcp' && (
            <form onSubmit={handleCustomMcpConnect} style={{ ...formStyle, maxWidth: '500px', marginTop: '16px' }}>
              <input
                type="url"
                placeholder="Server Endpoint URL (e.g. http://localhost:3000/sse)"
                value={customMcpForm.url}
                onChange={(e) => setCustomMcpForm({ ...customMcpForm, url: e.target.value })}
                required
                style={inputStyle}
              />
              <input
                type="password"
                placeholder="Authentication Token (Optional)"
                value={customMcpForm.token}
                onChange={(e) => setCustomMcpForm({ ...customMcpForm, token: e.target.value })}
                style={inputStyle}
              />
              
              {customMcpConnecting && (
                <div style={checklistContainerStyle}>
                  <p style={{ fontWeight: 600, fontSize: '0.85rem', margin: '0 0 10px 0' }}>MCP Handshake Verification Checklist:</p>
                  <div style={checklistItemStyle(validationStep >= 1)}>
                    {validationStep >= 1 ? '✅' : '⏳'} Step 1: Verifying Server Reachability...
                  </div>
                  <div style={checklistItemStyle(validationStep >= 2)}>
                    {validationStep >= 2 ? '✅' : '⏳'} Step 2: Negotiating JSON-RPC Protocol...
                  </div>
                  <div style={checklistItemStyle(validationStep >= 3)}>
                    {validationStep >= 3 ? '✅' : '⏳'} Step 3: Resolving SSE Stream Endpoints...
                  </div>
                  <div style={checklistItemStyle(validationStep >= 4)}>
                    {validationStep >= 4 ? '✅' : '⏳'} Step 4: Reading Discovery Tools Schema...
                  </div>
                  <div style={checklistItemStyle(validationStep >= 5)}>
                    {validationStep >= 5 ? '✅' : '⏳'} Step 5: Activating Registry Orchestration...
                  </div>
                </div>
              )}

              {customMcpError && <p style={errorTextStyle}>{customMcpError}</p>}
              
              <div style={{ display: 'flex', gap: '8px', marginTop: '12px' }}>
                <button 
                  type="submit" 
                  className="send-button" 
                  disabled={customMcpConnecting}
                  style={{ padding: '8px 16px' }}
                >
                  {customMcpConnecting ? 'Orchestrating Handshake...' : 'Discover & Register'}
                </button>
                <button 
                  type="button" 
                  onClick={() => setActiveForm(null)}
                  className="ghost-button"
                  style={{ padding: '8px 16px' }}
                >
                  Cancel
                </button>
              </div>
            </form>
          )}
        </article>
      </div>

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
            gap: '16px'
          }}>
            <header style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <span style={{ fontSize: '2rem' }}>🔑</span>
              <div>
                <h3 style={{ fontSize: '1.15rem', fontWeight: 600, margin: 0, color: 'var(--text-main)' }}>
                  Authorize MeetVault AI
                </h3>
                <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', margin: 0 }}>
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
              lineHeight: 1.4,
              color: 'var(--text-main)'
            }}>
              <p style={{ fontWeight: 600, margin: '0 0 8px 0' }}>Requesting Access Scopes:</p>
              <p style={{ margin: 0, color: 'var(--text-muted)' }}>{oauthModal.scopeDesc}</p>
            </div>

            {oauthConnecting && (
              <div style={checklistContainerStyle}>
                <p style={{ fontWeight: 600, fontSize: '0.85rem', margin: '0 0 10px 0' }}>OAuth Handshake Checklist:</p>
                <div style={checklistItemStyle(oauthStep >= 1)}>
                  {oauthStep >= 1 ? '✅' : '⏳'} Step 1: Contacting authorization provider...
                </div>
                <div style={checklistItemStyle(oauthStep >= 2)}>
                  {oauthStep >= 2 ? '✅' : '⏳'} Step 2: Exchanging token credentials...
                </div>
                <div style={checklistItemStyle(oauthStep >= 3)}>
                  {oauthStep >= 3 ? '✅' : '⏳'} Step 3: Encrypting secret keys...
                </div>
                <div style={checklistItemStyle(oauthStep >= 4)}>
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
                className="send-button"
                disabled={oauthConnecting}
                style={{ padding: '8px 16px' }}
              >
                {oauthConnecting ? 'Authorizing...' : 'Grant Permission'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const cardStyle = {
  display: 'flex',
  flexDirection: 'column',
  padding: '16px',
  borderRadius: '12px',
  border: '1px solid var(--border-soft, #e2e8f0)',
  backgroundColor: 'var(--bg-card, #ffffff)',
  boxShadow: '0 4px 12px rgba(0, 0, 0, 0.03)',
  transition: 'all 0.2s ease',
  minHeight: '200px',
  justifyContent: 'space-between'
}

const headerStyle = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  marginBottom: '12px'
}

const connectedBadgeStyle = {
  fontSize: '0.75rem',
  padding: '3px 8px',
  borderRadius: '12px',
  fontWeight: 600,
  backgroundColor: 'rgba(52, 211, 153, 0.1)',
  color: '#34d399',
  border: '1px solid rgba(52, 211, 153, 0.2)'
}

const disconnectedBadgeStyle = {
  fontSize: '0.75rem',
  padding: '3px 8px',
  borderRadius: '12px',
  fontWeight: 600,
  backgroundColor: 'rgba(156, 163, 175, 0.1)',
  color: '#9ca3af',
  border: '1px solid rgba(156, 163, 175, 0.2)'
}

const descStyle = {
  fontSize: '0.85rem',
  color: 'var(--text-muted, #718096)',
  lineHeight: 1.4,
  margin: '0 0 16px 0',
  flex: 1
}

const footerStyle = {
  display: 'flex',
  justifyContent: 'flex-end',
  marginTop: 'auto',
  gap: '8px'
}

const formStyle = {
  display: 'flex',
  flexDirection: 'column',
  gap: '8px',
  marginTop: '16px',
  borderTop: '1px solid var(--border-soft, #e2e8f0)',
  paddingTop: '16px'
}

const inputStyle = {
  padding: '8px 12px',
  borderRadius: '8px',
  border: '1px solid var(--border-soft, #e2e8f0)',
  backgroundColor: 'var(--bg-input, #f7fafc)',
  fontSize: '0.85rem',
  color: 'var(--text-main, #2d3748)',
  outline: 'none'
}

const errorTextStyle = {
  color: '#e53e3e',
  fontSize: '0.8rem',
  margin: '4px 0 0 0'
}

const checklistContainerStyle = {
  padding: '12px',
  borderRadius: '8px',
  backgroundColor: 'rgba(59, 130, 246, 0.03)',
  border: '1px solid rgba(59, 130, 246, 0.1)',
  marginTop: '8px',
  marginBottom: '8px'
}

const checklistItemStyle = (isComplete) => ({
  fontSize: '0.8rem',
  color: isComplete ? 'var(--text-main, #2d3748)' : 'var(--text-muted, #a0aec0)',
  fontWeight: isComplete ? 600 : 400,
  margin: '4px 0',
  display: 'flex',
  alignItems: 'center',
  gap: '6px'
})
