"""Tinder web (tinder.com) via Playwright.

Session is persistent — you log in ONCE by hand in the launched browser,
and the profile directory keeps you logged in after that. The bot never
touches your password.

Selectors change regularly. Everything site-specific lives in SEL at the
top, so fixing a break is a two-minute job rather than archaeology.
"""

import asyncio
import base64
import pathlib
import random
import re
from pathlib import Path
from playwright.async_api import async_playwright

PROFILE_DIR = Path.home() / ".dating-copilot" / "tinder-session"

SEL = {
    # data-testid is GONE from tinder.com as of 2026. Everything below is
    # based on a live DOM probe. Swipe buttons carry no aria-label — they
    # are identified by their inner text instead.
    "name": 'span[itemprop="name"]',
    "age": 'span[itemprop="age"]',
    "like_btn": 'button:has-text("LIKE")',
    "pass_btn": 'button:has-text("NON")',
    "open_profile": 'button:has-text("Ouvrir le profil")',
    "photo_tabs": 'button[aria-label^="Photo "]',
    "next_photo": 'button[aria-label="Photo suivante"]',
    # messaging (verified against the live DOM)
    "match_links": 'a[href^="/app/messages/"]',
    "tab_matches": 'button:has-text("Matchs"), a:has-text("Matchs")',
    "tab_messages": 'button:has-text("Messages"), a:has-text("Messages")',
    "msg_input": 'textarea[placeholder="Rédigez un message"]',
    "send_btn": 'button:has-text("Envoyer")',
}

# Tinder web is fully keyboard-driven, and using keys beats clicking:
# it survives class-name churn and looks closer to real input.
#
#   ArrowRight  like          ArrowLeft  pass
#   ArrowUp     open profile  ArrowDown  close profile
#   Space       next photo
USE_KEYBOARD = True


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
    "are you a robot", "unusual activity", "activité inhabituelle",
    "suspicious activity", "activité suspecte",
]


from platforms.base import Platform
from platforms.capture import save_capture


