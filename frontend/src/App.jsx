import { useCallback, useEffect, useMemo, useState } from 'react'
import { supabase } from './lib/supabase'
import MCPPanel from './components/mcp/MCPPanel'
import './App.css'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const CHAT_HISTORY_TABLE = 'chat_history'
const STATUS_POLL_MS = 5000
const REQUIRED_LOGIN_SCOPES =
  'openid profile email offline_access User.Read Calendars.Read Files.Read OnlineMeetings.Read OnlineMeetingTranscript.Read.All'
const THEME_STORAGE_KEY = 'meetvault-theme'
const FALLBACK_TOPIC_CARDS = [
  'Latest recording summary',
  'Decisions',
  'Action items',
  'Blockers',
  'LWC Training',
  'MuleSoft',
  'Sales Assistant Agent',
  'Integration Training',
]

const mcpServers = [
  {
    id: 'graph',
    name: 'Microsoft Graph',
    status: 'Workspace sync',
    description: 'Uses admin-consented Microsoft Graph scopes to fetch meetings, SharePoint recordings, and transcripts.',
  },
  {
    id: 'rag',
    name: 'RAG Layer',
    status: 'Grounded answers',
    description: 'MeetVault now queries ChromaDB and composes grounded answers on top of stored transcript chunks.',
  },
]

const readErrorMessage = async (response, fallbackMessage) => {
  try {
    const raw = await response.text()
    if (!raw) return fallbackMessage

    try {
      const parsed = JSON.parse(raw)
      if (typeof parsed.detail === 'string') return parsed.detail
      if (typeof parsed.detail?.message === 'string') return parsed.detail.message
      if (typeof parsed.message === 'string') return parsed.message
    } catch {
      // keep the raw response below
    }

    return raw
  } catch {
    return fallbackMessage
  }
}

const formatDateTime = (value) => {
  if (!value) return 'Waiting for the first sync'

  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString()
}

const mapHistoryRow = (row) => ({
  id: row.id,
  title: row.title,
  preview: row.preview || (row.meeting_title ? `Context: ${row.meeting_title}` : ''),
  query: row.query,
  meetingId: row.meeting_id,
  meetingTitle: row.meeting_title,
  createdAt: row.created_at,
})

const answerEyebrowForMode = (mode) => {
  switch (mode) {
    case 'gemini':
      return 'Grounded answer'
    case 'extractive_summary':
      return 'Fallback summary'
    case 'retrieval_brief':
      return 'Fallback brief'
    case 'retrieval_only':
      return 'Retrieved context'
    case 'no_context':
      return 'No context found'
    default:
      return 'Retrieved answer'
  }
}

