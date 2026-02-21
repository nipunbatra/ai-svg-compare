#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["google-genai"]
# ///
"""
Compare SVG generation across Gemini + Claude + Codex models.
Supports multiple prompts; results cached per (prompt_id, model).

Run:         uv run pelican_compare.py
HTML only:   uv run pelican_compare.py --html-only
One prompt:  uv run pelican_compare.py --prompt pelican
"""

import asyncio
import json
import os
import re
import sys
import time
from html import escape
from pathlib import Path

# ── prompts ───────────────────────────────────────────────────────────────────

PROMPTS = {
    "pelican": (
        "Generate a complete, detailed SVG image of a pelican riding a bicycle. "
        "Output ONLY the raw SVG code, nothing else — no markdown, no explanation, "
        "no code fences. Start directly with <svg and end with </svg>."
    ),
    "indian": (
        "Generate a complete, detailed SVG image of a person in traditional Indian "
        "clothing (kurta-pyjama or saree) riding a bicycle through a colourful Indian "
        "street market with stalls, signs, and vendors. Show cultural details accurately. "
        "Output ONLY the raw SVG code, nothing else — no markdown, no explanation, "
        "no code fences. Start directly with <svg and end with </svg>."
    ),
    "animated_pelican": (
        "Generate a complete animated SVG of a pelican riding a bicycle. "
        "Use CSS @keyframes or SMIL animations for spinning wheels and the pelican's "
        "legs pedalling. The animation should loop indefinitely. "
        "Output ONLY the raw SVG code, nothing else — no markdown, no explanation, "
        "no code fences. Start directly with <svg and end with </svg>."
    ),
    "animated_indian": (
        "Generate a complete animated SVG of a colourful Indian auto-rickshaw (tuk-tuk) "
        "moving along a street, with spinning wheels and a driver visible. "
        "Use CSS @keyframes or SMIL animations that loop indefinitely. "
        "Output ONLY the raw SVG code, nothing else — no markdown, no explanation, "
        "no code fences. Start directly with <svg and end with </svg>."
    ),
}

PROMPT_LABELS = {
    "pelican":          "Pelican on Bicycle",
    "indian":           "Indian Street Cyclist",
    "animated_pelican": "Animated Pelican (CSS)",
    "animated_indian":  "Animated Auto-Rickshaw",
}

# ── models ────────────────────────────────────────────────────────────────────

GEMINI_MODELS = [
    "gemini-3-flash-preview",
    "gemini-3-pro-preview",
    "gemini-3.1-pro-preview",
]

CLAUDE_MODELS = [
    "claude-sonnet-4-5",
    "claude-sonnet-4-6",
    "claude-opus-4-5",
    "claude-opus-4-6",
]

CODEX_MODELS = [
    "gpt-5.3-codex",
    "gpt-5.2-codex",
]

CLAUDE_BIN     = os.path.expanduser("~/.local/bin/claude")
CLAUDE_TIMEOUT = 600
CODEX_TIMEOUT  = 300
CACHE_FILE     = Path(__file__).parent / "pelican_cache.json"
OUT_FILE       = Path(__file__).parent / "index.html"

_codex_sem = asyncio.Semaphore(1)   # codex starts agents-mcp per call — serialize to avoid conflicts


# ── helpers ───────────────────────────────────────────────────────────────────

def cache_key(prompt_id: str, model: str) -> str:
    return f"{prompt_id}::{model}"

def extract_svg(text: str) -> str:
    m = re.search(r"(<svg[\s\S]*?</svg>)", text, re.IGNORECASE)
    return m.group(1) if m else ""

def load_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}

def save_cache(cache: dict) -> None:
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


# ── callers ───────────────────────────────────────────────────────────────────

async def call_gemini(model: str, prompt: str) -> dict:
    from google import genai
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
    client = genai.Client(api_key=api_key)
    t0 = time.monotonic()
    try:
        response = await client.aio.models.generate_content(model=model, contents=prompt)
        svg = extract_svg(response.text)
        print(f"  ✓ gemini  {model} ({time.monotonic()-t0:.0f}s)")
        return {"provider": "Gemini", "svg": svg or None,
                "error": None if svg else "No SVG found in response"}
    except Exception as e:
        print(f"  ✗ gemini  {model} ({time.monotonic()-t0:.0f}s): {e}")
        return {"provider": "Gemini", "svg": None, "error": str(e)}


