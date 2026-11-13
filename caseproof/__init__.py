"""caseproof - certify differential-test case counts by content, not by loop."""

from .ledger import (
    CaseCountError,
    CaseLedger,
    Duplicate,
    certify_cases,
    default_key,
)

__version__ = "0.1.0"
__all__ = [
    "CaseCountError",
    "CaseLedger",
    "Duplicate",
    "certify_cases",
    "default_key",
]
