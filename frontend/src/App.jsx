import { useEffect, useMemo, useState } from 'react'

import { supabase } from './lib/supabase'

import './App.css'
 
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

const CHAT_HISTORY_TABLE = 'chat_history'
 
const initialMeetings = [

  {

    id: 'mv-101',

    title: 'Hackathon Sync',

    team: 'Team 6',

    time: 'Today, 10:00 AM',

    summary: 'Graph API integration, transcript ingestion, and RAG milestones.',

    tags: ['Graph API', 'RAG', 'Backend'],

  },

  {

    id: 'mv-102',

    title: 'Backend Pipeline Review',

    team: 'MeetVault AI',

    time: 'Yesterday, 5:30 PM',

    summary: 'Chunking strategy, embeddings, ChromaDB persistence, and search API.',

    tags: ['ChromaDB', 'Embeddings'],

  },

  {

    id: 'mv-103',

    title: 'Product UX Notes',

    team: 'Frontend',

    time: 'May 15, 3:00 PM',

    summary: 'Search-first interface, recent meetings context, and MCP settings.',

    tags: ['UX', 'Agent Context'],

  },

]
 
const mcpServers = [

  {

    id: 'jira',

    name: 'Jira',

    status: 'Planned',

    description: 'Map meeting action items to tickets and sprint context.',

  },

  {

    id: 'graph',

    name: 'Microsoft Graph',

    status: 'Ready',

    description: 'Fetch Teams meetings, transcripts, and organizer metadata.',

  },

  {

    id: 'notion',

    name: 'Notion',

    status: 'Optional',

    description: 'Publish meeting notes and decision logs to team pages.',

  },

]
 
const mapHistoryRow = (row) => ({

  id: row.id,

  title: row.title,

  preview: row.preview || (row.meeting_title ? `Context: ${row.meeting_title}` : ''),

  query: row.query,

  meetingId: row.meeting_id,

  meetingTitle: row.meeting_title,

  createdAt: row.created_at,

})
 
