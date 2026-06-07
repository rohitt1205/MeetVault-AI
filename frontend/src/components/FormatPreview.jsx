import AnswerPresentation from './AnswerPresentation'
import { SAMPLE_ANSWER_TEXT } from '../utils/answerFormatting'
import { getOutputFormatMeta, normalizeOutputFormat, normalizeRawViewMode } from '../utils/outputPreferences'

export const resolveMessageFormat = (turn, fallbackFormat) =>
  normalizeOutputFormat(turn?.outputFormat || fallbackFormat)

export const resolveMessageRawView = (turn, fallbackRawView) =>
  normalizeRawViewMode(turn?.rawViewMode || fallbackRawView)

export default function FormatPreview({
  format,
  rawViewMode,
  text = SAMPLE_ANSWER_TEXT,
  mode = 'extractive_summary',
  compact = false,
}) {
  const meta = getOutputFormatMeta(format)
  const resolvedRawView = normalizeRawViewMode(rawViewMode)

  return (
    <div className={`format-preview ${compact ? 'compact' : ''}`} aria-live="polite">
      <div className="format-preview-head">
        <span className="format-preview-label">Live preview</span>
        <strong>
          {meta.label}
          {format === 'raw' ? ` · ${resolvedRawView === 'markdown' ? 'Markdown' : 'Plain'}` : ''}
        </strong>
      </div>
      <div className="format-preview-frame">
        <AnswerPresentation
          text={text}
          mode={mode}
          format={format}
          rawViewMode={resolvedRawView}
          showCopy={false}
          showKicker={false}
        />
      </div>
    </div>
  )
}
