const renderInline = (text, keyPrefix) => {
  const parts = []
  const pattern = /\*\*(.+?)\*\*/g
  let lastIndex = 0
  let match = pattern.exec(text)
  let index = 0

  while (match) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index))
    }
    parts.push(
      <strong key={`${keyPrefix}-strong-${index}`}>{match[1]}</strong>,
    )
    lastIndex = match.index + match[0].length
    match = pattern.exec(text)
    index += 1
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }

  return parts.length ? parts : [text]
}

const parseBlocks = (text) => {
  const blocks = []
  let listItems = null
  let listOrdered = false

  const flushList = () => {
    if (!listItems?.length) return
    blocks.push({
      type: listOrdered ? 'ol' : 'ul',
      items: listItems,
    })
    listItems = null
    listOrdered = false
  }

  for (const rawLine of (text || '').split('\n')) {
    const line = rawLine.trimEnd()
    const trimmed = line.trim()

    if (!trimmed) {
      flushList()
      continue
    }

    if (trimmed.startsWith('### ')) {
      flushList()
      blocks.push({ type: 'h4', text: trimmed.slice(4) })
      continue
    }

    if (trimmed.startsWith('## ')) {
      flushList()
      blocks.push({ type: 'h3', text: trimmed.slice(3) })
      continue
    }

    if (trimmed.startsWith('# ')) {
      flushList()
      blocks.push({ type: 'h2', text: trimmed.slice(2) })
      continue
    }

    const bulletMatch = trimmed.match(/^[-*•]\s+(.+)/)
    if (bulletMatch) {
      if (!listItems || listOrdered) {
        flushList()
        listItems = []
        listOrdered = false
      }
      listItems.push(bulletMatch[1])
      continue
    }

    const orderedMatch = trimmed.match(/^\d+\.\s+(.+)/)
    if (orderedMatch) {
      if (!listItems || !listOrdered) {
        flushList()
        listItems = []
        listOrdered = true
      }
      listItems.push(orderedMatch[1])
      continue
    }

    flushList()
    blocks.push({ type: 'p', text: trimmed })
  }

  flushList()
  return blocks
}

export default function ChatMarkdown({ text }) {
  const blocks = parseBlocks(text)

  return (
    <div className="chat-markdown">
      {blocks.map((block, index) => {
        const key = `block-${index}`

        if (block.type === 'h2') {
          return <h2 key={key}>{renderInline(block.text, key)}</h2>
        }
        if (block.type === 'h3') {
          return <h3 key={key}>{renderInline(block.text, key)}</h3>
        }
        if (block.type === 'h4') {
          return <h4 key={key}>{renderInline(block.text, key)}</h4>
        }
        if (block.type === 'ul') {
          return (
            <ul key={key}>
              {block.items.map((item, itemIndex) => (
                <li key={`${key}-li-${itemIndex}`}>{renderInline(item, `${key}-li-${itemIndex}`)}</li>
              ))}
            </ul>
          )
        }
        if (block.type === 'ol') {
          return (
            <ol key={key}>
              {block.items.map((item, itemIndex) => (
                <li key={`${key}-li-${itemIndex}`}>{renderInline(item, `${key}-li-${itemIndex}`)}</li>
              ))}
            </ol>
          )
        }

        return <p key={key}>{renderInline(block.text, key)}</p>
      })}
    </div>
  )
}
