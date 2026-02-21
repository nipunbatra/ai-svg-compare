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
    "scientist": (
        "Generate a complete, detailed SVG image of a scientist working in a laboratory. "
        "Include lab equipment, a lab coat, and a clear face with visible features. "
        "Output ONLY the raw SVG code, nothing else — no markdown, no explanation, "
        "no code fences. Start directly with <svg and end with </svg>."
    ),
    "wedding": (
        "Generate a complete, detailed SVG image of a wedding ceremony. "
        "Show the couple, decorations, and attire. "
        "Output ONLY the raw SVG code, nothing else — no markdown, no explanation, "
        "no code fences. Start directly with <svg and end with </svg>."
    ),
    "indian_wedding": (
        "Generate a complete, detailed SVG image of a traditional Indian Hindu wedding. "
        "Show the bride in a red lehenga or saree with gold jewellery, the groom in a "
        "sherwani and safa (turban), a decorated mandap (wedding canopy) with marigold "
        "flowers, diyas (oil lamps), and guests in colourful Indian attire. "
        "Include rich colours and cultural details. "
        "Output ONLY the raw SVG code, nothing else — no markdown, no explanation, "
        "no code fences. Start directly with <svg and end with </svg>."
    ),
    "elephant_zoo": (
        "Generate a complete, detailed SVG image of an elephant in an Indian zoo. "
        "Show the elephant decorated with traditional Indian paint patterns and a "
        "howdah (seat) on its back, with a mahout (elephant keeper) in traditional "
        "Indian clothing. Include zoo surroundings with Indian architectural elements, "
        "tropical trees, and signage in Hindi and English. "
        "Output ONLY the raw SVG code, nothing else — no markdown, no explanation, "
        "no code fences. Start directly with <svg and end with </svg>."
    ),
    "animated_scientist": (
        "Generate a complete animated SVG of a scientist working in a laboratory. "
        "Animate something meaningful — bubbling test tubes, a spinning centrifuge, "
        "blinking equipment lights, or the scientist writing on a board. "
        "Use CSS @keyframes or SMIL animations that loop indefinitely. "
        "Output ONLY the raw SVG code, nothing else — no markdown, no explanation, "
        "no code fences. Start directly with <svg and end with </svg>."
    ),
    "animated_wedding": (
        "Generate a complete animated SVG of a wedding ceremony. "
        "Animate something joyful — falling confetti or petals, waving guests, "
        "flickering candles, or ringing bells. "
        "Use CSS @keyframes or SMIL animations that loop indefinitely. "
        "Output ONLY the raw SVG code, nothing else — no markdown, no explanation, "
        "no code fences. Start directly with <svg and end with </svg>."
    ),
    "animated_indian_wedding": (
        "Generate a complete animated SVG of a traditional Indian Hindu wedding. "
        "Animate cultural details — diyas (oil lamps) flickering, marigold petals "
        "falling, the bride and groom exchanging garlands, or fireworks. "
        "Use CSS @keyframes or SMIL animations that loop indefinitely. "
        "Output ONLY the raw SVG code, nothing else — no markdown, no explanation, "
        "no code fences. Start directly with <svg and end with </svg>."
    ),
    "animated_elephant": (
        "Generate a complete animated SVG of a decorated Indian elephant walking slowly, "
        "with its trunk swaying, ears flapping, and the colourful howdah (seat) on its back. "
        "Include a mahout and a festive background with palm trees. "
        "Use CSS @keyframes or SMIL animations that loop indefinitely. "
        "Output ONLY the raw SVG code, nothing else — no markdown, no explanation, "
        "no code fences. Start directly with <svg and end with </svg>."
    ),
    "cricket": (
        "Generate a complete, detailed SVG image of a cricket match in progress. "
        "Show batsman, bowler, fielders, a pitch with wickets, and a crowd in the stands. "
        "Include realistic cricket attire and equipment. "
        "Output ONLY the raw SVG code, nothing else — no markdown, no explanation, "
        "no code fences. Start directly with <svg and end with </svg>."
    ),
    "animated_cricket": (
        "Generate a complete animated SVG of a cricket match. "
        "Animate the bowler running up and bowling, the batsman's swing, or the ball "
        "travelling through the air. Use CSS @keyframes or SMIL animations that loop indefinitely. "
        "Output ONLY the raw SVG code, nothing else — no markdown, no explanation, "
        "no code fences. Start directly with <svg and end with </svg>."
    ),
    # static counterpart for animated_indian (which is a rickshaw)
    "rickshaw": (
        "Generate a complete, detailed SVG image of a colourful Indian auto-rickshaw "
        "(tuk-tuk) on a busy street, with a driver visible and typical Indian street "
        "surroundings — shops, signs, and pedestrians. "
        "Output ONLY the raw SVG code, nothing else — no markdown, no explanation, "
        "no code fences. Start directly with <svg and end with </svg>."
    ),
    # animated counterpart for indian (which is a cyclist)
    "animated_indian_cyclist": (
        "Generate a complete animated SVG of a person in traditional Indian clothing "
        "riding a bicycle through a colourful Indian market street. "
        "Animate the spinning wheels, moving legs, and a gently swaying crowd or "
        "fluttering shop banners in the background. "
        "Use CSS @keyframes or SMIL animations that loop indefinitely. "
        "Output ONLY the raw SVG code, nothing else — no markdown, no explanation, "
        "no code fences. Start directly with <svg and end with </svg>."
    ),
}

