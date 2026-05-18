import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { supabase } from './lib/supabase'
import MCPPanel from './components/mcp/MCPPanel'
import MeetingsGridView from './views/MeetingsGridView'
import MeetingChatView from './views/MeetingChatView'
import WorkspaceLanding from './views/WorkspaceLanding'
import {
  CHAT_HISTORY_TABLE,
  CHAT_SELECT_FIELDS,
  ingestionStatusUnchanged,
  isChatPreparing,
  isChatReady,
  mapMeetingChatRow,
  MEETING_CHAT_LEGACY_QUERY,
  sanitizeChatPatch,
  shouldStartIngestion,
} from './utils/meetingChat'
import './App.css'

// In dev, use Vite proxy (/api → backend) so the API stays reachable during long syncs.
const API_BASE_URL = import.meta.env.DEV
  ? '/api'
  : import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const INGESTION_POLL_MS = 2500
const CATALOG_SYNC_MS = 5 * 60 * 1000
const REQUIRED_LOGIN_SCOPES =
  'openid profile email offline_access User.Read Calendars.Read Files.Read OnlineMeetings.Read OnlineMeetingTranscript.Read.All'
const THEME_STORAGE_KEY = 'meetvault-theme'
const SUMMARY_PROMPT =
  'Provide a concise executive summary of this meeting: key topics, decisions, action items, and open questions.'

const mcpServers = [
  {
    id: 'graph',
    name: 'Microsoft Graph',
    status: 'Meeting catalog',
    description: 'Discovers Teams calendar meetings with recordings. Ingestion runs when you open a meeting chat.',
  },
  {
    id: 'rag',
    name: 'RAG Layer',
    status: 'Grounded answers',
    description: 'Queries ChromaDB and composes grounded answers from indexed transcript chunks.',
  },
]

