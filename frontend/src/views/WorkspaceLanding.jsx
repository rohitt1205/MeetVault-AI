import ChatMarkdown from '../components/ChatMarkdown'

const formatDateTime = (value) => {
  if (!value) return 'Not yet'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString()
}

const autoSyncMessage = (status) => {
  if (!status) return 'Checking indexed recording status...'
  if (!status.enabled) return 'Manual preparation is active. Open a recording card to generate transcript embeddings.'

  const workspace = status.workspace_sync || {}
  if (workspace.status === 'RUNNING' || workspace.status === 'QUEUED') {
    return workspace.message || 'Indexing recordings in the background.'
  }
  if (workspace.status === 'FAILED') {
    return workspace.message || 'The last automatic sync failed.'
  }
  if (status.registered_user_count === 0) {
    return 'Waiting for Microsoft sign-in before automatic sync can start.'
  }
  return workspace.message || 'Automatic sync is watching for new recording assets.'
}

const answerEyebrowForMode = (mode) => {
  switch (mode) {
    case 'meeting_assistant':
    case 'conversational':
    case 'conversational_fallback':
      return 'MeetVault'
    case 'retrieval_brief':
    case 'retrieval_only':
      return 'Workspace answer'
    default:
      return 'Answer'
  }
}

export default function WorkspaceLanding({
  autoSyncStatus,
  autoSyncError,
  query,
  messages = [],
  isSearching = false,
  searchMessage = '',
  pipelineNotice = '',
  onQueryChange,
  onSubmit,
  onRefreshAutoSync,
  onOpenMeetings,
}) {
  const workspace = autoSyncStatus?.workspace_sync || {}
  const vectorStore = autoSyncStatus?.vector_store || {}
  const autoEnabled = Boolean(autoSyncStatus?.enabled)
  const isRunning = workspace.status === 'RUNNING' || workspace.status === 'QUEUED'
  const hasMessages = messages.length > 0
  const readyMeetings = vectorStore.indexed_meeting_count ?? 0
  const readyChunks = vectorStore.indexed_document_count ?? 0

  return (
    <section className={`workspace-landing ${hasMessages ? 'workspace-chat-active' : ''}`} aria-label="Workspace home">
      <div className="workspace-chat-shell">
        {!hasMessages ? (
          <div className="workspace-search-intro">
            <p className="eyebrow">Search stored meeting knowledge</p>
            <h2>Ask across your ready recordings</h2>
          </div>
        ) : (
          <div className="conversation-panel workspace-conversation" aria-label="Workspace conversation">
            {messages.map((turn, index) => (
              <div className="turn-stack" key={turn.id || `${turn.role}-${index}`}>
                {turn.role === 'user' ? (
                  <article className="message-row user">
                    <div className="message-bubble user">
                      <p>{turn.text}</p>
                    </div>
                  </article>
                ) : (
                  <article className="message-row assistant">
                    <div className="message-bubble assistant">
                      <p className="message-label">{answerEyebrowForMode(turn.mode)}</p>
                      <ChatMarkdown text={turn.text} />
                    </div>
                  </article>
                )}
              </div>
            ))}
            {isSearching ? (
              <div className="message-row assistant">
                <div className="message-bubble assistant typing" aria-live="polite">
                  <span className="typing-dots" aria-hidden="true">
                    <span />
                    <span />
                    <span />
                  </span>
                  <span className="typing-label">Thinking...</span>
                </div>
              </div>
            ) : null}
          </div>
        )}

        <form className="workspace-search-form" onSubmit={onSubmit}>
          <textarea
            aria-label="Ask across indexed recordings"
            value={query}
            onChange={(event) => onQueryChange?.(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                event.currentTarget.form?.requestSubmit()
              }
            }}
            placeholder="Ask anything across ready meeting recordings..."
            rows={1}
            disabled={isSearching}
          />
          <button type="submit" disabled={isSearching || !query.trim()}>
            {isSearching ? '...' : 'Send'}
          </button>
        </form>
        {(pipelineNotice || searchMessage) && (
          <div className="status-stack compact">
            {pipelineNotice ? <p className="feedback">{pipelineNotice}</p> : null}
            {searchMessage ? <p className="feedback error">{searchMessage}</p> : null}
          </div>
        )}
      </div>

      <article className="auto-sync-card" aria-live="polite">
        <div className="auto-sync-header">
          <div>
            <p className="eyebrow">{autoEnabled ? 'Automatic sync' : 'Manual preparation'}</p>
            <h3>
              {isRunning
                ? 'Embedding generation is running'
                : autoEnabled
                  ? 'Recording watcher is active'
                  : 'Open a recording to prepare it for chat'}
            </h3>
          </div>
          <span className={isRunning ? 'sync-pill running' : 'sync-pill'}>
            {autoEnabled ? workspace.status || 'IDLE' : 'MANUAL'}
          </span>
        </div>
        <p className="auto-sync-message">{autoSyncError || autoSyncMessage(autoSyncStatus)}</p>
        <dl className="auto-sync-grid">
          <div>
            <dt>Mode</dt>
            <dd>{autoEnabled ? `Auto, ${autoSyncStatus?.interval_seconds || 60}s` : 'Manual'}</dd>
          </div>
          <div>
            <dt>Last check</dt>
            <dd>{formatDateTime(autoSyncStatus?.last_checked_at || workspace.updated_at)}</dd>
          </div>
          <div>
            <dt>Ready recordings</dt>
            <dd>{readyMeetings}</dd>
          </div>
          <div>
            <dt>Transcript chunks</dt>
            <dd>{readyChunks}</dd>
          </div>
        </dl>
        <div className="auto-sync-actions">
          <button className="ghost-button" type="button" onClick={onRefreshAutoSync}>
            Refresh status
          </button>
          <button className="ghost-button" type="button" onClick={onOpenMeetings}>
            Browse catalog
          </button>
        </div>
      </article>
    </section>
  )
}