class Tinder(Platform):
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
        await self.page.goto("https://tinder.com/app/recs",
                             wait_until="domcontentloaded")
        await asyncio.sleep(3)
        if "/app/" not in self.page.url:
            print("\n>>> Not logged in. Log in manually in the browser window.")
            print(">>> Press Enter here once you're on the swipe screen.\n")
            input()

    async def check_blocked(self, expect: str = "recs") -> str | None:
        """Detect a CAPTCHA, rate-limit wall or ban screen.

        `expect` says which page this caller should be on: the swipe loop
        lives on /app/recs, the chat loop on /app/matches and
        /app/messages. Being on the "wrong" one is only a problem if it
        isn't where the caller expects to be.
        """
        try:
            body = (await self.page.inner_text("body")).lower()
        except Exception:
            return None

        for marker in CAPTCHA_MARKERS:
            if marker in body:
                pathlib.Path("debug_blocked.txt").write_text(
                    f"MARKER: {marker}\nURL: {self.page.url}\n\n{body[:3000]}",
                    encoding="utf-8")
                try:
                    await self.page.screenshot(path="debug_blocked.png")
                except Exception:
                    pass
                return f"challenge screen detected ({marker})"

        if "out of likes" in body or "plus de likes" in body:
            return "out of likes"
        if "account has been banned" in body or "compte a été banni" in body:
            return "account banned"

        ok_paths = {
            "recs": ("/app/recs",),
            "chat": ("/app/matches", "/app/messages"),
            "any": ("/app/",),
        }.get(expect, ("/app/",))

        if not any(p in self.page.url for p in ok_paths):
            return f"unexpected page ({self.page.url})"
        return None

    async def dismiss_modals(self) -> str | None:
        """Tinder interrupts the deck with upsells, match popups and
        'first like' promos. They block swiping entirely, so clear any
        that are up before reading a card.

        Returns the label of whatever it dismissed, or None.
        """
        DISMISS = [
            # Data-sharing consent for Tinder's chat AI features. Decline:
            # never opt in to data sharing on someone's behalf.
            "Non merci",
            "No thanks",
            "Peut-être plus tard",      # Gold / Plus upsell
            "Maybe later",
            "Pas maintenant",
            "Not now",
            "Continuer à swiper",       # after a match
            "Keep swiping",
            "Plus tard",
            "Ignorer",
            "Refuser",
        ]
        for label in DISMISS:
            try:
                btn = self.page.locator(f'button:has-text("{label}")').first
                if await btn.is_visible(timeout=700):
                    await asyncio.sleep(random.uniform(0.6, 1.8))
                    await btn.click()
                    await asyncio.sleep(random.uniform(0.8, 2.0))
                    return label
            except Exception:
                continue

        # Fall back to the close (X) control some modals use instead.
        for sel in ['button[aria-label="Close"]',
                    'button[aria-label="Fermer"]',
                    'button[title="Close"]']:
            try:
                btn = self.page.locator(sel).first
                if await btn.is_visible(timeout=500):
                    await asyncio.sleep(random.uniform(0.5, 1.4))
                    await btn.click()
                    await asyncio.sleep(random.uniform(0.8, 1.8))
                    return "close button"
            except Exception:
                continue
        return None

    async def diagnose_no_card(self) -> str:
        """Called when the deck looks empty. Dumps state so the reason is
        visible after the browser has closed."""
        try:
            body = await self.page.inner_text("body")
        except Exception as e:
            return f"no card found (page unreadable: {e})"

        try:
            await self.page.screenshot(path="debug_nocard.png")
            pathlib.Path("debug_nocard.txt").write_text(
                f"URL: {self.page.url}\n\n{body[:4000]}", encoding="utf-8")
        except Exception:
            pass

        # A modal we didn't recognise may simply be in the way.
        if await self.dismiss_modals():
            return "popup was blocking the deck (dismissed, retry next run)"

        low = body.lower()
        known = [
            ("out of likes", "out of likes"),
            ("plus de likes", "out of likes"),
            ("tu as atteint", "daily like limit reached"),
            ("reviens plus tard", "told to come back later"),
            ("aucun profil", "no profiles left in this area"),
            ("no one new", "no new profiles"),
            ("élargis tes critères", "no profiles left - widen your filters"),
            ("c'est un match", "a match popup is blocking the deck"),
            ("obtenir tinder", "an upsell popup is blocking the deck"),
            ("abonne", "a subscription popup is blocking the deck"),
            ("premier like", "Gold upsell popup ('first like') blocking the deck"),
            ("tinder gold", "Tinder Gold upsell blocking the deck"),
            ("passez à tinder", "Tinder upsell blocking the deck"),
        ]
        for needle, label in known:
            if needle in low:
                return label
        return "no card found (see debug_nocard.png / .txt)"

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
        """Read the top card.

        ArrowUp opens the profile, which renders EVERYTHING (bio, prompts,
        lifestyle, distance, height) into the page text at once. Do NOT
        scroll afterwards — the wheel closes the profile again.
        """
        await asyncio.sleep(_pause(0.8, 1.6))

        dismissed = await self.dismiss_modals()
        if dismissed:
            print(f"  (dismissed popup: {dismissed})")
            await asyncio.sleep(random.uniform(1.0, 2.2))

        photos = []
        try:
            photos.append(base64.b64encode(
                await self.page.screenshot(type="jpeg", quality=72)).decode())
        except Exception:
            pass

        await self.page.keyboard.press("ArrowUp")
        await asyncio.sleep(_pause(1.4, 2.8))

        try:
            body = await self.page.inner_text("body")
        except Exception:
            return None

        save_capture(body)

        name, age = _parse_name_age(body)
        if not name:
            return None

        for _ in range(3):
            try:
                await self.page.keyboard.press("Space")
                await asyncio.sleep(random.uniform(0.5, 1.1))
                photos.append(base64.b64encode(
                    await self.page.screenshot(type="jpeg", quality=72)).decode())
            except Exception:
                break

        await self.page.keyboard.press("ArrowDown")
        await asyncio.sleep(random.uniform(0.4, 1.0))

        fields = _parse_fields(body, name)
        return {
            "id": f"tinder:{name}:{age}",
            "platform": "tinder",
            "name": name,
            "age": age,
            "photos": photos,
            "last_active_days": None,
            **fields,
        }

    async def swipe(self, like: bool):
        await asyncio.sleep(_pause())
        if USE_KEYBOARD:
            await self.page.keyboard.press("ArrowRight" if like else "ArrowLeft")
        else:
            await self.page.click(SEL["like_btn"] if like else SEL["pass_btn"])
        await asyncio.sleep(_pause(0.6, 1.8))

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    async def _links_in_sidebar(self) -> list[dict]:
        out = []
        for el in await self.page.query_selector_all(SEL["match_links"]):
            href = await el.get_attribute("href")
            if not href or "/app/messages/" not in href:
                continue
            name = (await el.inner_text()).strip().split("\n")[0]
            out.append({"id": href.rsplit("/", 1)[-1], "name": name})
        return out

    async def list_matches(self) -> list[dict]:
        """Every match thread, from BOTH sidebar tabs.

        Tinder splits them: "Matchs" holds matches with no conversation
        yet, "Messages" holds ones you've already written to. Reading only
        one tab misses half of them — and specifically misses every thread
        with a reply waiting.
        """
        await self.page.goto("https://tinder.com/app/matches",
                             wait_until="domcontentloaded")
        await asyncio.sleep(_pause(2.5, 4.5))
        await self.dismiss_modals()

        found, seen = [], set()
        for tab in ("tab_matches", "tab_messages"):
            try:
                el = self.page.locator(SEL[tab]).first
                if await el.is_visible(timeout=2000):
                    await el.click()
                    await asyncio.sleep(random.uniform(1.5, 3.0))
            except Exception:
                pass

            for entry in await self._links_in_sidebar():
                if entry["id"] in seen:
                    continue
                seen.add(entry["id"])
                found.append(entry)

        return found

    async def read_match(self, match_id: str,
                         name_hint: str = "") -> tuple[dict, list[dict]]:
        """Open a thread. Returns (match_info, history).

        The right-hand panel carries her full profile — intent, bio,
        passions, lifestyle — which is far richer hook material than the
        swipe card offers.

        The panel loads asynchronously, so we wait for it rather than
        reading whatever happens to be rendered. A half-loaded page looks
        exactly like an empty profile, and drafting from that produces a
        useless opener.
        """
        await self.page.goto(f"https://tinder.com/app/messages/{match_id}",
                             wait_until="domcontentloaded")

        body = ""
        for attempt in range(4):
            await asyncio.sleep(_pause(1.5, 3.0) if attempt == 0
                                else random.uniform(2.0, 3.5))
            try:
                body = await self.page.inner_text("body")
            except Exception:
                continue
            if any(m in body for m in ("Je recherche", "L’essentiel",
                                       "L'essentiel", "Bloquer",
                                       "Historique de conversation")):
                break

        if not body:
            return {"id": match_id, "name": name_hint or match_id,
                    "loaded": False}, []

        name, age = _parse_name_age(body)
        name = name or name_hint or match_id[:8]

        profile = _parse_match_profile(body, name)
        history = _parse_history(body, name, profile.get("passions"))

        loaded = bool(profile.get("bio") or profile.get("passions")
                      or profile.get("lifestyle") or history)

        return ({"id": match_id, "name": name, "age": age,
                 "loaded": loaded, **profile}, history)

    async def send_message(self, match_id: str, text: str):
        if match_id not in self.page.url:
            await self.page.goto(f"https://tinder.com/app/messages/{match_id}",
                                 wait_until="domcontentloaded")
            await asyncio.sleep(_pause(1.5, 3))

        box = await self.page.query_selector(SEL["msg_input"])
        if not box:
            raise RuntimeError("message input not found")

        await box.click()
        # Typed, not pasted — an instant full-string fill is a tell.
        for ch in text:
            await box.type(ch, delay=random.uniform(30, 130))
            if random.random() < 0.03:
                await asyncio.sleep(random.uniform(0.3, 1.2))
        await asyncio.sleep(random.uniform(0.5, 1.8))

        try:
            await self.page.click(SEL["send_btn"], timeout=3000)
        except Exception:
            await self.page.keyboard.press("Enter")
        await asyncio.sleep(_pause(1, 3))


