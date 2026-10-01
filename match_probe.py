"""Inspect the matches / messages pages so the chat selectors can be
written against reality rather than guessed.

    python match_probe.py

Reads only. Sends nothing, clicks nothing destructive.
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

        out = []

        # ---- matches list ----
        await page.goto("https://tinder.com/app/matches")
        await asyncio.sleep(6)

        out.append("=== URL ===")
        out.append(page.url)

        out.append("\n=== ALL LINKS ===")
        for l in await page.eval_on_selector_all("a", """els => els.map(e => ({
            href: e.getAttribute('href'),
            text: (e.innerText||'').trim().slice(0,50)
        }))"""):
            out.append(str(l))

        out.append("\n=== MATCHES PAGE TEXT ===")
        out.append(await page.inner_text("body"))

        await page.screenshot(path="match_probe_list.png")

        # ---- open the first conversation, if there is one ----
        links = await page.eval_on_selector_all(
            "a", "els => els.map(e => e.getAttribute('href')).filter(h => h && h.includes('/app/messages/'))")
        out.append(f"\n=== MESSAGE THREAD HREFS ===\n{links}")

        if links:
            await page.goto("https://tinder.com" + links[0])
            await asyncio.sleep(5)

            out.append(f"\n=== THREAD URL ===\n{page.url}")

            out.append("\n=== THREAD PAGE TEXT ===")
            out.append(await page.inner_text("body"))

            out.append("\n=== TEXTAREAS / INPUTS ===")
            out.append(str(await page.eval_on_selector_all(
                "textarea, input[type=text]", """els => els.map(e => ({
                    tag: e.tagName,
                    placeholder: e.getAttribute('placeholder'),
                    aria: e.getAttribute('aria-label'),
                    cls: (e.className||'').toString().slice(0,60)
                }))""")))

            await page.screenshot(path="match_probe_thread.png")
        else:
            out.append("\n(no message threads found)")

        Path("match_probe.txt").write_text("\n".join(out), encoding="utf-8")
        print("Saved match_probe.txt, match_probe_list.png, match_probe_thread.png")
        await ctx.close()


asyncio.run(main())
