import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type Props = {
  content: string;
};

function safeMarkdownUrl(url: string) {
  const value = url.trim();
  if (/^https?:\/\//i.test(value) || value.startsWith("#")) return value;
  return "";
}

export function SafeMarkdown({ content }: Props) {
  return (
    <div className="exception-ai-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        urlTransform={safeMarkdownUrl}
        components={{
          a: ({ node: _node, href, children, ...props }) => (
            <a
              {...props}
              href={href || undefined}
              rel={href?.startsWith("http") ? "noreferrer noopener" : undefined}
              target={href?.startsWith("http") ? "_blank" : undefined}
            >
              {children}
            </a>
          ),
          img: ({ node: _node, alt }) => (
            <span className="exception-ai-markdown-image">{alt ? `[图片：${alt}]` : "[图片已隐藏]"}</span>
          ),
          table: ({ node: _node, children, ...props }) => (
            <div className="exception-ai-markdown-table" role="region" aria-label="Markdown 表格" tabIndex={0}>
              <table {...props}>{children}</table>
            </div>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
