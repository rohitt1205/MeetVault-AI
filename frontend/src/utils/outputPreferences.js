export const DEFAULT_OUTPUT_FORMAT = 'visual_card'

export const DEFAULT_RAW_VIEW_MODE = 'markdown'

export const RAW_VIEW_MODES = [
  {
    id: 'markdown',
    label: 'Markdown',
    description: 'Render headings and lists without card chrome.',
  },
  {
    id: 'plain',
    label: 'Plain text',
    description: 'Show the model output exactly as plain text.',
  },
]

export const RAW_VIEW_MODE_IDS = RAW_VIEW_MODES.map((mode) => mode.id)

export const isValidRawViewMode = (value) => RAW_VIEW_MODE_IDS.includes(value)

export const normalizeRawViewMode = (value) =>
  isValidRawViewMode(value) ? value : DEFAULT_RAW_VIEW_MODE

export const OUTPUT_FORMATS = [
  {
    id: 'visual_card',
    label: 'Visual card',
    shortLabel: 'Card',
    description: 'Polished answer card with a focused title and readable structure.',
  },
  {
    id: 'bullets',
    label: 'Bullet brief',
    shortLabel: 'Bullets',
    description: 'Compact bullet points for fast review.',
  },
  {
    id: 'raw',
    label: 'Raw output',
    shortLabel: 'Raw',
    description: 'Plain model text with minimal formatting.',
  },
  {
    id: 'insight_canvas',
    label: 'Insight canvas',
    shortLabel: 'Canvas',
    description: 'A visual summary panel for high-level takeaways.',
  },
]

export const OUTPUT_FORMAT_IDS = OUTPUT_FORMATS.map((format) => format.id)

export const isValidOutputFormat = (value) => OUTPUT_FORMAT_IDS.includes(value)

export const normalizeOutputFormat = (value) =>
  isValidOutputFormat(value) ? value : DEFAULT_OUTPUT_FORMAT

export const getOutputFormatMeta = (value) =>
  OUTPUT_FORMATS.find((format) => format.id === value) ||
  OUTPUT_FORMATS.find((format) => format.id === DEFAULT_OUTPUT_FORMAT)

export const outputPreferenceStorageKey = (userId) =>
  `meetvault-output-format:${userId || 'anonymous'}`

export const rawViewStorageKey = (userId) =>
  `meetvault-raw-view:${userId || 'anonymous'}`
