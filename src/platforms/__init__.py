"""Platform registry. Imports are lazy so an unused platform's code (and
its dependencies) is never loaded."""

PLATFORM_NAMES = ("tinder",)


def get_platform(name: str):
    """Return the Platform class registered under `name`."""
    if name == "tinder":
        from platforms.tinder import Tinder
        return Tinder
    raise ValueError(f"unknown platform {name!r}; "
                     f"choose one of: {', '.join(PLATFORM_NAMES)}")