async def call_claude(model: str, prompt: str) -> dict:
    child_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    t0 = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            CLAUDE_BIN, "-p", prompt,
            "--model", model,
            "--tools", "",
            "--no-session-persistence",
            "--mcp-config", '{"mcpServers":{}}',
            "--strict-mcp-config",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=child_env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=CLAUDE_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            print(f"  ✗ claude  {model} (timeout)")
            return {"provider": "Claude", "svg": None, "error": f"Timed out after {CLAUDE_TIMEOUT}s"}
        elapsed = f"{time.monotonic()-t0:.0f}s"
        if proc.returncode != 0:
            err = stderr.decode().strip() or f"exit code {proc.returncode}"
            print(f"  ✗ claude  {model} ({elapsed}): {err[:100]}")
            return {"provider": "Claude", "svg": None, "error": err}
        svg = extract_svg(stdout.decode())
        print(f"  ✓ claude  {model} ({elapsed})")
        return {"provider": "Claude", "svg": svg or None,
                "error": None if svg else "No SVG found in response"}
    except Exception as e:
        print(f"  ✗ claude  {model}: {e}")
        return {"provider": "Claude", "svg": None, "error": str(e)}


async def call_codex(model: str, prompt: str) -> dict:
    async with _codex_sem:
        return await _codex_inner(model, prompt)

async def _codex_inner(model: str, prompt: str) -> dict:
    t0 = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            "codex", "exec",
            "-m", model,
            "--skip-git-repo-check",
            "--dangerously-bypass-approvals-and-sandbox",
            prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=CODEX_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            print(f"  ✗ codex   {model} (timeout)")
            return {"provider": "Codex", "svg": None, "error": f"Timed out after {CODEX_TIMEOUT}s"}
        elapsed = f"{time.monotonic()-t0:.0f}s"
        raw = stdout.decode()
        if proc.returncode != 0:
            err = stderr.decode().strip() or raw.strip() or f"exit code {proc.returncode}"
            print(f"  ✗ codex   {model} ({elapsed}): {err[:100]}")
            return {"provider": "Codex", "svg": None, "error": err}
        svg = extract_svg(raw)
        print(f"  ✓ codex   {model} ({elapsed})")
        return {"provider": "Codex", "svg": svg or None,
                "error": None if svg else "No SVG found in response"}
    except Exception as e:
        print(f"  ✗ codex   {model}: {e}")
        return {"provider": "Codex", "svg": None, "error": str(e)}


# ── HTML ──────────────────────────────────────────────────────────────────────

STYLES = {
    "Claude": ("#3d2a1a", "#ff9a4d"),
    "Gemini": ("#1a3a5c", "#4da6ff"),
    "Codex":  ("#1a3d1a", "#6dcc6d"),
}

ALL_MODELS_ORDERED = (
    [(m, "Gemini", call_gemini) for m in GEMINI_MODELS]
    + [(m, "Claude", call_claude) for m in CLAUDE_MODELS]
    + [(m, "Codex",  call_codex)  for m in CODEX_MODELS]
)

def card(model: str, r: dict) -> str:
    bg, fg = STYLES.get(r["provider"], ("#222", "#aaa"))
    body = (r["svg"] if r.get("svg") else
            f'<div class="err">{escape(r.get("error") or "not generated")}</div>')
    dim = ' <span class="dim">(cached)</span>' if r.get("cached") else ""
    return f"""<div class="card">
  <div class="hdr">
    <span class="badge" style="background:{bg};color:{fg}">{r["provider"]}</span>
    <span class="name">{model}{dim}</span>
  </div>
  <div class="canvas">{body}</div>
</div>"""

PROMPT_DESCRIPTIONS = {
    "pelican":          "A classic prompt with no cultural context — useful as a neutral baseline.",
    "indian":           "Tests whether models depict South Asian cultural elements accurately (clothing, street scene, vendors).",
    "animated_pelican": "Tests CSS/SMIL animation capability on a familiar subject.",
    "animated_indian":  "Combines cultural accuracy with animation — reveals both biases and technical skill.",
}

