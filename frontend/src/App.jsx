import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { supabase } from './lib/supabase'
import MCPPanel from './components/mcp/MCPPanel'
import FormatPreview from './components/FormatPreview'
import MeetingsGridView from './views/MeetingsGridView'
import MeetingChatView from './views/MeetingChatView'
import WorkspaceLanding from './views/WorkspaceLanding'
import OnboardingView from './views/OnboardingView'
import { publishMcpOAuthEvent, subscribeMcpOAuthEvents } from './utils/mcpOAuthSync'
import { mcpService } from './services/mcpService'
import {
  DEFAULT_OUTPUT_FORMAT,
  DEFAULT_RAW_VIEW_MODE,
  OUTPUT_FORMATS,
  RAW_VIEW_MODES,
  getOutputFormatMeta,
  isValidOutputFormat,
  isValidRawViewMode,
  normalizeOutputFormat,
  normalizeRawViewMode,
  outputPreferenceStorageKey,
  rawViewStorageKey,
} from './utils/outputPreferences'
import {
  CHAT_HISTORY_TABLE,
  CHAT_SELECT_FIELDS,
  ingestionStatusUnchanged,
  isChatPreparing,
  isChatReady,
  mapMeetingChatRow,
  mapRagCitationsForUi,
  mapWorkspaceChatRow,
  MEETING_CHAT_LEGACY_QUERY,
  sanitizeChatPatch,
} from './utils/meetingChat'
import './App.css'

// In dev, use Vite proxy (/api → backend) so the API stays reachable during long syncs.
const API_BASE_URL = import.meta.env.DEV
  ? '/api'
  : import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const INGESTION_POLL_MS = 2500
const AUTO_SYNC_STATUS_MS = 5000
const AUTO_SYNC_ENABLED = import.meta.env.VITE_MEETVAULT_AUTO_SYNC_ENABLED === 'true'
const REQUIRED_LOGIN_SCOPES =
  'openid profile email offline_access User.Read Calendars.Read Files.Read OnlineMeetings.Read OnlineMeetingTranscript.Read.All'
const THEME_STORAGE_KEY = 'meetvault-theme'
const GRAPH_TOKEN_STORAGE_KEY = 'meetvault-graph-token'
const SUMMARY_PROMPT =
  'Provide a concise executive summary of this meeting: key topics, decisions, action items, and open questions.'