def _first_int(s: str):
    digits = "".join(c if c.isdigit() else " " for c in s).split()
    return int(digits[0]) if digits else None


# ----------------------------------------------------------------------
# Page-text parsing
#
# With a profile open, tinder.com renders everything as flat text:
#
#   Morgan27                 <- name and age, concatenated
#   Retour
#   Je recherche             <- relationship intent
#   L'essentiel
#   à 24 kilomètres          <- distance
#   170 cm                   <- height (optional)
#   Mode de vie
#   Alcool / En soirée le week-end
#   Bloquer <name>           <- end of profile content
# ----------------------------------------------------------------------

_CHROME = {
    "Passer au contenu principal", "Vous", "BOOST", "Explore", "Mode bureau",
    "Outils de sécurité", "Matches navigation", "Matchs", "Messages",
    "Retour", "L'essentiel", "L’essentiel", "Mode de vie", "NON",
    "SUPERLIKE", "LIKE", "Masquer", "Raccourci clavier", "Non", "Like",
    "Ouvrir le profil", "Fermer le profil", "Superlike", "Photo suivante",
    "Commencez à matcher.", "Dites bonjour", "REWIND", "SWIPE NOTES",
    "Par activité récente", "Voir plus",
}

_LIFESTYLE_KEYS = {
    "Alcool": "drinking",
    "Sport": "exercise",
    "Animal de compagnie": "pets",
    "À quelle fréquence tu fumes ?": "smoking",
    "Tabac": "smoking",
    "Je recherche": "intent",
    "Niveau d'études": "education",
    "Niveau d’études": "education",
}


