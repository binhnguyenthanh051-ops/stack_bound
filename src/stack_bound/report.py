"""Reports. One model (JSON, versioned schema), three renderings: text, JSON, HTML.

`model()` is the only place that reads the analysis; `text()` and `html()` render the model, so the
formats can't disagree (ADR-0001 D11, addendum 2026-11-11).
"""
from __future__ import annotations

import html as _html
import json as _json

from stack_bound import __version__
from stack_bound.analyze import StackResult
from stack_bound.elfread import Image
from stack_bound.project import Project

SCHEMA = "stack_bound.report/1"
WORD = 4                                        # bytes per stack word in the "w" column


def model(image: Image, project: Project, results: list[StackResult]) -> dict:
    """The report as plain data: every number and string any rendering shows."""
    # @impl REQ-SB-304 : per stack: required, configured, margin, recommended, status, worst path
    # @impl REQ-SB-309 : records the ELF SHA-256, tool version and profile name/version
    # (part of REQ-SB-306: text and JSON with a versioned schema; SARIF comes later)
    p = project.profile
    stacks = []
    for r in results:
        path = []
        for i, s in enumerate(r.path):
            edge = "entry" if i == 0 else ("listed" if s.via.startswith("listed") else "call")
            path.append({"function": s.fn.name, "frame": s.fn.frame, "frame_source": s.fn.frame_source,
                         "edge": edge, "reason": s.via if edge == "listed" else None})
        stacks.append({"kind": "task", "entry": r.entry, "required": r.required, "path_bytes": r.path_bytes,
                       "switch_bytes": r.switch_bytes, "configured": r.configured,
                       "configured_from": r.configured_from, "used": r.used, "recommended": r.recommended,
                       "recommended_words": r.recommended // WORD, "status": r.status, "path": path})
    # @impl REQ-SB-305 : every assumption the result depends on is listed
    a = [{"kind": "indirect", "layer": "project",
          "text": f"indirect {i.function} -> {', '.join(i.targets)}: {i.reason}"} for i in project.indirect]
    a += [{"kind": "frame", "layer": "project", "text": f"frame {n} = {b} B: {src}"}
          for n, (b, src) in project.frames.items()]
    a.append({"kind": "profile", "layer": f"profile {p.name}",
              "text": f"switch frame {p.switch_fpu} B (FPU) / {p.switch_basic} B [profile {p.name}]: {p.source}"})
    a.append({"kind": "profile", "layer": f"profile {p.name}",
              "text": f"stack alignment {p.stack_alignment} B [profile {p.name}]"})
    a.append({"kind": "margin", "layer": project.margin_layer,
              "text": f"margin rule {project.margin_rule:.2f} [{project.margin_layer}]"})
    if image.not_linked:
        # @impl REQ-SB-011 : the ignored compiler entries are counted in the report
        a.append({"kind": "not_linked", "layer": "ELF",
                  "text": f"{len(image.not_linked)} compiler frame entries name functions not in the "
                          f"image (removed by the linker), ignored"})
    return {"schema": SCHEMA,
            "tool": {"name": "stack_bound", "version": __version__},
            "image": {"name": image.path.name, "sha256": image.sha256, "compiler": image.compiler},
            "profile": {"name": p.name, "version": p.version},
            "margin": {"rule": project.margin_rule, "layer": project.margin_layer},
            "stacks": stacks, "assumptions": a}


def json(m: dict) -> str:
    return _json.dumps(m, indent=2) + "\n"


def text(m: dict) -> str:
    lines = [
        f"{m['tool']['name']} {m['tool']['version']} | {m['image']['name']} (sha256 {m['image']['sha256'][:12]}) "
        f"| {m['image']['compiler']}",
        f"profile {m['profile']['name']} v{m['profile']['version']} | margin: required <= "
        f"{m['margin']['rule']:.0%} of configured ({m['margin']['layer']})",
        "",
        f"{'STACK':<18}{'REQUIRED':>10}{'CONFIGURED':>12}{'USED':>7}{'RECOMMENDED':>18}  STATUS",
    ]
    for s in m["stacks"]:
        rec = f"{s['recommended']} B ({s['recommended_words']} w)"
        lines.append(f"{(s['kind'] + ' ' + s['entry']):<18}{s['required']:>8} B{s['configured']:>10} B"
                     f"{s['used']:>7.0%}{rec:>18}  {s['status']}")
    for s in m["stacks"]:
        lines += ["", f"worst path, {s['kind']} {s['entry']} ({s['path_bytes']} B + {s['switch_bytes']} B "
                      f"switch frame, stack from {s['configured_from']}):"]
        for st in s["path"]:
            arrow = {"entry": "   ", "call": " -> ", "listed": " ~> "}[st["edge"]]
            note = f"   [{st['reason']}]" if st["edge"] == "listed" else ""
            lines.append(f"  {arrow}{st['function']} {st['frame']} B{note}")
    lines += ["", "  ->  direct call    ~>  function-pointer target (from the [[indirect]] list)", "",
              "assumptions:"] + [f"  - {a['text']}" for a in m["assumptions"]]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- HTML

def html(m: dict) -> str:
    """One self-contained page: inline CSS, no script, nothing fetched (ADR-0001 D11 addendum)."""
    # @impl REQ-SB-311 : self-contained HTML rendered from the JSON model
    e = _html.escape
    rule = m["margin"]["rule"]
    title = f"Stack report · {m['image']['name']}"
    fails = sum(1 for s in m["stacks"] if s["status"] != "ok")
    verdict = "every stack passes" if not fails else f"{fails} of {len(m['stacks'])} stacks fail"

    rows = []
    for s in m["stacks"]:
        scale = max(s["configured"], s["required"]) or 1
        rows.append(
            f'<tr><td class="name"><a href="#{e(_anchor(s))}">{e(s["kind"])} <b>{e(s["entry"])}</b></a></td>'
            f'<td class="num">{s["required"]} B</td><td class="num">{s["configured"]} B</td>'
            f'<td class="num">{s["used"]:.0%}</td>'
            f'<td class="bar">{_bar(s, rule, scale)}</td>'
            f'<td class="num">{s["recommended"]} B <span class="dim">({s["recommended_words"]} w)</span></td>'
            f'<td>{_chip(s["status"])}</td></tr>')

    sections = [_stack_section(s, rule) for s in m["stacks"]]
    assumptions = "".join(f'<tr><td>{e(a["kind"])}</td><td>{e(a["text"])}</td><td class="dim">{e(a["layer"])}</td></tr>'
                          for a in m["assumptions"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="{e(m['tool']['name'])} {e(m['tool']['version'])}">
<title>{e(title)}</title>
<style>{_CSS}</style></head>
<body><main>
<header>
<p class="eyebrow">stack_bound report</p>
<h1>{e(m['image']['name'])}</h1>
<p class="verdict {'ok' if not fails else 'fail'}">{e(verdict)}: required ≤ {rule:.0%} of configured</p>
<dl class="meta">
<dt>ELF sha256</dt><dd><code>{e(m['image']['sha256'][:16])}…</code></dd>
<dt>Compiler</dt><dd>{e(m['image']['compiler'])}</dd>
<dt>Profile</dt><dd>{e(m['profile']['name'])} v{e(m['profile']['version'])}</dd>
<dt>Margin rule</dt><dd>{rule:.2f} <span class="dim">({e(m['margin']['layer'])})</span></dd>
<dt>Tool</dt><dd>{e(m['tool']['name'])} {e(m['tool']['version'])}</dd>
</dl>
</header>

<section>
<h2>1. Stacks</h2>
<div class="scroll"><table class="stacks">
<thead><tr><th>Stack</th><th class="num">Required</th><th class="num">Configured</th><th class="num">Used</th>
<th>Required against configured</th><th class="num">Recommended</th><th>Status</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<p class="caption"><b>Table 1.</b> Each bar is one stack. Dark: the deepest call path. Light: the context-switch
frame, red where it runs past the stack. Dashed line: the margin rule ({rule:.0%} of the stack). Solid line:
the configured size.</p>
</section>

<section>
<h2>2. Worst paths</h2>
{''.join(sections)}
</section>

<section>
<h2>3. Assumptions</h2>
<div class="scroll"><table class="assume"><thead><tr><th>Kind</th><th>Assumption</th><th>Set by</th></tr></thead>
<tbody>{assumptions}</tbody></table></div>
<p class="caption"><b>Table 2.</b> Everything the numbers depend on that the ELF can't show by itself.</p>
</section>

<footer>Generated by {e(m['tool']['name'])} {e(m['tool']['version'])} from report schema
<code>{e(m['schema'])}</code>. The same data as the text and JSON reports.</footer>
</main></body></html>
"""


def _anchor(s: dict) -> str:
    return f"{s['kind']}-{s['entry']}"


def _chip(status: str) -> str:
    cls = "ok" if status == "ok" else "fail"
    return f'<span class="chip {cls}">{_html.escape(status)}</span>'


def _pct(n: float, scale: int) -> str:
    return f"{100.0 * n / scale:.2f}%"


def _bar(s: dict, rule: float, scale: int) -> str:
    """Path + switch frame against the configured size, with the margin line."""
    label = (f"{s['path_bytes']} B path + {s['switch_bytes']} B switch frame = {s['required']} B "
             f"of {s['configured']} B configured")
    over = s["required"] > s["configured"]
    return (f'<div class="track" role="img" aria-label="{_html.escape(label)}" title="{_html.escape(label)}">'
            f'<span class="cfg" style="width:{_pct(s["configured"], scale)}"></span>'
            f'<span class="seg path{" over" if over else ""}" style="width:{_pct(s["path_bytes"], scale)}"></span>'
            f'<span class="seg switch{" over" if over else ""}" style="width:{_pct(s["switch_bytes"], scale)}"></span>'
            f'<span class="rule" style="left:{_pct(rule * s["configured"], scale)}"></span>'
            f'<span class="end" style="left:{_pct(s["configured"], scale)}"></span></div>')


def _stack_section(s: dict, rule: float) -> str:
    """The worst path as a waterfall: each frame starts where its caller's ends."""
    e = _html.escape
    scale = max(s["configured"], s["required"]) or 1
    lines, depth = [], 0
    for st in s["path"]:
        sym = {"entry": "", "call": "→", "listed": "⇒"}[st["edge"]]
        reason = (f'<div class="reason">function pointer, listed: {e(st["reason"].removeprefix("listed: "))}</div>'
                  if st["edge"] == "listed" else "")
        lines.append(
            f'<tr class="{e(st["edge"])}"><td class="edge">{sym}</td>'
            f'<td class="fn"><code>{e(st["function"])}</code>{reason}</td>'
            f'<td class="num">{st["frame"]} B</td><td class="num dim">{depth + st["frame"]} B</td>'
            f'<td class="wf">{_wf(depth, st["frame"], s, rule, scale, "path")}</td></tr>')
        depth += st["frame"]
    lines.append(
        f'<tr class="switch"><td class="edge">+</td><td class="fn">context-switch frame '
        f'<span class="dim">(profile)</span></td><td class="num">{s["switch_bytes"]} B</td>'
        f'<td class="num dim">{depth + s["switch_bytes"]} B</td>'
        f'<td class="wf">{_wf(depth, s["switch_bytes"], s, rule, scale, "switch")}</td></tr>')
    return f"""<article id="{e(_anchor(s))}">
<h3>{e(s['kind'])} <code>{e(s['entry'])}</code> {_chip(s['status'])}</h3>
<p class="sub">{s['required']} B required ({s['path_bytes']} B path + {s['switch_bytes']} B switch frame) of
{s['configured']} B, {s['used']:.0%} used. Stack from {e(s['configured_from'])}. Recommended:
<b>{s['recommended']} B ({s['recommended_words']} words)</b>.</p>
<div class="scroll"><table class="path"><thead><tr><th></th><th>Function</th><th class="num">Frame</th>
<th class="num">Depth</th><th>Where the stack goes</th></tr></thead>
<tbody>{''.join(lines)}</tbody></table></div>
</article>
"""


def _wf(start: int, size: int, s: dict, rule: float, scale: int, kind: str) -> str:
    over = " over" if start + size > s["configured"] else ""
    return (f'<div class="track thin"><span class="cfg" style="width:{_pct(s["configured"], scale)}"></span>'
            f'<span class="seg {kind}{over} abs" style="left:{_pct(start, scale)};width:{_pct(size, scale)}"></span>'
            f'<span class="rule" style="left:{_pct(rule * s["configured"], scale)}"></span>'
            f'<span class="end" style="left:{_pct(s["configured"], scale)}"></span></div>')


_CSS = """
:root{--bg:#f6efe6;--card:#fffaf3;--ink:#2b2320;--dim:#7a6c63;--line:#e3d6c6;--key:#2b2320;--switch:#b9a796;
--track:#ece2d4;--rule:#b35a3a;--ok:#3f6e4f;--okbg:#e2ecdf;--fail:#a8321f;--failbg:#f6dcd4}
@media (prefers-color-scheme:dark){:root{--bg:#1d1916;--card:#26211d;--ink:#efe6da;--dim:#a8998c;--line:#3b332d;
--key:#efe6da;--switch:#7d6e61;--track:#332c26;--rule:#e08a66;--ok:#8fc29f;--okbg:#25372b;--fail:#f08f78;--failbg:#45251d}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1080px;margin:0 auto;padding:32px 16px 48px}
h1{font-family:Georgia,"Times New Roman",serif;font-weight:500;font-size:2rem;margin:.1em 0 .2em}
h2{font-family:Georgia,"Times New Roman",serif;font-weight:500;font-size:1.35rem;margin:2em 0 .6em}
h3{font-size:1.05rem;margin:1.6em 0 .3em;display:flex;gap:.6em;align-items:center;flex-wrap:wrap}
code{font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;font-size:.92em}
.eyebrow{text-transform:uppercase;letter-spacing:.08em;font-size:.75rem;color:var(--dim);margin:0}
.verdict{font-weight:600;margin:.2em 0 1em}.verdict.ok{color:var(--ok)}.verdict.fail{color:var(--fail)}
.meta{display:grid;grid-template-columns:max-content 1fr;gap:.2em 1em;background:var(--card);border:1px solid var(--line);
border-radius:10px;padding:12px 16px;margin:0}.meta dt{color:var(--dim)}.meta dd{margin:0;overflow-wrap:anywhere}
.scroll{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%}th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
tbody tr:last-child td{border-bottom:0}th{font-size:.8rem;color:var(--dim);font-weight:600}
.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}.dim{color:var(--dim)}
.name a{color:inherit;text-decoration:none}.name a:hover{text-decoration:underline}
td.bar{min-width:220px;width:34%;vertical-align:middle}td.wf{min-width:200px;width:36%;vertical-align:middle}
.track{position:relative;height:16px;background:transparent;display:flex}.track.thin{height:12px}
.track .cfg{position:absolute;left:0;top:0;bottom:0;background:var(--track);border-radius:3px}
.seg{position:relative;height:100%}.seg.path{background:var(--key)}.seg.switch{background:var(--switch)}
.seg.over{background:var(--fail)}.seg.abs{position:absolute;top:0;border-radius:2px;min-width:2px}
.track:not(.thin) .seg:first-of-type{border-radius:3px 0 0 3px}
.rule{position:absolute;top:-3px;bottom:-3px;border-left:2px dashed var(--rule)}
.end{position:absolute;top:-4px;bottom:-4px;margin-left:-2px;border-left:2px solid var(--ink)}
.chip{display:inline-block;padding:1px 9px;border-radius:999px;font-size:.78rem;font-weight:700;letter-spacing:.03em}
.chip.ok{background:var(--okbg);color:var(--ok)}.chip.fail{background:var(--failbg);color:var(--fail)}
.caption{font-size:.85rem;color:var(--dim);margin:.5em 2px 0}
.sub{margin:.2em 0 .7em;color:var(--dim)}.sub b{color:var(--ink)}
td.edge{width:1.5em;color:var(--dim);text-align:center}tr.listed td.edge{color:var(--rule);font-weight:700}
.reason{font-size:.8rem;color:var(--dim);margin-top:2px}tr.switch td{color:var(--dim)}
footer{margin-top:3em;font-size:.8rem;color:var(--dim);border-top:1px solid var(--line);padding-top:1em}
@media print{body{background:#fff}.scroll,.meta{border-color:#ccc}}
"""
