// markdown.js — shared markdown rendering for slide-out panels.
// Uses the `marked` CDN when available (full tables/lists/etc.), with a minimal
// built-in fallback if the CDN failed to load. The fallback covers headings,
// hr, em/strong/code, bullet lists, pipe tables, and paragraphs — enough for
// the briefing and the lineage doc.

/** Render markdown to an HTML string. */
export function renderMarkdown(md) {
  if (window.marked && typeof window.marked.parse === "function") {
    return window.marked.parse(md);
  }
  return fallbackMarkdown(md);
}

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function inline(s) {
  return s
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`(.+?)`/g, "<code>$1</code>");
}

/** True for a markdown pipe-table row like `| a | b |`. */
function isTableRow(line) {
  return /^\|.*\|$/.test(line.trim());
}

/** A separator row like `|---|:--:|` — marks the header/body boundary. */
function isTableSep(line) {
  return /^\|[\s:|-]+\|$/.test(line.trim()) && line.includes("-");
}

function splitCells(line) {
  // drop the leading/trailing pipe, then split; keep inner empties
  const inner = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return inner.split("|").map((c) => c.trim());
}

function fallbackMarkdown(md) {
  const lines = String(md).split("\n");
  const out = [];
  let inList = false;
  const closeList = () => { if (inList) { out.push("</ul>"); inList = false; } };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trimEnd();
    const trimmed = line.trim();

    // --- table block: a header row followed by a separator row ---
    if (isTableRow(line) && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      closeList();
      const header = splitCells(line);
      let j = i + 2;
      const rows = [];
      while (j < lines.length && isTableRow(lines[j])) {
        rows.push(splitCells(lines[j]));
        j++;
      }
      out.push("<table><thead><tr>");
      out.push(header.map((h) => `<th>${inline(esc(h))}</th>`).join(""));
      out.push("</tr></thead><tbody>");
      for (const r of rows) {
        out.push("<tr>" + r.map((c) => `<td>${inline(esc(c))}</td>`).join("") + "</tr>");
      }
      out.push("</tbody></table>");
      i = j - 1;
      continue;
    }

    let m;
    if (/^---+$/.test(trimmed)) {
      closeList();
      out.push("<hr>");
    } else if ((m = line.match(/^(#{1,6})\s+(.*)$/))) {
      closeList();
      const lvl = m[1].length;
      out.push(`<h${lvl}>${inline(esc(m[2]))}</h${lvl}>`);
    } else if ((m = line.match(/^[-*]\s+(.*)$/))) {
      if (!inList) { out.push("<ul>"); inList = true; }
      out.push(`<li>${inline(esc(m[1]))}</li>`);
    } else if (trimmed === "") {
      closeList();
    } else {
      closeList();
      out.push(`<p>${inline(esc(line))}</p>`);
    }
  }
  closeList();
  return out.join("\n");
}