const titleFromQuery = (value) => {
  const words = (value || '').trim().split(/\s+/).filter(Boolean)
  if (words.length === 0) return 'Workspace chat'
  return words.slice(0, 6).join(' ')
}
const normalizeChatTitle = (value) =>
  String(value || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()

const chatTitleMatchesIndex = (chatTitle, indexedTitle) => {
  const left = normalizeChatTitle(chatTitle)
  const right = normalizeChatTitle(indexedTitle)
  if (!left || !right) return true
  if (left === right || left.includes(right) || right.includes(left)) return true

  const leftWords = left.split(/\s+/).filter((word) => word.length > 2)
  const rightWords = new Set(right.split(/\s+/).filter((word) => word.length > 2))
  if (!leftWords.length || !rightWords.size) return false

  const overlap = leftWords.filter((word) => rightWords.has(word)).length
  return overlap >= Math.min(2, leftWords.length)
}

const isStaleMeetingChat = (row, ingestion) => {
  if (!row || ingestion?.status === 'EMBEDDED') {
    if (ingestion?.status === 'EMBEDDED') {
      const indexedTitle = ingestion.indexed_meeting_title
      const chatTitle = row.title || row.meetingTitle
      return indexedTitle && !chatTitleMatchesIndex(chatTitle, indexedTitle)
    }
    return false
  }

  if (row.status === 'ready' && (row.messages || []).length > 0) {
    return true
  }

  return false
}
const mcpServers = [
  {
    id: 'graph',
    name: 'Microsoft Graph',
    status: 'Meeting catalog',
    description: 'Discovers Teams calendar meetings and recording assets for manual preparation.',
  },
  {
    id: 'rag',
    name: 'RAG Layer',
    status: 'Grounded answers',
    description: 'Queries ChromaDB and composes grounded answers from indexed transcript chunks.',
  },
]

let currentSupabaseToken = ''

const bearerHeaders = (token, extraHeaders = {}) => {
  const headers = { ...extraHeaders }
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  if (currentSupabaseToken) {
    headers['X-Supabase-Token'] = currentSupabaseToken
  }
  return headers
}

const readErrorMessage = async (response, fallbackMessage) => {
  try {
    const raw = await response.text()
    if (!raw) return fallbackMessage

    try {
      const parsed = JSON.parse(raw)
      if (typeof parsed.detail === 'string') return parsed.detail
      if (typeof parsed.detail === 'object' && parsed.detail) {
        if (typeof parsed.detail.graph_message === 'string') return parsed.detail.graph_message
        if (typeof parsed.detail.message === 'string') return parsed.detail.message
      }
      if (typeof parsed.sync_error === 'string') return parsed.sync_error
      if (typeof parsed.message === 'string') return parsed.message
    } catch {
      // keep raw
    }

    return raw
  } catch {
    return fallbackMessage
  }
}

const formatDateTime = (value) => {
  if (!value) return ''
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString()
}

const catalogSummaryForMeeting = (meeting, isIndexed) => {
  if (isIndexed) {
    return 'Indexed and ready for chat.'
  }
  if (['QUEUED', 'PROCESSING'].includes(meeting?.ingestion_status)) {
    return 'Preparation is running. Open this card to watch progress.'
  }
  if (['FAILED', 'NO_TRANSCRIPT'].includes(meeting?.ingestion_status)) {
    return 'Preparation failed earlier. Open this card to try again.'
  }
  return 'Recording available. Open this card to prepare transcript embeddings.'
}

const patchCatalogMeetingIndexed = (meetings, meetingId, isIndexed) =>
  meetings.map((meeting) =>
    meeting.id === meetingId
      ? {
          ...meeting,
          isIndexed,
          summary: catalogSummaryForMeeting(meeting, isIndexed),
          ingestionStatus: isIndexed ? 'EMBEDDED' : 'NOT_STARTED',
        }
      : meeting,
  )

const normalizeCatalogMeeting = (meeting) => {
  const source = meeting.content_source || 'teams'
  const isOnedrive = source === 'onedrive' || source === 'shared_onedrive'

  return {
    id: meeting.event_id || meeting.meeting_id,
    title: meeting.title || 'Untitled meeting',
    team: meeting.organizer || (isOnedrive ? 'OneDrive' : 'Microsoft Teams'),
    time: formatDateTime(meeting.start_time) || 'Recent',
    startTimeIso: meeting.start_time || null,
    summary: catalogSummaryForMeeting(meeting, Boolean(meeting.is_indexed)),
    tags: isOnedrive
      ? [meeting.organizer === 'Shared with me' ? 'Shared' : 'OneDrive', 'Video']
      : ['Teams', 'Recording'],
    isIndexed: Boolean(meeting.is_indexed),
    ingestionStatus: meeting.ingestion_status || 'NOT_STARTED',
    hasRecording: Boolean(meeting.has_recording),
  }
}

function App() {
  const [session, setSession] = useState(undefined)
  const [showProfile, setShowProfile] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [showOnboarding, setShowOnboarding] = useState(false)
  const [settingsView, setSettingsView] = useState('appearance')
  const [theme, setTheme] = useState(() => localStorage.getItem(THEME_STORAGE_KEY) || 'light')
  const [outputPreference, setOutputPreference] = useState('')
  const [previewFormat, setPreviewFormat] = useState(DEFAULT_OUTPUT_FORMAT)
  const [rawViewMode, setRawViewMode] = useState(DEFAULT_RAW_VIEW_MODE)
  const [hasPreferenceLoaded, setHasPreferenceLoaded] = useState(false)
  const [isPreferenceLoading, setIsPreferenceLoading] = useState(false)
  const [preferenceSaving, setPreferenceSaving] = useState(false)
  const [preferenceError, setPreferenceError] = useState('')

  const [activeNav, setActiveNav] = useState('workspace')
  const [workspaceChats, setWorkspaceChats] = useState([])
  const [activeWorkspaceChatId, setActiveWorkspaceChatId] = useState('')
  const [meetingChats, setMeetingChats] = useState([])
  const [activeChatId, setActiveChatId] = useState('')
  const [isHistoryLoading, setIsHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState('')

  const [catalogMeetings, setCatalogMeetings] = useState([])
  const [catalogSyncedAt, setCatalogSyncedAt] = useState(null)
  const [catalogLoading, setCatalogLoading] = useState(false)
  const [catalogSyncing, setCatalogSyncing] = useState(false)
  const [catalogError, setCatalogError] = useState('')

  const [ingestionByMeeting, setIngestionByMeeting] = useState({})
  const summaryRequestedRef = useRef(new Set())
  const summarySkippedRef = useRef(new Set())
  const workspaceChatsRef = useRef([])
  const activeChatIdRef = useRef('')
  const meetingChatsRef = useRef([])
  const ingestionByMeetingRef = useRef({})
  const graphTokenRef = useRef('')
  const pollIngestionRef = useRef(async () => {})
  const catalogSyncInFlightRef = useRef(false)
  const catalogBootstrapDoneRef = useRef(false)
  const syncCatalogRef = useRef(null)
  const loadMeetingChatsRef = useRef(null)
  const lastBackendWarnAtRef = useRef(0)
  const autoSyncRegisteredTokenRef = useRef('')

  const [query, setQuery] = useState('')
  const [searchingMeetingChatId, setSearchingMeetingChatId] = useState(null)
  const [searchingWorkspaceChatId, setSearchingWorkspaceChatId] = useState(null)
  const [summarizingChatIds, setSummarizingChatIds] = useState([])
  const [isDeletingChat, setIsDeletingChat] = useState(false)
  const [searchMessage, setSearchMessage] = useState('')
  const [pipelineNotice, setPipelineNotice] = useState('')
  const mcpAutoConnectRef = useRef(false)
  const [autoSyncStatus, setAutoSyncStatus] = useState(null)
  const [autoSyncError, setAutoSyncError] = useState('')

  const graphToken = session?.provider_token || localStorage.getItem(GRAPH_TOKEN_STORAGE_KEY) || ''
  const supabaseToken = session?.access_token || ''
  const backendToken = graphToken || supabaseToken
  const user = session?.user
  const userId = user?.id

  workspaceChatsRef.current = workspaceChats
  meetingChatsRef.current = meetingChats
  ingestionByMeetingRef.current = ingestionByMeeting
  graphTokenRef.current = graphToken
  activeChatIdRef.current = activeChatId

  const activeChat = useMemo(
    () => meetingChats.find((chat) => chat.id === activeChatId) || null,
    [activeChatId, meetingChats],
  )

  const activeWorkspaceChat = useMemo(
    () => workspaceChats.find((chat) => chat.id === activeWorkspaceChatId) || null,
    [activeWorkspaceChatId, workspaceChats],
  )

  const activeIngestion = activeChat?.meetingId
    ? ingestionByMeeting[activeChat.meetingId]
    : null

  const isMeetingChatBusy = useCallback(
    (chatId) =>
      Boolean(chatId) &&
      (searchingMeetingChatId === chatId || summarizingChatIds.includes(chatId)),
    [searchingMeetingChatId, summarizingChatIds],
  )

  const isWorkspaceChatBusy = useCallback(
    (chatId) => Boolean(chatId) && searchingWorkspaceChatId === chatId,
    [searchingWorkspaceChatId],
  )

  const markSummarizingChat = useCallback((chatId, busy) => {
    if (!chatId) return
    setSummarizingChatIds((current) => {
      const isBusy = current.includes(chatId)
      if (busy) {
        return isBusy ? current : [...current, chatId]
      }
      return isBusy ? current.filter((id) => id !== chatId) : current
    })
  }, [])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem(THEME_STORAGE_KEY, theme)
  }, [theme])

  useEffect(() => {
    if (session?.provider_token) {
      localStorage.setItem(GRAPH_TOKEN_STORAGE_KEY, session.provider_token)
      return
    }
    if (!session) {
      localStorage.removeItem(GRAPH_TOKEN_STORAGE_KEY)
    }
  }, [session])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const oauthProviders = ['github', 'slack', 'salesforce', 'notion', 'gmail']
    const returnedProvider = oauthProviders.find((provider) => params.has(`${provider}_connected`))

    if (!returnedProvider) {
      return
    }

    const connected = params.get(`${returnedProvider}_connected`) === 'true'
    const error = params.get('mcp_error') || ''

    try {
      localStorage.setItem(
        'meetvault-mcp-oauth-event',
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
    window.setTimeout(() => {
      try {
        window.close()
      } catch {
        // If the browser blocks auto-close, leave the popup on the final page.
      }
    }, 100)
  }, [])


  useEffect(() => {
    currentSupabaseToken = supabaseToken
  }, [supabaseToken])
  const saveOutputPreference = useCallback(
    async (format) => {
      const nextFormat = isValidOutputFormat(format) ? format : DEFAULT_OUTPUT_FORMAT
      setPreferenceSaving(true)
      setPreferenceError('')
      setOutputPreference(nextFormat)
      setPreviewFormat(nextFormat)

      if (userId) {
        localStorage.setItem(outputPreferenceStorageKey(userId), nextFormat)
      }

      try {
        if (userId) {
          const { error } = await supabase
            .from('user_preferences')
            .upsert(
              {
                user_id: userId,
                output_format: nextFormat,
                raw_view_mode: rawViewMode,
                updated_at: new Date().toISOString(),
              },
              { onConflict: 'user_id' },
            )

          if (error) throw error
        }
      } catch (error) {
        console.error('Output preference save failed:', error)
        setPreferenceError(
          'Saved on this device. Run supabase migrations 005–006 if cloud sync fails.',
        )
      } finally {
        setHasPreferenceLoaded(true)
        setPreferenceSaving(false)
      }
    },
    [rawViewMode, userId],
  )

  const saveRawViewMode = useCallback(
    async (mode) => {
      const nextMode = isValidRawViewMode(mode) ? mode : DEFAULT_RAW_VIEW_MODE
      setPreferenceSaving(true)
      setPreferenceError('')
      setRawViewMode(nextMode)

      if (userId) {
        localStorage.setItem(rawViewStorageKey(userId), nextMode)
      }

      try {
        if (userId && outputPreference) {
          const { error } = await supabase
            .from('user_preferences')
            .upsert(
              {
                user_id: userId,
                output_format: outputPreference,
                raw_view_mode: nextMode,
                updated_at: new Date().toISOString(),
              },
              { onConflict: 'user_id' },
            )

          if (error) throw error
        }
      } catch (error) {
        console.error('Raw view preference save failed:', error)
        setPreferenceError('Raw view saved locally. Run migration 006 for Supabase sync.')
      } finally {
        setPreferenceSaving(false)
      }
    },
    [outputPreference, userId],
  )

  const buildAssistantMessage = useCallback(
    (payload, answerText) => {
      const citations = mapRagCitationsForUi(payload.citations || payload.sources || [])
      return {
        id: `assistant-${crypto.randomUUID()}`,
        role: 'assistant',
        text: answerText,
        mode: payload.answer_mode || 'rag_answer',
        outputFormat: normalizeOutputFormat(payload.output_format || outputPreference),
        rawViewMode,
        sources: citations,
        sourceCount: citations.length,
        createdAt: new Date().toISOString(),
      }
    },
    [outputPreference, rawViewMode],
  )

  useEffect(() => {
    if (!userId) {
      return undefined
    }

    let cancelled = false
    const storageKey = outputPreferenceStorageKey(userId)
    const rawStorageKey = rawViewStorageKey(userId)
    const localFormat = localStorage.getItem(storageKey)
    const localRawView = localStorage.getItem(rawStorageKey)

    const loadPreference = async () => {
      setIsPreferenceLoading(true)
      setHasPreferenceLoaded(false)
      setPreferenceError('')

      try {
        const { data, error } = await supabase
          .from('user_preferences')
          .select('output_format, raw_view_mode')
          .eq('user_id', userId)
          .maybeSingle()

        if (cancelled) return
        if (error) throw error

        if (isValidRawViewMode(data?.raw_view_mode)) {
          setRawViewMode(data.raw_view_mode)
          localStorage.setItem(rawStorageKey, data.raw_view_mode)
        } else if (isValidRawViewMode(localRawView)) {
          setRawViewMode(localRawView)
        }

        if (isValidOutputFormat(data?.output_format)) {
          setOutputPreference(data.output_format)
          setPreviewFormat(data.output_format)
          localStorage.setItem(storageKey, data.output_format)
          return
        }

        if (isValidOutputFormat(localFormat)) {
          setOutputPreference(localFormat)
          setPreviewFormat(localFormat)
          const { error: syncError } = await supabase
            .from('user_preferences')
            .upsert(
              {
                user_id: userId,
                output_format: localFormat,
                raw_view_mode: isValidRawViewMode(localRawView)
                  ? localRawView
                  : DEFAULT_RAW_VIEW_MODE,
                updated_at: new Date().toISOString(),
              },
              { onConflict: 'user_id' },
            )
          if (syncError && !cancelled) {
            setPreferenceError(
              'Preference is saved on this device. Supabase sync is not ready yet.',
            )
          }
          return
        }

        setOutputPreference('')
        setPreviewFormat(DEFAULT_OUTPUT_FORMAT)
      } catch (error) {
        if (cancelled) return
        console.error('Output preference load failed:', error)
        if (isValidOutputFormat(localFormat)) {
          setOutputPreference(localFormat)
          setPreviewFormat(localFormat)
        } else {
          setOutputPreference('')
          setPreviewFormat(DEFAULT_OUTPUT_FORMAT)
        }
        if (isValidRawViewMode(localRawView)) {
          setRawViewMode(localRawView)
        }
        setPreferenceError(
          'Preference is stored locally until Supabase migrations 005–006 are applied.',
        )
      } finally {
        if (!cancelled) {
          setHasPreferenceLoaded(true)
          setIsPreferenceLoading(false)
        }
      }
    }

    void loadPreference()

    return () => {
      cancelled = true
    }
  }, [userId])

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
      token: graphToken || session?.access_token || 'No token',
    }
  }, [graphToken, session?.access_token, user])

  const loadWorkspaceChats = useCallback(async () => {
    if (!userId) {
      setWorkspaceChats([])
      setActiveWorkspaceChatId('')
      return
    }

    const { data, error } = await supabase
      .from(CHAT_HISTORY_TABLE)
      .select(CHAT_SELECT_FIELDS)
      .eq('user_id', userId)
      .is('meeting_id', null)
      .order('created_at', { ascending: false })

    if (error) {
      console.error('Workspace chats load failed:', error)
      return
    }

    const rows = (data || []).map(mapWorkspaceChatRow)
    setWorkspaceChats(rows)
    setActiveWorkspaceChatId((current) =>
      rows.some((item) => item.id === current) ? current : '',
    )
  }, [userId])

  const persistWorkspaceChat = useCallback(
    async (chatId, patch) => {
      if (!userId || !chatId) return null

      const cleanPatch = sanitizeChatPatch(patch)
      if (Object.keys(cleanPatch).length === 0) return null

      const { data, error } = await supabase
        .from(CHAT_HISTORY_TABLE)
        .update(cleanPatch)
        .eq('id', chatId)
        .eq('user_id', userId)
        .select(CHAT_SELECT_FIELDS)
        .maybeSingle()

      if (error) {
        console.error('Workspace chat persist failed:', error)
        setHistoryError(error.message || 'Could not save workspace chat.')
        return null
      }

      if (!data) return null

      const updated = mapWorkspaceChatRow(data)
      setWorkspaceChats((items) => [updated, ...items.filter((item) => item.id !== updated.id)])
      return updated
    },
    [userId],
  )

  const createWorkspaceChat = useCallback(
    async ({ title, firstQuery, messages }) => {
      if (!userId) return null

      const { data, error } = await supabase
        .from(CHAT_HISTORY_TABLE)
        .insert({
          user_id: userId,
          title,
          query: firstQuery,
          status: 'ready',
          messages: messages ?? [],
          meeting_id: null,
          meeting_title: null,
        })
        .select(CHAT_SELECT_FIELDS)
        .maybeSingle()

      if (error) {
        console.error('Workspace chat create failed:', error)
        setHistoryError(error.message || 'Could not create workspace chat.')
        return null
      }

      if (!data) return null

      const row = mapWorkspaceChatRow(data)
      setWorkspaceChats((items) => [row, ...items.filter((item) => item.id !== row.id)])
      setActiveWorkspaceChatId(row.id)
      return row
    },
    [userId],
  )

  const loadMeetingChats = useCallback(async () => {
    if (!userId) {
      setMeetingChats([])
      setActiveChatId('')
      return
    }

    setIsHistoryLoading(true)
    setHistoryError('')

    const { data, error } = await supabase
      .from(CHAT_HISTORY_TABLE)
      .select(CHAT_SELECT_FIELDS)
      .eq('user_id', userId)
      .not('meeting_id', 'is', null)
      .order('created_at', { ascending: false })

    if (error) {
      console.error('Meeting chats load failed:', error)
      setHistoryError('Meeting chats could not be loaded.')
      setMeetingChats([])
      setActiveChatId('')
    } else {
      let rows = (data || []).map(mapMeetingChatRow)
      const token = graphTokenRef.current
      if (token) {
        const statusChecks = await Promise.all(
          rows.map(async (row) => {
            try {
              const response = await fetch(
                `${API_BASE_URL}/ingestion/status/${encodeURIComponent(row.meetingId)}`,
                { headers: bearerHeaders(token) },
              )
              if (!response.ok) return null
              return await response.json()
            } catch {
              return null
            }
          }),
        )

        const reconciledRows = []
        for (let index = 0; index < rows.length; index += 1) {
          const row = rows[index]
          const ingestion = statusChecks[index]

          if (isStaleMeetingChat(row, ingestion)) {
            const { error: updateError } = await supabase
              .from(CHAT_HISTORY_TABLE)
              .update({ status: 'failed', messages: [] })
              .eq('id', row.id)
              .eq('user_id', userId)

            if (!updateError) {
              summaryRequestedRef.current.delete(row.id)
              summarySkippedRef.current.delete(row.id)
            }
            reconciledRows.push({ ...row, status: 'failed', messages: [] })
            continue
          }

          if (ingestion?.status === 'EMBEDDED') {
            reconciledRows.push({ ...row, status: 'ready' })
            continue
          }
          if (['QUEUED', 'PROCESSING'].includes(ingestion?.status)) {
            reconciledRows.push({ ...row, status: 'preparing' })
            continue
          }
          if (['FAILED', 'NO_TRANSCRIPT'].includes(ingestion?.status)) {
            reconciledRows.push({ ...row, status: 'failed' })
            continue
          }
          reconciledRows.push(row)
        }

        rows = reconciledRows.filter((row) => row.status !== 'failed')
      }
      setMeetingChats(rows)
      setActiveChatId((current) =>
        rows.some((item) => item.id === current) ? current : '',
      )
    }

    setIsHistoryLoading(false)
  }, [userId])

  loadMeetingChatsRef.current = loadMeetingChats

  const upsertMeetingChat = useCallback(
    async ({ meetingId, title, status, messages }) => {
      if (!userId) return null

      const baseRow = {
        user_id: userId,
        meeting_id: meetingId,
        meeting_title: title,
        title,
        status,
        messages: messages ?? [],
        query: MEETING_CHAT_LEGACY_QUERY,
      }

      const { data: existing, error: findError } = await supabase
        .from(CHAT_HISTORY_TABLE)
        .select(CHAT_SELECT_FIELDS)
        .eq('user_id', userId)
        .eq('meeting_id', meetingId)
        .maybeSingle()

      if (findError) {
        console.error('Chat lookup failed:', findError)
        setHistoryError(
          findError.message ||
            'Could not load meeting chat. Check Supabase connection and RLS policies.',
        )
        return null
      }

      const writeChat = async () => {
        if (existing?.id) {
          return supabase
            .from(CHAT_HISTORY_TABLE)
            .update({
              title,
              meeting_title: title,
              status,
              messages: messages ?? existing.messages ?? [],
            })
            .eq('id', existing.id)
            .eq('user_id', userId)
            .select(CHAT_SELECT_FIELDS)
            .maybeSingle()
        }

        return supabase
          .from(CHAT_HISTORY_TABLE)
          .insert(baseRow)
          .select(CHAT_SELECT_FIELDS)
          .maybeSingle()
      }

      let { data, error } = await writeChat()

      if (error?.code === '23505') {
        const retry = await supabase
          .from(CHAT_HISTORY_TABLE)
          .update({
            title,
            meeting_title: title,
            status,
            messages: messages ?? [],
          })
          .eq('user_id', userId)
          .eq('meeting_id', meetingId)
          .select(CHAT_SELECT_FIELDS)
          .maybeSingle()
        data = retry.data
        error = retry.error
      }

      if (error) {
        console.error('Chat upsert failed:', error)
        const needsMigration =
          error.code === '42703' ||
          error.message?.includes('status') ||
          error.message?.includes('messages')
        setHistoryError(
          needsMigration
            ? 'Could not create meeting chat. Run supabase/migrations/001 and 002 in the Supabase SQL editor.'
            : error.message || 'Could not create meeting chat.',
        )
        return null
      }

      if (!data) {
        setHistoryError('Could not save meeting chat (no row returned).')
        return null
      }

      setHistoryError('')
      const row = mapMeetingChatRow(data)
      setMeetingChats((items) => {
        const remaining = items.filter((item) => item.id !== row.id)
        return [row, ...remaining]
      })
      return row
    },
    [userId],
  )

  const persistChat = useCallback(
    async (chatId, patch) => {
      if (!userId) return null

      const cleanPatch = sanitizeChatPatch(patch)
      if (Object.keys(cleanPatch).length === 0) return null

      const { data, error } = await supabase
        .from(CHAT_HISTORY_TABLE)
        .update(cleanPatch)
        .eq('id', chatId)
        .eq('user_id', userId)
        .select(CHAT_SELECT_FIELDS)
        .maybeSingle()

      if (error) {
        console.error('Chat persist failed:', error)
        setHistoryError(
          error.code === 'PGRST116'
            ? 'Could not save chat changes (row not found or blocked by RLS).'
            : error.message || 'Could not save chat changes.',
        )
      }

      if (data) {
        setHistoryError('')
        const updated = mapMeetingChatRow(data)
        setMeetingChats((items) => {
          const remaining = items.filter((item) => item.id !== updated.id)
          return [updated, ...remaining]
        })
        return updated
      }

      const localChat = meetingChatsRef.current.find((item) => item.id === chatId)
      if (localChat?.meetingId) {
        const recovered = await upsertMeetingChat({
          meetingId: localChat.meetingId,
          title: localChat.title,
          status: cleanPatch.status ?? localChat.status,
          messages: cleanPatch.messages ?? localChat.messages,
        })
        return recovered
      }

      if (!error) {
        setHistoryError('Could not save chat changes (row not found).')
      }
      return null
    },
    [upsertMeetingChat, userId],
  )

  const sleep = useCallback(
    (ms) => new Promise((resolve) => window.setTimeout(resolve, ms)),
    [],
  )

  const isNetworkFetchError = useCallback((error) => {
    return error instanceof TypeError && String(error.message).includes('Failed to fetch')
  }, [])

  const checkBackendHealth = useCallback(async () => {
    for (let attempt = 0; attempt < 5; attempt += 1) {
      try {
        const response = await fetch(`${API_BASE_URL}/`, { method: 'GET' })
        if (response.ok) return true
      } catch {
        // retry — backend may be reloading or briefly busy
      }
      if (attempt < 4) {
        await sleep(800)
      }
    }
    return false
  }, [sleep])

  const fetchAutoSyncStatus = useCallback(async () => {
    const token = graphTokenRef.current
    if (!token) return null

    try {
      const response = await fetch(`${API_BASE_URL}/ingestion/auto-sync/status`, {
        headers: bearerHeaders(token),
      })
      if (!response.ok) {
        throw new Error(await readErrorMessage(response, 'Auto-sync status failed.'))
      }
      const payload = await response.json()
      setAutoSyncStatus(payload)
      setAutoSyncError('')
      return payload
    } catch (error) {
      setAutoSyncError(error.message || 'Auto-sync status is unavailable.')
      return null
    }
  }, [])

  const registerAutoSync = useCallback(async () => {
    const token = graphTokenRef.current
    if (!token || autoSyncRegisteredTokenRef.current === token) {
      return fetchAutoSyncStatus()
    }

    const backendUp = await checkBackendHealth()
    if (!backendUp) {
      setAutoSyncError(`Cannot reach the API at ${API_BASE_URL}.`)
      return null
    }

    try {
      const response = await fetch(`${API_BASE_URL}/ingestion/auto-sync/register?limit=50`, {
        method: 'POST',
        headers: bearerHeaders(token),
      })
      if (!response.ok) {
        throw new Error(await readErrorMessage(response, 'Auto-sync registration failed.'))
      }
      const payload = await response.json()
      autoSyncRegisteredTokenRef.current = token
      setAutoSyncStatus(payload)
      setAutoSyncError('')
      return payload
    } catch (error) {
      setAutoSyncError(error.message || 'Auto-sync registration failed.')
      return null
    }
  }, [checkBackendHealth, fetchAutoSyncStatus])

  const loadCatalog = useCallback(async () => {
    const token = graphTokenRef.current
    if (!token) return

    try {
      const response = await fetch(`${API_BASE_URL}/meetings/catalog`, {
        headers: bearerHeaders(token),
      })
      if (!response.ok) return
      const payload = await response.json()
      setCatalogMeetings((payload.meetings || []).map(normalizeCatalogMeeting))
      setCatalogSyncedAt(payload.synced_at || null)
    } catch {
      // Backend may be starting or Vite proxy reloading — sync will retry later.
    }
  }, [])

  const syncCatalog = useCallback(
    async ({ silent = false } = {}) => {
      if (catalogSyncInFlightRef.current) {
        return null
      }

      if (!graphToken) {
        if (!silent) {
          setCatalogError(
            'Microsoft Graph token is not available. Sign out and sign in again to sync meetings.',
          )
        }
        return null
      }

      const backendUp = await checkBackendHealth()
      if (!backendUp) {
        const message =
          'Backend API is not reachable yet. Start uvicorn on port 8000, wait a few seconds, then refresh.'
        const now = Date.now()
        if (!silent || now - lastBackendWarnAtRef.current > 60_000) {
          lastBackendWarnAtRef.current = now
          if (silent) {
            console.warn('Background catalog sync skipped:', message)
          } else {
            setCatalogError(message)
          }
        }
        return null
      }

      catalogSyncInFlightRef.current = true
      if (!silent) setCatalogSyncing(true)
      if (!silent) setCatalogError('')

      try {
        let payload = null
        let lastNetworkError = null
        let mergeHttpStatus = null

        const authHeaders = bearerHeaders(graphToken)

        for (let attempt = 0; attempt < 3; attempt += 1) {
          try {
            const teamsResponse = await fetch(
              `${API_BASE_URL}/meetings/catalog/discover/teams?limit=30`,
              { method: 'POST', headers: authHeaders },
            )

            if (!teamsResponse.ok) {
              throw new Error(
                await readErrorMessage(teamsResponse, 'Teams catalog discovery failed.'),
              )
            }

            const teamsSource = await teamsResponse.json()
            const meetingTitles = (teamsSource.calendar_meetings || [])
              .map((meeting) => meeting.title)
              .filter(Boolean)

            const onedriveResponse = await fetch(
              `${API_BASE_URL}/meetings/catalog/discover/onedrive`,
              {
                method: 'POST',
                headers: { ...authHeaders, 'Content-Type': 'application/json' },
                body: JSON.stringify({ meeting_titles: meetingTitles }),
              },
            )

            if (!onedriveResponse.ok) {
              throw new Error(
                await readErrorMessage(onedriveResponse, 'OneDrive catalog discovery failed.'),
              )
            }

            const onedriveSource = await onedriveResponse.json()

            const mergeResponse = await fetch(`${API_BASE_URL}/meetings/catalog/merge`, {
              method: 'POST',
              headers: {
                ...authHeaders,
                'Content-Type': 'application/json',
              },
              body: JSON.stringify({ teams: teamsSource, onedrive: onedriveSource }),
            })

            mergeHttpStatus = mergeResponse.status

            if (!mergeResponse.ok) {
              throw new Error(
                await readErrorMessage(mergeResponse, 'Meeting catalog merge failed.'),
              )
            }

            payload = await mergeResponse.json()
            break
          } catch (error) {
            if (!isNetworkFetchError(error) || attempt >= 2) {
              throw error
            }
            lastNetworkError = error
            const backendUp = await checkBackendHealth()
            if (!backendUp) {
              throw error
            }
            await sleep(1500 * (attempt + 1))
          }
        }

        if (!payload) {
          throw lastNetworkError || new Error('Meeting catalog sync failed.')
        }

        const normalized = (payload.meetings || [])
          .map(normalizeCatalogMeeting)
        setCatalogMeetings(normalized)
        setCatalogSyncedAt(payload.synced_at || null)

        if (payload.sync_status === 'FAILED' && payload.sync_error && !silent) {
          setCatalogError(payload.sync_error)
          await loadMeetingChatsRef.current?.()
          return payload
        }

        if (payload.sync_error && !silent) {
          setCatalogError(payload.sync_error)
          await loadMeetingChatsRef.current?.()
          return payload
        }

        if (!silent && normalized.length === 0) {
          const diagnostics = payload.diagnostics || {}
          const scanned = diagnostics.calendar_meetings_scanned ?? 0
          const withContent =
            diagnostics.meetings_with_recording_or_transcript
            ?? diagnostics.meetings_with_graph_recording_or_transcript
            ?? 0
          const onedriveMatched = diagnostics.onedrive_matched_calendar_meetings ?? 0
          const indexed = diagnostics.meetings_indexed_in_chroma ?? 0
          const resolved = diagnostics.resolved_online_meeting_id ?? 0
          const unresolved = diagnostics.unresolved_online_meeting_id ?? 0
          const withTranscripts = diagnostics.with_graph_transcripts ?? 0
          const permissionErrors = diagnostics.graph_permission_errors ?? 0

          console.warn('Meetings catalog sync returned no meetings.', {
            diagnostics,
            httpStatus: mergeHttpStatus,
            calendarRange: {
              oldest: diagnostics.calendar_oldest_scanned,
              newest: diagnostics.calendar_newest_scanned,
            },
            hint:
              'If your meeting is outside this date range or not in the scanned set, it will not appear. Check Teams recap exists for an organizer calendar meeting.',
          })

          let message =
            scanned === 0
              ? 'No past Teams meetings were found on your calendar (last 30 days). Record a Teams meeting, then sync again.'
              : withContent === 0 && indexed === 0
                ? `Found ${scanned} Teams meeting(s), but none with a detectable recording or transcript in Teams or OneDrive.`
                : 'No meetings matched the catalog filter. Try Sync again.'

          if (scanned > 0 && withContent === 0 && indexed === 0) {
            if (diagnostics.calendar_oldest_scanned && diagnostics.calendar_newest_scanned) {
              message += ` Scanned calendar range: ${formatDateTime(diagnostics.calendar_oldest_scanned)} – ${formatDateTime(diagnostics.calendar_newest_scanned)}.`
            }
            if (unresolved > 0 && resolved === 0) {
              message += ` Could not link ${unresolved} meeting(s) to a Teams online meeting ID (join URL lookup failed).`
            } else if (resolved > 0 && withTranscripts === 0) {
              message +=
                ' Teams online meetings were found, but Graph returned no recordings or transcripts. Enable transcription on the meeting and wait until the transcript appears in Teams.'
            }
            if (onedriveMatched > 0 && withContent === 0) {
              message += ` Found ${onedriveMatched} OneDrive asset(s) but they did not match calendar titles closely enough.`
            }
            if (permissionErrors > 0) {
              message += ` Graph returned permission errors for ${permissionErrors} meeting(s) — confirm OnlineMeetingTranscript.Read.All is consented in Azure.`
            }
            const throttled = diagnostics.graph_throttled ?? 0
            if (throttled > 0) {
              message += ` Microsoft Graph throttled ${throttled} lookup(s). Wait a minute and sync again.`
            }
          }

          setCatalogError(message)
        }

        await loadMeetingChatsRef.current?.()
        return payload
      } catch (error) {
        const isNetworkError = isNetworkFetchError(error)
        const message = isNetworkError
          ? `Cannot reach the API at ${API_BASE_URL}. Start the backend (uvicorn on port 8000) and refresh.`
          : error.message || 'Meeting catalog sync failed.'

        if (silent) {
          console.warn('Background catalog sync failed:', message)
        } else {
          console.error(error)
          setCatalogError(message)
        }
        return null
      } finally {
        catalogSyncInFlightRef.current = false
        if (!silent) setCatalogSyncing(false)
        if (!silent) setCatalogLoading(false)
      }
    },
    [checkBackendHealth, graphToken, isNetworkFetchError, sleep],
  )

  syncCatalogRef.current = syncCatalog

  useEffect(() => {
    const syncUpdatedAt = autoSyncStatus?.workspace_sync?.updated_at
    if (!graphToken || !userId || !syncUpdatedAt) return
    void loadCatalog()
  }, [autoSyncStatus?.workspace_sync?.updated_at, graphToken, loadCatalog, userId])

  const fetchIngestionStatus = useCallback(async (meetingId) => {
    const token = graphTokenRef.current
    if (!token) return null

    try {
      const response = await fetch(
        `${API_BASE_URL}/ingestion/status/${encodeURIComponent(meetingId)}`,
        { headers: bearerHeaders(token) },
      )
      if (!response.ok) return null
      const payload = await response.json()
      setIngestionByMeeting((current) => {
        if (ingestionStatusUnchanged(current[meetingId], payload)) {
          return current
        }
        return { ...current, [meetingId]: payload }
      })
      return payload
    } catch {
      return null
    }
  }, [])

  const startMeetingIngestion = useCallback(
    async (meetingId) => {
      if (!graphToken) return null

      const response = await fetch(
        `${API_BASE_URL}/ingestion/meetings/${encodeURIComponent(meetingId)}/start`,
        {
          method: 'POST',
          headers: bearerHeaders(graphToken),
        },
      )

      if (!response.ok) {
        throw new Error(await readErrorMessage(response, 'Could not start meeting preparation.'))
      }

      const payload = await response.json()
      await fetchIngestionStatus(meetingId)
      return payload
    },
    [fetchIngestionStatus, graphToken],
  )
  const generateSummary = useCallback(
    async (chat) => {
      if (!chat?.meetingId || summaryRequestedRef.current.has(chat.id)) return
      if (summarySkippedRef.current.has(chat.id)) return

      const hasAssistant = (chat.messages || []).some((message) => message.role === 'assistant')
      if (hasAssistant) return

      const token = graphTokenRef.current
      if (!token) return

      summaryRequestedRef.current.add(chat.id)
      markSummarizingChat(chat.id, true)

      try {
        const response = await fetch(`${API_BASE_URL}/rag/query`, {
          method: 'POST',
          headers: bearerHeaders(token, { 'Content-Type': 'application/json' }),
          body: JSON.stringify({
            query: SUMMARY_PROMPT,
            meeting_id: chat.meetingId,
            output_format: outputPreference,
          }),
        })

        if (!response.ok) {
          throw new Error(await readErrorMessage(response, 'Summary generation failed.'))
        }

        const payload = await response.json()
        const text =
          typeof payload.answer === 'string' && payload.answer.trim()
            ? payload.answer.trim()
            : 'Summary is not available yet.'

        const summaryMessage = {
          ...buildAssistantMessage(payload, text),
          id: `summary-${crypto.randomUUID()}`,
          mode: payload.answer_mode || 'extractive_summary',
        }

        const nextMessages = [...(chat.messages || []), summaryMessage]
        await persistChat(chat.id, {
          messages: nextMessages,
          status: 'ready',
        })
      } catch (error) {
        console.error(error)
        summaryRequestedRef.current.delete(chat.id)
        if (activeChatIdRef.current === chat.id) {
          setPipelineNotice('Could not generate a meeting summary. You can still ask questions below.')
        }
      } finally {
        markSummarizingChat(chat.id, false)
      }
    },
    [buildAssistantMessage, markSummarizingChat, outputPreference, persistChat],
  )

  const markChatReady = useCallback(
    async (chat) => {
      if (!chat || chat.status === 'ready') {
        if (chat) await generateSummary(chat)
        return
      }

      const updated = await persistChat(chat.id, { status: 'ready' })

      if (updated) {
        await generateSummary(updated)
        return
      }

      if (chat.meetingId) {
        const recovered = await upsertMeetingChat({
          meetingId: chat.meetingId,
          title: chat.title,
          status: 'ready',
          messages: chat.messages ?? [],
        })
        if (recovered) {
          await generateSummary(recovered)
        }
      }
    },
    [generateSummary, persistChat, upsertMeetingChat],
  )

  const handleMeetingReady = useCallback(
    async (chat, ingestionPayload) => {
      if (!chat) return

      if (ingestionPayload?.status === 'EMBEDDED') {
        await markChatReady(chat)
        setCatalogMeetings((items) => patchCatalogMeetingIndexed(items, chat.meetingId, true))
        return
      }

      if (['FAILED', 'NO_TRANSCRIPT'].includes(ingestionPayload?.status)) {
        await persistChat(chat.id, { status: 'failed' })
      }
    },
    [markChatReady, persistChat],
  )

  const openMeeting = useCallback(
    async (meeting) => {
      const meetingId = meeting.id
      const title = meeting.title
      const token = graphTokenRef.current

      setActiveNav('workspace')
      setQuery('')
      setSearchMessage('')
      setPipelineNotice('')

      if (!token) {
        setSearchMessage('Microsoft Graph token is not available. Sign out and sign in again.')
        return
      }

      const ingestion = await fetchIngestionStatus(meetingId)
      const isEmbedded = Boolean(meeting.isIndexed) || ingestion?.status === 'EMBEDDED'

      let chat = meetingChatsRef.current.find((item) => item.meetingId === meetingId)
      if (!chat) {
        chat = await upsertMeetingChat({
          meetingId,
          title,
          status: isEmbedded ? 'ready' : 'preparing',
          messages: [],
        })
      } else if (!isEmbedded && chat.status !== 'preparing') {
        chat = await persistChat(chat.id, { status: 'preparing' })
      }

      if (!chat) return

      setActiveChatId(chat.id)

      if (isEmbedded) {
        setCatalogMeetings((items) => patchCatalogMeetingIndexed(items, meetingId, true))
        await markChatReady(chat)
        return
      }

      setPipelineNotice('Preparing transcript and embeddings for this recording. You can keep this page open while MeetVault works.')

      try {
        const response = await fetch(
          `${API_BASE_URL}/ingestion/meetings/${encodeURIComponent(meetingId)}/start`,
          {
            method: 'POST',
            headers: bearerHeaders(token),
          },
        )

        if (!response.ok) {
          throw new Error(await readErrorMessage(response, 'Could not start meeting preparation.'))
        }

        const payload = await response.json()
        setIngestionByMeeting((current) => ({ ...current, [meetingId]: payload }))

        if (payload.status === 'EMBEDDED') {
          await handleMeetingReady(chat, payload)
        }
      } catch (error) {
        console.error(error)
        setPipelineNotice('')
        setSearchMessage(error.message || 'Could not start meeting preparation.')
        await persistChat(chat.id, { status: 'failed' })
      }
    },
    [
      fetchIngestionStatus,
      handleMeetingReady,
      markChatReady,
      persistChat,
      upsertMeetingChat,
    ],
  )

  const deleteMeetingChat = useCallback(
    async (chatId) => {
      const chat = meetingChatsRef.current.find((item) => item.id === chatId)
      if (!chat?.id || !chat.meetingId) return

      const confirmed = window.confirm(
        'Delete this meeting chat and remove all indexed transcript data for this meeting?',
      )
      if (!confirmed) return

      const token = graphTokenRef.current
      if (!token) {
        setSearchMessage(
          'Microsoft Graph token is not available. Sign out and sign in again.',
        )
        return
      }

      setIsDeletingChat(true)
      setSearchMessage('')
      setPipelineNotice('')

      try {
        const response = await fetch(
          `${API_BASE_URL}/ingestion/meetings/${encodeURIComponent(chat.meetingId)}`,
          {
            method: 'DELETE',
            headers: bearerHeaders(token),
          },
        )

        if (!response.ok) {
          throw new Error(
            await readErrorMessage(response, 'Could not delete meeting data.'),
          )
        }

        const { error } = await supabase
          .from(CHAT_HISTORY_TABLE)
          .delete()
          .eq('id', chatId)
          .eq('user_id', userId)

        if (error) {
          throw new Error(error.message || 'Could not delete chat.')
        }

        const meetingId = chat.meetingId
        summaryRequestedRef.current.delete(chatId)
        summarySkippedRef.current.delete(chatId)

        const remaining = meetingChatsRef.current.filter((item) => item.id !== chatId)
        setMeetingChats(remaining)
        setActiveChatId((current) => (current === chatId ? remaining[0]?.id || '' : current))
        setIngestionByMeeting((current) => {
          const next = { ...current }
          delete next[meetingId]
          return next
        })
        setCatalogMeetings((items) => patchCatalogMeetingIndexed(items, meetingId, false))

        try {
          const catalogResponse = await fetch(`${API_BASE_URL}/meetings/catalog`, {
            headers: bearerHeaders(token),
          })
          if (catalogResponse.ok) {
            const payload = await catalogResponse.json()
            setCatalogMeetings(
              (payload.meetings || [])
                .map(normalizeCatalogMeeting),
            )
            setCatalogSyncedAt(payload.synced_at || null)
          }
        } catch {
          // Local patch is enough if catalog refresh fails.
        }

        setQuery('')
        setHistoryError('')
      } catch (error) {
        console.error(error)
        setSearchMessage(error.message || 'Could not delete chat.')
      } finally {
        setIsDeletingChat(false)
      }
    },
    [userId],
  )

  const clearMeetingChat = useCallback(
    async (chatId) => {
      const chat = meetingChatsRef.current.find((item) => item.id === chatId)
      if (!chat?.id) return

      const hasMessages = (chat.messages || []).length > 0
      if (!hasMessages) return

      const confirmed = window.confirm(
        'Clear all messages in this meeting chat? This cannot be undone.',
      )
      if (!confirmed) return

      summaryRequestedRef.current.delete(chatId)
      summarySkippedRef.current.add(chatId)
      setQuery('')
      setSearchMessage('')
      setPipelineNotice('')

      const saved = await persistChat(chatId, { messages: [] })
      if (!saved) {
        summarySkippedRef.current.delete(chatId)
        setSearchMessage('Could not clear chat. Try again.')
        return
      }

      setMeetingChats((items) =>
        items.map((item) => (item.id === chatId ? { ...item, messages: [] } : item)),
      )
    },
    [persistChat],
  )

  const handleMeetingSearch = useCallback(
    async (event) => {
      event.preventDefault()
      if (!activeChat?.meetingId) return

      const trimmedQuery = query.trim()
      if (!trimmedQuery) return

      if (!isChatReady(activeChat.status, activeIngestion?.status)) return

      const chatId = activeChat.id
      const meetingId = activeChat.meetingId
      const priorMessages = activeChat.messages || []
      const token = graphTokenRef.current

      if (!token) {
        setSearchMessage('Microsoft Graph token is not available. Sign out and sign in again.')
        return
      }

      setSearchingMeetingChatId(chatId)
      setSearchingWorkspaceChatId(null)
      setSearchMessage('')
      setPipelineNotice('')

      const userMessage = {
        id: `user-${crypto.randomUUID()}`,
        role: 'user',
        text: trimmedQuery,
        createdAt: new Date().toISOString(),
      }

      const optimisticMessages = [...priorMessages, userMessage]
      setMeetingChats((items) =>
        items.map((item) =>
          item.id === chatId ? { ...item, messages: optimisticMessages } : item,
        ),
      )
      setQuery('')

      try {
        const response = await fetch(`${API_BASE_URL}/rag/query`, {
          method: 'POST',
          headers: bearerHeaders(token, { 'Content-Type': 'application/json' }),
          body: JSON.stringify({
            query: trimmedQuery,
            meeting_id: meetingId,
            output_format: outputPreference,
          }),
        })

        if (!response.ok) {
          throw new Error(await readErrorMessage(response, 'RAG query failed.'))
        }

        const payload = await response.json()
        const answerText =
          typeof payload.answer === 'string' && payload.answer.trim()
            ? payload.answer.trim()
            : 'No grounded answer is available for this meeting yet.'

        const assistantMessage = buildAssistantMessage(payload, answerText)

        const nextMessages = [...optimisticMessages, assistantMessage]
        await persistChat(chatId, {
          messages: nextMessages,
          status: 'ready',
        })

        if (activeChatIdRef.current === chatId) {
          if (payload.llm_error) {
            setPipelineNotice(
              'The answer model is unavailable right now, so MeetVault showed a retrieval-based fallback.',
            )
          }
        }
      } catch (error) {
        console.error(error)
        if (activeChatIdRef.current === chatId) {
          setSearchMessage(error.message || 'Search failed.')
        }
        setMeetingChats((items) =>
          items.map((item) =>
            item.id === chatId ? { ...item, messages: priorMessages } : item,
          ),
        )
      } finally {
        setSearchingMeetingChatId((current) => (current === chatId ? null : current))
      }
    },
    [activeChat, activeIngestion?.status, buildAssistantMessage, outputPreference, persistChat, query],
  )

  const handleWorkspaceSearch = useCallback(
    async (event) => {
      event.preventDefault()

      const trimmedQuery = query.trim()
      if (!trimmedQuery) return

      const token = graphTokenRef.current
      if (!token) {
        setSearchMessage('Microsoft Graph token is not available. Sign out and sign in again.')
        return
      }

      setSearchingMeetingChatId(null)
      setSearchMessage('')
      setPipelineNotice('')

      const userMessage = {
        id: `user-${crypto.randomUUID()}`,
        role: 'user',
        text: trimmedQuery,
        createdAt: new Date().toISOString(),
      }

      let chat = activeWorkspaceChat
      const priorMessages = chat?.messages || []
      const optimisticMessages = [...priorMessages, userMessage]

      if (!chat) {
        chat = await createWorkspaceChat({
          title: titleFromQuery(trimmedQuery),
          firstQuery: trimmedQuery,
          messages: optimisticMessages,
        })
      } else {
        setWorkspaceChats((items) =>
          items.map((item) =>
            item.id === chat.id ? { ...item, messages: optimisticMessages } : item,
          ),
        )
      }

      if (!chat) {
        setSearchMessage('Could not create workspace chat history.')
        return
      }

      setSearchingWorkspaceChatId(chat.id)
      setActiveWorkspaceChatId(chat.id)
      setActiveChatId('')
      setQuery('')

      try {
        const response = await fetch(`${API_BASE_URL}/rag/query`, {
          method: 'POST',
          headers: bearerHeaders(token, { 'Content-Type': 'application/json' }),
          body: JSON.stringify({
            query: trimmedQuery,
            output_format: outputPreference,
          }),
        })

        if (!response.ok) {
          throw new Error(await readErrorMessage(response, 'Workspace search failed.'))
        }

        const payload = await response.json()
        const answerText =
          typeof payload.answer === 'string' && payload.answer.trim()
            ? payload.answer.trim()
            : 'No grounded answer is available from indexed recordings yet.'

        const assistantMessage = buildAssistantMessage(payload, answerText)

        const nextMessages = [...optimisticMessages, assistantMessage]
        await persistWorkspaceChat(chat.id, {
          title: chat.title || titleFromQuery(trimmedQuery),
          messages: nextMessages,
          status: 'ready',
        })

        if (payload.llm_error) {
          setPipelineNotice(
            'The answer model is unavailable right now, so MeetVault showed a retrieval-based fallback.',
          )
        }
      } catch (error) {
        console.error(error)
        setSearchMessage(error.message || 'Workspace search failed.')
        setWorkspaceChats((items) =>
          items.map((item) =>
            item.id === chat.id ? { ...item, messages: priorMessages } : item,
          ),
        )
      } finally {
        setSearchingWorkspaceChatId((current) => (current === chat.id ? null : current))
      }
    },
    [activeWorkspaceChat, buildAssistantMessage, createWorkspaceChat, outputPreference, persistWorkspaceChat, query],
  )

  useEffect(() => {
    const fetchSession = async () => {
      const { data, error } = await supabase.auth.getSession()
      if (error) console.error(error)
      setSession(data.session)
      if (data.session?.provider_token) {
        localStorage.setItem(GRAPH_TOKEN_STORAGE_KEY, data.session.provider_token)
      }
    }

    fetchSession()

    const { data: authListener } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      if (!nextSession) {
        setWorkspaceChats([])
        setActiveWorkspaceChatId('')
        setMeetingChats([])
        setActiveChatId('')
        setCatalogMeetings([])
        setCatalogSyncedAt(null)
        setIngestionByMeeting({})
        summaryRequestedRef.current = new Set()
        catalogBootstrapDoneRef.current = false
        mcpAutoConnectRef.current = false
        setShowOnboarding(false)
        autoSyncRegisteredTokenRef.current = ''
        setAutoSyncStatus(null)
        setAutoSyncError('')
      } else if (event === 'SIGNED_IN') {
        const completed = localStorage.getItem('meetvault-onboarding-completed') === 'true'
        setShowOnboarding(!completed)
      }
      if (nextSession?.provider_token) {
        localStorage.setItem(GRAPH_TOKEN_STORAGE_KEY, nextSession.provider_token)
      } else if (!nextSession) {
        localStorage.removeItem(GRAPH_TOKEN_STORAGE_KEY)
      }
      setSession(nextSession)
    })

    return () => authListener.subscription.unsubscribe()
  }, [])

  useEffect(() => {
    if (!userId) return
    loadWorkspaceChats()
    loadMeetingChats()
    loadCatalog()
  }, [loadCatalog, loadMeetingChats, loadWorkspaceChats, userId])

  useEffect(() => {
    const refreshMcpState = () => {
      if (!session) return
      void loadMeetingChats()
      setCatalogLoading(true)
      void (async () => {
        try {
          await syncCatalogRef.current?.({ silent: true })
        } finally {
          setCatalogLoading(false)
        }
      })()
    }

    const unsubscribeOAuth = subscribeMcpOAuthEvents(() => {
      refreshMcpState()
    })

    return () => {
      unsubscribeOAuth()
    }
  }, [session, loadMeetingChats])


  useEffect(() => {
    if (!graphToken || !userId) return undefined

    if (catalogBootstrapDoneRef.current) {
      return undefined
    }
    catalogBootstrapDoneRef.current = true

    const bootstrap = async () => {
      // Let Vite proxy and uvicorn settle after dev-server or HMR restarts.
      await new Promise((resolve) => window.setTimeout(resolve, 3000))
      const backendUp = await checkBackendHealth()
      if (!backendUp) {
        return
      }
      setCatalogLoading(true)
      try {
        await syncCatalogRef.current?.({ silent: true })
      } finally {
        setCatalogLoading(false)
      }
    }

    bootstrap()

    return undefined
  }, [checkBackendHealth, graphToken, userId])

  useEffect(() => {
    if (!graphToken || !userId) return
    if (mcpAutoConnectRef.current) return
    mcpAutoConnectRef.current = true

    const autoConnectMicrosoft = async () => {
      const providerUserId = user?.email || 'Microsoft user'
      const providers = ['outlook', 'calendar']

      await Promise.all(
        providers.map(async (provider) => {
          try {
            await mcpService.connectProvider(provider, providerUserId, graphToken, supabaseToken)
            publishMcpOAuthEvent({ provider, connected: true, error: '' })
          } catch (error) {
            console.error(`Auto-connect for ${provider} failed:`, error)
          }
        }),
      )
    }

    void autoConnectMicrosoft()
  }, [graphToken, userId, supabaseToken, user?.email])

  useEffect(() => {
    if (!graphToken || !userId) return undefined

    const tick = () => {
      void fetchAutoSyncStatus()
    }

    if (AUTO_SYNC_ENABLED) {
      void registerAutoSync()
    } else {
      void fetchAutoSyncStatus()
    }
    const intervalId = window.setInterval(tick, AUTO_SYNC_STATUS_MS)
    return () => window.clearInterval(intervalId)
  }, [fetchAutoSyncStatus, graphToken, registerAutoSync, userId])

  pollIngestionRef.current = async () => {
    const targets = meetingChatsRef.current.filter((chat) =>
      isChatPreparing(
        chat.status,
        ingestionByMeetingRef.current[chat.meetingId]?.status,
      ),
    )

    if (targets.length === 0) return

    await Promise.all(
      targets.map(async (chat) => {
        let payload = await fetchIngestionStatus(chat.meetingId)

        if (payload) {
          await handleMeetingReady(chat, payload)
        }
      }),
    )
  }

  useEffect(() => {
    if (!userId) return undefined

    const tick = () => {
      void pollIngestionRef.current()
    }

    tick()
    const intervalId = window.setInterval(tick, INGESTION_POLL_MS)
    return () => window.clearInterval(intervalId)
  }, [userId])

  const handleAuth = async () => {
    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'azure',
      options: {
        scopes: REQUIRED_LOGIN_SCOPES,
        redirectTo: window.location.origin,
      },
    })
    if (error) console.error(error)
  }

  const handleSignOut = async () => {
    await supabase.auth.signOut()
    setShowProfile(false)
  }

  const mainTitle = 'Video Catalog'

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
              <h1>Meeting intelligence from Teams recordings</h1>
            </div>
          </div>
          <div className="login-copy">
            <p className="eyebrow">Required authentication</p>
            <h2 id="login-title">Sign in with Microsoft to browse recorded meetings</h2>
            <p>
              MeetVault discovers your recorded Teams meetings, prepares transcripts when you open
              a recording, and answers questions grounded in your meeting content.
            </p>
          </div>
          <button className="auth-button full-width" type="button" onClick={handleAuth}>
            Continue with Microsoft
          </button>
        </section>
      </main>
    )
  }

  if (showOnboarding) {
    return (
      <OnboardingView
        token={backendToken}
        supabaseToken={supabaseToken}
        userEmail={user?.email}
        onComplete={() => {
          localStorage.setItem('meetvault-onboarding-completed', 'true')
          setShowOnboarding(false)
        }}
      />
    )
  }

  if (!hasPreferenceLoaded || isPreferenceLoading) {
    return (
      <main className="login-gate">
        <section className="login-card" aria-label="Loading MeetVault preferences">
          <div className="brand-lockup">
            <div className="brand-mark">M</div>
            <div>
              <p className="eyebrow">MeetVault AI</p>
              <h1>Preparing your workspace</h1>
            </div>
          </div>
          <p>Loading your answer style...</p>
        </section>
      </main>
    )
  }

  if (!outputPreference) {
    const previewMeta = getOutputFormatMeta(previewFormat)

    return (
      <main className="login-gate preference-gate">
        <section className="login-card preference-card" aria-labelledby="preference-title">
          <div className="brand-lockup">
            <div className="brand-mark">M</div>
            <div>
              <p className="eyebrow">MeetVault AI</p>
              <h1 id="preference-title">Choose your answer style</h1>
            </div>
          </div>
          <div className="preference-copy">
            <p>
              Pick how MeetVault presents grounded answers from your meeting recordings. Hover a
              style to preview it, then continue into the workspace.
            </p>
          </div>
          <div className="preference-layout">
            <div className="preference-grid" role="group" aria-label="Answer style choices">
              {OUTPUT_FORMATS.map((format) => (
                <button
                  className={
                    previewFormat === format.id
                      ? 'preference-option active'
                      : 'preference-option'
                  }
                  key={format.id}
                  type="button"
                  disabled={preferenceSaving}
                  onMouseEnter={() => setPreviewFormat(format.id)}
                  onFocus={() => setPreviewFormat(format.id)}
                  onClick={() => setPreviewFormat(format.id)}
                >
                  <span>{format.label}</span>
                  <small>{format.description}</small>
                </button>
              ))}
            </div>
            {previewFormat === 'raw' ? (
              <div className="raw-view-toggle" role="group" aria-label="Raw display mode">
                {RAW_VIEW_MODES.map((mode) => (
                  <button
                    key={mode.id}
                    type="button"
                    className={rawViewMode === mode.id ? 'raw-view-option active' : 'raw-view-option'}
                    onClick={() => setRawViewMode(mode.id)}
                  >
                    {mode.label}
                  </button>
                ))}
              </div>
            ) : null}
            <FormatPreview format={previewFormat} rawViewMode={rawViewMode} />
          </div>
          <button
            className="auth-button preference-continue"
            type="button"
            disabled={preferenceSaving}
            onClick={() => saveOutputPreference(previewFormat)}
          >
            {preferenceSaving ? 'Saving…' : `Continue with ${previewMeta.label}`}
          </button>
          {preferenceError ? <p className="feedback error">{preferenceError}</p> : null}
        </section>
      </main>
    )
  }

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Navigation and meeting chats">
        <div className="brand-lockup compact">
          <div className="brand-mark">M</div>
          <div>
            <p className="eyebrow">MeetVault AI</p>
            <h1>Workspace</h1>
          </div>
        </div>

        <nav className="sidebar-nav" aria-label="Primary navigation">
          <button
            type="button"
            className={activeNav === 'workspace' ? 'nav-tab active' : 'nav-tab'}
            onClick={() => {
              setActiveNav('workspace')
              setActiveChatId('')
              setActiveWorkspaceChatId('')
              setQuery('')
              setSearchMessage('')
              setPipelineNotice('')
            }}
          >
            Workspace
          </button>
          <button
            type="button"
            className={activeNav === 'meetings' ? 'nav-tab active' : 'nav-tab'}
            onClick={() => {
              setActiveNav('meetings')
              setActiveChatId('')
              setActiveWorkspaceChatId('')
              setQuery('')
              setSearchMessage('')
              setPipelineNotice('')
            }}
          >
            Show Meetings
          </button>
        </nav>

        <div className="sidebar-section">
          <p className="eyebrow">Workspace history</p>
          <div className="history-list compact-history">
            {workspaceChats.length === 0 ? (
              <p className="sidebar-note">Ask from Workspace to create a search thread.</p>
            ) : null}
            {workspaceChats.map((item) => {
              const isThinking = isWorkspaceChatBusy(item.id)
              return (
              <button
                className={`history-item ${item.id === activeWorkspaceChatId ? 'active' : ''}`}
                key={item.id}
                type="button"
                onClick={() => {
                  setActiveWorkspaceChatId(item.id)
                  setActiveChatId('')
                  setActiveNav('workspace')
                  setQuery('')
                  setSearchMessage('')
                  setPipelineNotice('')
                }}
              >
                <span className="history-item-row">
                  <span className="history-item-title">{item.title}</span>
                  {isThinking ? (
                    <span className="inline-spinner" aria-label="Thinking" />
                  ) : null}
                </span>
                <small>{isThinking ? 'Thinking…' : 'Workspace search'}</small>
              </button>
              )
            })}
          </div>
        </div>

        <div className="sidebar-section">
          <p className="eyebrow">Meeting chats</p>
          <div className="history-list">
            {isHistoryLoading ? <p className="sidebar-note">Loading chats…</p> : null}
            {!isHistoryLoading && meetingChats.length === 0 ? (
              <p className="sidebar-note">Open a meeting from Show Meetings to start a chat.</p>
            ) : null}
            {historyError ? <p className="sidebar-note error">{historyError}</p> : null}
            {meetingChats.filter((item) => item.status !== 'failed').map((item) => {
              const ingestion = ingestionByMeeting[item.meetingId]
              const preparing = isChatPreparing(item.status, ingestion?.status)
              const isThinking = isMeetingChatBusy(item.id)
              return (
                <button
                  className={`history-item ${item.id === activeChatId ? 'active' : ''}`}
                  key={item.id}
                  type="button"
                  onClick={() => {
                    setActiveChatId(item.id)
                    setActiveWorkspaceChatId('')
                    setActiveNav('workspace')
                    setQuery('')
                    setSearchMessage('')
                    setPipelineNotice('')
                  }}
                >
                  <span className="history-item-row">
                    <span className="history-item-title">{item.title}</span>
                    {isThinking ? (
                      <span className="inline-spinner" aria-label="Thinking" />
                    ) : preparing ? (
                      <span className="inline-spinner" aria-label="Preparing" />
                    ) : null}
                  </span>
                  <small>
                    {isThinking
                      ? 'Thinking…'
                      : item.status === 'ready'
                        ? 'Ready'
                        : preparing
                          ? 'Preparing…'
                          : item.status}
                  </small>
                </button>
              )
            })}
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
            <p className="eyebrow">Internal meeting intelligence</p>
            <h2>{mainTitle}</h2>
          </div>
          <button
            className="profile-button"
            type="button"
            onClick={() => setShowProfile((value) => !value)}
            aria-label="User profile"
            title="User profile"
          >
            <span className="presence-dot" aria-hidden="true" />
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
              </dl>
              <button className="signout-button" type="button" onClick={handleSignOut}>
                Sign out
              </button>
            </section>
          ) : null}
        </header>

        <main className={`main-panel ${activeChat || activeWorkspaceChat ? 'chat-mode' : ''}`}>
          {activeNav === 'meetings' ? (
            <MeetingsGridView
              meetings={catalogMeetings}
              syncedAt={catalogSyncedAt}
              autoSyncStatus={autoSyncStatus}
              autoSyncError={autoSyncError}
              loading={catalogLoading}
              syncing={catalogSyncing}
              error={catalogError}
              onSync={() => syncCatalog()}
              onSelectMeeting={openMeeting}
            />
          ) : null}

          {activeNav === 'workspace' && activeChat ? (
            <MeetingChatView
              title={activeChat.title}
              chatStatus={activeChat.status}
              ingestionStatus={activeIngestion}
              messages={activeChat.messages}
              query={query}
              isSearching={isMeetingChatBusy(activeChat.id)}
              searchMessage={searchMessage}
              pipelineNotice={pipelineNotice}
              outputPreference={outputPreference}
              rawViewMode={rawViewMode}
              canClearChat={
                isChatReady(activeChat.status, activeIngestion?.status) &&
                (activeChat.messages || []).length > 0 &&
                !isMeetingChatBusy(activeChat.id) &&
                !isDeletingChat
              }
              canDeleteChat={!isMeetingChatBusy(activeChat.id) && !isDeletingChat}
              isDeletingChat={isDeletingChat}
              onClearChat={() => clearMeetingChat(activeChat.id)}
              onDeleteChat={() => deleteMeetingChat(activeChat.id)}
              onQueryChange={setQuery}
              onSubmit={handleMeetingSearch}
              onSuggestedQuery={setQuery}
            />
          ) : null}

          {activeNav === 'workspace' && !activeChat ? (
            <WorkspaceLanding
              autoSyncStatus={autoSyncStatus}
              autoSyncError={autoSyncError}
              query={query}
              messages={activeWorkspaceChat?.messages || []}
              isSearching={isWorkspaceChatBusy(activeWorkspaceChat?.id)}
              searchMessage={searchMessage}
              pipelineNotice={pipelineNotice}
              outputPreference={outputPreference}
              rawViewMode={rawViewMode}
              onQueryChange={setQuery}
              onSubmit={handleWorkspaceSearch}
              onRefreshAutoSync={fetchAutoSyncStatus}
              onOpenMeetings={() => {
                setActiveNav('meetings')
                setActiveChatId('')
                setActiveWorkspaceChatId('')
                setQuery('')
                setSearchMessage('')
                setPipelineNotice('')
              }}
            />
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
              <button className="subtle-button" type="button" onClick={() => setShowSettings(false)}>
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
                <div className="settings-section">
                  <p className="eyebrow">Theme</p>
                  <div className="appearance-grid">
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
                </div>
                <div className="settings-section">
                  <p className="eyebrow">AI output</p>
                  <div className="preference-grid compact" role="group" aria-label="AI output style">
                    {OUTPUT_FORMATS.map((format) => (
                      <button
                        className={
                          outputPreference === format.id
                            ? 'preference-option active'
                            : 'preference-option'
                        }
                        key={format.id}
                        type="button"
                        disabled={preferenceSaving}
                        onMouseEnter={() => setPreviewFormat(format.id)}
                        onFocus={() => setPreviewFormat(format.id)}
                        onClick={() => saveOutputPreference(format.id)}
                      >
                        <span>{format.label}</span>
                        <small>{format.description}</small>
                      </button>
                    ))}
                  </div>
                  {(previewFormat === 'raw' || outputPreference === 'raw') ? (
                    <div className="settings-section">
                      <p className="eyebrow">Raw display</p>
                      <div className="raw-view-toggle compact" role="group" aria-label="Raw display mode">
                        {RAW_VIEW_MODES.map((mode) => (
                          <button
                            key={mode.id}
                            type="button"
                            className={
                              rawViewMode === mode.id ? 'raw-view-option active' : 'raw-view-option'
                            }
                            disabled={preferenceSaving}
                            onClick={() => saveRawViewMode(mode.id)}
                          >
                            <span>{mode.label}</span>
                            <small>{mode.description}</small>
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  <FormatPreview
                    format={previewFormat || outputPreference}
                    rawViewMode={rawViewMode}
                    compact
                  />
                  {preferenceError ? <p className="feedback error">{preferenceError}</p> : null}
                </div>
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
                <div className="mcp-panel-shell">
                  <MCPPanel token={backendToken} supabaseToken={supabaseToken} userEmail={user?.email} />
                </div>
              </div>
            )}
          </section>
        </div>
      ) : null}
    </div>
  )
}

export default App
