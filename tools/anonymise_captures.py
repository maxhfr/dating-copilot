"""Turn raw profile captures into anonymised fixture candidates.

    python tools/anonymise_captures.py [captures_dir] [out_dir]

Reads ~/.dating-copilot/captures/*.txt, writes fixtures_candidates/capture-NN.txt
with names replaced, match-list names removed and handles/links/phone numbers
redacted, then prints what each file contains and suggests up to 5 varied ones.

It cannot know what is identifying inside a bio (a school, a workplace, a
pet's name...). Read the files you intend to share before committing them.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from platforms.tinder import _CHROME, _parse_name_age  # noqa: E402

NAME = "Alex"
REDACT = [(re.compile(r"https?://\S+"), "[removed]"),
          (re.compile(r"\S+@\S+\.\S+"), "[removed]"),
          (re.compile(r"@\w+"), "[removed]"),
          (re.compile(r"\+?\d[\d .\-]{7,}\d"), "[removed]")]


def _card_name(lines: list[str]) -> str | None:
    """Closed card: name and age sit on separate lines before 'Ouvrir le profil'."""
    for i, l in enumerate(lines):
        if (l.strip() == "Ouvrir le profil" and i >= 2
                and re.fullmatch(r"\d{2}", lines[i - 1].strip())):
            return lines[i - 2].strip()
    return None


def anonymise(body: str) -> str:
    lines = body.splitlines()
    name, _ = _parse_name_age(body)
    card_name = _card_name(lines)

    # Everything between "Messages" and the profile / card is the match list.
    start = next((i for i, l in enumerate(lines) if l.strip() == "Messages"), -1)
    end = len(lines)
    for i in range(start + 1, len(lines)):
        s = lines[i].strip()
        if s in ("Retour", "Par activité récente") or (
                name and re.fullmatch(rf"{re.escape(name)}\d{{2}}", s)):
            end = i
            break

    out = []
    for i, l in enumerate(lines):
        s = l.strip()
        if (start < i < end and s and s not in _CHROME
                and not re.fullmatch(r"[\d  ]*(Likes?)?", s)):
            l = "Match"
        out.append(l)
    text = "\n".join(out)

    for n in {name, card_name} - {None}:
        if len(n) > 1:
            text = re.sub(rf"(?<![A-Za-zÀ-ÿ]){re.escape(n)}(?![A-Za-zÀ-ÿ0-9])", NAME, text)
            text = re.sub(rf"^{re.escape(n)}(?=\d{{2}}$)", NAME, text, flags=re.M)
        else:   # one-letter name: only the name+age line is safe to rewrite
            text = re.sub(rf"^{re.escape(n)}(?=\d{{2}}$)", NAME, text, flags=re.M)
    for pat, repl in REDACT:
        text = pat.sub(repl, text)
    return text


def features(body: str) -> dict:
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    name, _ = _parse_name_age(body)
    km = [int(m.group(1)) for l in lines
          if (m := re.search(r"(\d+)\s*kilom", l.replace(" ", " ")))]
    return {
        "panel_open": any(l.startswith("Bloquer") for l in lines),
        "name_age_line": name is not None,
        "one_letter_name": bool(name) and len(name) == 1,
        "height": any(re.fullmatch(r"\d{2,3}\s*cm", l.replace(" ", " ")) for l in lines),
        "far_away": any(k >= 100 for k in km),
        "prompts": sum(1 for l in lines if l.endswith(("?", ":"))),
        "emoji_lines": sum(1 for l in lines if not re.search(r"[A-Za-zÀ-ÿ0-9]", l)),
        "lines": len(lines),
    }


def signature(f: dict) -> tuple:
    return (f["panel_open"], f["name_age_line"], f["one_letter_name"], f["height"],
            f["far_away"], min(f["prompts"], 2), f["emoji_lines"] > 0, f["lines"] // 25)


def pick(feats: list[dict], n: int = 5) -> list[int]:
    """Greedy: the richest file for each distinct signature."""
    order = sorted(range(len(feats)), key=lambda i: -feats[i]["lines"])
    seen, chosen = set(), []
    for i in order:
        sig = signature(feats[i])
        if sig not in seen:
            seen.add(sig)
            chosen.append(i)
        if len(chosen) == n:
            break
    return sorted(chosen)


def main(argv):
    src = Path(argv[1]) if len(argv) > 1 else Path.home() / ".dating-copilot" / "captures"
    dst = Path(argv[2]) if len(argv) > 2 else Path("fixtures_candidates")
    files = sorted(src.glob("*.txt"))
    if not files:
        print(f"No captures found in {src}")
        return 1
    dst.mkdir(parents=True, exist_ok=True)
    feats = []
    for i, f in enumerate(files, 1):
        body = f.read_text(encoding="utf-8")
        (dst / f"capture-{i:02d}.txt").write_text(anonymise(body), encoding="utf-8")
        feats.append(features(body))
    yn = lambda v: "yes" if v else "-"  # noqa: E731
    print(f"{len(files)} captures -> {dst}/capture-NN.txt\n")
    print("no  panel  name  1-letter  height  far  prompts  emoji  lines")
    for i, f in enumerate(feats, 1):
        print(f"{i:02d}  {yn(f['panel_open']):5}  {yn(f['name_age_line']):4}  "
              f"{yn(f['one_letter_name']):8}  {yn(f['height']):6}  {yn(f['far_away']):3}  "
              f"{f['prompts']:7}  {f['emoji_lines']:5}  {f['lines']:5}")
    chosen = pick(feats)
    print("\nSuggested (most varied):",
          ", ".join(f"capture-{i + 1:02d}.txt" for i in chosen))
    print("\nBefore sharing: open the suggested files and check the bio text for "
          "anything that identifies someone (school, workplace, pet or family names).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