# ── groups: each entry = (tab label, static_pid, animated_pid) ──────────────
PROMPT_GROUPS = [
    ("Pelican on Bicycle",  "pelican",       "animated_pelican"),
    ("Indian Cyclist",      "indian",        "animated_indian_cyclist"),
    ("Auto-Rickshaw",       "rickshaw",      "animated_indian"),
    ("Scientist in Lab",    "scientist",     "animated_scientist"),
    ("Wedding Ceremony",    "wedding",       "animated_wedding"),
    ("Indian Wedding",      "indian_wedding","animated_indian_wedding"),
    ("Indian Elephant",     "elephant_zoo",  "animated_elephant"),
    ("Cricket Match",       "cricket",       "animated_cricket"),
]

PROMPT_LABELS = {
    "pelican":                 "Pelican on Bicycle",
    "indian":                  "Indian Street Cyclist",
    "rickshaw":                "Indian Auto-Rickshaw",
    "animated_pelican":        "Animated Pelican",
    "animated_indian":         "Animated Auto-Rickshaw",
    "animated_indian_cyclist": "Animated Indian Cyclist",
    "scientist":               "Scientist in Lab",
    "wedding":                 "Wedding Ceremony",
    "indian_wedding":          "Indian Hindu Wedding",
    "elephant_zoo":            "Elephant at Indian Zoo",
    "animated_scientist":      "Animated Scientist",
    "animated_wedding":        "Animated Wedding",
    "animated_indian_wedding": "Animated Indian Wedding",
    "animated_elephant":       "Animated Indian Elephant",
    "cricket":                 "Cricket Match",
    "animated_cricket":        "Animated Cricket Match",
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
CACHE_FILE     = Path(__file__).parent / "svg_cache.json"
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
    "pelican":          "A neutral baseline — no cultural context, tests raw illustration quality.",
    "indian":           "Tests South Asian cultural accuracy: clothing, street scene, vendors, signage.",
    "animated_pelican": "Tests CSS/SMIL animation capability on a familiar subject.",
    "animated_indian":  "Combines cultural accuracy with animation — reveals both biases and technical skill.",
    "scientist":        "Classic bias probe: what does the default 'scientist' look like across models?",
    "wedding":          "What culture does a 'wedding' default to? Western white-dress or something else?",
    "indian_wedding":          "Explicitly Indian wedding — tests accuracy of cultural details, jewellery, mandap, attire.",
    "elephant_zoo":            "Indian zoo with decorated elephant — tests cultural specificity vs generic depiction.",
    "animated_scientist":      "Can models animate a lab scene meaningfully? Reveals technical skill.",
    "animated_wedding":        "Animated wedding — does the culture of the default wedding change when animated?",
    "animated_indian_wedding": "Animated Indian wedding — diyas, garlands, petals. Cultural + animation accuracy.",
    "animated_elephant":       "Animated decorated Indian elephant — trunk sway, ear flap, festive motion.",
    "rickshaw":                "Static auto-rickshaw — pair with animated version to compare.",
    "animated_indian_cyclist": "Animated Indian street cyclist — pair with static version to compare.",
    "cricket":                 "Cricket match — how do models depict the world's most popular bat-and-ball sport?",
    "animated_cricket":        "Animated cricket — bowler run-up, batting swing, or fielding action.",
}

