const TENSION_COLORS: Record<string, string> = {
  critical: 'bg-red-500/20 text-red-400 border-red-500/30',
  high: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  medium: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  'low-medium': 'bg-yellow-500/15 text-yellow-300 border-yellow-500/20',
  low: 'bg-green-500/20 text-green-400 border-green-500/30',
}

/**
 * Extract just the tension level from a string that may contain
 * extra context like "high (reframed — path is clearer)".
 */
function parseTension(raw: string): { level: string; detail: string | null } {
  const match = raw.match(/^(critical|high|medium|low-medium|low)\b(.*)/)
  if (match) {
    const detail = match[2].replace(/^\s*[\(—\-]\s*/, '').replace(/\)\s*$/, '').trim()
    return { level: match[1], detail: detail || null }
  }
  return { level: raw, detail: null }
}

export default function TensionBadge({ tension }: { tension: string }) {
  const { level, detail } = parseTension(tension)
  const colors = TENSION_COLORS[level] || 'bg-slate-500/20 text-slate-400 border-slate-500/30'
  return (
    <span
      className={`inline-block px-2 py-0.5 text-xs font-medium rounded border whitespace-nowrap ${colors}`}
      title={detail ? `${level}: ${detail}` : level}
    >
      {level}
    </span>
  )
}
