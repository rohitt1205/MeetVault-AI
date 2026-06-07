/** Shared parsing + labels for assistant answer presentation. */

export const SAMPLE_ANSWER_TEXT = `## Weekly product sync

**Decision:** Ship the Docker Compose demo for the hackathon jury.

**Action items**
- Rohan finalizes EC2 deployment docs by Friday
- Team runs Supabase migration 005 before demo day
- Confirm Graph scopes for meeting transcript access

**Open question:** Do we need Mail.Send for the first live demo?

The team aligned on manual meeting prep as the primary flow — open a recording card, wait for indexing, then chat.`

export const CONVERSATIONAL_MODES = new Set([
  'conversational',
  'conversational_fallback',
  'clarification',
  'meeting_assistant',
])

export const answerEyebrowForMode = (mode) => {
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
    case 'rag_answer':
      return 'Answer'
    default:
      return 'Answer'
  }
}

export const isConversationalMode = (mode) => CONVERSATIONAL_MODES.has(mode)

export const stripMarkdownInline = (text) =>
  (text || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/[*_`>]/g, '')
    .replace(/\s+/g, ' ')
    .trim()

const normalizeLine = (line) => line.trim().replace(/^#{1,6}\s+/, '')

export const extractListItems = (text) =>
  (text || '')
    .split('\n')
    .map((line) => line.trim())
    .map((line) => {
      const bullet = line.match(/^[-*•]\s+(.+)/)
      if (bullet) return stripMarkdownInline(bullet[1])

      const ordered = line.match(/^\d+\.\s+(.+)/)
      if (ordered) return stripMarkdownInline(ordered[1])

      const labeled = line.match(/^\*\*(.+?)\*\*[:\s-]*(.*)$/)
      if (labeled) {
        const detail = labeled[2]?.trim()
        return detail
          ? stripMarkdownInline(`${labeled[1]}: ${detail}`)
          : stripMarkdownInline(labeled[1])
      }

      return ''
    })
    .filter(Boolean)

export const splitSentences = (text) => {
  const normalized = stripMarkdownInline(text)
  if (!normalized) return []

  return normalized
    .split(/(?<=[.!?])\s+/)
    .map((sentence) => sentence.trim())
    .filter(Boolean)
}

export const mergeShortFragments = (items, minLength = 28) => {
  if (!items.length) return []

  const merged = []
  for (const item of items) {
    if (merged.length && item.length < minLength) {
      merged[merged.length - 1] = `${merged[merged.length - 1]} ${item}`.trim()
    } else {
      merged.push(item)
    }
  }
  return merged
}

export const bulletLimitForMode = (mode) => {
  if (mode === 'extractive_summary' || mode === 'retrieval_brief') return 12
  if (mode === 'rag_answer') return 10
  return 8
}

export const buildBulletPoints = (text, mode) => {
  const explicitItems = extractListItems(text)
  const sourceItems = explicitItems.length ? explicitItems : splitSentences(text)
  return mergeShortFragments(sourceItems).slice(0, bulletLimitForMode(mode))
}

const SECTION_PATTERNS = [
  { id: 'decisions', label: 'Decisions', pattern: /^(decisions?|decision)\s*:?\s*$/i },
  { id: 'actions', label: 'Action items', pattern: /^(action items?|actions?|next steps?)\s*:?\s*$/i },
  { id: 'questions', label: 'Open questions', pattern: /^(open questions?|questions?)\s*:?\s*$/i },
  { id: 'topics', label: 'Key topics', pattern: /^(key topics?|topics?|discussion)\s*:?\s*$/i },
]

export const buildSections = (text) => {
  const lines = (text || '').split('\n')
  const sections = []
  let current = null

  const pushCurrent = () => {
    if (current?.items.length) sections.push(current)
    current = null
  }

  for (const rawLine of lines) {
    const line = rawLine.trim()
    if (!line) continue

    const heading = line.replace(/^#{1,6}\s+/, '')
    const sectionMatch = SECTION_PATTERNS.find(({ pattern }) => pattern.test(heading))
    if (sectionMatch) {
      pushCurrent()
      current = { ...sectionMatch, items: [] }
      continue
    }

    const listItem = extractListItems(line)
    if (listItem.length) {
      if (!current) current = { id: 'highlights', label: 'Highlights', items: [] }
      current.items.push(...listItem)
      continue
    }

    const labeled = heading.match(/^\*\*(.+?)\*\*[:\s-]*(.*)$/)
    if (labeled) {
      if (!current) current = { id: 'highlights', label: 'Highlights', items: [] }
      const detail = labeled[2]?.trim()
      current.items.push(
        detail
          ? stripMarkdownInline(`${labeled[1]}: ${detail}`)
          : stripMarkdownInline(labeled[1]),
      )
    }
  }

  pushCurrent()
  return sections.filter((section) => section.items.length)
}

export const extractTitleAndBody = (text, fallbackTitle = 'Meeting answer') => {
  const raw = (text || '').trim()
  if (!raw) {
    return { title: fallbackTitle, body: '' }
  }

  const lines = raw.split('\n')
  let titleLineIndex = -1
  let title = ''

  for (let index = 0; index < lines.length; index += 1) {
    const trimmed = lines[index].trim()
    if (!trimmed) continue

    const heading = trimmed.match(/^#{1,6}\s+(.+)/)
    if (heading) {
      title = stripMarkdownInline(heading[1])
      titleLineIndex = index
      break
    }

    if (/^[-*•]\s+/.test(trimmed)) {
      continue
    }

    title = stripMarkdownInline(trimmed)
    titleLineIndex = index
    break
  }

  const bodyLines = lines.filter((_, index) => index !== titleLineIndex)
  let body = bodyLines.join('\n').trim()

  if (!title) {
    title = fallbackTitle
    body = raw
  }

  const duplicateFirst = bodyLines.find((line) => line.trim())
  if (duplicateFirst && stripMarkdownInline(duplicateFirst) === stripMarkdownInline(title)) {
    body = bodyLines.slice(bodyLines.indexOf(duplicateFirst) + 1).join('\n').trim()
  }

  return {
    title: title || fallbackTitle,
    body: body || raw,
  }
}

export const buildHighlight = (text) => {
  const { body } = extractTitleAndBody(text)
  const paragraphs = (body || text || '')
    .split(/\n\s*\n/)
    .map((part) => stripMarkdownInline(part))
    .filter(Boolean)

  if (paragraphs[0]) return paragraphs[0]

  const sentences = splitSentences(text)
  return sentences[0] || stripMarkdownInline(text) || 'No answer text available yet.'
}

export const shouldUseSimpleLayout = (text, mode) => {
  if (isConversationalMode(mode)) return true

  const plain = stripMarkdownInline(text)
  if (!plain) return true

  const lineCount = (text || '').split('\n').filter((line) => line.trim()).length
  return plain.length < 120 && lineCount <= 2
}

export const bodyMatchesSections = (body, sections) => {
  if (!sections.length) return false

  const bodyItems = extractListItems(body)
  const sectionItems = sections.flatMap((section) => section.items)
  if (!bodyItems.length || !sectionItems.length) return false

  const normalize = (value) => stripMarkdownInline(value).toLowerCase()
  return bodyItems.every((item) =>
    sectionItems.some(
      (sectionItem) =>
        normalize(sectionItem) === normalize(item) ||
        normalize(sectionItem).includes(normalize(item)) ||
        normalize(item).includes(normalize(sectionItem)),
    ),
  )
}

export const resolveInsightCanvasView = (parsed, fallbackTitle = 'Meeting summary') => {
  const sections = parsed.sections.filter((section) => section.items.length)
  const bodyItems = extractListItems(parsed.body)
  const bulletOnlyBody =
    bodyItems.length >= 2 &&
    bodyItems.length >= (parsed.body || '').split('\n').filter((line) => line.trim()).length - 1

  let title = parsed.title
  if (
    !title ||
    title === fallbackTitle ||
    title.startsWith('-') ||
    bodyItems.some((item) => stripMarkdownInline(item) === stripMarkdownInline(title))
  ) {
    title = 'Meeting summary'
  }

  if (sections.length && bodyMatchesSections(parsed.body, sections)) {
    return {
      title,
      sections,
      body: '',
      showSections: true,
      showBody: false,
      showLead: false,
    }
  }

  if (bulletOnlyBody && sections.length === 1 && sections[0].id === 'highlights') {
    return {
      title,
      sections: [{ ...sections[0], label: 'Key points' }],
      body: '',
      showSections: true,
      showBody: false,
      showLead: false,
    }
  }

  if (sections.some((section) => section.id !== 'highlights')) {
    return {
      title,
      sections,
      body: parsed.body,
      showSections: true,
      showBody: !bodyMatchesSections(parsed.body, sections),
      showLead: false,
    }
  }

  return {
    title,
    sections: [],
    body: parsed.body || parsed.plainText,
    showSections: false,
    showBody: true,
    showLead: Boolean(parsed.highlight) && !bulletOnlyBody,
  }
}

export const parseAnswerContent = (text, mode, fallbackTitle = 'Meeting answer') => {
  const { title, body } = extractTitleAndBody(text, fallbackTitle)
  const bullets = buildBulletPoints(text, mode)
  const highlight = buildHighlight(text)
  const sections = buildSections(text)
  const useSimpleLayout = shouldUseSimpleLayout(text, mode)

  return {
    title,
    body,
    bullets,
    highlight,
    sections,
    useSimpleLayout,
    plainText: stripMarkdownInline(text),
  }
}

export const shouldShowFormatKicker = (format, mode) => {
  if (isConversationalMode(mode)) return false
  return format !== 'visual_card'
}