def models_for_group(cache: dict, static_pid: str, anim_pid: str) -> list:
    """Models that have SVGs for both pids in a group."""
    return [
        (m, provider, fn) for m, provider, fn in ALL_MODELS_ORDERED
        if (cache.get(cache_key(static_pid, m), {}).get("svg") and
            cache.get(cache_key(anim_pid,   m), {}).get("svg"))
    ]

def build_html(cache: dict) -> str:
    # Only show groups where both prompts have at least one result
    active_groups = [
        (label, sp, ap) for label, sp, ap in PROMPT_GROUPS
        if any(cache.get(cache_key(sp, m), {}).get("svg") for m, _, _ in ALL_MODELS_ORDERED)
        and any(cache.get(cache_key(ap, m), {}).get("svg") for m, _, _ in ALL_MODELS_ORDERED)
    ]

    # Count totals for header
    all_pids      = [pid for _, sp, ap in active_groups for pid in (sp, ap)]
    complete_set  = set(m for m, _, _ in ALL_MODELS_ORDERED
                        if all(cache.get(cache_key(pid, m), {}).get("svg") for pid in all_pids))
    n_groups  = len(active_groups)
    n_prompts = len(all_pids)

    # Build JS registry — safe for embedding in <script>:
    # replace </script> → <\/script> so it can't terminate the tag
    def safe_js(s: str) -> str:
        return s.replace("</", "<\\/")

    registry_entries = []
    for _, static_pid, anim_pid in active_groups:
        for pid in (static_pid, anim_pid):
            models = models_for_group(cache, static_pid, anim_pid)
            entries = []
            for m, provider, _ in models:
                bg, fg = STYLES.get(provider, ("#222", "#aaa"))
                svg = cache.get(cache_key(pid, m), {}).get("svg", "")
                entries.append(
                    f"{{model:{json.dumps(m)},provider:{json.dumps(provider)},"
                    f"bg:{json.dumps(bg)},fg:{json.dumps(fg)},"
                    f"svg:{json.dumps(safe_js(svg))}}}"
                )
            registry_entries.append(f"  {json.dumps(pid)}: [{','.join(entries)}]")
    registry_js = "const REG = {\n" + ",\n".join(registry_entries) + "\n};\n"

    prompts_js = ("const PROMPTS_TEXT = " +
                  safe_js(json.dumps({p: PROMPTS[p] for _, sp, ap in active_groups
                                      for p in (sp, ap)})) + ";\n")

    tabs_html   = ""
    panels_html = ""
    for i, (group_label, static_pid, anim_pid) in enumerate(active_groups):
        gid        = static_pid          # use static pid as group id
        active_cls = " active" if i == 0 else ""
        tabs_html += (
            f'<button class="tab{active_cls}" onclick="showTab(\'{gid}\')" id="tab-{gid}">'
            f'{group_label}</button>\n'
        )

        models = models_for_group(cache, static_pid, anim_pid)
        dropped = [m for m, _, _ in ALL_MODELS_ORDERED if m not in {x for x, _, _ in models}]
        if dropped and i == 0:
            print(f"  [{group_label}] no full coverage for: {dropped}")

        def section(pid: str, is_anim: bool) -> str:
            desc = PROMPT_DESCRIPTIONS.get(pid, "")
            sec_label = "Animated ▶" if is_anim else "Static"
            cards = ""
            for idx, (m, provider, _) in enumerate(models):
                bg, fg = STYLES.get(provider, ("#222", "#aaa"))
                svg = cache.get(cache_key(pid, m), {}).get("svg", "")
                cards += (
                    f'<div class="card" onclick="openLb({json.dumps(pid)},{idx})" '
                    f'role="button" tabindex="0" aria-label="Expand {m}">'
                    f'<div class="hdr">'
                    f'<span class="badge" style="background:{bg};color:{fg}">{provider}</span>'
                    f'<span class="name">{m}</span></div>'
                    f'<div class="canvas">{svg}</div>'
                    f'<div class="card-foot">tap to expand</div></div>'
                )
            return (
                f'<div class="section-hdr">'
                f'<span class="sec-label{"  anim" if is_anim else ""}">{sec_label}</span>'
                f'<span class="sec-desc">{desc}</span>'
                f'<details class="prompt-full"><summary>prompt</summary>'
                f'<p>{escape(PROMPTS[pid])}</p></details>'
                f'</div>'
                f'<div class="grid">{cards}</div>'
            )

        panels_html += (
            f'<div class="panel{active_cls}" id="panel-{gid}">'
            f'{section(static_pid, False)}'
            f'<div class="section-divider"></div>'
            f'{section(anim_pid, True)}'
            f'</div>'
        )

    n_models = len(models_for_group(cache, active_groups[0][1], active_groups[0][2])) if active_groups else 0

    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI SVG — Bias &amp; Style Comparison</title>
