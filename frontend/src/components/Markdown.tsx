"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Children, isValidElement, type ReactNode } from "react";

type Props = { text: string; onCite?: (ref: string) => void; className?: string };

const CITE_RE = /\[(S-[0-9a-f]{8}|\d{1,2})\]/g;

/** Remplace [n] / [S-xxxx] dans les nœuds texte par des puces de citation cliquables. */
function withCitations(children: ReactNode, onCite?: (ref: string) => void): ReactNode {
  return Children.map(children, (child) => {
    if (typeof child === "string") {
      const parts: ReactNode[] = [];
      let last = 0;
      for (const m of child.matchAll(CITE_RE)) {
        const i = m.index ?? 0;
        if (i > last) parts.push(child.slice(last, i));
        const ref = m[1];
        parts.push(<button key={i} type="button" className="cite" onClick={() => onCite?.(ref)} title={ref}>{ref.startsWith("S-") ? ref.slice(2, 6) : ref}</button>);
        last = i + m[0].length;
      }
      if (last < child.length) parts.push(child.slice(last));
      return parts.length ? parts : child;
    }
    if (isValidElement<{ children?: ReactNode }>(child) && child.props.children) {
      return { ...child, props: { ...child.props, children: withCitations(child.props.children, onCite) } };
    }
    return child;
  });
}

export function Markdown({ text, onCite, className }: Props) {
  const wrap = (Tag: keyof HTMLElementTagNameMap) =>
    // eslint-disable-next-line react/display-name
    ({ children, ...rest }: { children?: ReactNode }) => <Tag {...(rest as object)}>{withCitations(children, onCite)}</Tag>;
  return (
    <div className={`prose-jz ${className ?? ""}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ p: wrap("p"), li: wrap("li"), td: wrap("td"), h2: wrap("h2"), h3: wrap("h3"), strong: wrap("strong"), em: wrap("em") }}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
