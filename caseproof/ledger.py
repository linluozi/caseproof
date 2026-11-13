"""Cryptographic accounting for differential-test case counts.

A test that says "2000 random documents, 0 mismatches" is only as strong as
the number of *distinct* documents it actually exercised.  This module keeps
a sha256 ledger of every case, so the declared count can be checked against
the number of independent samples before a claim is published.
"""

from __future__ import annotations

import hashlib
import json
import pickle
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence


class CaseCountError(AssertionError):
    """Raised when a declared differential-test count is not backed by data."""


def default_key(case: Any) -> bytes:
    """Return a deterministic byte key for *case*.

    JSON values use a canonical, key-sorted encoding.  Bytes and strings get
    explicit type tags so that ``b"1"``, ``"1"`` and ``1`` never collapse into
    one sample.  Objects that JSON cannot encode fall back to pickle; callers
    with non-deterministic objects should pass their own ``key=`` function.
    """
    if isinstance(case, bytes):
        return b"b:" + case
    if isinstance(case, bytearray):
        return b"b:" + bytes(case)
    if isinstance(case, str):
        return b"s:" + case.encode("utf-8", "surrogatepass")
    try:
        text = json.dumps(
            case,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        try:
            return b"p:" + pickle.dumps(case, protocol=4)
        except Exception as exc:  # pragma: no cover - defensive
            raise TypeError(
                "case is not JSON- or pickle-serialisable; pass key= explicitly"
            ) from exc
    return b"j:" + text.encode("utf-8", "surrogatepass")


def _preview(case: Any, limit: int) -> str:
    try:
        text = repr(case)
    except Exception:  # pragma: no cover - defensive
        text = "<unrepr-able %s>" % type(case).__name__
    if len(text) > limit:
        text = text[: limit - 1] + "\u2026"
    return text


@dataclass
class _Entry:
    count: int
    key_bytes: int
    sample: str


@dataclass(frozen=True)
class Duplicate:
    """One content key that was supplied more than once."""

    digest: str
    count: int
    key_bytes: int
    sample: str


class CaseLedger:
    """Count declared cases and unique content keys side by side.

    >>> ledger = CaseLedger()
    >>> _ = ledger.add({"a": 1})
    >>> _ = ledger.add({"a": 1})
    >>> ledger.total, ledger.unique
    (2, 1)
    """

    def __init__(
        self,
        key: Optional[Callable[[Any], bytes]] = None,
        sample_chars: int = 80,
    ) -> None:
        self._key = key or default_key
        self._sample_chars = sample_chars
        self._entries: Dict[str, _Entry] = {}
        self._labels: Dict[str, set] = {}
        self._label_totals: Dict[str, int] = {}
        self._total = 0

    def add(self, case: Any, label: Optional[str] = None) -> str:
        """Record one case and return its sha256 digest."""
        raw = self._key(case)
        if not isinstance(raw, (bytes, bytearray)):
            raise TypeError("key function must return bytes, got %r" % type(raw))
        digest = hashlib.sha256(bytes(raw)).hexdigest()
        entry = self._entries.get(digest)
        if entry is None:
            self._entries[digest] = _Entry(1, len(raw), _preview(case, self._sample_chars))
        else:
            entry.count += 1
        self._total += 1
        if label is not None:
            self._labels.setdefault(label, set()).add(digest)
            self._label_totals[label] = self._label_totals.get(label, 0) + 1
        return digest

    def extend(
        self,
        cases: Iterable[Any],
        label: Optional[str] = None,
        labels: Optional[Sequence[Optional[str]]] = None,
    ) -> "CaseLedger":
        """Add every case; optionally give each case its own label."""
        if labels is not None and len(labels) != len(cases):  # type: ignore[arg-type]
            raise ValueError("labels must have the same length as cases")
        for index, case in enumerate(cases):
            self.add(case, labels[index] if labels is not None else label)
        return self

    @property
    def total(self) -> int:
        return self._total

    @property
    def unique(self) -> int:
        return len(self._entries)

    @property
    def duplicate_events(self) -> int:
        return self._total - self.unique

    @property
    def unique_ratio(self) -> float:
        return self.unique / self._total if self._total else 0.0

    def duplicates(self, top: int = 10) -> List[Duplicate]:
        """Repeated keys, worst first (ties broken by digest for stability)."""
        repeated = [
            Duplicate(digest, entry.count, entry.key_bytes, entry.sample)
            for digest, entry in self._entries.items()
            if entry.count > 1
        ]
        repeated.sort(key=lambda item: (-item.count, item.digest))
        return repeated[:top]

    def label_counts(self) -> Dict[str, Dict[str, int]]:
        return {
            label: {
                "total": self._label_totals.get(label, 0),
                "unique": len(self._labels.get(label, ())),
            }
            for label in sorted(self._labels)
        }

    def report(self, top: int = 10) -> Dict[str, Any]:
        """Machine-readable accounting; no pass/fail judgement."""
        return {
            "total": self.total,
            "unique": self.unique,
            "duplicate_events": self.duplicate_events,
            "unique_ratio": round(self.unique_ratio, 6),
            "labels": self.label_counts(),
            "top_duplicates": [
                {
                    "digest": item.digest,
                    "count": item.count,
                    "key_bytes": item.key_bytes,
                    "sample": item.sample,
                }
                for item in self.duplicates(top)
            ],
        }

    def certify(
        self,
        min_unique: int,
        per_label: Optional[Dict[str, int]] = None,
        top: int = 3,
    ) -> Dict[str, Any]:
        """Return ``report()`` plus explicit failures for every unmet floor."""
        report = self.report(top=top)
        failures: List[str] = []
        if self.unique < min_unique:
            failures.append(
                "unique %d < required %d (declared %d, %.3f%% distinct)"
                % (self.unique, min_unique, self.total, 100.0 * self.unique_ratio)
            )
            worst = self.duplicates(top=1)
            if worst:
                item = worst[0]
                failures.append(
                    "worst key sha256:%s repeated %dx (%d bytes): %s"
                    % (item.digest[:16], item.count, item.key_bytes, item.sample)
                )
        if per_label:
            counts = self.label_counts()
            for label, floor in sorted(per_label.items()):
                seen = counts.get(label, {}).get("unique", 0)
                if seen < floor:
                    failures.append(
                        "label %r: unique %d < required %d" % (label, seen, floor)
                    )
        report["requirements"] = {
            "min_unique": min_unique,
            "per_label": dict(sorted((per_label or {}).items())),
        }
        report["certified"] = not failures
        report["failures"] = failures
        return report

    def require(
        self,
        min_unique: int,
        per_label: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """Like :meth:`certify`, but raise :class:`CaseCountError` on failure."""
        report = self.certify(min_unique, per_label)
        if not report["certified"]:
            raise CaseCountError("; ".join(report["failures"]))
        return report


def certify_cases(
    cases: Iterable[Any],
    min_unique: int,
    key: Optional[Callable[[Any], bytes]] = None,
    label: Optional[str] = None,
) -> Dict[str, Any]:
    """One-shot convenience wrapper around :class:`CaseLedger`."""
    return CaseLedger(key=key).extend(cases, label=label).certify(min_unique)
