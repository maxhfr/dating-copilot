"""The surface a dating platform must expose to the swipe session.

Extracted from what `Tinder` already provides. Only the swipe-side methods
live here; messaging (list_matches, read_match, send_message) stays
Tinder-specific for now.

Implementations are async context managers: entering launches the browser,
leaving closes it.
"""

from abc import ABC, abstractmethod


class Platform(ABC):
    @abstractmethod
    async def __aenter__(self): ...

    @abstractmethod
    async def __aexit__(self, *a): ...

    @abstractmethod
    async def ensure_logged_in(self):
        """Open the app; if not logged in, wait for the user to log in by hand."""

    @abstractmethod
    async def check_blocked(self, expect: str = "recs") -> str | None:
        """Return a description of a CAPTCHA / rate-limit / ban screen, else None.

        `expect` is the page context the caller should be on ("recs",
        "chat" or "any").
        """

    @abstractmethod
    async def dismiss_modals(self) -> str | None:
        """Clear upsells and popups blocking the deck. Return what was dismissed."""

    @abstractmethod
    async def read_current_profile(self) -> dict | None:
        """Read the top card.

        Returns a dict with at least: id, platform, name, age, photos
        (base64 JPEG), bio, distance_km, stated_height_cm, lifestyle,
        last_active_days. None if no readable card.
        """

    @abstractmethod
    async def swipe(self, like: bool):
        """Like (True) or pass (False) the current card."""

    @abstractmethod
    async def idle(self):
        """Do something that isn't swiping, to break up the decision stream."""

    @abstractmethod
    async def diagnose_no_card(self) -> str:
        """Explain why no card was found (and save debug output)."""