<style>
/* ── themes ── */
[data-theme="dark"]{{
  --bg:#0b0b0e;--surface:#15151a;--surface2:#1e1e26;
  --border:#26262f;--border2:#3a3a48;
  --text:#e2e2e8;--muted:#888;--muted2:#555;
  --canvas-bg:#f5f5f5;
  --lb-bg:#1a1a22;--lb-border:#33334a;--lb-text:#e2e2e8;
  --tab-active:#7c7cff;
}}
[data-theme="light"]{{
  --bg:#f5f5f8;--surface:#ffffff;--surface2:#eeeef4;
  --border:#dddde8;--border2:#c8c8d8;
  --text:#18181f;--muted:#777;--muted2:#aaa;
  --canvas-bg:#f9f9f9;
  --lb-bg:#ffffff;--lb-border:#dddde8;--lb-text:#18181f;
  --tab-active:#5555ee;
}}
/* ── reset ── */
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;transition:background .2s,color .2s}}
a{{color:inherit}}
/* ── header ── */
.site-header{{
  text-align:center;padding:22px 20px 14px;
  border-bottom:1px solid var(--border);position:relative;
}}
.site-header h1{{font-size:clamp(1.1rem,4vw,1.5rem);font-weight:700;letter-spacing:-.01em;margin-bottom:3px}}
.site-header p{{color:var(--muted);font-size:clamp(.72rem,2vw,.84rem)}}
.pills{{display:flex;gap:6px;justify-content:center;margin-top:8px;flex-wrap:wrap}}
.pill{{background:var(--surface2);border:1px solid var(--border2);border-radius:20px;font-size:.68rem;color:var(--muted);padding:2px 9px}}
/* ── theme toggle ── */
.theme-btn{{
  position:absolute;top:16px;right:16px;
  background:var(--surface2);border:1px solid var(--border2);border-radius:8px;
  color:var(--text);cursor:pointer;font-size:1.1rem;padding:5px 9px;
  transition:background .15s;
}}
.theme-btn:hover{{background:var(--border2)}}
/* ── tab bar ── */
.tab-bar{{
  position:sticky;top:0;z-index:20;background:var(--bg);
  border-bottom:1px solid var(--border);
  display:flex;overflow-x:auto;padding:0 12px;
  scrollbar-width:none;-ms-overflow-style:none;
}}
.tab-bar::-webkit-scrollbar{{display:none}}
.tab{{
  background:none;border:none;border-bottom:3px solid transparent;
  color:var(--muted);cursor:pointer;font-size:clamp(.75rem,2vw,.85rem);font-weight:500;
  padding:12px 14px;white-space:nowrap;transition:color .15s,border-color .15s;flex-shrink:0;
}}
.tab:hover{{color:var(--text)}}
.tab.active{{color:var(--text);border-bottom-color:var(--tab-active)}}
/* ── prompt bar ── */
.prompt-bar{{
  background:var(--surface);border-bottom:1px solid var(--border);
  padding:12px 20px;display:flex;flex-direction:column;gap:4px;
}}
.prompt-meta{{display:flex;align-items:baseline;flex-wrap:wrap;gap:8px}}
.prompt-label{{font-weight:600;font-size:.9rem}}
.prompt-desc{{color:var(--muted);font-size:.78rem}}
.anim-badge{{background:#1a2e1a;color:#5dbb5d;border:1px solid #2d4a2d;
             border-radius:4px;font-size:.58rem;padding:1px 5px;font-weight:700;text-transform:uppercase;vertical-align:middle}}
.prompt-full{{margin-top:4px}}
.prompt-full summary{{font-size:.72rem;color:var(--muted);cursor:pointer;user-select:none}}
.prompt-full p{{margin-top:6px;font-size:.75rem;color:var(--muted);font-style:italic;
                background:var(--surface2);padding:8px 12px;border-radius:6px;line-height:1.5}}
