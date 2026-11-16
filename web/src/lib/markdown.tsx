/**
 * Minimal escape-first markdown → HTML for agent replies: code fences, inline code, bold, italics, headings, lists,
 * GitHub-style tables, horizontal rules and paragraphs. The input is HTML-escaped before any markup is added, so
 * input HTML is never trusted.
 */
const esc = (s: string) => s.replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));

const inl = (t: string) => t
  .replace(/`([^`]+)`/g, "<code>$1</code>")
  .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
  .replace(/(^|[^*\w])\*(?!\s)([^*\n]+?)\*(?![*\w])/g, "$1<i>$2</i>")
  .replace(/(^|[^_\w])_(?!\s)([^_\n]+?)_(?![_\w])/g, "$1<i>$2</i>");

/** Cells of a table row; `\|` is a literal pipe. Leading/trailing pipes are optional. */
export function splitRow(line: string): string[] {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|") && !s.endsWith("\\|")) s = s.slice(0, -1);
  const cells: string[] = []; let cur = "";
  for (let i = 0; i < s.length; i++) {
    if (s[i] === "\\" && s[i + 1] === "|") { cur += "|"; i++; }
    else if (s[i] === "|") { cells.push(cur.trim()); cur = ""; }
    else cur += s[i];
  }
  cells.push(cur.trim());
  return cells;
}

const isSep = (line: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);
const isRow = (line: string) => line.trim().startsWith("|") || (line.includes("|") && line.trim().length > 0 && /\|/.test(line.trim().slice(1, -1)));

function table(lines: string[]): string {
  const head = splitRow(lines[0]!);
  const align = splitRow(lines[1]!).map(c => (c.startsWith(":") && c.endsWith(":") ? "center" : c.endsWith(":") ? "right" : "left"));
  const body = lines.slice(2).map(splitRow);
  const cell = (tag: "th" | "td", text: string, i: number) => `<${tag} style="text-align:${align[i] ?? "left"}">${inl(text)}</${tag}>`;
  return `<div class="fw-md-table"><table><thead><tr>${head.map((h, i) => cell("th", h, i)).join("")}</tr></thead>`
    + `<tbody>${body.map(r => `<tr>${head.map((_, i) => cell("td", r[i] ?? "", i)).join("")}</tr>`).join("")}</tbody></table></div>`;
}

export function mdToHtml(src: string): string {
  return src.replace(/\r\n?/g, "\n").split(/```[^\n]*\n?/).map((part, i) => {
    if (i % 2) return `<pre><code>${esc(part.replace(/\n$/, ""))}</code></pre>`;
    let html = ""; let list: { tag: string; items: string[] } | null = null; let para: string[] = [];
    const flushP = () => { if (para.length) html += `<p>${para.map(inl).join("<br>")}</p>`; para = []; };
    const flushL = () => { if (list) html += `<${list.tag}>${list.items.map(x => `<li>${inl(x)}</li>`).join("")}</${list.tag}>`; list = null; };
    const lines = esc(part).split("\n");
    for (let k = 0; k < lines.length; k++) {
      const line = lines[k]!;
      // table: a header row followed by a |---|---| separator, then rows until a non-row line
      if (isRow(line) && k + 1 < lines.length && isSep(lines[k + 1]!)) {
        flushP(); flushL();
        const block = [line, lines[k + 1]!]; k += 2;
        while (k < lines.length && lines[k]!.trim() && isRow(lines[k]!) && !isSep(lines[k]!)) block.push(lines[k++]!);
        k--;
        html += table(block);
        continue;
      }
      const h = line.match(/^\s*(#{1,6})\s+(.*)$/);
      if (h) { flushP(); flushL(); const lvl = Math.min(6, h[1]!.length + 2); html += `<h${lvl}>${inl(h[2]!)}</h${lvl}>`; continue; }
      if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flushP(); flushL(); html += "<hr>"; continue; }
      const ul = line.match(/^\s*[-*•] (.*)$/); const ol = line.match(/^\s*\d+[.)] (.*)$/); const m = ul || ol;
      if (m) { flushP(); const tag = ul ? "ul" : "ol"; if (!list || list.tag !== tag) { flushL(); list = { tag, items: [] }; } list.items.push(m[1]!); }
      else if (!line.trim()) { flushP(); flushL(); }
      else { flushL(); para.push(line); }
    }
    flushP(); flushL();
    return html;
  }).join("");
}

export function Markdown({ text }: { text: string }) {
  return <div className="fw-md" dangerouslySetInnerHTML={{ __html: mdToHtml(text) }} />;
}
