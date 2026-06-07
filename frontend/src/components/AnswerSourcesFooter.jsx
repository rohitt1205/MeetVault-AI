import { formatCitationTimeLabel } from '../utils/meetingChat'

export default function AnswerSourcesFooter({ sources = [] }) {
  if (!sources.length) return null

  return (
    <details className="answer-sources-footer source-details">
      <summary>{`Sources & proof (${sources.length})`}</summary>
      <ol className="source-list">
        {sources.map((source, index) => (
          <li className="source-item" key={source.id || `source-${index}`}>
            <div className="source-proof-meta">
              {source.topic ? (
                <span className="source-topic">{source.topic}</span>
              ) : null}
              <span className="source-time">
                {formatCitationTimeLabel(source) || 'Time not available'}
              </span>
              {source.speaker ? (
                <span className="source-speaker">{source.speaker}</span>
              ) : null}
            </div>
            {source.meetingTitle ? (
              <span className="source-meeting">{source.meetingTitle}</span>
            ) : null}
            <p>{source.excerpt}</p>
          </li>
        ))}
      </ol>
    </details>
  )
}