/* ── panel / sections / grid ── */
.panel{{display:none;padding:0 0 40px}}
.panel.active{{display:block}}
.section-hdr{{
  padding:12px 20px;background:var(--surface);border-bottom:1px solid var(--border);
  display:flex;align-items:baseline;flex-wrap:wrap;gap:10px;
}}
.sec-label{{font-weight:700;font-size:.8rem;letter-spacing:.04em;color:var(--text);white-space:nowrap}}
.sec-label.anim{{color:#5dbb5d}}
.sec-desc{{font-size:.76rem;color:var(--muted);flex:1}}
.section-divider{{height:4px;background:var(--border)}}
.grid{{
  display:grid;gap:12px;max-width:1900px;margin:0 auto;padding:14px 16px;
  grid-template-columns:repeat(4,1fr);
}}
@media(max-width:1200px){{.grid{{grid-template-columns:repeat(3,1fr)}}}}
@media(max-width:800px) {{.grid{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:500px) {{.grid{{grid-template-columns:1fr}}}}
/* ── cards ── */
.card{{
  background:var(--surface);border:1px solid var(--border);border-radius:10px;
  overflow:hidden;display:flex;flex-direction:column;cursor:pointer;
  transition:border-color .15s,box-shadow .15s;
}}
.card:hover{{border-color:var(--border2);box-shadow:0 4px 20px rgba(0,0,0,.15)}}
.card:focus{{outline:2px solid var(--tab-active);outline-offset:2px}}
.hdr{{padding:8px 11px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:6px}}
.badge{{font-size:.57rem;font-weight:700;padding:2px 6px;border-radius:3px;
        text-transform:uppercase;letter-spacing:.07em;white-space:nowrap;flex-shrink:0}}
.name{{font-size:.72rem;color:var(--muted);word-break:break-all;flex:1;min-width:0}}
.canvas{{padding:8px;background:var(--canvas-bg);flex:1;display:flex;align-items:center;
         justify-content:center;min-height:180px;overflow:hidden}}
.canvas svg{{width:100%;height:auto;max-height:300px;display:block}}
.card-foot{{padding:4px 11px;font-size:.62rem;color:var(--muted2);text-align:right;
            border-top:1px solid var(--border)}}
/* ── lightbox overlay ── */
#lb-overlay{{
  display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:100;
  align-items:center;justify-content:center;padding:16px;
}}
#lb-overlay.open{{display:flex}}
/* ── lightbox box ── */
#lb-box{{
  background:var(--lb-bg);border:1px solid var(--lb-border);border-radius:14px;
  display:flex;flex-direction:column;max-width:min(860px,96vw);width:100%;
  max-height:95vh;overflow:hidden;position:relative;
}}
/* ── lightbox header ── */
#lb-hdr{{
  padding:12px 16px;border-bottom:1px solid var(--lb-border);
  display:flex;align-items:center;gap:8px;flex-shrink:0;
}}
#lb-badge{{font-size:.6rem;font-weight:700;padding:2px 7px;border-radius:3px;
           text-transform:uppercase;letter-spacing:.07em;white-space:nowrap}}
#lb-model{{font-size:.85rem;font-weight:600;color:var(--lb-text);flex:1}}
#lb-counter{{font-size:.75rem;color:var(--muted);white-space:nowrap}}
#lb-close{{background:none;border:none;font-size:1.2rem;cursor:pointer;color:var(--muted);padding:2px 6px;border-radius:4px}}
#lb-close:hover{{color:var(--lb-text)}}
/* ── lightbox svg area ── */
#lb-svg{{
  flex:1;overflow:auto;padding:16px;background:var(--canvas-bg);
  display:flex;align-items:center;justify-content:center;min-height:200px;
}}
#lb-svg svg{{width:100%;height:auto;max-height:60vh;display:block}}
/* ── lightbox footer ── */
#lb-ftr{{
  padding:10px 16px;border-top:1px solid var(--lb-border);
  display:flex;align-items:center;gap:10px;flex-shrink:0;
}}
#lb-prompt{{font-size:.72rem;color:var(--muted);font-style:italic;flex:1;
            line-height:1.4;max-height:4em;overflow:auto}}
.lb-nav{{
  background:var(--surface2);border:1px solid var(--lb-border);border-radius:8px;
  color:var(--lb-text);cursor:pointer;font-size:1rem;padding:6px 14px;
  transition:background .15s;flex-shrink:0;
}}
.lb-nav:hover{{background:var(--border2)}}
.lb-nav:disabled{{opacity:.3;cursor:default}}
</style>
</head>
<body>
<header class="site-header">
  <h1>AI SVG — Bias &amp; Style Comparison</h1>
  <p>Same prompt · {n_models} models · {n_groups} subjects · {n_prompts} total prompts · click any image to explore</p>
  <div class="pills">
    <span class="pill">{n_models} models</span>
    <span class="pill">{n_groups} subjects</span>
    <span class="pill">static + animated per subject</span>
    <span class="pill">Gemini · Claude · Codex</span>
  </div>
  <button class="theme-btn" onclick="toggleTheme()" id="theme-btn" title="Toggle light/dark">🌙</button>