def build_html(cache: dict, active_prompts: list) -> str:
    complete_models = [
        (m, provider, fn) for m, provider, fn in ALL_MODELS_ORDERED
        if all(cache.get(cache_key(pid, m), {}).get("svg") for pid in active_prompts)
    ]
    dropped = [m for m, _, _ in ALL_MODELS_ORDERED
               if m not in {x for x, _, _ in complete_models}]
    if dropped:
        print(f"Dropped from HTML (incomplete): {dropped}")

    n_models = len(complete_models)
    cols = min(n_models, 4)

    tabs_html = ""
    panels_html = ""
    for i, pid in enumerate(active_prompts):
        label = PROMPT_LABELS.get(pid, pid)
        desc  = PROMPT_DESCRIPTIONS.get(pid, "")
        is_animated = "animated" in pid
        active_tab   = " active" if i == 0 else ""
        active_panel = " active" if i == 0 else ""
        anim_badge   = '<span class="anim-badge">animated</span>' if is_animated else ""
        tabs_html += (
            f'<button class="tab{active_tab}" onclick="show(\'{pid}\')" id="tab-{pid}">'
            f'{label}{" ▶" if is_animated else ""}</button>\n'
        )

        cards_html = ""
        for m, provider, _ in complete_models:
            key = cache_key(pid, m)
            r = cache[key]
            bg, fg = STYLES.get(provider, ("#222", "#aaa"))
            svg_content = r.get("svg", "")
            cards_html += f"""
<div class="card" onclick="openLight(this)">
  <div class="hdr">
    <span class="badge" style="background:{bg};color:{fg}">{provider}</span>
    <span class="name">{m}</span>
  </div>
  <div class="canvas" data-svg>{svg_content}</div>
  <div class="card-foot">click to expand</div>
</div>"""

        panels_html += f"""
<div class="panel{active_panel}" id="panel-{pid}">
  <div class="prompt-bar">
    <div class="prompt-label">{label} {anim_badge}</div>
    <div class="prompt-desc">{desc}</div>
    <div class="prompt-text"><em>Prompt:</em> {escape(PROMPTS[pid][:160])}…</div>
  </div>
  <div class="grid" style="grid-template-columns:repeat({cols},1fr)">{cards_html}</div>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI SVG Bias &amp; Style Comparison</title>
<style>
:root{{
  --bg:#0b0b0e;--surface:#15151a;--border:#26262f;--border2:#32323e;
  --text:#e2e2e8;--muted:#666;--muted2:#444;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}}
/* ── header ── */
.site-header{{
  text-align:center;padding:28px 20px 16px;
  border-bottom:1px solid var(--border);margin-bottom:0;
}}
.site-header h1{{font-size:1.5rem;font-weight:700;letter-spacing:-.01em;margin-bottom:4px}}
.site-header p{{color:var(--muted);font-size:.82rem}}
.pills{{display:flex;gap:8px;justify-content:center;margin-top:10px;flex-wrap:wrap}}
.pill{{background:var(--surface);border:1px solid var(--border2);border-radius:20px;
       font-size:.7rem;color:var(--muted);padding:3px 10px}}
/* ── tabs ── */
.tab-bar{{
  position:sticky;top:0;z-index:10;
  background:var(--bg);border-bottom:1px solid var(--border);
  display:flex;gap:0;overflow-x:auto;padding:0 20px;
}}
.tab{{
  background:none;border:none;border-bottom:3px solid transparent;
  color:var(--muted);cursor:pointer;font-size:.85rem;font-weight:500;
  padding:13px 18px;white-space:nowrap;transition:color .15s,border-color .15s;
}}
.tab:hover{{color:var(--text)}}
.tab.active{{color:var(--text);border-bottom-color:#7c7cff}}
/* ── prompt bar ── */
.prompt-bar{{
  background:var(--surface);border-bottom:1px solid var(--border);
  padding:14px 24px;display:flex;flex-direction:column;gap:4px;
}}
.prompt-label{{font-weight:600;font-size:.95rem;display:flex;align-items:center;gap:8px}}
.prompt-desc{{color:#aaa;font-size:.8rem}}
.prompt-text{{color:var(--muted);font-size:.74rem;font-style:italic;margin-top:2px}}
.anim-badge{{background:#1a2e1a;color:#5dbb5d;border:1px solid #2d4a2d;
             border-radius:4px;font-size:.6rem;padding:2px 6px;font-style:normal;font-weight:700;text-transform:uppercase}}
/* ── panels ── */
.panel{{display:none;padding:20px 20px 32px}}
.panel.active{{display:block}}
/* ── grid ── */
.grid{{display:grid;gap:16px;max-width:1900px;margin:0 auto}}
/* ── cards ── */
.card{{
  background:var(--surface);border:1px solid var(--border);border-radius:10px;
  overflow:hidden;display:flex;flex-direction:column;cursor:pointer;
  transition:border-color .15s,transform .1s;
}}
.card:hover{{border-color:var(--border2);transform:translateY(-2px)}}
.hdr{{padding:9px 12px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:7px}}
.badge{{font-size:.58rem;font-weight:700;padding:2px 6px;border-radius:3px;
        text-transform:uppercase;letter-spacing:.07em;white-space:nowrap}}
.name{{font-size:.74rem;color:var(--muted);word-break:break-all;flex:1}}
.canvas{{padding:10px;background:#f5f5f5;flex:1;display:flex;align-items:center;
         justify-content:center;min-height:200px;overflow:hidden}}
.canvas svg{{width:100%;height:auto;max-height:340px;display:block}}
.card-foot{{padding:5px 12px;font-size:.65rem;color:var(--muted2);text-align:right;
            border-top:1px solid var(--border);background:var(--bg)}}
/* ── lightbox ── */
#lightbox{{
  display:none;position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:100;
  align-items:center;justify-content:center;padding:24px;
}}
#lightbox.open{{display:flex}}
#lb-inner{{
  background:#fff;border-radius:12px;max-width:90vw;max-height:90vh;
  overflow:auto;padding:16px;position:relative;
}}
#lb-inner svg{{width:80vw;height:auto;max-height:80vh;display:block}}
#lb-close{{
  position:absolute;top:10px;right:14px;background:none;border:none;
  font-size:1.4rem;cursor:pointer;color:#333;line-height:1;
}}
</style>
</head>
<body>
<header class="site-header">
  <h1>AI SVG — Bias &amp; Style Comparison</h1>
  <p>Same prompt, {n_models} models. How do they differ — culturally, aesthetically, technically?</p>
  <div class="pills">
    <span class="pill">{n_models} models</span>
    <span class="pill">{len(active_prompts)} prompts</span>
    <span class="pill">Gemini · Claude · Codex</span>
  </div>
</header>

<div class="tab-bar">
{tabs_html}
</div>

{panels_html}

<!-- lightbox -->
<div id="lightbox" onclick="closeLight(event)">
  <div id="lb-inner">
    <button id="lb-close" onclick="closeLightDirect()">✕</button>
    <div id="lb-content"></div>
  </div>
</div>

<script>
function show(id){{
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.getElementById('panel-'+id).classList.add('active');
  document.getElementById('tab-'+id).classList.add('active');
}}
function openLight(card){{
  const svg = card.querySelector('[data-svg]').innerHTML;
  document.getElementById('lb-content').innerHTML = svg;
  document.getElementById('lightbox').classList.add('open');
}}
function closeLight(e){{
  if(e.target===document.getElementById('lightbox')) closeLightDirect();
}}
function closeLightDirect(){{
  document.getElementById('lightbox').classList.remove('open');
  document.getElementById('lb-content').innerHTML='';
}}
document.addEventListener('keydown',e=>{{ if(e.key==='Escape') closeLightDirect(); }});
</script>
</body>
</html>"""


