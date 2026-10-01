"""Strip AI tells from outgoing messages.

The model will produce clean, well-punctuated, slightly over-structured
prose no matter what the prompt says. That register is the tell — nobody
texts like that. This runs on every message after generation and before
sending.

Ordered roughly by how obvious the tell is.
"""

import random
import re
import unicodedata

# ---------------------------------------------------------------
# Phrases no human types on a dating app
# ---------------------------------------------------------------

BANNED_PHRASES = [
    # English AI tics
    "i'd love to", "i must say", "that said", "that being said",
    "it's worth noting", "i appreciate", "absolutely", "certainly",
    "delve", "navigate", "landscape", "testament", "tapestry",
    "dive into", "unpack", "resonate", "curated", "elevate",
    "game changer", "at the end of the day", "needless to say",
    "i hope this finds you", "feel free to", "don't hesitate",
    "sounds like a plan", "looking forward to hearing",
    # French AI tics
    "je serais ravi", "n'hésite pas", "cela dit", "il est vrai que",
    "je dois dire", "c'est fascinant", "absolument", "en effet",
    "je suis curieux de savoir", "cela me rappelle",
    "au plaisir", "je t'en prie", "ravi de faire ta connaissance",
]

# Structural giveaways
TRIPLE_DOT = re.compile(r"\.{3,}")
MULTI_PUNCT = re.compile(r"([!?])\1{1,}")
MULTI_SPACE = re.compile(r"[ \t]{2,}")
MULTI_NEWLINE = re.compile(r"\n{3,}")
LIST_MARKER = re.compile(r"^\s*[-*•]\s+", re.M)
NUMBERED = re.compile(r"^\s*\d+[.)]\s+", re.M)
MARKDOWN = re.compile(r"(\*\*|__|\*|_|`)")
EMOJI = re.compile(
    "["
    "\U0001F300-\U0001FAFF"   # symbols, pictographs, supplemental
    "\U00002600-\U000027BF"   # misc symbols, dingbats
    "\U0001F1E6-\U0001F1FF"   # regional indicators (flags)
    "\U00002190-\U000021FF"   # arrows
    "\U0001F900-\U0001F9FF"   # supplemental symbols
    "\U0001FA70-\U0001FAFF"
    "\U00002B00-\U00002BFF"
    "\U0000FE00-\U0000FE0F"   # variation selectors
    "\U0001F3FB-\U0001F3FF"   # skin tone modifiers
    "\U0000200D"               # zero-width joiner
    "\U000020E3"               # combining keycap
    "]+"
)

# Dashes: the single most recognisable tell
DASH_CHARS = {"\u2014": ", ", "\u2013": "-", "\u2015": ", "}


def _kill_dashes(text: str) -> str:
    """Em/en dashes never appear in casual texting. Replace, don't strip —
    the clause structure they hold together still needs to read."""
    for ch, repl in DASH_CHARS.items():
        text = text.replace(f" {ch} ", repl)
        text = text.replace(ch, repl.strip() or "-")
    # " - " used as an em dash substitute is equally telling
    text = re.sub(r"\s+-\s+", ", ", text)
    return text


def _limit_emoji(text: str, max_emoji: int = 1) -> str:
    """One emoji maximum, and only if it survived the coin flip."""
    found = EMOJI.findall(text)
    if not found:
        return text
    text = EMOJI.sub("", text)
    total = sum(len(f) for f in found)
    if total <= max_emoji and random.random() < 0.5:
        text = text.rstrip() + " " + found[0][0]
    return MULTI_SPACE.sub(" ", text).strip()


def _casualise_french(text: str) -> str:
    """Light register shift. Not slang cosplay — just the things that
    actually differ between written French and texted French."""
    subs = [
        (r"\bc'est-à-dire\b", "genre"),
        (r"\bcependant\b", "mais"),
        (r"\btoutefois\b", "mais"),
        (r"\bnéanmoins\b", "mais"),
        (r"\bafin de\b", "pour"),
        (r"\bde plus\b", "et"),
        (r"\bpar ailleurs\b", "sinon"),
        (r"\bvéritablement\b", "vraiment"),
        (r"\bextrêmement\b", "super"),
        (r"\bJ'apprécie\b", "J'aime bien"),
    ]
    for pat, rep in subs:
        text = re.sub(pat, rep, text, flags=re.I)
    # "ne ... pas" is dropped in speech and texting
    text = re.sub(r"\bne (\w+) pas\b", r"\1 pas", text)
    text = re.sub(r"\bn'(\w+) pas\b", r"\1 pas", text)

    # a substitution can leave a capitalised word mid-sentence
    def _fix(m):
        return m.group(1) + m.group(2).lower() + m.group(3)
    text = re.sub(r"([,;] )([A-ZÀ-Þ])(?=[a-zà-ÿ])", lambda m: m.group(1) + m.group(2).lower(), text)
    return text


def _drop_terminal_period(text: str) -> str:
    """Short texts don't end in full stops. Longer ones sometimes do."""
    lines = text.split("\n")
    out = []
    for ln in lines:
        ln = ln.rstrip()
        if ln.endswith(".") and not ln.endswith("..") and len(ln) < 90:
            ln = ln[:-1]
        out.append(ln)
    return "\n".join(out)


def _soften_caps(text: str) -> str:
    """People lowercase the start of a text fairly often. Not always —
    always-lowercase is its own tell."""
    if text and text[0].isupper() and random.random() < 0.35:
        text = text[0].lower() + text[1:]
    return text


def sanitize(text: str, lang: str = "fr") -> str:
    text = unicodedata.normalize("NFC", text.strip())

    # strip any markdown / list structure the model reached for
    text = LIST_MARKER.sub("", text)
    text = NUMBERED.sub("", text)
    text = MARKDOWN.sub("", text)

    text = _kill_dashes(text)
    text = TRIPLE_DOT.sub("...", text)
    text = MULTI_PUNCT.sub(r"\1", text)
    text = _limit_emoji(text)

    if lang == "fr":
        text = _casualise_french(text)

    text = MULTI_NEWLINE.sub("\n\n", text)
    text = MULTI_SPACE.sub(" ", text)
    # emoji removal can leave " ." or " !"
    text = re.sub(r"\s+([.,!?])", r"\1", text)
    text = MULTI_SPACE.sub(" ", text)

    text = _drop_terminal_period(text)
    text = _soften_caps(text)

    return text.strip()


def has_tells(text: str) -> list[str]:
    """Check for anything the sanitizer can't fix by rewriting. Caller
    should escalate rather than send if this returns anything."""
    problems = []
    low = text.lower()

    for phrase in BANNED_PHRASES:
        if phrase in low:
            problems.append(f"banned phrase: {phrase}")

    if len(text) > 320:
        problems.append("too long for a dating app message")
    if text.count("?") > 2:
        problems.append("interrogating her")
    if len(EMOJI.findall(text)) > 1:
        problems.append("emoji spam")
    if "\n\n" in text and len(text) > 200:
        problems.append("structured like an email")
    if re.search(r"\b(firstly|secondly|moreover|furthermore|premièrement|deuxièmement)\b", low):
        problems.append("essay connectives")

    return problems


def typing_delay(text: str) -> float:
    """Seconds to wait before sending, as if it were typed. Roughly
    40 wpm with a variable pause for reading her message first."""
    words = max(1, len(text.split()))
    return random.uniform(4, 14) + words * random.uniform(0.28, 0.55)
