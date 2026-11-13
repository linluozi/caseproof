"""Reproduce the seed-reset bug that inflated a published case count 200x.

Run from the repository root:

    python3 examples/seed_reset.py

The buggy generator creates ``random.Random(4321)`` *inside* the function, so
every call returns the same document.  The loop still runs 2000 times, and a
naive test reports "2000 random documents, 0 mismatches".  caseproof hashes the
documents and shows the real number: 1.
"""

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from caseproof import CaseLedger


def buggy_doc():
    rng = random.Random(4321)  # BUG: reset per call -> identical document
    return {
        "title": "t" * 5,
        "words": [round(rng.random(), 12) for _ in range(40)],
        "nested": {"k": rng.randrange(1000) for _ in range(5)},
    }


def fixed_doc(rng):
    return {
        "title": "t" * 5,
        "words": [round(rng.random(), 12) for _ in range(40)],
        "nested": {"k": rng.randrange(1000) for _ in range(5)},
    }


def main():
    buggy = CaseLedger().extend(buggy_doc() for _ in range(2000))
    rng = random.Random(4321)
    fixed = CaseLedger().extend(fixed_doc(rng) for _ in range(2000))

    print("buggy generator (seed reset inside):")
    print("  declared %d  unique %d  ratio %.4f%%" % (
        buggy.total, buggy.unique, 100.0 * buggy.unique_ratio))
    print("  worst key repeated %dx" % buggy.duplicates()[0].count)
    print("fixed generator (seed created once):")
    print("  declared %d  unique %d  ratio %.4f%%" % (
        fixed.total, fixed.unique, 100.0 * fixed.unique_ratio))

    verdict = buggy.certify(min_unique=1000)
    print("certification: %s" % ("CERTIFIED" if verdict["certified"] else "REJECTED"))
    for failure in verdict["failures"]:
        print("  - %s" % failure)

    assert buggy.unique == 1
    assert fixed.unique == 2000
    assert not verdict["certified"]


if __name__ == "__main__":
    main()
