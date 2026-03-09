import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export default function Markdown({ children }: { children: string }) {
  return (
    <div className="prose prose-invert prose-sm max-w-none
      prose-headings:text-[#f1f5f9] prose-headings:font-semibold prose-headings:mt-4 prose-headings:mb-2
      prose-h1:text-base prose-h2:text-sm prose-h3:text-sm
      prose-p:text-[#94a3b8] prose-p:text-xs prose-p:leading-relaxed prose-p:my-1.5
      prose-li:text-[#94a3b8] prose-li:text-xs prose-li:my-0.5
      prose-strong:text-[#f1f5f9]
      prose-code:text-[#38bdf8] prose-code:text-xs prose-code:bg-[#0f172a] prose-code:px-1 prose-code:py-0.5 prose-code:rounded
      prose-pre:bg-[#0f172a] prose-pre:border prose-pre:border-[#334155] prose-pre:rounded prose-pre:text-xs
      prose-a:text-[#38bdf8] prose-a:no-underline hover:prose-a:underline
      prose-hr:border-[#334155]
      prose-table:text-xs prose-th:text-[#94a3b8] prose-td:text-[#94a3b8]
      [&_input[type=checkbox]]:mr-1.5 [&_input[type=checkbox]]:accent-[#38bdf8]
      prose-table:border-collapse [&_th]:border [&_th]:border-[#334155] [&_th]:px-2 [&_th]:py-1
      [&_td]:border [&_td]:border-[#334155] [&_td]:px-2 [&_td]:py-1
    ">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  )
}
