import DOMPurify from 'dompurify'
import { marked } from 'marked'

marked.setOptions({
  gfm: true,
  breaks: false,
})

/** 将正文中的「综合评分」段落移到最前（仅 assistant 回复使用）。 */
export function moveComprehensiveScoreFirst(text) {
  const trimmed = (text || '').trim()
  if (!trimmed || !trimmed.includes('综合评分')) return trimmed

  if (/^(?:\s*#+\s*)?(?:\*\*)?综合评分/m.test(trimmed.slice(0, 160))) {
    return trimmed
  }

  const patterns = [
    /(?:^|\n)(#{1,3}\s*综合评分[^\n]*(?:\n(?![#])[^\n]+){0,4})/i,
    /(?:^|\n)((?:\*\*)?综合评分(?:\*\*)?[：:][^\n]+)/i,
    /(?:^|\n)(综合评分[^\n]{0,100})/i,
  ]

  let block = ''
  let matched = ''
  for (const pattern of patterns) {
    const match = pattern.exec(trimmed)
    if (match) {
      block = match[1].trim()
      matched = match[0]
      break
    }
  }

  if (!block) return trimmed

  const rest = trimmed.replace(matched, '\n').replace(/\n{3,}/g, '\n\n').trim()
  const header = block.startsWith('#') ? block : `### 综合评分\n\n${block}`

  if (!rest) return header
  return `${header}\n\n---\n\n${rest}`
}

export function renderMarkdown(text) {
  if (!text) return ''
  const prepared = moveComprehensiveScoreFirst(text)
  const html = marked.parse(prepared, { async: false })
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
  })
}