</header>

<div class="tab-bar" id="tab-bar">
{tabs_html}
</div>

{panels_html}

<!-- lightbox -->
<div id="lb-overlay" role="dialog" aria-modal="true" aria-label="SVG viewer">
  <div id="lb-box">
    <div id="lb-hdr">
      <span id="lb-badge"></span>
      <span id="lb-model"></span>
      <span id="lb-counter"></span>
      <button id="lb-close" onclick="closeLb()" title="Close (Esc)">✕</button>
    </div>
    <div id="lb-svg"></div>
    <div id="lb-ftr">
      <button class="lb-nav" id="lb-prev" onclick="lbNav(-1)">&#8592;</button>
      <div id="lb-prompt"></div>
      <button class="lb-nav" id="lb-next" onclick="lbNav(1)">&#8594;</button>
    </div>
  </div>
</div>

<script>
{registry_js}
{prompts_js}
let lbPid = null, lbIdx = 0;

function openLb(pid, idx) {{
  lbPid = pid; lbIdx = idx;
  renderLb();
  document.getElementById('lb-overlay').classList.add('open');
  document.getElementById('lb-overlay').focus();
}}

function renderLb() {{
  const items = REG[lbPid];
  const item  = items[lbIdx];
  document.getElementById('lb-badge').textContent  = item.provider;
  document.getElementById('lb-badge').style.background = item.bg;
  document.getElementById('lb-badge').style.color      = item.fg;
  document.getElementById('lb-model').textContent  = item.model;
  document.getElementById('lb-counter').textContent = (lbIdx+1) + ' / ' + items.length;
  document.getElementById('lb-svg').innerHTML       = item.svg;
  document.getElementById('lb-prompt').textContent  = PROMPTS_TEXT[lbPid] || '';
  document.getElementById('lb-prev').disabled = lbIdx === 0;
  document.getElementById('lb-next').disabled = lbIdx === items.length - 1;
}}

function lbNav(dir) {{
  const items = REG[lbPid];
  lbIdx = Math.max(0, Math.min(items.length - 1, lbIdx + dir));
  renderLb();
}}

function closeLb() {{
  document.getElementById('lb-overlay').classList.remove('open');
  document.getElementById('lb-svg').innerHTML = '';
  lbPid = null;
}}

// Close on overlay click
document.getElementById('lb-overlay').addEventListener('click', e => {{
  if (e.target === document.getElementById('lb-overlay')) closeLb();
}});

// Keyboard nav
document.addEventListener('keydown', e => {{
  if (!document.getElementById('lb-overlay').classList.contains('open')) return;
  if (e.key === 'Escape')     closeLb();
  if (e.key === 'ArrowRight') lbNav(1);
  if (e.key === 'ArrowLeft')  lbNav(-1);
}});

// Card keyboard activation
document.querySelectorAll('.card').forEach(c => {{
  c.addEventListener('keydown', e => {{ if (e.key === 'Enter' || e.key === ' ') c.click(); }});
}});

// Tab switching
function showTab(id) {{
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('panel-' + id).classList.add('active');
  document.getElementById('tab-'   + id).classList.add('active');
}}

// Theme toggle
function toggleTheme() {{
  const html = document.documentElement;
  const next = html.dataset.theme === 'dark' ? 'light' : 'dark';
  html.dataset.theme = next;
  document.getElementById('theme-btn').textContent = next === 'dark' ? '🌙' : '☀️';
  try {{ localStorage.setItem('theme', next); }} catch(e) {{}}
}}
// Restore saved theme
try {{
  const saved = localStorage.getItem('theme');
  if (saved) {{
    document.documentElement.dataset.theme = saved;
    document.getElementById('theme-btn').textContent = saved === 'dark' ? '🌙' : '☀️';
  }}
}} catch(e) {{}}

// Scroll active tab into view on load
document.querySelector('.tab.active')?.scrollIntoView({{block:'nearest',inline:'center'}});
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
        f.write(build_html(cache))          # always render all prompts with data
    print(f"\nSaved → {OUT_FILE}")


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--html-only" in args:
        cache = load_cache()
        with open(OUT_FILE, "w") as f:
            f.write(build_html(cache))
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
