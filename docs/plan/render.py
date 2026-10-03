"""Render docs/architecture.md into the styled review page docs/plan/architecture.html.

Usage: python docs/plan/render.py   (needs `pip install markdown`)
The Markdown file is the source of truth; never edit the HTML by hand.
"""

import html
import re
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs" / "architecture.md"
OUT = ROOT / "docs" / "plan" / "architecture.html"
BLUEPRINT_URL = "https://claude.ai/artifact/HE5trVkqVBFrXt41QV67oy"

MERMAID = re.compile(r"```mermaid\n(.*?)```", re.S)


def render() -> str:
    text = SRC.read_text(encoding="utf-8")
    title_match = re.match(r"# (.+)\n", text)
    text = text[title_match.end():] if title_match else text

    diagrams: list[str] = []

    def stash(m: re.Match) -> str:
        diagrams.append(m.group(1))
        return f"\n\nMERMAIDBLOCK{len(diagrams) - 1}\n\n"

    text = MERMAID.sub(stash, text)
    md = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "sane_lists"])
    body = md.convert(text)
    for i, src in enumerate(diagrams):
        body = body.replace(f"<p>MERMAIDBLOCK{i}</p>", f'<pre class="mermaid">{html.escape(src)}</pre>')
    body = re.sub(r"<table>", '<div class="tbl"><table>', body).replace("</table>", "</table></div>")
    body = body.replace('href="plan/blueprint.html"', f'href="{BLUEPRINT_URL}"')

    toc = [(t["id"], html.unescape(t["name"])) for t in md.toc_tokens if t["level"] == 2]
    nav = "".join(f'<a href="#{i}">{html.escape(n)}</a>' for i, n in toc)
    return TEMPLATE.replace("{{NAV}}", nav).replace("{{BODY}}", body)


