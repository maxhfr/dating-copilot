"""Check the quality gate against known-good and known-bad drafts.

    python test_gate.py

Makes real API calls (a few cents). Run it after changing gate.py or the
opener rules, to confirm the gate still catches what it should.
"""

import sys
sys.path.insert(0, "src")
from gate import review

# (message, should_pass, why[, kind])
CASES = [
    ("alors je tente ma chance : dimanche matin en salle de sport, à négocier "
     "un cours et avec la coach. J'ai bon?",
     False, "broken syntax"),
    ("Paddle et canoë dans la même liste, faut choisir un camp normalement. "
     "T'es plutôt debout stable ou t'aimes bien te retrouver à l'eau?",
     True, "clean, one idea"),
    ("Cuisine et sushi tous les deux dans tes passions, du coup t'es plutôt "
     "du genre à rouler tes propres makis ou c'est juste pour les manger direct?",
     True, "one question with two-noun setup - must NOT be rejected"),
    ("T'es plutôt sushi ou pizza ? Et sinon tu fais quoi comme sport ?",
     False, "genuinely two questions"),
    ("Paddle et canoë dans la même liste, faut choisir un camp normalement.",
     True, "two nouns, one idea"),
    ("Ton chat a exactement la même tête que le mien quand il veut manger",
     True, "natural"),
    ("je pense pas que ce soit une bonne idée", True,
     "dropped 'ne' is correct register", "reply"),
    ("t'es plutôt du genre à te lever tôt le dimanche ou pas du tout",
     True, "casual forms are fine"),
    ("Je serais ravi de faire ta connaissance et j'espère que ce message te "
     "trouve en bonne santé.",
     False, "stilted, nobody texts this"),
]

if __name__ == "__main__":
    passed = 0
    for case in CASES:
        msg, expected, why = case[0], case[1], case[2]
        kind = case[3] if len(case) > 3 else "opener"
        ok, problem = review(msg, kind=kind)
        good = ok == expected
        passed += good
        mark = "OK  " if good else "MISS"
        print(f"{mark} expected={'pass' if expected else 'fail'} "
              f"got={'pass' if ok else 'fail'}  ({why})")
        if not ok:
            print(f"       gate said: {problem}")
    print(f"\n{passed}/{len(CASES)} correct")