function App() {

  const [session, setSession] = useState(undefined)

  const [showSettings, setShowSettings] = useState(false)

  const [showProfile, setShowProfile] = useState(false)

  const [settingsView, setSettingsView] = useState('appearance')

  const [theme, setTheme] = useState('light')

  const [query, setQuery] = useState('')

  const [isSearching, setIsSearching] = useState(false)
 
  const [history, setHistory] = useState([])

  const [activeHistoryId, setActiveHistoryId] = useState('')

  const [isHistoryLoading, setIsHistoryLoading] = useState(false)

  const [historyError, setHistoryError] = useState('')
 
  const [meetings, setMeetings] = useState(initialMeetings)

  const [selectedMeetingId, setSelectedMeetingId] = useState(initialMeetings[0].id)
 
  const authToken = session?.access_token || ''

  const user = session?.user
 
  const activeHistory = useMemo(

    () => history.find((item) => item.id === activeHistoryId),

    [activeHistoryId, history],

  )
 
  const selectedMeeting = useMemo(

    () => meetings.find((meeting) => meeting.id === selectedMeetingId) || meetings[0],

    [meetings, selectedMeetingId],

  )
 
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

      tokenPreview: authToken ? `${authToken.slice(0, 24)}...` : 'No token',

    }

  }, [authToken, user])
 
  useEffect(() => {

    document.documentElement.dataset.theme = theme

  }, [theme])
 
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

      setSession(nextSession)

    })
 
    return () => {

      authListener.subscription.unsubscribe()

    }

  }, [])
 
  useEffect(() => {

    if (!session?.user?.id) {

      setHistory([])

      setActiveHistoryId('')

      return

    }
 
    let ignore = false
 
    const loadHistory = async () => {

      setIsHistoryLoading(true)

      setHistoryError('')
 
      const { data, error } = await supabase

        .from(CHAT_HISTORY_TABLE)

        .select('id,title,preview,query,meeting_id,meeting_title,created_at')

        .order('created_at', { ascending: false })
 
      if (ignore) return
 
      if (error) {

        console.error('History load failed:', error)

        setHistoryError('History could not be loaded.')

        setHistory([])

        setActiveHistoryId('')

      } else {

        const savedHistory = data.map(mapHistoryRow)

        setHistory(savedHistory)

        setActiveHistoryId(savedHistory[0]?.id || '')

      }
 
      setIsHistoryLoading(false)

    }
 
    loadHistory()
 
    return () => {

      ignore = true

    }

  }, [session?.user?.id])
 
  const handleAuth = async () => {

    const { error } = await supabase.auth.signInWithOAuth({

      provider: 'azure',

      options: {

        scopes: 'openid profile email User.Read',

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
 
  const handleSearch = async (event) => {

    event.preventDefault()
 
    const trimmedQuery = query.trim()

    if (!trimmedQuery) return
 
    const historyItem = {

      id: `local-${Date.now()}`,

      title: trimmedQuery,

      preview: selectedMeeting ? `Context: ${selectedMeeting.title}` : 'New agent conversation',

      query: trimmedQuery,

      meetingId: selectedMeeting?.id || null,

      meetingTitle: selectedMeeting?.title || null,

    }
 
    setHistory((items) => [historyItem, ...items])

    setActiveHistoryId(historyItem.id)

    setIsSearching(true)

    setHistoryError('')
 
    try {

      const { data: savedHistory, error: historyInsertError } = await supabase

        .from(CHAT_HISTORY_TABLE)

        .insert({
          user_id: session?.user?.id,
          title: historyItem.title,
          preview: historyItem.preview,
          query: historyItem.query,
          meeting_id: historyItem.meetingId,
          meeting_title: historyItem.meetingTitle,
        })

        .select('id,title,preview,query,meeting_id,meeting_title,created_at')

        .single()
 
      if (historyInsertError) {

        console.error('History insert failed:', historyInsertError)

        setHistoryError('This chat is only saved locally until history storage is ready.')

      } else {

        const persistedHistory = mapHistoryRow(savedHistory)
 
        setHistory((items) =>

          items.map((item) => (item.id === historyItem.id ? persistedHistory : item)),

        )
 
        setActiveHistoryId(persistedHistory.id)

      }
 
      const response = await fetch(

        `${API_BASE_URL}/search?query=${encodeURIComponent(trimmedQuery)}`,

        {

          headers: authToken

            ? {

                Authorization: `Bearer ${authToken}`,

                'X-Meeting-Context': selectedMeeting?.id || '',

              }

            : undefined,

        },

      )
 
      if (!response.ok) {

        throw new Error('Search request failed')

      }

    } catch (error) {

      console.error(error)

    } finally {

      setIsSearching(false)

      setQuery('')

    }

  }
 
  const refreshLatestMeetings = async () => {

    try {

      const response = await fetch(`${API_BASE_URL}/meetings/recent`, {

        headers: authToken ? { Authorization: `Bearer ${authToken}` } : undefined,

      })
 
      if (!response.ok) {

        throw new Error('Meeting request failed')

      }
 
      const data = await response.json()

      const normalizedMeetings = data.map((meeting) => ({

        id: meeting.meeting_id,

        title: meeting.title,

        team: meeting.organizer || 'Microsoft Teams',

        time: meeting.start_time || 'Latest',

        summary:

          'Retrieved from Microsoft Graph. RAG topics will attach after transcript ingestion.',

        tags: ['Graph', 'Latest'],

      }))
 
      if (normalizedMeetings.length > 0) {

        setMeetings(normalizedMeetings)

        setSelectedMeetingId(normalizedMeetings[0].id)

      }

    } catch (error) {

      console.error(error)

      setMeetings(initialMeetings)

      setSelectedMeetingId(initialMeetings[0].id)

    }

  }
 
  if (session === undefined) {

    return (
<main className="login-gate">
<section className="login-card" aria-label="Loading MeetVault">
<div className="brand-block login-brand">
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
<div className="brand-block login-brand">
<div className="brand-mark">M</div>
<div>
<p className="eyebrow">MeetVault AI</p>
<h1>Secure meeting intelligence</h1>
</div>
</div>
 
          <div className="login-copy">
<p className="eyebrow">Required authentication</p>
<h2 id="login-title">Connect with Microsoft to continue</h2>
<p>

              MeetVault uses Supabase with Azure OAuth. After login, the session token can

              be passed to backend routes for Graph, RAG, and meeting-scoped search.
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
<aside className="sidebar" aria-label="Conversation history">
<div className="brand-block">
<div className="brand-mark">M</div>
<div>
<p className="eyebrow">MeetVault AI</p>
<h1>Workspace</h1>
</div>
</div>
 
        <button

          className="new-chat-button"

          type="button"

          onClick={() => {

            setActiveHistoryId('')

            setQuery('')

          }}
>
<span aria-hidden="true">+</span>

          New chat
</button>
 
        <nav className="history-list" aria-label="Recent agent chats">
<p className="sidebar-label">History</p>
 
          {isHistoryLoading ? <p className="history-note">Loading history...</p> : null}
 
          {!isHistoryLoading && history.length === 0 ? (
<p className="history-note">Your saved chats will appear here.</p>

          ) : null}
 
          {!isHistoryLoading

            ? history.map((item) => (
<button

                  className={`history-item ${item.id === activeHistoryId ? 'active' : ''}`}

                  key={item.id}

                  type="button"

                  onClick={() => {

                    setActiveHistoryId(item.id)

                    setQuery(item.query || '')

                  }}
>
<span>{item.title}</span>
<small>{item.preview}</small>
</button>

              ))

            : null}
 
          {historyError ? <p className="history-note error">{historyError}</p> : null}
</nav>
 
        <button

          className="settings-button"

          type="button"

          onClick={() => setShowSettings(true)}
>

          Settings
</button>
</aside>
 
      <main className="main-panel">
<header className="topbar">
<div>
<p className="eyebrow">Internal meeting intelligence</p>
<h2>{activeHistory?.title || 'Ask about your meetings'}</h2>
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
<div className="profile-avatar">

                  {userProfile.name.slice(0, 2).toUpperCase()}
</div>
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
<dt>Access token</dt>
<dd>{userProfile.tokenPreview}</dd>
</div>
</dl>
 
              <button className="signout-button" type="button" onClick={handleSignOut}>

                Sign out
</button>
</section>

          ) : null}
</header>
 
        <section className="ask-zone" aria-label="Ask MeetVault">
<div className="search-wrap">
<div className="context-strip">
<span>Context</span>
<strong>{selectedMeeting?.title}</strong>
<small>{selectedMeeting?.time}</small>
</div>
<p className="eyebrow">Ask the agent</p>
<form className="search-form" onSubmit={handleSearch}>
<textarea

                aria-label="Ask about meeting transcripts"

                value={query}

                onChange={(event) => setQuery(event.target.value)}

                placeholder="Ask anything about meetings, decisions, blockers, or action items"

                rows="3"

              />
<div className="search-actions">
<span className="context-note">Using selected latest meeting only</span>
<button className="send-button" type="submit" disabled={isSearching}>

                  {isSearching ? 'Searching' : 'Send'}
</button>
</div>
</form>
</div>
 
          <section className="meetings-section" aria-labelledby="meetings-title">
<div className="section-header">
<div>
<p className="eyebrow">Agent context</p>
<h3 id="meetings-title">Latest meetings</h3>
</div>
<button className="ghost-button" type="button" onClick={refreshLatestMeetings}>

                Refresh
</button>
</div>
 
            <div className="meeting-list">

              {meetings.map((meeting) => (
<button

                  className={`meeting-card ${

                    meeting.id === selectedMeetingId ? 'selected' : ''

                  }`}

                  key={meeting.id}

                  type="button"

                  onClick={() => setSelectedMeetingId(meeting.id)}
>
<div className="meeting-card-top">
<div>
<h4>{meeting.title}</h4>
<p>{meeting.team}</p>
</div>
<time>{meeting.time}</time>
</div>
<p>{meeting.summary}</p>
<div className="tag-row">

                    {meeting.tags.map((tag) => (
<span key={tag}>{tag}</span>

                    ))}
</div>
</button>

              ))}
</div>
</section>
</section>
</main>
 
      {showSettings ? (
<div

          className="modal-backdrop"

          role="presentation"

          onMouseDown={() => setShowSettings(false)}
>
<section

            className="settings-modal"

            role="dialog"

            aria-modal="true"

            aria-labelledby="settings-title"

            onMouseDown={(event) => event.stopPropagation()}
>
<div className="modal-header">
<div>
<p className="eyebrow">Integrations</p>
<h3 id="settings-title">Settings</h3>
</div>
<button

                className="icon-button"

                type="button"

                onClick={() => setShowSettings(false)}

                aria-label="Close settings"

                title="Close"
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
<small>Clean workspace mode</small>
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
<div className="server-list">

                {mcpServers.map((server) => (
<article className="server-row" key={server.id}>
<div>
<h4>{server.name}</h4>
<p>{server.description}</p>
</div>
<button className="connect-button" type="button">

                      {server.status}
</button>
</article>

                ))}
</div>

            )}
</section>
</div>

      ) : null}
</div>

  )

}
 
export default App

 