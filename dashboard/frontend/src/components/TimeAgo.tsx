export default function TimeAgo({ timestamp }: { timestamp: string | null }) {
  if (!timestamp) return <span className="text-[#475569]">never</span>

  const date = new Date(timestamp)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  const diffHr = Math.floor(diffMs / 3600000)

  let text: string
  if (diffMin < 1) text = 'just now'
  else if (diffMin < 60) text = `${diffMin}m ago`
  else if (diffHr < 24) text = `${diffHr}h ago`
  else text = `${Math.floor(diffHr / 24)}d ago`

  return (
    <span className="text-[#64748b]" title={date.toLocaleString()}>
      {text}
    </span>
  )
}
