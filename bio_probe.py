"""Dump what the expanded profile actually contains, so bio extraction
can be written against reality instead of guesswork.

    python bio_probe.py

Opens Tinder, waits 20s for you to reach a card, then opens the profile
and writes bio_probe.txt with the raw page text at each scroll step.
"""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

PROFILE_DIR = Path.home() / ".dating-copilot" / "tinder-session"


async def main():
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR), headless=False,
            viewport={"width": 1280, "height": 900}, locale="fr-FR",
            timezone_id="Europe/Paris",
            geolocation={"latitude": 48.8566, "longitude": 2.3522},
            permissions=["geolocation"])
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://tinder.com/app/recs")

        print("\n>>> Get to a card with a visible bio. Starting in 20s...\n")
        await asyncio.sleep(20)

        out = []

        names = await page.query_selector_all('span[itemprop="name"]')
        name = (await names[-1].inner_text()).strip() if names else "?"
        out.append(f"=== NAME DETECTED: {name!r} ===")
        out.append(f"=== name elements found: {len(names)} ===\n")

        out.append("=== BODY, CARD COLLAPSED ===")
        out.append(await page.inner_text("body"))

        await page.keyboard.press("ArrowUp")
        await asyncio.sleep(2.5)

        for i in range(4):
            out.append(f"\n\n=== BODY, PROFILE OPEN, SCROLL STEP {i} ===")
            out.append(await page.inner_text("body"))
            await page.mouse.wheel(0, 400)
            await asyncio.sleep(1.2)

        Path("bio_probe.txt").write_text("\n".join(out), encoding="utf-8")
        await page.screenshot(path="bio_probe.png")
        print("Saved bio_probe.txt and bio_probe.png")
        await ctx.close()


asyncio.run(main())
