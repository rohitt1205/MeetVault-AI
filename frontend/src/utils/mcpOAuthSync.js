export const MCP_OAUTH_EVENT_KEY = 'meetvault-mcp-oauth-event'
export const MCP_OAUTH_CHANNEL_NAME = 'meetvault-mcp-oauth'

export const publishMcpOAuthEvent = (payload) => {
  const event = {
    provider: payload.provider,
    connected: Boolean(payload.connected),
    error: payload.error || '',
    ts: Date.now(),
  }

  try {
    localStorage.setItem(MCP_OAUTH_EVENT_KEY, JSON.stringify(event))
  } catch (storageError) {
    console.error('Could not broadcast MCP OAuth completion via localStorage.', storageError)
  }

  try {
    const channel = new BroadcastChannel(MCP_OAUTH_CHANNEL_NAME)
    channel.postMessage(event)
    channel.close()
  } catch {
    // BroadcastChannel is not available in every browser; localStorage is the fallback.
  }
}

export const subscribeMcpOAuthEvents = (onEvent) => {
  const handleStorage = (event) => {
    if (event.key !== MCP_OAUTH_EVENT_KEY || !event.newValue) return
    try {
      onEvent(JSON.parse(event.newValue))
    } catch {
      // Ignore malformed payloads.
    }
  }

  let channel = null
  const handleMessage = (event) => {
    if (!event?.data) return
    onEvent(event.data)
  }

  window.addEventListener('storage', handleStorage)
  window.addEventListener('message', handleMessage)

  try {
    channel = new BroadcastChannel(MCP_OAUTH_CHANNEL_NAME)
    channel.addEventListener('message', handleMessage)
  } catch {
    channel = null
  }

  return () => {
    window.removeEventListener('storage', handleStorage)
    window.removeEventListener('message', handleMessage)
    if (channel) {
      channel.removeEventListener('message', handleMessage)
      channel.close()
    }
  }
}
