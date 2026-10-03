import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Release notes renderer. Raw HTML in the Markdown is ignored (react-markdown's default),
 * so notes from GitHub can't inject markup or scripts. Links open in a new tab.
 */
export function MarkdownRenderer({ children }: { children: string }) {
  return (
    <div className="prose-notes">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children: content }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {content}
            </a>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