def _is_emoji_only(line: str) -> bool:
    """Tinder pads some fields with a decorative emoji on its own line."""
    return bool(line) and not re.search(r"[A-Za-zÀ-ÿ0-9]", line)


def _clean_lines(body: str) -> list[str]:
    out = []
    for raw in body.splitlines():
        l = raw.strip()
        if not l or l in _CHROME or l.startswith(("Appuie sur", "Vos Matchs",
                                                  "Vous souhaitez engager")):
            continue
        out.append(l)
    return out


def _parse_name_age(body: str) -> tuple[str | None, int | None]:
    """Name and age arrive concatenated, e.g. 'Morgan27'."""
    for l in _clean_lines(body):
        m = re.fullmatch(r"([^\d]{2,30}?)(\d{2})", l)
        if m and 18 <= int(m.group(2)) <= 99:
            return m.group(1).strip(), int(m.group(2))
    return None, None


def _parse_fields(body: str, name: str) -> dict:
    lines = _clean_lines(body)

    # Everything before "Bloquer <name>" is profile content.
    try:
        end = next(i for i, l in enumerate(lines) if l.startswith("Bloquer"))
        lines = lines[:end]
    except StopIteration:
        pass

    distance = height = None
    lifestyle, free_text = {}, []
    i = 0
    while i < len(lines):
        l = lines[i]

        m = re.search(r"(\d+)\s*kilom", l)
        if m:
            distance = int(m.group(1)); i += 1; continue

        m = re.fullmatch(r"(\d{2,3})\s*cm", l)
        if m:
            height = int(m.group(1)); i += 1; continue

        if l in _LIFESTYLE_KEYS:
            # The value may be preceded by a decorative emoji line.
            j = i + 1
            while j < len(lines) and _is_emoji_only(lines[j]):
                j += 1
            if j < len(lines):
                lifestyle[_LIFESTYLE_KEYS[l]] = lines[j]
            i = j + 1; continue

        # A prompt ends with ':' or '?'; the next line is its answer.
        if l.endswith((":", "?")) and i + 1 < len(lines):
            free_text.append(f"{l} {lines[i + 1]}")
            i += 2; continue

        if (l not in {"Femme", "Homme"}
                and not re.fullmatch(r"[\W\d]+", l)
                and l != name
                and not re.fullmatch(rf"{re.escape(name)}\d{{2}}", l)):
            free_text.append(l)
        i += 1

    return {
        "bio": " | ".join(free_text)[:900],
        "distance_km": distance,
        "stated_height_cm": height,
        "lifestyle": lifestyle,
    }


# ----------------------------------------------------------------------
# Message-thread parsing
# ----------------------------------------------------------------------

_THREAD_CHROME = {
    "Retour", "Emoji", "Envoyer", "Rédigez un message", "GIF",
    "Plus d’infos sur moi", "Plus d'infos sur moi", "Passions",
    "L’essentiel", "L'essentiel", "Mode de vie", "Je recherche",
    "Dites bonjour", "Matchs", "Messages", "Explore", "Vous",
    "BOOST", "Mode bureau", "Outils de sécurité", "Matches navigation",
    "Bio Tinder",
}

_PROFILE_SECTIONS = ("Je recherche", "L’essentiel", "L'essentiel",
                     "Plus d’infos sur moi", "Plus d'infos sur moi",
                     "Mode de vie", "Passions", "Bio Tinder")