TEMPLATE = """<title>SIQE Studio Architecture</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Unbounded:wght@500;700&family=Instrument+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
/* Layout: technical proposal; sticky section index on the left, one 780px reading column */
:root{
  color-scheme: dark;
  --bg:#060A14; --surface:#0D1427; --surface-2:#121B33; --line:#1D2947; --line-2:#2B3A63;
  --fg:#E8EEFA; --fg-2:#B8C5DF; --muted:#8090B3;
  --cyan:#4DCBF3; --cyan-soft:rgba(77,203,243,.10); --gold:#F5BD45; --gold-soft:rgba(245,189,69,.12);
  --code-bg:#080D1A;
  --f-display:"Unbounded","Arial Black",system-ui,sans-serif;
  --f-body:"Instrument Sans","Segoe UI",system-ui,-apple-system,sans-serif;
  --f-mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme: light){
  :root:not([data-theme="dark"]){
    color-scheme: light;
    --bg:#F4F6FB; --surface:#FFFFFF; --surface-2:#EEF2F9; --line:#D7DEEB; --line-2:#BAC6DD;
    --fg:#0A1330; --fg-2:#2B3A5E; --muted:#56648A;
    --cyan:#0784B6; --cyan-soft:rgba(7,132,182,.08); --gold:#A56A00; --gold-soft:rgba(201,138,16,.12);
    --code-bg:#EEF2F9;
  }
}
:root[data-theme="light"]{
  color-scheme: light;
  --bg:#F4F6FB; --surface:#FFFFFF; --surface-2:#EEF2F9; --line:#D7DEEB; --line-2:#BAC6DD;
  --fg:#0A1330; --fg-2:#2B3A5E; --muted:#56648A;
  --cyan:#0784B6; --cyan-soft:rgba(7,132,182,.08); --gold:#A56A00; --gold-soft:rgba(201,138,16,.12);
  --code-bg:#EEF2F9;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth; scroll-padding-top:24px}
body{background:var(--bg); color:var(--fg); font:16px/1.65 var(--f-body); -webkit-font-smoothing:antialiased}
a{color:var(--cyan); text-underline-offset:3px}
:focus-visible{outline:2px solid var(--cyan); outline-offset:2px}
.page{max-width:1180px; margin:0 auto; padding-inline:20px; display:grid; grid-template-columns:220px minmax(0,1fr); gap:56px}
header.top{grid-column:1/-1; padding-block:64px 8px; border-bottom:1px solid var(--line)}
.eyebrow{font:12px var(--f-mono); letter-spacing:.12em; text-transform:uppercase; color:var(--cyan)}
header.top h1{font-family:var(--f-display); font-weight:700; font-size:clamp(40px,7vw,76px); line-height:1; letter-spacing:-.02em; margin:16px 0 14px}
header.top h1 span{color:var(--muted); font-weight:500; font-size:.42em; letter-spacing:0; display:block; margin-top:14px}
header.top p{color:var(--fg-2); font-size:18px; max-width:62ch; margin:0 0 28px}
nav.toc{position:sticky; top:24px; align-self:start; padding-block:32px; display:grid; gap:2px; max-height:calc(100vh - 48px); overflow:auto}
nav.toc .h{font:11px var(--f-mono); letter-spacing:.12em; text-transform:uppercase; color:var(--muted); margin-bottom:8px}
nav.toc a{color:var(--fg-2); text-decoration:none; font-size:13.5px; padding:5px 10px; border-left:2px solid var(--line); line-height:1.35}
nav.toc a:hover{color:var(--fg); border-color:var(--cyan)}
article{padding-block:16px 96px; max-width:780px; min-width:0}
article h2{font-family:var(--f-display); font-weight:500; font-size:clamp(24px,3vw,30px); line-height:1.15; margin:64px 0 16px; letter-spacing:-.01em; text-wrap:balance}
article h3{font-size:19px; margin:36px 0 10px; font-weight:600}
article p, article li{color:var(--fg-2)}
article strong{color:var(--fg)}
article hr{border:0; border-top:1px solid var(--line); margin:48px 0 0}
article ul, article ol{padding-left:22px}
article li{margin-bottom:6px}
article code{font:0.86em var(--f-mono); background:var(--surface-2); border:1px solid var(--line); padding:1px 5px; border-radius:4px; color:var(--fg)}
article pre{background:var(--code-bg); border:1px solid var(--line); border-radius:10px; padding:16px 18px; overflow-x:auto; font:12.5px/1.6 var(--f-mono)}
article pre code{background:none; border:0; padding:0; font-size:inherit; color:var(--fg-2)}
pre.mermaid{background:var(--surface); text-align:center; padding:20px}
.tbl{overflow-x:auto; margin:18px 0; border:1px solid var(--line); border-radius:10px; background:var(--surface)}
table{border-collapse:collapse; width:100%; font-size:14px; font-variant-numeric:tabular-nums}
th,td{padding:10px 14px; text-align:left; vertical-align:top; border-bottom:1px solid var(--line)}
tr:last-child td{border-bottom:0}
th{font:500 11.5px var(--f-mono); letter-spacing:.06em; text-transform:uppercase; color:var(--muted); background:var(--surface-2)}
td{color:var(--fg-2)}
td strong{color:var(--fg)}
article > .tbl:first-child{border-color:var(--gold); background:var(--gold-soft)}
article > .tbl:first-child th{display:none}
article blockquote{margin:16px 0; padding:12px 16px; border-left:3px solid var(--gold); background:var(--gold-soft); border-radius:0 8px 8px 0}
@media (max-width:900px){.page{grid-template-columns:1fr; gap:0} nav.toc{display:none}}
</style>

<div class="page">
  <header class="top">
    <div class="eyebrow">Architecture · v3 · approved · Phases 0 to 6 implemented · 3 Oct 2026</div>
    <h1>SIQE Studio<span>How the platform is built, and why</span></h1>
    <p>Stack, Temporal orchestration, database, memory safety for 8K+ images, the Update Center, repository layout and build order. Rendered from docs/architecture.md, the source of truth.</p>
  </header>
  <nav class="toc" aria-label="Sections"><div class="h">Sections</div>{{NAV}}</nav>
  <article>
{{BODY}}
  </article>
</div>
"""

if __name__ == "__main__":
    OUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
