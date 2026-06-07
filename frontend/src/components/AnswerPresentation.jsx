import { useMemo, useState } from 'react'
import ChatMarkdown from './ChatMarkdown'
import AnswerSourcesFooter from './AnswerSourcesFooter'
import {
  DEFAULT_OUTPUT_FORMAT,
  DEFAULT_RAW_VIEW_MODE,
  getOutputFormatMeta,
  normalizeOutputFormat,
  normalizeRawViewMode,
} from '../utils/outputPreferences'
import {
  parseAnswerContent,
  resolveInsightCanvasView,
  shouldShowFormatKicker,
} from '../utils/answerFormatting'
import { shouldShowAnswerSources } from '../utils/meetingChat'

const CopyAnswerButton = ({ text }) => {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    const value = (text || '').trim()
    if (!value) return

    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1800)
    } catch {
      setCopied(false)
    }
  }

  return (
    <button
      type="button"
      className="copy-answer-button"
      onClick={handleCopy}
      aria-label={copied ? 'Copied answer' : 'Copy answer'}
    >
      {copied ? 'Copied' : 'Copy'}
    </button>
  )
}

export default function AnswerPresentation({
  text,
  mode,
  format = DEFAULT_OUTPUT_FORMAT,
  rawViewMode = DEFAULT_RAW_VIEW_MODE,
  sourceCount,
  sources = [],
  showCopy = true,
  showKicker = true,
}) {
  const normalizedFormat = normalizeOutputFormat(format)
  const meta = getOutputFormatMeta(normalizedFormat)
  const parsed = useMemo(
    () => parseAnswerContent(text, mode, meta?.label || 'Meeting answer'),
    [text, mode, meta?.label],
  )
  const canvasView = useMemo(
    () => resolveInsightCanvasView(parsed, meta?.label || 'Meeting summary'),
    [parsed, meta?.label],
  )

  const kickerVisible = showKicker && shouldShowFormatKicker(normalizedFormat, mode)
  const toolbar = showCopy ? <CopyAnswerButton text={text} /> : null
  const showSourcesFooter = shouldShowAnswerSources(mode, sources)
  const resolvedSourceCount =
    typeof sourceCount === 'number' ? sourceCount : sources.length

  let presentation = null

  if (parsed.useSimpleLayout) {
    presentation = (
      <div className="answer-presentation answer-simple">
        {toolbar}
        <div className="answer-simple-body">
          <ChatMarkdown text={text} />
        </div>
      </div>
    )
  } else if (normalizedFormat === 'raw') {
    const resolvedRawView = normalizeRawViewMode(rawViewMode)

    presentation = (
      <div className="answer-presentation answer-raw-wrap">
        {toolbar}
        {resolvedRawView === 'markdown' ? (
          <div className="answer-raw-markdown">
            <ChatMarkdown text={text || 'No answer text available yet.'} />
          </div>
        ) : (
          <pre className="answer-raw-output">{text || 'No answer text available yet.'}</pre>
        )}
      </div>
    )
  } else if (normalizedFormat === 'bullets') {
    const items = parsed.bullets.length ? parsed.bullets : [parsed.highlight]

    presentation = (
      <div className="answer-presentation answer-bullet-brief">
        <div className="answer-format-head">
          <div>
            {kickerVisible ? <span>{meta.shortLabel}</span> : null}
            <strong>{parsed.title}</strong>
          </div>
          {toolbar}
        </div>
        <ul>
          {items.map((item, index) => (
            <li key={`${mode || 'answer'}-${index}`}>{item}</li>
          ))}
        </ul>
      </div>
    )
  } else if (normalizedFormat === 'insight_canvas') {
    const sectionItemLimit = 8

    presentation = (
      <article className="answer-presentation answer-insight-canvas" aria-label={canvasView.title}>
        <div className="canvas-grid" aria-hidden="true" />
        <div className="canvas-content">
          <div className="canvas-top-row">
            <div>
              {kickerVisible ? <span className="canvas-kicker">{meta.shortLabel}</span> : null}
              <h3>{canvasView.title}</h3>
            </div>
            <div className="canvas-meta">
              {resolvedSourceCount > 0 ? (
                <span className="canvas-source-badge">{resolvedSourceCount} sources</span>
              ) : null}
              {toolbar}
            </div>
          </div>
          {canvasView.showLead ? <p className="canvas-lead">{parsed.highlight}</p> : null}
          {canvasView.showSections ? (
            <div className="canvas-section-grid">
              {canvasView.sections.map((section) => (
                <div className="canvas-section" key={section.id}>
                  <span>{section.label}</span>
                  <ul>
                    {section.items.slice(0, sectionItemLimit).map((item, index) => (
                      <li key={`${section.id}-${index}`}>{item}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          ) : null}
          {canvasView.showBody ? (
            <div className="canvas-full-body">
              <ChatMarkdown text={canvasView.body} />
            </div>
          ) : null}
        </div>
      </article>
    )
  } else {
    presentation = (
      <article className="answer-presentation answer-visual-card">
        <div className="answer-card-top">
          <div>
            <strong className="answer-card-title">{parsed.title}</strong>
          </div>
          {toolbar}
        </div>
        <div className="answer-card-body">
          <ChatMarkdown text={parsed.body} />
        </div>
      </article>
    )
  }

  return (
    <div className="answer-presentation-stack">
      {presentation}
      {showSourcesFooter ? <AnswerSourcesFooter sources={sources} /> : null}
    </div>
  )
}
