"""Records the README's hero GIF from a running console.

    uv run --with playwright==1.62.0 --with pillow python hero_gif.py --out ../docs/media/console.gif

Screenshots a short scripted visit (the feed moving, a ring case, a question to the analyst)
and assembles them with one shared palette, which keeps a dark, text-heavy UI small. No ffmpeg.
Playwright is pinned to the release matching the locally installed Chromium build.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import time

from PIL import Image
from playwright.async_api import async_playwright


async def capture(url: str, case_id: str, question: str, fps: float, size: tuple[int, int]) -> list[tuple[Image.Image, int]]:
    frames: list[tuple[Image.Image, int]] = []
    interval = 1.0 / fps

    async def shoot(page, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            t0 = time.monotonic()
            png = await page.screenshot(type="png")
            frames.append((Image.open(io.BytesIO(png)).convert("RGB"), int(interval * 1000)))
            await asyncio.sleep(max(0.0, interval - (time.monotonic() - t0)))

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": size[0], "height": size[1]}, color_scheme="dark",
                                      device_scale_factor=1)
        await page.goto(url)
        await page.wait_for_timeout(2500)                    # let the feed fill
        await shoot(page, 3.0)                               # decisions streaming in
        await page.goto(f"{url}#/case/{case_id}")
        await page.locator(".chat__suggest .qchip").first.wait_for(state="visible", timeout=20000)
        await page.wait_for_timeout(600)
        await shoot(page, 2.0)                               # the case: signals in words, the ring
        chip = page.locator(".chat__suggest .qchip", has_text=question)
        await chip.click()
        await shoot(page, 0.6)                               # the question going out
        await page.locator(".answer").first.wait_for(state="visible", timeout=90000)
        await page.wait_for_timeout(300)
        await shoot(page, 3.5)                               # the cited answer
        await browser.close()
    return frames


def assemble(frames: list[tuple[Image.Image, int]], out: str, width: int, hold_last_ms: int) -> None:
    scaled = [(im.resize((width, round(im.height * width / im.width)), Image.LANCZOS), d) for im, d in frames]
    # One palette for every frame: stable colours between frames compress far better. The
    # verdict and accent colours (dashboard/src/styles/tokens.css, dark theme) are rare pixels
    # in a dark UI, so a palette learnt from the frames alone greys them out; a band of
    # swatches in the sample guarantees them a slot.
    w, h = scaled[0][0].size
    picks = sorted({0, len(scaled) // 4, len(scaled) // 2, 3 * len(scaled) // 4, len(scaled) - 1})
    swatches = ["#4fb8c0", "#6ccbd2", "#3fb27f", "#e0a33a", "#e5534b", "#f0736c"]
    band = h // 6
    sample = Image.new("RGB", (w, h * len(picks) + band))
    for i, idx in enumerate(picks):
        sample.paste(scaled[idx][0], (0, i * h))
    for i, colour in enumerate(swatches):
        sample.paste(Image.new("RGB", (w // len(swatches), band), colour), (i * (w // len(swatches)), h * len(picks)))
    palette = sample.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    images = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im, _ in scaled]
    durations = [d for _, d in scaled]
    durations[-1] += hold_last_ms
    images[0].save(out, save_all=True, append_images=images[1:], duration=durations, loop=0,
                   optimize=True, disposal=1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:3000/")
    ap.add_argument("--case", default=None,
                    help="default: the featured ring case in ../dashboard/public/showcase/manifest.json")
    ap.add_argument("--question", default="Where did the money come from")
    ap.add_argument("--out", default="../docs/media/console.gif")
    ap.add_argument("--fps", type=float, default=5.0)
    ap.add_argument("--width", type=int, default=1024, help="output width; captured at 1440x900")
    args = ap.parse_args()
    if args.case is None:
        import json, pathlib
        manifest = json.loads((pathlib.Path(__file__).resolve().parent.parent / "dashboard/public/showcase/manifest.json")
                              .read_text())
        args.case = next(f["caseId"] for f in manifest["featured"] if f["pattern"] == "RING")
    frames = asyncio.run(capture(args.url, args.case, args.question, args.fps, (1440, 900)))
    assemble(frames, args.out, args.width, hold_last_ms=2500)
    import os
    print(f"{len(frames)} frames -> {args.out} ({os.path.getsize(args.out) / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
