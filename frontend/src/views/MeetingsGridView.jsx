const formatSyncTime = (value) => {
  if (!value) return 'Never synced'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return `Last synced ${parsed.toLocaleString()}`
}

export default function MeetingsGridView({
  meetings,
  syncedAt,
  loading,
  syncing,
  error,
  onSync,
  onSelectMeeting,
}) {
  return (
    <section className="meetings-page" aria-label="Meetings with recordings">
      <header className="meetings-page-header">
        <div>
          <p className="eyebrow">Calendar</p>
          <h2>Meetings with recordings</h2>
          <p className="meetings-sync-meta">{formatSyncTime(syncedAt)}</p>
        </div>
        <button className="ghost-button" type="button" onClick={onSync} disabled={syncing || loading}>
          {syncing ? 'Syncing…' : 'Sync'}
        </button>
      </header>

      {error ? <p className="feedback error">{error}</p> : null}
      {loading && meetings.length === 0 ? (
        <p className="sidebar-note">Loading meetings from Microsoft Teams…</p>
      ) : null}
      {!loading && meetings.length === 0 && !error ? (
        <p className="sidebar-note">
          No Teams calendar meetings with recordings were found. Sync again after your next recorded
          meeting.
        </p>
      ) : null}

      <div className="meeting-list meetings-grid">
        {meetings.map((meeting) => (
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
              {meeting.isIndexed ? (
                <span className="status-badge success">Ready for chat</span>
              ) : (
                <span className="status-badge warning">Prepare on open</span>
              )}
            </div>
          </button>
        ))}
      </div>
    </section>
  )
}
