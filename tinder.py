"""Tinder web (tinder.com) via Playwright.

Session is persistent — you log in ONCE by hand in the launched browser,
and the profile directory keeps you logged in after that. The bot never
touches your password.

Selectors on tinder.com change regularly. Expect to fix these. They're
kept in one dict at the top so it's a two-minute job, not an archaeology
expedition.
"""

import asyncio
import base64
import random
from pathlib import Path
from playwright.async_api import async_playwright

PROFILE_DIR = Path.home() / ".dating-copilot" / "tinder-session"

SEL = {
    "card": 'div[data-testid="card"]',
    "matches_tab": 'a[href="/app/matches"]',
    "match_items": 'a[href^="/app/messages/"]',
    "msg_bubbles": 'div[class*="msg"]',
    "msg_input": 'textarea[placeholder], textarea',
    "match_name": 'h1, div[class*="chatName"]',
    "name": 'div[data-testid="card"] span[itemprop="name"]',
    "age": 'div[data-testid="card"] span[itemprop="age"]',
    "bio": 'div[class*="BreakWord"]',
    "distance": 'div:has-text("kilometres away")',
    "like_btn": 'button[aria-label="Like"]',
    "pass_btn": 'button[aria-label="Nope"]',
    "expand": 'button[aria-label="Open Profile"]',
    "photos": 'div[aria-label*="Profile slider"] div[role="img"]',
}


def _pause(lo=1.4, hi=4.2):
    """Human-ish gap. Uniform timing is the easiest bot tell there is."""
    r = random.random()
    if r < 0.08:
        # occasionally something distracts you
        return random.uniform(20, 75)
    if r < 0.22:
        # sometimes you actually read the profile
        return random.uniform(6, 16)
    if r < 0.34:
        # sometimes you're just clearing the queue
        return random.uniform(0.7, 1.3)
    return random.uniform(lo, hi)


CAPTCHA_MARKERS = [
    "captcha", "recaptcha", "hcaptcha", "arkose", "funcaptcha",
    "verify you", "are you a robot", "unusual activity",
    "vérification", "activité inhabituelle",
]


class Tinder:
    def __init__(self, headless=False):
        self.headless = headless

    async def __aenter__(self):
        self._pw = await async_playwright().start()
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self.ctx = await self._pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=self.headless,
            viewport={"width": 1280, "height": 900},
            locale="fr-FR",
            timezone_id="Europe/Paris",
            geolocation={"latitude": 48.8566, "longitude": 2.3522},
            permissions=["geolocation"],
        )
        self.page = self.ctx.pages[0] if self.ctx.pages else await self.ctx.new_page()
        return self

    async def __aexit__(self, *a):
        await self.ctx.close()
        await self._pw.stop()

    async def ensure_logged_in(self):
        await self.page.goto("https://tinder.com/app/recs", wait_until="domcontentloaded")
        await asyncio.sleep(3)
        if "/app/recs" not in self.page.url:
            print("\n>>> Not logged in. Log in manually in the browser window.")
            print(">>> Press Enter here once you're on the swipe screen.\n")
            input()

    async def check_blocked(self) -> str | None:
        """Detect a CAPTCHA, rate-limit wall, or ban screen. We do NOT
        attempt to solve or bypass any of these — the session stops and
        you get pinged."""
        try:
            body = (await self.page.inner_text("body")).lower()
        except Exception:
            return None

        for marker in CAPTCHA_MARKERS:
            if marker in body:
                return f"challenge screen detected ({marker})"
        if "out of likes" in body or "plus de likes" in body:
            return "out of likes"
        if "account has been banned" in body or "compte a été banni" in body:
            return "account banned"
        if "/app/recs" not in self.page.url:
            return f"navigated away from swipe screen ({self.page.url})"
        return None

    async def idle(self):
        """Do something that isn't swiping. Real users don't produce an
        unbroken stream of decisions."""
        action = random.random()
        if action < 0.4:
            await self.page.mouse.move(random.randint(300, 900),
                                       random.randint(200, 700))
        elif action < 0.7:
            await self.page.mouse.wheel(0, random.randint(-300, 300))
        await asyncio.sleep(random.uniform(2, 9))

    async def read_current_profile(self) -> dict | None:
        """Expand the card and pull everything the rubric needs."""
        try:
            await self.page.click(SEL["expand"], timeout=5000)
        except Exception:
            pass
        await asyncio.sleep(_pause(0.8, 1.6))

        async def _text(sel):
            try:
                el = await self.page.query_selector(sel)
                return (await el.inner_text()).strip() if el else None
            except Exception:
                return None

        name = await _text(SEL["name"])
        if not name:
            return None

        photos = []
        for el in (await self.page.query_selector_all(SEL["photos"]))[:4]:
            try:
                shot = await el.screenshot()
                photos.append(base64.b64encode(shot).decode())
            except Exception:
                continue

        age_txt = await _text(SEL["age"])
        dist_txt = await _text(SEL["distance"]) or ""

        return {
            "id": f"tinder:{name}:{age_txt}",
            "platform": "tinder",
            "name": name,
            "age": int(age_txt) if age_txt and age_txt.isdigit() else None,
            "bio": await _text(SEL["bio"]) or "",
            "distance_km": _first_int(dist_txt),
            "photos": photos,
            "last_active_days": None,  # tinder web doesn't expose this
        }

    async def swipe(self, like: bool):
        await asyncio.sleep(_pause())
        await self.page.click(SEL["like_btn"] if like else SEL["pass_btn"])
        await asyncio.sleep(_pause(0.6, 1.8))


