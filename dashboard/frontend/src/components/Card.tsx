import type { ReactNode } from 'react'

interface CardProps {
  title?: string
  children: ReactNode
  className?: string
}

export default function Card({ title, children, className = '' }: CardProps) {
  return (
    <div className={`bg-[#1e293b] border border-[#334155] rounded-lg ${className}`}>
      {title && (
        <div className="px-4 py-3 border-b border-[#334155]">
          <h3 className="text-sm font-medium text-[#94a3b8]">{title}</h3>
        </div>
      )}
      <div className="p-4">{children}</div>
    </div>
  )
}
