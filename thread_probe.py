"""Dump a message thread that HAS messages in it, so speaker attribution
can be written properly.

    python thread_probe.py <thread-url-or-id>

Example:
    python thread_probe.py https://tinder.com/app/messages/6a74bcc9...

Reads only. Sends nothing.
"""

import asyncio
import sys
from pathlib import Path
from playwright.async_api import async_playwright

PROFILE_DIR = Path.home() / ".dating-copilot" / "tinder-session"


async def main(thread: str):
    tid = thread.rsplit("/", 1)[-1]
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR), headless=False,
            viewport={"width": 1280, "height": 900}, locale="fr-FR",
            timezone_id="Europe/Paris",
            geolocation={"latitude": 48.8566, "longitude": 2.3522},
            permissions=["geolocation"])
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        await page.goto(f"https://tinder.com/app/messages/{tid}")
        await asyncio.sleep(8)

        out = [f"=== URL ===\n{page.url}\n"]

        out.append("=== PAGE TEXT ===")
        out.append(await page.inner_text("body"))

        # The important part: how is each message marked in the DOM?
        out.append("\n\n=== MESSAGE ELEMENTS ===")
        out.append(str(await page.eval_on_selector_all(
            "div, span, p", """els => els
                .filter(e => e.children.length === 0
                          && (e.innerText||'').trim().length > 3
                          && (e.innerText||'').trim().length < 300)
                .slice(-60)
                .map(e => ({
                    text: (e.innerText||'').trim().slice(0,120),
                    tag: e.tagName,
                    cls: (e.className||'').toString().slice(0,110),
                    parentCls: (e.parentElement?.className||'').toString().slice(0,110)
                }))""")))

        out.append("\n\n=== ARIA / ROLE ATTRIBUTES ===")
        out.append(str(await page.eval_on_selector_all(
            "[aria-label], [role]", """els => els.slice(-40).map(e => ({
                aria: e.getAttribute('aria-label'),
                role: e.getAttribute('role'),
                text: (e.innerText||'').trim().slice(0,80)
            }))""")))

        Path("thread_probe.txt").write_text("\n".join(out), encoding="utf-8")
        await page.screenshot(path="thread_probe.png")
        print("Saved thread_probe.txt and thread_probe.png")
        await ctx.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
