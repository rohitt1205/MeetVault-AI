import { useEffect, useRef } from 'react'
import ChatMarkdown from '../components/ChatMarkdown'
import {
  ingestionProgressPercent,
  ingestionStageLabel,
  isChatPreparing,
  isChatReady,
  isIngestionFailed,
} from '../utils/meetingChat'

const SUGGESTED_PROMPTS = [
  'Summarize this meeting',
  'What are the main tips discussed?',
  'List action items mentioned',
]

const answerEyebrowForMode = (mode) => {
  switch (mode) {
    case 'extractive_summary':
      return 'Summary'
    case 'meeting_assistant':
    case 'conversational':
    case 'conversational_fallback':
    case 'clarification':
      return 'MeetVault'
    case 'retrieval_brief':
    case 'retrieval_only':
      return 'Assistant'
    default:
      return 'Answer'
  }
}

export default function MeetingChatView({
  title,
  chatStatus,
  ingestionStatus,
  messages,
  query,
  isSearching,
  searchMessage,
  pipelineNotice,
  onQueryChange,
  onSubmit,
  onSuggestedQuery,
  canClearChat = false,
  onClearChat,
  canDeleteChat = false,
  onDeleteChat,
  isDeletingChat = false,
}) {
  const preparing = isChatPreparing(chatStatus, ingestionStatus?.status)
  const ready = isChatReady(chatStatus, ingestionStatus?.status)
  const progress = ingestionProgressPercent(ingestionStatus)
  const stageLabel = ingestionStageLabel(ingestionStatus)
  const scrollRef = useRef(null)
  const hasMessages = messages.length > 0

  useEffect(() => {
    if (!hasMessages) return
    const container = scrollRef.current
    if (!container) return

    const scrollToBottom = () => {
      container.scrollTop = container.scrollHeight
    }

    scrollToBottom()
    const frame = window.requestAnimationFrame(scrollToBottom)
    return () => window.cancelAnimationFrame(frame)
  }, [messages, isSearching, hasMessages])

  const deleteButton = canDeleteChat ? (
    <button
      className="delete-chat-button"
      type="button"
      disabled={isDeletingChat}
      onClick={() => onDeleteChat?.()}
    >
      {isDeletingChat ? 'Deleting…' : 'Delete chat'}
    </button>
  ) : null

  if (preparing && !ready) {
    return (
      <section className="meeting-preparing" aria-label="Preparing meeting chat">
        <p className="eyebrow">Preparing the chat</p>
        <h2>{title}</h2>
        <p className="preparing-copy">
          We are discovering, downloading, transcribing, and indexing this meeting. You can leave and
          come back — preparation continues in the background.
        </p>
        <div className="progress-track" aria-hidden="true">
          <div className="progress-fill" style={{ width: `${progress}%` }} />
        </div>
        <p className="preparing-stage">
          {stageLabel} · {progress}%
        </p>
        {deleteButton ? <div className="preparing-actions">{deleteButton}</div> : null}
      </section>
    )
  }

  if (chatStatus === 'failed' || isIngestionFailed(ingestionStatus?.status)) {
    return (
      <section className="meeting-preparing failed" aria-label="Meeting preparation failed">
        <p className="eyebrow">Preparation failed</p>
        <h2>{title}</h2>
        <p className="feedback error">
          {ingestionStatus?.message ||
            'We could not prepare this meeting. Try opening it again after the recording is available.'}
        </p>
        {deleteButton ? <div className="preparing-actions">{deleteButton}</div> : null}
      </section>
    )
  }

  return (
    <section className="meeting-chat" aria-label={`Chat for ${title}`}>
      <div className="chat-shell">
        {canClearChat || canDeleteChat ? (
          <div className="chat-toolbar">
            {canClearChat ? (
              <button
                className="clear-chat-button"
                type="button"
                disabled={isSearching || isDeletingChat}
                onClick={() => onClearChat?.()}
              >
                Clear chat
              </button>
            ) : null}
            {deleteButton}
          </div>
        ) : null}

        <div
          ref={scrollRef}
          className={`meeting-chat-scroll ${hasMessages ? 'has-messages' : 'is-empty'}`}
        >
          {hasMessages ? (
            <div className="conversation-panel" aria-label="Conversation">
              {messages.map((turn, index) => (
                <div
                  className="turn-stack"
                  key={turn.id || `${turn.role}-${index}`}
                >
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
                    <span className="typing-label">Thinking…</span>
                  </div>
                </div>
              ) : null}
            </div>
          ) : (
            <div className="chat-empty-state">
              <p className="chat-empty-copy">
                Ask about decisions, action items, frameworks discussed, or follow-ups from this
                recording.
              </p>
              <div className="suggested-prompts" role="group" aria-label="Suggested questions">
                {SUGGESTED_PROMPTS.map((prompt) => (
                  <button
                    className="prompt-chip"
                    key={prompt}
                    type="button"
                    disabled={!ready || isSearching || isDeletingChat}
                    onClick={() => onSuggestedQuery?.(prompt)}
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        <form className="meeting-composer" onSubmit={onSubmit}>
          <div className="composer-field">
            <textarea
              className="composer-input"
              aria-label="Ask about this meeting"
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  event.currentTarget.form?.requestSubmit()
                }
              }}
              placeholder="Ask anything about this meeting…"
              rows={1}
              disabled={!ready || isSearching || isDeletingChat}
            />
            <button
              className="composer-send"
              type="submit"
              disabled={!ready || isSearching || isDeletingChat || !query.trim()}
              aria-label={isSearching ? 'Sending' : 'Send message'}
            >
              {isSearching ? '…' : 'Send'}
            </button>
          </div>
          <p className="composer-hint">
            {ready ? 'Enter to send · Shift+Enter for new line' : 'Preparing meeting…'}
          </p>
        </form>
      </div>

      {(pipelineNotice || searchMessage) && (
        <div className="status-stack compact chat-status-notes">
          {pipelineNotice ? <p className="feedback">{pipelineNotice}</p> : null}
          {searchMessage ? <p className="feedback error">{searchMessage}</p> : null}
        </div>
      )}
    </section>
  )
}