# ── main ──────────────────────────────────────────────────────────────────────

async def main(prompt_filter: list | None = None):
    cache = load_cache()
    active_prompts = prompt_filter or list(PROMPTS.keys())

    # Determine what needs calling
    to_call = []
    for pid in active_prompts:
        prompt_text = PROMPTS[pid]
        for m, provider, fn in ALL_MODELS_ORDERED:
            key = cache_key(pid, m)
            if key not in cache:
                to_call.append((pid, m, provider, fn, prompt_text))

    cached_count = sum(
        1 for pid in active_prompts for m, _, _ in ALL_MODELS_ORDERED
        if cache_key(pid, m) in cache
    )

    print(f"Prompts : {active_prompts}")
    print(f"Cached  : {cached_count}  |  To call: {len(to_call)}\n")

    if to_call:
        tasks = [fn(m, pt) for pid, m, provider, fn, pt in to_call]
        results = await asyncio.gather(*tasks)
        for (pid, m, provider, fn, _), result in zip(to_call, results):
            result["provider"] = provider
            if result.get("svg"):
                cache[cache_key(pid, m)] = result
        save_cache(cache)

    with open(OUT_FILE, "w") as f:
        f.write(build_html(cache, active_prompts))
    print(f"\nSaved → {OUT_FILE}")


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--html-only" in args:
        cache = load_cache()
        active = list(PROMPTS.keys())
        with open(OUT_FILE, "w") as f:
            f.write(build_html(cache, active))
        print(f"HTML regenerated → {OUT_FILE}")
        sys.exit(0)

    prompt_filter = None
    if "--prompt" in args:
        idx = args.index("--prompt")
        pid = args[idx + 1]
        if pid not in PROMPTS:
            print(f"Unknown prompt '{pid}'. Available: {list(PROMPTS.keys())}")
            sys.exit(1)
        prompt_filter = [pid]

    asyncio.run(main(prompt_filter))