def _parse_history(body: str, name: str,
                   passions: list[str] | None = None) -> list[dict]:
    """Messages exchanged so far, with correct speaker attribution.

    Tinder prefixes each message with a speaker line:

        Historique de conversation avec Sarah
        Envoyé à 21:01
        21:01
        Vous:                          <- speaker marker
        alors on doit deviner...       <- the message
        Envoyé                         <- delivery receipt

    Without this, every message reads as hers and the bot ends up
    replying to itself.
    """
    lines = [l.strip() for l in body.splitlines() if l.strip()]

    try:
        start = next(i for i, l in enumerate(lines)
                     if l.startswith("Historique de conversation"))
    except StopIteration:
        return []

    try:
        end = next(i for i, l in enumerate(lines[start:], start)
                   if l.startswith("Réponds à") or l == "Rédigez un message")
    except StopIteration:
        end = len(lines)

    # On a new match Tinder shows the interests you have in common as
    # chips inside the empty thread. They are not messages.
    shared = set(passions or [])
    SKIP_EXACT = {"Envoyé", "Distribué", "Vu", "Lu", "Delivered", "Sent", "Seen"}

    history, speaker = [], None
    for l in lines[start + 1:end]:
        # Speaker markers
        if l == "Vous:" or l.startswith("Vous :"):
            speaker = "me"
            continue
        if l == f"{name}:" or l.startswith(f"{name} :"):
            speaker = "her"
            continue

        # Chrome, receipts, timestamps, shared-interest chips
        if (l in _THREAD_CHROME or l in SKIP_EXACT or l in shared
                or l.startswith(("Envoyé à", "Vous avez obtenu un Match",
                                 "il y a ", "Tu peux choisir",
                                 "Ton dernier message",
                                 "Le dernier message"))
                or re.fullmatch(r"\d{1,2}:\d{2}", l)
                or re.fullmatch(r"\d{2}/\d{2}/\d{4}", l)
                # date + time on one line, e.g. "20/08/2026 21:16"
                or re.fullmatch(r"\d{2}/\d{2}/\d{4}\s+\d{1,2}:\d{2}", l)
                or re.fullmatch(r"(hier|aujourd'hui|today|yesterday)\s*\d{0,2}:?\d{0,2}",
                                l, re.I)):
            continue

        # Unmarked lines default to her: Tinder labels your own messages
        # explicitly, so anything unlabelled came from the other side.
        history.append({"role": speaker or "her", "text": l})
        speaker = None

    return history


def _parse_match_profile(body: str, name: str) -> dict:
    """Her profile from the right-hand panel: bio, intent, passions,
    lifestyle.

    Passions and her written bio are the best opener material on the page
    — they're specific and she chose them.
    """
    lines = [l.strip() for l in body.splitlines() if l.strip()]

    try:
        start = next(i for i, l in enumerate(lines) if l == "Je recherche")
    except StopIteration:
        return {"bio": "", "passions": [], "lifestyle": {}, "distance_km": None}

    try:
        end = next(i for i, l in enumerate(lines[start:], start)
                   if l.startswith(("Supprimer le Match", "Bloquer", "Signaler")))
    except StopIteration:
        end = len(lines)

    seg = lines[start:end]
    passions, lifestyle, essentials, free_bio = [], {}, [], []
    distance = None
    section = None

    i = 0
    while i < len(seg):
        l = seg[i]
        if l in _PROFILE_SECTIONS:
            section = l
            i += 1
            continue

        m = re.search(r"(\d+)\s*kilom", l)
        if m:
            distance = int(m.group(1))
            i += 1
            continue

        if section == "Bio Tinder":
            free_bio.append(l)
        elif section == "Passions":
            passions.append(l)
        elif section == "Mode de vie" and i + 1 < len(seg):
            key = _LIFESTYLE_KEYS.get(l)
            if key:
                j = i + 1
                while j < len(seg) and _is_emoji_only(seg[j]):
                    j += 1
                if j < len(seg):
                    lifestyle[key] = seg[j]
                i = j + 1
                continue
        elif not _is_emoji_only(l) and l != name:
            essentials.append(l)
        i += 1

    # Her own written bio first — it's the richest hook material.
    bio_bits = free_bio + essentials
    if passions:
        bio_bits.append(f"Passions: {', '.join(passions)}")

    return {
        "bio": " | ".join(bio_bits)[:900],
        "passions": passions,
        "lifestyle": lifestyle,
        "distance_km": distance,
    }
