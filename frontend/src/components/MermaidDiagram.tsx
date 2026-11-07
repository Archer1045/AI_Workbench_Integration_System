import { useEffect, useRef } from 'react';
import mermaid from 'mermaid';

let initialized = false;

/** 渲染 Mermaid 流程图 */
export default function MermaidDiagram({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const idRef = useRef(`mc-mermaid-${Math.random().toString(36).slice(2, 9)}`);

  useEffect(() => {
    if (!initialized) {
      mermaid.initialize({
        startOnLoad: false,
        theme: 'neutral',
        flowchart: { curve: 'basis', padding: 12 },
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif',
      });
      initialized = true;
    }
  }, []);

  useEffect(() => {
    if (!ref.current || !code.trim()) return;
    let cancelled = false;

    mermaid
      .render(idRef.current, code)
      .then(({ svg }) => {
        if (cancelled || !ref.current) return;
        ref.current.innerHTML = svg;
      })
      .catch(() => {
        if (cancelled || !ref.current) return;
        ref.current.innerHTML = '<div class="mc-mermaid-error">流程图渲染失败</div>';
      });

    return () => {
      cancelled = true;
      // mermaid 会往 body 里塞临时节点，清掉
      document.getElementById(`d${idRef.current}`)?.remove();
    };
  }, [code]);

  return <div className="mc-mermaid" ref={ref} />;
}
