const formatSyncTime = (value) => {
  if (!value) return 'Never synced'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return `Last synced ${parsed.toLocaleString()}`
}

export default function MeetingsGridView({
  meetings,
  syncedAt,
  autoSyncStatus,
  autoSyncError,
  loading,
  syncing,
  error,
  onSync,
  onSelectMeeting,
}) {
  const workspaceSync = autoSyncStatus?.workspace_sync || {}
  const vectorStore = autoSyncStatus?.vector_store || {}
  const autoEnabled = Boolean(autoSyncStatus?.enabled)
  const autoRunning = workspaceSync.status === 'RUNNING' || workspaceSync.status === 'QUEUED'

  return (
    <section className="meetings-page" aria-label="Meetings with recordings">
      <header className="meetings-page-header">
        <div>
          <p className="eyebrow">Video catalog</p>
          <h2>Recorded meetings ready for AI</h2>
          <p className="meetings-sync-meta">{formatSyncTime(syncedAt)}</p>
        </div>
        <button className="ghost-button" type="button" onClick={onSync} disabled={syncing || loading}>
          {syncing ? 'Syncing...' : 'Refresh catalog'}
        </button>
      </header>

      <section className="meetings-auto-sync" aria-live="polite">
        <div>
          <p className="eyebrow">{autoEnabled ? 'Automatic indexing' : 'Manual preparation'}</p>
          <h3>
            {autoRunning
              ? workspaceSync.message || 'Generating transcript embeddings now'
              : 'Open a recording card to generate transcript embeddings'}
          </h3>
          <p>
            {autoSyncError ||
              `${
                vectorStore.indexed_meeting_count || 0
              } ready recording(s), ${vectorStore.indexed_document_count || 0} transcript chunk(s). ${
                autoEnabled ? `Auto polling every ${autoSyncStatus?.interval_seconds || 60}s.` : 'Auto polling is off.'
              }`}
          </p>
        </div>
        <span className={autoRunning ? 'sync-pill running' : 'sync-pill'}>
          {autoEnabled ? workspaceSync.status || 'IDLE' : 'MANUAL'}
        </span>
      </section>

      {error ? <p className="feedback error">{error}</p> : null}
      {loading && meetings.length === 0 ? (
        <p className="sidebar-note">Loading recorded meetings from Microsoft...</p>
      ) : null}
      {!loading && meetings.length === 0 && !error ? (
        <p className="sidebar-note">
          No recorded meeting assets were found yet. Refresh after your Teams recording appears in
          OneDrive or SharePoint.
        </p>
      ) : null}

      <div className="meeting-list meetings-grid">
        {meetings.map((meeting) => {
          const preparing = ['QUEUED', 'PROCESSING'].includes(meeting.ingestionStatus)
          const failed = ['FAILED', 'NO_TRANSCRIPT'].includes(meeting.ingestionStatus)
          return (
            <button
              className="meeting-card meeting-grid-card"
              key={meeting.id}
              type="button"
              onClick={() => onSelectMeeting(meeting)}
            >
              <div className="meeting-card-header">
                <h4 className="meeting-card-title" title={meeting.title}>
                  {meeting.title}
                </h4>
                <time className="meeting-card-date" dateTime={meeting.startTimeIso || undefined}>
                  {meeting.time}
                </time>
              </div>
              <p className="meeting-card-organizer">{meeting.team}</p>
              <p className="meeting-card-summary">{meeting.summary}</p>
              <div className="meeting-card-footer">
                <div className="tag-row">
                  {meeting.tags.map((tag) => (
                    <span key={tag}>{tag}</span>
                  ))}
                </div>
                <span
                  className={
                    meeting.isIndexed
                      ? 'status-badge success'
                      : failed
                        ? 'status-badge error'
                        : 'status-badge warning'
                  }
                >
                  {meeting.isIndexed
                    ? 'Ready for chat'
                    : preparing
                      ? 'Preparing'
                      : failed
                        ? 'Retry prepare'
                        : 'Prepare for chat'}
                </span>
              </div>
            </button>
          )
        })}
      </div>
    </section>
  )
}
