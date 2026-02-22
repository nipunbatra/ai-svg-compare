#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright", "Pillow"]
# ///
"""
Capture animated SVGs from the comparison site as GIFs.

Run:  uv run save_gifs.py
"""

import io
import json
import sys
import threading
import http.server
from pathlib import Path
from playwright.sync_api import sync_playwright
from PIL import Image

CACHE_FILE = Path(__file__).parent / "svg_cache.json"
OUT_DIR    = Path(__file__).parent / "screenshots"
OUT_DIR.mkdir(exist_ok=True)

# animated prompt_id → (tab_gid, sub)
ANIMATED = {
    "animated_pelican":        "pelican",
    "animated_indian_cyclist": "indian",
    "animated_indian":         "rickshaw",
    "animated_scientist":      "scientist",
    "animated_wedding":        "wedding",
    "animated_diwali":         "diwali",
    "animated_cricket":        "cricket",
    "animated_indian_wedding": "indian_wedding",
    "animated_elephant":       "elephant_zoo",
    "animated_peacock":        "peacock",
    "animated_chess":          "chess",
    "animated_archery":        "archery",
    "animated_macbook_pro":    "macbook_pro",
    "animated_surface_laptop": "surface_laptop",
}

FPS      = 12
DURATION = 3.0   # seconds to record
WIDTH    = 1400
HEIGHT   = 860


def start_server(directory: Path, port: int) -> threading.Thread:
    handler = http.server.SimpleHTTPRequestHandler
    handler.log_message = lambda *a: None  # silence logs
    server = http.server.HTTPServer(("127.0.0.1", port), handler)

    import os
    os.chdir(directory)

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


def capture_gif(page, tab_gid: str, pid: str, out_path: Path):
    page.goto("http://127.0.0.1:8743", wait_until="networkidle")
    page.evaluate(f"showTab('{tab_gid}'); showSub('{tab_gid}','anim');")
    page.wait_for_timeout(800)   # let animation start

    frames = []
    n_frames = int(DURATION * FPS)
    interval = int(1000 / FPS)

    for _ in range(n_frames):
        png = page.screenshot()
        frames.append(Image.open(io.BytesIO(png)).convert("RGBA"))
        page.wait_for_timeout(interval)

    # Save as GIF
    frames[0].save(
        out_path,
        save_all=True,
        append_images=frames[1:],
        loop=0,
        duration=int(1000 / FPS),
        optimize=False,
    )
    print(f"  saved → {out_path.name}  ({len(frames)} frames)")


def main():
    filter_pid = sys.argv[1] if len(sys.argv) > 1 else None

    server = start_server(Path(__file__).parent, 8743)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})

        for pid, tab_gid in ANIMATED.items():
            if filter_pid and pid != filter_pid:
                continue
            out_path = OUT_DIR / f"{pid}.gif"
            print(f"Recording {pid} ...")
            capture_gif(page, tab_gid, pid, out_path)

        browser.close()

    server.shutdown()
    print("\nDone.")


if __name__ == "__main__":
    main()
