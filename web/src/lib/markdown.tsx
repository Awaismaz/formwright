/** Minimal escape-first markdown → HTML (code fences, inline code, bold, lists, paragraphs). Never trusts input HTML. */
const esc = (s: string) => s.replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));

export function mdToHtml(src: string): string {
  return src.split(/```[^\n]*\n?/).map((part, i) => {
    if (i % 2) return `<pre><code>${esc(part.replace(/\n$/, ""))}</code></pre>`;
    const inl = (t: string) => t.replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
    let html = ""; let list: { tag: string; items: string[] } | null = null; let para: string[] = [];
    const flushP = () => { if (para.length) html += `<p>${para.map(inl).join("<br>")}</p>`; para = []; };
    const flushL = () => { if (list) html += `<${list.tag}>${list.items.map(x => `<li>${inl(x)}</li>`).join("")}</${list.tag}>`; list = null; };
    for (const line of esc(part).split("\n")) {
      const ul = line.match(/^\s*[-*] (.*)$/); const ol = line.match(/^\s*\d+[.)] (.*)$/); const m = ul || ol;
      if (m) { flushP(); const tag = ul ? "ul" : "ol"; if (!list || list.tag !== tag) { flushL(); list = { tag, items: [] }; } list.items.push(m[1]!); }
      else if (!line.trim()) { flushP(); flushL(); }
      else { flushL(); para.push(line.replace(/^#{1,6}\s+/, "")); }
    }
    flushP(); flushL();
    return html;
  }).join("");
}

export function Markdown({ text }: { text: string }) {
  return <div className="fw-md" dangerouslySetInnerHTML={{ __html: mdToHtml(text) }} />;
}