def _first_int(s: str):
    digits = "".join(c if c.isdigit() else " " for c in s).split()
    return int(digits[0]) if digits else None


    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    async def list_matches(self) -> list[str]:
        """Match IDs that have a conversation thread."""
        await self.page.goto("https://tinder.com/app/matches",
                             wait_until="domcontentloaded")
        await asyncio.sleep(_pause(2, 4))
        ids = []
        for el in await self.page.query_selector_all(SEL["match_items"]):
            href = await el.get_attribute("href")
            if href and "/app/messages/" in href:
                ids.append(href.rsplit("/", 1)[-1])
        return ids

    async def read_match(self, match_id: str) -> tuple[dict, list[dict]]:
        """Open a thread and return (match_info, history)."""
        await self.page.goto(f"https://tinder.com/app/messages/{match_id}",
                             wait_until="domcontentloaded")
        await asyncio.sleep(_pause(1.5, 3.5))

        name = None
        try:
            el = await self.page.query_selector(SEL["match_name"])
            name = (await el.inner_text()).strip() if el else None
        except Exception:
            pass

        history = []
        for b in await self.page.query_selector_all(SEL["msg_bubbles"]):
            try:
                txt = (await b.inner_text()).strip()
                if not txt:
                    continue
                cls = (await b.get_attribute("class")) or ""
                role = "me" if "out" in cls.lower() else "her"
                history.append({"role": role, "text": txt})
            except Exception:
                continue

        return {"id": match_id, "name": name or match_id}, history

    async def send_message(self, match_id: str, text: str):
        if self.page.url.rsplit("/", 1)[-1] != match_id:
            await self.page.goto(f"https://tinder.com/app/messages/{match_id}",
                                 wait_until="domcontentloaded")
            await asyncio.sleep(_pause(1.5, 3))

        box = await self.page.query_selector(SEL["msg_input"])
        if not box:
            raise RuntimeError("message input not found")

        await box.click()
        # Type it rather than pasting — instant full-string fill is a tell.
        for ch in text:
            await box.type(ch, delay=random.uniform(30, 130))
            if random.random() < 0.03:
                await asyncio.sleep(random.uniform(0.3, 1.2))
        await asyncio.sleep(random.uniform(0.4, 1.6))
        await self.page.keyboard.press("Enter")
        await asyncio.sleep(_pause(1, 3))