function App() {
  const [session, setSession] = useState(undefined)
  const [showProfile, setShowProfile] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [settingsView, setSettingsView] = useState('appearance')
  const [theme, setTheme] = useState(() => localStorage.getItem(THEME_STORAGE_KEY) || 'light')
  const [query, setQuery] = useState('')
  const [isSearching, setIsSearching] = useState(false)
  const [conversationTurns, setConversationTurns] = useState([])
  const [activeConversationRecordId, setActiveConversationRecordId] = useState('')
  const [selectedTopicContext, setSelectedTopicContext] = useState(null)
  const [searchMessage, setSearchMessage] = useState('')
  const [pipelineNotice, setPipelineNotice] = useState('')
  const [historyError, setHistoryError] = useState('')
  const [vectorStoreStatus, setVectorStoreStatus] = useState(null)
  const [workspaceSyncStatus, setWorkspaceSyncStatus] = useState(null)
  const [ingestionStatuses, setIngestionStatuses] = useState([])
  const [history, setHistory] = useState([])
  const [activeHistoryId, setActiveHistoryId] = useState('')
  const [isHistoryLoading, setIsHistoryLoading] = useState(false)

  const graphToken = session?.provider_token || ''
  const supabaseToken = session?.access_token || ''
  const backendToken = graphToken || supabaseToken
  const user = session?.user
  const userId = user?.id

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem(THEME_STORAGE_KEY, theme)
  }, [theme])

  const userProfile = useMemo(() => {
    const metadata = user?.user_metadata || {}
    const name =
      metadata.full_name ||
      metadata.name ||
      metadata.preferred_username ||
      user?.email ||
      'MeetVault user'

    return {
      name,
      email: user?.email || 'No email available',
      provider: 'Azure OAuth via Supabase',
      tenant: metadata.tid || metadata.tenant_id || 'Azure workspace',
      tokenType: graphToken ? 'Microsoft Graph provider token' : 'Supabase access token',
      token: backendToken || 'No token',
    }
  }, [backendToken, graphToken, user])

  const loadVectorStoreStatus = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/vector-store/status`)
      if (!response.ok) {
        throw new Error(await readErrorMessage(response, 'Unable to read ChromaDB status.'))
      }

      const payload = await response.json()
      setVectorStoreStatus(payload)
      return payload
    } catch (error) {
      console.error(error)
      return null
    }
  }, [])

  const loadIngestionStatuses = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/ingestion/status`)
      if (!response.ok) {
        throw new Error(await readErrorMessage(response, 'Unable to read ingestion status.'))
      }

      const payload = await response.json()
      setIngestionStatuses(Array.isArray(payload) ? payload : [])
      return payload
    } catch (error) {
      console.error(error)
      return []
    }
  }, [])

  const loadWorkspaceSyncStatus = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/ingestion/workspace-status`)
      if (!response.ok) {
        throw new Error(await readErrorMessage(response, 'Unable to read workspace sync status.'))
      }

      const payload = await response.json()
      setWorkspaceSyncStatus(payload)
      return payload
    } catch (error) {
      console.error(error)
      return null
    }
  }, [])

  const startGraphWorkspaceSync = useCallback(async () => {
    if (!graphToken) {
      setPipelineNotice('Microsoft Graph token is not available. Sign out and sign in again before starting workspace sync.')
      return null
    }

    try {
      const response = await fetch(`${API_BASE_URL}/ingestion/workspace-sync?limit=20`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${graphToken}`,
        },
      })

      if (!response.ok) {
        throw new Error(await readErrorMessage(response, 'Graph workspace sync could not start.'))
      }

      const payload = await response.json()
      setWorkspaceSyncStatus(payload)
      setPipelineNotice('Microsoft Graph workspace sync started. Large recordings can take several minutes while MeetVault downloads, transcribes, chunks, embeds, and stores them.')
      await Promise.all([loadVectorStoreStatus(), loadWorkspaceSyncStatus(), loadIngestionStatuses()])
      return payload
    } catch (error) {
      console.error(error)
      setPipelineNotice(error.message || 'Graph workspace sync could not start.')
      return null
    }
  }, [graphToken, loadIngestionStatuses, loadVectorStoreStatus, loadWorkspaceSyncStatus])

  const loadHistory = useCallback(async () => {
    if (!userId) {
      setHistory([])
      setActiveHistoryId('')
      return
    }

    setIsHistoryLoading(true)
    setHistoryError('')

    const { data, error } = await supabase
      .from(CHAT_HISTORY_TABLE)
      .select('id,title,preview,query,meeting_id,meeting_title,created_at')
      .eq('user_id', userId)
      .order('created_at', { ascending: false })

    if (error) {
      console.error('History load failed:', error)
      setHistoryError('History could not be loaded.')
      setHistory([])
      setActiveHistoryId('')
    } else {
      const rows = data.map(mapHistoryRow)
      setHistory(rows)
      setActiveHistoryId((currentId) =>
        rows.some((item) => item.id === currentId) ? currentId : rows[0]?.id || '',
      )
    }

    setIsHistoryLoading(false)
  }, [userId])

  const sortedIngestionStatuses = useMemo(
    () =>
      [...ingestionStatuses].sort((left, right) => {
        const leftTime = Date.parse(left.updated_at || '') || 0
        const rightTime = Date.parse(right.updated_at || '') || 0
        return rightTime - leftTime
      }),
    [ingestionStatuses],
  )

  const latestEmbedded = sortedIngestionStatuses.find((status) => status.status === 'EMBEDDED')
  const latestActiveIngestion = sortedIngestionStatuses.find((status) =>
    ['QUEUED', 'PROCESSING'].includes(status.status),
  )
  const latestFailedIngestion = sortedIngestionStatuses.find((status) => status.status === 'FAILED')
  const latestSkippedIngestion = sortedIngestionStatuses.find((status) => status.status === 'SKIPPED')
  const formatStatusDetail = (detail) => {
    if (!detail) return ''
    if (typeof detail === 'string') return detail
    return detail.message || detail.graph_message || detail.error || JSON.stringify(detail)
  }
  const graphSyncSummary = useMemo(() => {
    if (!workspaceSyncStatus?.status || workspaceSyncStatus.status === 'IDLE') {
      return 'Graph workspace sync is idle. Sign in or click Sync workspace now to check recent meetings.'
    }

    if (['QUEUED', 'RUNNING'].includes(workspaceSyncStatus.status)) {
      return workspaceSyncStatus.message ||
        'Graph workspace sync is running. Long recordings may take several minutes to download, transcribe, embed, and store.'
    }

    if (workspaceSyncStatus.status === 'COMPLETED') {
      const embedded = workspaceSyncStatus.embedded ?? 0
      const alreadyIndexed = workspaceSyncStatus.already_indexed ?? 0
      const ignored = workspaceSyncStatus.ignored ?? 0
      const failed = workspaceSyncStatus.failed ?? 0
      return workspaceSyncStatus.message ||
        `Graph workspace sync finished. Embedded ${embedded} new item${embedded === 1 ? '' : 's'}, reused ${alreadyIndexed} already indexed item${alreadyIndexed === 1 ? '' : 's'}, ignored ${ignored} non-transcribable item${ignored === 1 ? '' : 's'}, failed ${failed}.`
    }

    if (workspaceSyncStatus.status === 'FAILED') {
      const detail =
        typeof workspaceSyncStatus.error_detail === 'string'
          ? workspaceSyncStatus.error_detail
          : workspaceSyncStatus.error_detail?.message ||
            workspaceSyncStatus.error_detail?.graph_message ||
            ''
      return `Graph workspace sync failed${detail ? `: ${detail}` : '.'}`
    }

    return workspaceSyncStatus.message || `Graph workspace sync status: ${workspaceSyncStatus.status}`
  }, [workspaceSyncStatus])

  const indexedCount = vectorStoreStatus?.indexed_document_count ?? 0
  const totalCount = vectorStoreStatus?.document_count ?? 0
  const sourceCountEntries = Object.entries(vectorStoreStatus?.source_counts || {}).sort(
    (left, right) => right[1] - left[1],
  )
  const hasConversation = conversationTurns.length > 0
  const embeddedTopicCards = useMemo(() => {
    const topics = []
    const seen = new Set()
    const addTopic = (title, meetingId = null) => {
      const normalized = (title || '').trim()
      if (!normalized || normalized.length < 3) return

      const key = normalized.toLowerCase()
      if (seen.has(key)) return

      seen.add(key)
      topics.push({
        id: meetingId || key,
        title: normalized.replace(/\.(mp4|webm|m4a|mp3|wav|vtt|txt)$/i, ''),
        meetingId,
      })
    }

    sortedIngestionStatuses
      .filter((status) => status.status === 'EMBEDDED')
      .forEach((status) => addTopic(status.meeting_title || status.original_filename, status.meeting_id))

    ;(vectorStoreStatus?.sample_chunks || []).forEach((chunk) =>
      addTopic(chunk.meeting_title, chunk.meeting_id),
    )

    FALLBACK_TOPIC_CARDS.forEach((title) => addTopic(title))

    return topics.slice(0, 8)
  }, [sortedIngestionStatuses, vectorStoreStatus])
  const pipelineSummary = useMemo(() => {
    const collectionName = vectorStoreStatus?.collection_name || 'meetvault_transcripts'
    const latestChunkCount =
      latestEmbedded?.stored_chunks || latestEmbedded?.chunks || indexedCount || 0

    if (latestActiveIngestion) {
      return `Indexing ${latestActiveIngestion.meeting_title || latestActiveIngestion.original_filename || latestActiveIngestion.meeting_id} right now. ${indexedCount} chunk${indexedCount === 1 ? '' : 's'} already live in ${collectionName}.`
    }

    if (latestFailedIngestion) {
      const detail = formatStatusDetail(latestFailedIngestion.error_detail)
      return `Last failed asset: ${latestFailedIngestion.meeting_title || latestFailedIngestion.meeting_id}${detail ? ` - ${detail}` : ''}`
    }

    if (latestEmbedded) {
      return `Last indexed ${latestEmbedded.meeting_title || latestEmbedded.original_filename || latestEmbedded.meeting_id} with ${latestChunkCount} chunk${latestChunkCount === 1 ? '' : 's'}. ${indexedCount} chunk${indexedCount === 1 ? '' : 's'} are live in ${collectionName}.`
    }

    if (latestSkippedIngestion) {
      const ignored = workspaceSyncStatus?.ignored ?? 0
      const alreadyIndexed = workspaceSyncStatus?.already_indexed ?? 0
      if (ignored || alreadyIndexed) {
        return `No new embeddings were needed in the latest sync. ${indexedCount} chunk${indexedCount === 1 ? '' : 's'} remain live in ${collectionName}; ${alreadyIndexed} already indexed item${alreadyIndexed === 1 ? '' : 's'} reused and ${ignored} non-transcribable item${ignored === 1 ? '' : 's'} ignored.`
      }

      const detail =
        formatStatusDetail(latestSkippedIngestion.error_detail) ||
        latestSkippedIngestion.message ||
        latestSkippedIngestion.source_type ||
        ''
      return `Last skipped asset: ${latestSkippedIngestion.meeting_title || latestSkippedIngestion.meeting_id}${detail ? ` - ${detail}` : ''}`
    }

    return `Graph sync runs after sign-in using your admin-consented Microsoft token. ${indexedCount} chunk${indexedCount === 1 ? '' : 's'} are currently indexed in ${collectionName}.`
  }, [indexedCount, latestActiveIngestion, latestEmbedded, latestFailedIngestion, latestSkippedIngestion, vectorStoreStatus, workspaceSyncStatus])

  useEffect(() => {
    const fetchSession = async () => {
      const { data, error } = await supabase.auth.getSession()

      if (error) {
        console.error(error)
      }

      setSession(data.session)
    }

    fetchSession()

    const { data: authListener } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      if (!nextSession) {
        setConversationTurns([])
        setActiveConversationRecordId('')
        setSearchMessage('')
        setPipelineNotice('')
        setHistoryError('')
        setVectorStoreStatus(null)
        setWorkspaceSyncStatus(null)
        setIngestionStatuses([])
        setHistory([])
        setActiveHistoryId('')
      }

      setSession(nextSession)
    })

    return () => {
      authListener.subscription.unsubscribe()
    }
  }, [])

  useEffect(() => {
    if (!userId) return

    const bootstrap = async () => {
      await Promise.all([
        loadVectorStoreStatus(),
        loadWorkspaceSyncStatus(),
        loadIngestionStatuses(),
        loadHistory(),
      ])
    }

    bootstrap()
  }, [loadHistory, loadIngestionStatuses, loadVectorStoreStatus, loadWorkspaceSyncStatus, userId])

  useEffect(() => {
    if (!userId || !graphToken) return

    const syncKey = `meetvault-graph-sync-${userId}`
    if (sessionStorage.getItem(syncKey)) return

    sessionStorage.setItem(syncKey, 'started')
    const syncTimer = window.setTimeout(() => {
      startGraphWorkspaceSync()
    }, 0)

    return () => window.clearTimeout(syncTimer)
  }, [graphToken, startGraphWorkspaceSync, userId])

  useEffect(() => {
    if (!userId) return undefined

    const intervalId = window.setInterval(() => {
      loadVectorStoreStatus()
      loadWorkspaceSyncStatus()
      loadIngestionStatuses()
    }, STATUS_POLL_MS)

    return () => window.clearInterval(intervalId)
  }, [loadIngestionStatuses, loadVectorStoreStatus, loadWorkspaceSyncStatus, userId])

  const handleAuth = async () => {
    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'azure',
      options: {
        scopes: REQUIRED_LOGIN_SCOPES,
      },
    })

    if (error) {
      console.error(error)
    }
  }

  const handleSignOut = async () => {
    await supabase.auth.signOut()
    setShowProfile(false)
  }

  const executeSearch = useCallback(
    async (rawQuery, { persistHistory = true, historyId = '', meetingId = null } = {}) => {
      const trimmedQuery = rawQuery.trim()
      if (!trimmedQuery) return

      setIsSearching(true)
      setSearchMessage('')
      setPipelineNotice('')
      setHistoryError('')

      try {
        const response = await fetch(`${API_BASE_URL}/rag/query`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            query: trimmedQuery,
            meeting_id: meetingId,
          }),
        })

        if (!response.ok) {
          throw new Error(await readErrorMessage(response, 'RAG query failed.'))
        }

        const payload = await response.json()
        const results = (payload.sources || []).map((source, index) => ({
          chunk_id: source.chunk_id || `source-${index + 1}`,
          text: source.text || '',
          metadata: source.metadata || {},
          distance: typeof source.distance === 'number' ? source.distance : null,
        }))
        const answer =
          typeof payload.answer === 'string' && payload.answer.trim()
            ? {
                mode: payload.answer_mode || 'rag_answer',
                text: payload.answer,
              }
            : null

        setQuery(trimmedQuery)
        setConversationTurns((previous) => [
          ...previous,
          {
            id: `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
            query: trimmedQuery,
            answer,
            sourceCount: results.length,
            meetingTitle: results[0]?.metadata?.meeting_title || '',
          },
        ])
        setQuery('')
        setSearchMessage(
          results.length
            ? `Generated an answer from ${results.length} grounded chunk${results.length === 1 ? '' : 's'} in ChromaDB.`
            : 'No matching transcript chunk is indexed yet. Run Graph workspace sync and wait for recordings to finish indexing.',
        )
        if (payload.llm_error) {
          setPipelineNotice(
            'The answer model is unavailable right now. Start Ollama/Qwen to generate a full RAG answer.',
          )
        }

        if (!persistHistory || !userId) {
          setActiveHistoryId(historyId || '')
          return
        }

        const preview = payload.answer_mode === 'rag_answer' ? 'RAG answer' : 'Workspace retrieval'
        const meeting_id = results[0]?.metadata?.meeting_id || null
        const meeting_title = results[0]?.metadata?.meeting_title || null

        if (activeConversationRecordId) {
          const { data, error } = await supabase
            .from(CHAT_HISTORY_TABLE)
            .update({
              preview,
              query: trimmedQuery,
              meeting_id,
              meeting_title,
            })
            .eq('id', activeConversationRecordId)
            .select('id,title,preview,query,meeting_id,meeting_title,created_at')
            .single()

          if (error) {
            console.error('History update failed:', error)
            setHistoryError('Search history could not be updated in Supabase.')
            return
          }

          const updatedHistoryItem = mapHistoryRow(data)
          setHistory((items) =>
            [updatedHistoryItem, ...items.filter((item) => item.id !== updatedHistoryItem.id)],
          )
          setActiveHistoryId(updatedHistoryItem.id)
          return
        }

        const { data, error } = await supabase
          .from(CHAT_HISTORY_TABLE)
          .insert({
            user_id: userId,
            title: trimmedQuery,
            preview,
            query: trimmedQuery,
            meeting_id,
            meeting_title,
          })
          .select('id,title,preview,query,meeting_id,meeting_title,created_at')
          .single()

        if (error) {
          console.error('History insert failed:', error)
          setHistoryError('This chat is only saved locally until history storage is ready.')
          return
        }

        const savedHistoryItem = mapHistoryRow(data)
        setHistory((items) => [savedHistoryItem, ...items])
        setActiveHistoryId(savedHistoryItem.id)
        setActiveConversationRecordId(savedHistoryItem.id)
      } catch (error) {
        console.error(error)
        setSearchMessage(error.message || 'Search request failed.')
      } finally {
        setIsSearching(false)
        setQuery('')
      }
    },
    [activeConversationRecordId, userId],
  )

  const handleSearch = (event) => {
    event.preventDefault()
    executeSearch(query, {
      meetingId: selectedTopicContext?.meetingId || null,
    })
  }

  const handleTopicSelect = (topic) => {
    setSelectedTopicContext(topic)
    setSearchMessage(`Context selected: ${topic.title}`)
  }

  const handleReset = () => {
    setQuery('')
    setConversationTurns([])
    setActiveConversationRecordId('')
    setActiveHistoryId('')
    setSelectedTopicContext(null)
    setSearchMessage('')
    setPipelineNotice('')
    setHistoryError('')
  }

  const handleHistorySelect = (item) => {
    setActiveHistoryId(item.id)
    setActiveConversationRecordId(item.id)
    setSelectedTopicContext(
      item.meetingId
        ? {
            id: item.meetingId,
            title: item.meetingTitle || item.title,
            meetingId: item.meetingId,
          }
        : null,
    )
    setConversationTurns([
      {
        id: item.id,
        query: item.query || item.title,
        answer: item.preview
          ? {
              mode: 'history',
              text: item.preview,
            }
          : null,
        sourceCount: 0,
        meetingTitle: item.meetingTitle || '',
      },
    ])
    setQuery('')
    setSearchMessage('')
  }

  const handleStartGraphSync = () => {
    startGraphWorkspaceSync()
  }

  if (session === undefined) {
    return (
      <main className="login-gate">
        <section className="login-card" aria-label="Loading MeetVault">
          <div className="brand-lockup">
            <div className="brand-mark">M</div>
            <div>
              <p className="eyebrow">MeetVault AI</p>
              <h1>Checking your session</h1>
            </div>
          </div>
          <p>Loading authentication state...</p>
        </section>
      </main>
    )
  }

  if (!session) {
    return (
      <main className="login-gate">
        <section className="login-card" aria-labelledby="login-title">
          <div className="brand-lockup">
            <div className="brand-mark">M</div>
            <div>
              <p className="eyebrow">MeetVault AI</p>
              <h1>Automatic meeting indexing</h1>
            </div>
          </div>

          <div className="login-copy">
            <p className="eyebrow">Required authentication</p>
            <h2 id="login-title">Sign in with Microsoft to search your synced recordings</h2>
            <p>
              MeetVault starts Microsoft Graph workspace sync after sign-in, fetches accessible
              SharePoint and OneDrive recordings, transcribes them, and stores embeddings in
              ChromaDB.
            </p>
          </div>

          <button className="auth-button full-width" type="button" onClick={handleAuth}>
            Continue with Microsoft
          </button>
        </section>
      </main>
    )
  }

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Search history">
        <div className="brand-lockup compact">
          <div className="brand-mark">M</div>
          <div>
            <p className="eyebrow">MeetVault AI</p>
            <h1>Workspace search</h1>
          </div>
        </div>

        <button className="subtle-button full-width" type="button" onClick={handleReset}>
          New chat
        </button>

        <div className="sidebar-section">
          <p className="eyebrow">History</p>
          <div className="history-list">
            {isHistoryLoading ? <p className="sidebar-note">Loading history...</p> : null}
            {!isHistoryLoading && history.length === 0 ? (
              <p className="sidebar-note">Saved searches will appear here.</p>
            ) : null}
            {history.map((item) => (
              <button
                className={`history-item ${item.id === activeHistoryId ? 'active' : ''}`}
                key={item.id}
                type="button"
                onClick={() => handleHistorySelect(item)}
              >
                <span>{item.title}</span>
                <small>{item.preview || formatDateTime(item.createdAt)}</small>
              </button>
            ))}
          </div>
        </div>

        <button
          className="subtle-button full-width settings-trigger"
          type="button"
          onClick={() => setShowSettings(true)}
        >
          Settings
        </button>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <div className="topbar-text">
            <p className="eyebrow">Search stored meeting knowledge</p>
            <h2>{hasConversation ? 'Ask follow-up questions about your recordings' : 'Ask about your indexed recordings'}</h2>
          </div>

          <button
            className="profile-button"
            type="button"
            onClick={() => setShowProfile((value) => !value)}
            aria-label="User profile"
            title="User profile"
          >
            <span className="presence-dot" aria-hidden="true"></span>
            <span>{userProfile.name.slice(0, 2).toUpperCase()}</span>
          </button>

          {showProfile ? (
            <section className="profile-popover" aria-label="User credentials">
              <div className="profile-heading">
                <div className="profile-avatar">{userProfile.name.slice(0, 2).toUpperCase()}</div>
                <div>
                  <h3>{userProfile.name}</h3>
                  <p>{userProfile.email}</p>
                </div>
              </div>

              <dl className="credential-list">
                <div>
                  <dt>Provider</dt>
                  <dd>{userProfile.provider}</dd>
                </div>
                <div>
                  <dt>Tenant</dt>
                  <dd>{userProfile.tenant}</dd>
                </div>
                <div>
                  <dt>Token type</dt>
                  <dd>{userProfile.tokenType}</dd>
                </div>
                <div className="token-row">
                  <dt>Access token</dt>
                  <dd>
                    <textarea
                      className="token-field"
                      value={userProfile.token}
                      readOnly
                      rows={6}
                      aria-label="Complete access token"
                    />
                  </dd>
                </div>
              </dl>

              <button className="signout-button" type="button" onClick={handleSignOut}>
                Sign out
              </button>
            </section>
          ) : null}
        </header>

        <main className={`main-panel ${hasConversation ? 'chat-mode' : ''}`}>
          <section className={`search-stage ${hasConversation ? 'has-results' : ''}`}>
            {!hasConversation ? (
              <section className="graph-sync-card" aria-label="Microsoft Graph workspace sync">
                <div>
                  <p className="eyebrow">Workspace sync</p>
                  <h3>Microsoft Graph and SharePoint automation</h3>
                  <p className="graph-sync-copy">
                    MeetVault checks accessible SharePoint and OneDrive recording files only.
                    Large videos may take several minutes while transcription and embedding run in
                    the backend.
                  </p>
                </div>

                <div className="graph-sync-actions">
                  <button className="subtle-button" type="button" onClick={handleStartGraphSync}>
                    Sync workspace now
                  </button>
                </div>

                <div className="graph-sync-box">
                  <p className="eyebrow">Current sync</p>
                  <code>{graphSyncSummary}</code>
                </div>
              </section>
            ) : null}

            {!hasConversation ? (
              <form className="search-form" onSubmit={handleSearch}>
                <textarea
                  aria-label="Search indexed meetings"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder={
                    selectedTopicContext
                      ? `Ask inside ${selectedTopicContext.title}`
                      : 'Ask for summaries, decisions, blockers, or any moment from the recording'
                  }
                  rows={2}
                />
                <button className="send-button" type="submit" disabled={isSearching}>
                  {isSearching ? 'Searching' : 'Search'}
                </button>
              </form>
            ) : null}

            {!hasConversation && !selectedTopicContext ? (
              <section className="topic-grid" aria-label="Indexed topic shortcuts">
                {embeddedTopicCards.map((topic) => (
                  <button
                    className="topic-chip"
                    key={topic.id}
                    type="button"
                    onClick={() => handleTopicSelect(topic)}
                  >
                    {topic.title}
                  </button>
                ))}
              </section>
            ) : null}

            {!hasConversation && selectedTopicContext ? (
              <div className="selected-topic-pill" aria-live="polite">
                <span>Context</span>
                <strong>{selectedTopicContext.title}</strong>
                <button type="button" onClick={() => setSelectedTopicContext(null)}>
                  Clear
                </button>
              </div>
            ) : null}

            <div className={`status-stack ${hasConversation ? 'compact' : ''}`}>
              <p>{pipelineSummary}</p>
              <p>{graphSyncSummary}</p>
              <p>
                Storage: <strong>{vectorStoreStatus?.db_path || './chroma_db'}</strong> /{' '}
                <strong>{vectorStoreStatus?.collection_name || 'meetvault_transcripts'}</strong>
                {` | ${indexedCount} live / ${totalCount} total chunks`}
              </p>
              {sourceCountEntries.length ? (
                <p>
                  Sources:{' '}
                  {sourceCountEntries.map(([sourceType, count]) => `${sourceType} (${count})`).join(', ')}
                </p>
              ) : null}
              {pipelineNotice ? <p className="feedback">{pipelineNotice}</p> : null}
              {historyError ? <p className="feedback error">{historyError}</p> : null}
              {searchMessage ? <p className="feedback">{searchMessage}</p> : null}
            </div>
          </section>

          {hasConversation ? (
            <section className="conversation-panel" aria-label="Conversation">
              {conversationTurns.map((turn) => (
                <div className="turn-stack" key={turn.id}>
                  <article className="message-row user">
                    <div className="message-bubble user">
                      <p>{turn.query}</p>
                    </div>
                  </article>

                  {turn.answer ? (
                    <article className="message-row assistant">
                      <div className="message-bubble assistant">
                        <p className="eyebrow">{answerEyebrowForMode(turn.answer.mode)}</p>
                        <div className="answer-body">
                          {turn.answer.text.split('\n').map((line) => (
                            <p key={`${turn.id}-${line}`}>{line}</p>
                          ))}
                        </div>
                        {turn.sourceCount ? (
                          <p className="answer-footnote">
                            Grounded by {turn.sourceCount} retrieved chunk{turn.sourceCount === 1 ? '' : 's'}
                            {turn.meetingTitle ? ` from ${turn.meetingTitle}` : ''}.
                          </p>
                        ) : null}
                      </div>
                    </article>
                  ) : null}
                </div>
              ))}
            </section>
          ) : (
            <section className="empty-state" aria-label="Indexing status">
              <p>
                Search results will appear here once Graph sync fetches a SharePoint recording or
                transcript and the backend finishes indexing it into ChromaDB.
              </p>
            </section>
          )}

          {hasConversation ? (
            <form className="search-form conversation-composer" onSubmit={handleSearch}>
              <textarea
                aria-label="Search indexed meetings"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Ask a follow-up about the indexed recordings"
                rows={2}
              />
              <button className="send-button" type="submit" disabled={isSearching}>
                {isSearching ? 'Searching' : 'Send'}
              </button>
            </form>
          ) : null}
        </main>
      </div>

      {showSettings ? (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setShowSettings(false)}>
          <section
            className="settings-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="settings-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="modal-header">
              <div>
                <p className="eyebrow">Workspace controls</p>
                <h3 id="settings-title">Settings</h3>
              </div>
              <button
                className="subtle-button"
                type="button"
                onClick={() => setShowSettings(false)}
              >
                Close
              </button>
            </div>

            <div className="settings-tabs" role="tablist" aria-label="Settings sections">
              <button
                className={settingsView === 'appearance' ? 'active' : ''}
                type="button"
                onClick={() => setSettingsView('appearance')}
              >
                Appearance
              </button>
              <button
                className={settingsView === 'mcp' ? 'active' : ''}
                type="button"
                onClick={() => setSettingsView('mcp')}
              >
                MCP
              </button>
            </div>

            {settingsView === 'appearance' ? (
              <div className="appearance-panel">
                <button
                  className={theme === 'light' ? 'theme-option active' : 'theme-option'}
                  type="button"
                  onClick={() => setTheme('light')}
                >
                  <span>Light</span>
                  <small>Default workspace mode</small>
                </button>
                <button
                  className={theme === 'dark' ? 'theme-option active' : 'theme-option'}
                  type="button"
                  onClick={() => setTheme('dark')}
                >
                  <span>Dark</span>
                  <small>Low-light review mode</small>
                </button>
              </div>
            ) : (
              <div className="mcp-settings-container">
                <div className="server-list" style={{ marginBottom: '24px' }}>
                  {mcpServers.map((server) => (
                    <article className="server-row" key={server.id}>
                      <div>
                        <h4>{server.name}</h4>
                        <p>{server.description}</p>
                      </div>
                      <span className="result-badge">{server.status}</span>
                    </article>
                  ))}
                </div>
                <MCPPanel token={backendToken} userEmail={user?.email} />
              </div>
            )}
          </section>
        </div>
      ) : null}
    </div>
  )
}

export default App