const bearerHeaders = (token, extraHeaders = {}) => {
  const headers = { ...extraHeaders }
  if (token) {
    headers.Authorization = `Bearer ${token}`
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
  const source = meeting.content_source || meeting.contentSource || 'teams'
  const isOnedrive = source === 'onedrive' || source === 'shared_onedrive'
  const tags = meeting.tags || []

  if (isIndexed) {
    return 'Indexed and ready for chat.'
  }
  if (isOnedrive || tags.includes('OneDrive')) {
    return 'Video on OneDrive — preparation runs when you open the chat.'
  }
  return 'Recording available — preparation runs when you open the chat.'
}

const patchCatalogMeetingIndexed = (meetings, meetingId, isIndexed) =>
  meetings.map((meeting) =>
    meeting.id === meetingId
      ? {
          ...meeting,
          isIndexed,
          summary: catalogSummaryForMeeting(meeting, isIndexed),
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
    summary: meeting.is_indexed
      ? 'Indexed and ready for chat.'
      : isOnedrive
        ? 'Video on OneDrive — preparation runs when you open the chat.'
        : 'Recording available — preparation runs when you open the chat.',
    tags: isOnedrive
      ? [meeting.organizer === 'Shared with me' ? 'Shared' : 'OneDrive', 'Video']
      : ['Teams', 'Recording'],
    isIndexed: Boolean(meeting.is_indexed),
    hasRecording: Boolean(meeting.has_recording),
  }
}

function App() {
  const [session, setSession] = useState(undefined)
  const [showProfile, setShowProfile] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [settingsView, setSettingsView] = useState('appearance')
  const [theme, setTheme] = useState(() => localStorage.getItem(THEME_STORAGE_KEY) || 'light')

  const [activeNav, setActiveNav] = useState('workspace')
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
  const ingestionStartAttemptedRef = useRef(new Set())
  const activeChatIdRef = useRef('')
  const meetingChatsRef = useRef([])
  const ingestionByMeetingRef = useRef({})
  const graphTokenRef = useRef('')
  const pollIngestionRef = useRef(async () => {})
  const catalogSyncInFlightRef = useRef(false)
  const catalogBootstrapDoneRef = useRef(false)
  const syncCatalogRef = useRef(null)
  const lastBackendWarnAtRef = useRef(0)

  const [query, setQuery] = useState('')
  const [isSearching, setIsSearching] = useState(false)
  const [isDeletingChat, setIsDeletingChat] = useState(false)
  const [searchMessage, setSearchMessage] = useState('')
  const [pipelineNotice, setPipelineNotice] = useState('')

  const graphToken = session?.provider_token || ''
  const supabaseToken = session?.access_token || ''
  const backendToken = graphToken || supabaseToken
  const user = session?.user
  const userId = user?.id

  meetingChatsRef.current = meetingChats
  ingestionByMeetingRef.current = ingestionByMeeting
  graphTokenRef.current = graphToken
  activeChatIdRef.current = activeChatId

  const activeChat = useMemo(
    () => meetingChats.find((chat) => chat.id === activeChatId) || null,
    [activeChatId, meetingChats],
  )

  const activeIngestion = activeChat?.meetingId
    ? ingestionByMeeting[activeChat.meetingId]
    : null

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
      token: graphToken || session?.access_token || 'No token',
    }
  }, [graphToken, session?.access_token, user])

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
      const rows = (data || []).map(mapMeetingChatRow)
      setMeetingChats(rows)
      setActiveChatId((current) =>
        rows.some((item) => item.id === current) ? current : rows[0]?.id || '',
      )
    }

    setIsHistoryLoading(false)
  }, [userId])

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
      setMeetingChats((items) => [row, ...items.filter((item) => item.id !== row.id)])
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
        setMeetingChats((items) =>
          [updated, ...items.filter((item) => item.id !== updated.id)],
        )
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

        const normalized = (payload.meetings || []).map(normalizeCatalogMeeting)
        setCatalogMeetings(normalized)
        setCatalogSyncedAt(payload.synced_at || null)

        if (payload.sync_status === 'FAILED' && payload.sync_error && !silent) {
          setCatalogError(payload.sync_error)
          return payload
        }

        if (payload.sync_error && !silent) {
          setCatalogError(payload.sync_error)
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
          headers: { Authorization: `Bearer ${graphToken}` },
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

      try {
        const response = await fetch(`${API_BASE_URL}/rag/query`, {
          method: 'POST',
          headers: bearerHeaders(token, { 'Content-Type': 'application/json' }),
          body: JSON.stringify({
            query: SUMMARY_PROMPT,
            meeting_id: chat.meetingId,
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
          id: `summary-${crypto.randomUUID()}`,
          role: 'assistant',
          text,
          mode: payload.answer_mode || 'extractive_summary',
          sourceCount: (payload.sources || []).length,
          createdAt: new Date().toISOString(),
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
      }
    },
    [persistChat],
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

      setActiveNav('workspace')
      setQuery('')
      setSearchMessage('')
      setPipelineNotice('')

      const ingestion = await fetchIngestionStatus(meetingId)
      const isEmbedded = ingestion?.status === 'EMBEDDED'

      let chat = meetingChatsRef.current.find((item) => item.meetingId === meetingId)
      if (!chat) {
        chat = await upsertMeetingChat({
          meetingId,
          title,
          status: isEmbedded ? 'ready' : 'preparing',
          messages: [],
        })
      } else if (!isEmbedded && chat.status === 'ready') {
        const reset = await persistChat(chat.id, { status: 'preparing', messages: [] })
        chat = reset || { ...chat, status: 'preparing', messages: [] }
      }

      if (!chat) return

      setActiveChatId(chat.id)

      if (isEmbedded) {
        setCatalogMeetings((items) => patchCatalogMeetingIndexed(items, meetingId, true))
        await markChatReady(chat)
        return
      }

      setCatalogMeetings((items) => patchCatalogMeetingIndexed(items, meetingId, false))

      if (['FAILED', 'NO_TRANSCRIPT'].includes(ingestion?.status)) {
        await persistChat(chat.id, { status: 'failed' })
        return
      }

      if (chat.status !== 'preparing') {
        await persistChat(chat.id, { status: 'preparing' })
      }

      if (shouldStartIngestion(ingestion)) {
        ingestionStartAttemptedRef.current.add(meetingId)
        try {
          await startMeetingIngestion(meetingId)
        } catch (error) {
          console.error(error)
          setCatalogError(error.message)
          await persistChat(chat.id, { status: 'failed' })
          ingestionStartAttemptedRef.current.delete(meetingId)
        }
      }
    },
    [
      fetchIngestionStatus,
      markChatReady,
      persistChat,
      startMeetingIngestion,
      upsertMeetingChat,
    ],
  )

  const deleteMeetingChat = useCallback(
    async (chatId) => {
      const chat = meetingChatsRef.current.find((item) => item.id === chatId)
      if (!chat?.id || !chat.meetingId) return

      const confirmed = window.confirm(
        'Delete this meeting chat and remove all indexed transcript data for this meeting? You can open the meeting again later to re-prepare it.',
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
        ingestionStartAttemptedRef.current.delete(meetingId)

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
            setCatalogMeetings((payload.meetings || []).map(normalizeCatalogMeeting))
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

      setIsSearching(true)
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

        const assistantMessage = {
          id: `assistant-${crypto.randomUUID()}`,
          role: 'assistant',
          text: answerText,
          mode: payload.answer_mode || 'rag_answer',
          createdAt: new Date().toISOString(),
        }

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
        setIsSearching(false)
      }
    },
    [activeChat, activeIngestion?.status, persistChat, query],
  )

  useEffect(() => {
    const fetchSession = async () => {
      const { data, error } = await supabase.auth.getSession()
      if (error) console.error(error)
      setSession(data.session)
    }

    fetchSession()

    const { data: authListener } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      if (!nextSession) {
        setMeetingChats([])
        setActiveChatId('')
        setCatalogMeetings([])
        setCatalogSyncedAt(null)
        setIngestionByMeeting({})
        summaryRequestedRef.current = new Set()
        ingestionStartAttemptedRef.current = new Set()
        catalogBootstrapDoneRef.current = false
      }
      setSession(nextSession)
    })

    return () => authListener.subscription.unsubscribe()
  }, [])

  useEffect(() => {
    if (!userId) return
    loadMeetingChats()
    loadCatalog()
  }, [loadCatalog, loadMeetingChats, userId])

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

    const intervalId = window.setInterval(() => {
      void syncCatalogRef.current?.({ silent: true })
    }, CATALOG_SYNC_MS)

    return () => window.clearInterval(intervalId)
  }, [checkBackendHealth, graphToken, userId])

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

        if (
          payload?.status === 'NOT_STARTED' &&
          graphTokenRef.current &&
          !ingestionStartAttemptedRef.current.has(chat.meetingId)
        ) {
          ingestionStartAttemptedRef.current.add(chat.meetingId)
          try {
            await startMeetingIngestion(chat.meetingId)
            payload = await fetchIngestionStatus(chat.meetingId)
          } catch (error) {
            console.error(error)
            setCatalogError(error.message)
            await persistChat(chat.id, { status: 'failed' })
            ingestionStartAttemptedRef.current.delete(chat.meetingId)
            return
          }
        }

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
      options: { scopes: REQUIRED_LOGIN_SCOPES },
    })
    if (error) console.error(error)
  }

  const handleSignOut = async () => {
    await supabase.auth.signOut()
    setShowProfile(false)
  }

  const mainTitle = activeChat?.title || (activeNav === 'meetings' ? 'Meetings' : 'Workspace')

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
              MeetVault discovers Teams calendar meetings with recordings, prepares transcripts when you
              open a chat, and answers questions grounded in your meeting content.
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
            onClick={() => setActiveNav('workspace')}
          >
            Workspace
          </button>
          <button
            type="button"
            className={activeNav === 'meetings' ? 'nav-tab active' : 'nav-tab'}
            onClick={() => setActiveNav('meetings')}
          >
            Show Meetings
          </button>
        </nav>

        <div className="sidebar-section">
          <p className="eyebrow">Meeting chats</p>
          <div className="history-list">
            {isHistoryLoading ? <p className="sidebar-note">Loading chats…</p> : null}
            {!isHistoryLoading && meetingChats.length === 0 ? (
              <p className="sidebar-note">Open a meeting from Show Meetings to start a chat.</p>
            ) : null}
            {historyError ? <p className="sidebar-note error">{historyError}</p> : null}
            {meetingChats.map((item) => {
              const ingestion = ingestionByMeeting[item.meetingId]
              const preparing = isChatPreparing(item.status, ingestion?.status)
              return (
                <button
                  className={`history-item ${item.id === activeChatId ? 'active' : ''}`}
                  key={item.id}
                  type="button"
                  onClick={() => {
                    setActiveChatId(item.id)
                    setActiveNav('workspace')
                  }}
                >
                  <span className="history-item-row">
                    <span className="history-item-title">{item.title}</span>
                    {preparing ? <span className="inline-spinner" aria-label="Preparing" /> : null}
                  </span>
                  <small>{item.status === 'ready' ? 'Ready' : preparing ? 'Preparing…' : item.status}</small>
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

        <main className={`main-panel ${activeChat ? 'chat-mode' : ''}`}>
          {activeNav === 'meetings' ? (
            <MeetingsGridView
              meetings={catalogMeetings}
              syncedAt={catalogSyncedAt}
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
              isSearching={isSearching}
              searchMessage={searchMessage}
              pipelineNotice={pipelineNotice}
              canClearChat={
                isChatReady(activeChat.status, activeIngestion?.status) &&
                (activeChat.messages || []).length > 0 &&
                !isSearching &&
                !isDeletingChat
              }
              canDeleteChat={!isSearching && !isDeletingChat}
              isDeletingChat={isDeletingChat}
              onClearChat={() => clearMeetingChat(activeChat.id)}
              onDeleteChat={() => deleteMeetingChat(activeChat.id)}
              onQueryChange={setQuery}
              onSubmit={handleMeetingSearch}
              onSuggestedQuery={setQuery}
            />
          ) : null}

          {activeNav === 'workspace' && !activeChat ? (
            <WorkspaceLanding onOpenMeetings={() => setActiveNav('meetings')} />
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
