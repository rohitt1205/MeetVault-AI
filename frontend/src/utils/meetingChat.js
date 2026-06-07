export const CHAT_HISTORY_TABLE = 'chat_history'

export const CHAT_SELECT_FIELDS =
  'id,title,query,meeting_id,meeting_title,status,messages,created_at'

/** Legacy NOT NULL column on chat_history (workspace search); meeting chats use messages. */
export const MEETING_CHAT_LEGACY_QUERY = ''

/** Fields allowed on update (meeting chats store conversation in messages jsonb). */
export const mapRagSourcesForUi = (sources = [], excerptLimit = 220) =>
  (sources || []).slice(0, 5).map((source, index) => {
    const cleaned = (source.text || '').replace(/\s+/g, ' ').trim()
    const excerpt =
      cleaned.length <= excerptLimit
        ? cleaned
        : `${cleaned.slice(0, excerptLimit).trim()}…`

    return {
      id: source.chunk_id || `source-${index}`,
      excerpt,
      start: source.metadata?.start_timestamp || null,
      meetingTitle: source.metadata?.meeting_title || null,
    }
  })

export const sanitizeChatPatch = (patch) => {
  const clean = {}
  if (patch.title !== undefined) clean.title = patch.title
  if (patch.meeting_title !== undefined) clean.meeting_title = patch.meeting_title
  if (patch.status !== undefined) clean.status = patch.status
  if (patch.messages !== undefined) clean.messages = patch.messages
  return clean
}

export const INGESTION_STAGE_PROGRESS = {
  discover: 12,
  download: 28,
  transcribe: 52,
  chunk: 72,
  embed: 88,
  ready: 100,
  failed: 0,
}

export const mapMeetingChatRow = (row) => ({
  id: row.id,
  title: row.title || row.meeting_title || 'Untitled meeting',
  meetingId: row.meeting_id,
  meetingTitle: row.meeting_title || row.title || 'Untitled meeting',
  status: row.status || 'ready',
  messages: Array.isArray(row.messages) ? row.messages : [],
  createdAt: row.created_at,
})

export const mapWorkspaceChatRow = (row) => ({
  id: row.id,
  title: row.title || row.query || 'Workspace chat',
  query: row.query || '',
  status: row.status || 'ready',
  messages: Array.isArray(row.messages) ? row.messages : [],
  createdAt: row.created_at,
})

export const ingestionProgressPercent = (payload) => {
  if (!payload) return 0
  if (payload.status === 'EMBEDDED') return 100
  if (payload.status === 'FAILED' || payload.status === 'NO_TRANSCRIPT') return 0

  const stage = payload.stage
  if (stage && INGESTION_STAGE_PROGRESS[stage] != null) {
    return INGESTION_STAGE_PROGRESS[stage]
  }

  if (payload.status === 'QUEUED') return 8
  if (payload.status === 'PROCESSING') return 45
  return 0
}

export const isIngestionFailed = (status) =>
  status === 'FAILED' || status === 'NO_TRANSCRIPT'

export const ingestionStageLabel = (payload) => {
  if (!payload) return 'Starting'
  if (payload.status === 'EMBEDDED') return 'Ready'
  if (payload.status === 'FAILED') return 'Failed'
  if (payload.status === 'NO_TRANSCRIPT') return 'No transcript available'
  if (payload.message) return payload.message

  switch (payload.stage) {
    case 'discover':
      return 'Discovering meeting resources'
    case 'download':
      return 'Downloading recording'
    case 'transcribe':
      return 'Transcribing audio'
    case 'chunk':
      return 'Chunking transcript'
    case 'embed':
      return 'Embedding for search'
    default:
      return 'Preparing your chat'
  }
}

export const isChatReady = (chatStatus, ingestionStatus) =>
  chatStatus === 'ready' || ingestionStatus === 'EMBEDDED'

export const isChatPreparing = (chatStatus, ingestionStatus) =>
  chatStatus === 'preparing' ||
  ['QUEUED', 'PROCESSING'].includes(ingestionStatus)

export const ingestionStatusUnchanged = (previous, next) =>
  previous?.status === next?.status &&
  previous?.stage === next?.stage &&
  previous?.message === next?.message
