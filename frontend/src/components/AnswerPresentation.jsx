import ChatMarkdown from './ChatMarkdown'
import { DEFAULT_OUTPUT_FORMAT, getOutputFormatMeta, normalizeOutputFormat } from '../utils/outputPreferences'

const stripMarkdown = (text) =>
  (text || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/[#*_`>]/g, '')
    .replace(/\s+/g, ' ')
    .trim()

const splitSentences = (text) => {
  const normalized = stripMarkdown(text)
  if (!normalized) return []

  return normalized
    .split(/(?<=[.!?])\s+/)
    .map((sentence) => sentence.trim())
    .filter(Boolean)
}

const extractListItems = (text) =>
  (text || '')
    .split('\n')
    .map((line) => line.trim())
    .map((line) => {
      const bullet = line.match(/^[-*•]\s+(.+)/)
      if (bullet) return bullet[1].trim()

      const ordered = line.match(/^\d+\.\s+(.+)/)
      if (ordered) return ordered[1].trim()

      return ''
    })
    .filter(Boolean)

const buildBulletPoints = (text, limit = 6) => {
  const explicitItems = extractListItems(text)
  const sourceItems = explicitItems.length ? explicitItems : splitSentences(text)
  return sourceItems.slice(0, limit)
}

const buildTitle = (text, fallback) => {
  const firstLine = (text || '')
    .split('\n')
    .map((line) => stripMarkdown(line))
    .find(Boolean)

  const title = firstLine || fallback || 'Meeting answer'
  if (title.length <= 76) return title
  return `${title.slice(0, 73).trim()}...`
}

const buildHighlight = (text) => {
  const sentences = splitSentences(text)
  return sentences[0] || stripMarkdown(text) || 'No answer text available yet.'
}

export default function AnswerPresentation({ text, mode, format = DEFAULT_OUTPUT_FORMAT }) {
  const normalizedFormat = normalizeOutputFormat(format)
  const meta = getOutputFormatMeta(normalizedFormat)
  const title = buildTitle(text, meta?.label)
  const bullets = buildBulletPoints(text)
  const highlight = buildHighlight(text)

  if (normalizedFormat === 'raw') {
    return (
      <pre className="answer-presentation answer-raw-output">
        {text || 'No answer text available yet.'}
      </pre>
    )
  }

  if (normalizedFormat === 'bullets') {
    return (
      <div className="answer-presentation answer-bullet-brief">
        <div className="answer-format-head">
          <span>{meta.shortLabel}</span>
          <strong>{title}</strong>
        </div>
        <ul>
          {(bullets.length ? bullets : [highlight]).map((item, index) => (
            <li key={`${mode || 'answer'}-${index}`}>{item}</li>
          ))}
        </ul>
      </div>
    )
  }

  if (normalizedFormat === 'insight_canvas') {
    return (
      <article className="answer-presentation answer-insight-canvas" aria-label={title}>
        <div className="canvas-grid" aria-hidden="true" />
        <div className="canvas-content">
          <span className="canvas-kicker">{meta.shortLabel}</span>
          <h3>{title}</h3>
          <p>{highlight}</p>
          <div className="canvas-pill-row" aria-label="Key points">
            {(bullets.length ? bullets.slice(0, 3) : [highlight]).map((item, index) => (
              <span key={`${mode || 'canvas'}-${index}`}>{item}</span>
            ))}
          </div>
        </div>
      </article>
    )
  }

  return (
    <article className="answer-presentation answer-visual-card">
      <div className="answer-card-top">
        <div>
          <span>{meta.shortLabel}</span>
          <h3>{title}</h3>
        </div>
      </div>
      <div className="answer-card-body">
        <ChatMarkdown text={text} />
      </div>
    </article>
  )
}
