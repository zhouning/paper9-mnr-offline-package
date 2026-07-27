"""Central land-use code handling for authority fusion and Paper9 MPC.

Production data follows GB/T 21010-2017 and the Third National Land Survey
four-digit base codes.  The original Paper9 test fixtures used a separate
three-digit code set, which remains readable but must never be mixed with the
production swappable codes in one dataset.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from numbers import Integral, Real
from typing import Iterable


CURRENT_LAND_USE_SCHEME = "gbt21010_2017_third_survey"
LEGACY_LAND_USE_SCHEME = "legacy_three_digit_test_data"
UNKNOWN_LAND_USE_SCHEME = "unknown"

CURRENT_FARMLAND_BASE_CODES = frozenset({"0101", "0102", "0103"})
CURRENT_ORCHARD_BASE_CODES = frozenset({"0201", "0202", "0203", "0204"})
CURRENT_FOREST_BASE_CODES = frozenset(
    {"0301", "0302", "0303", "0304", "0305", "0306", "0307"}
)

LEGACY_FARMLAND_CODES = frozenset({"011", "012", "013"})
LEGACY_ORCHARD_CODES = frozenset({"021", "022", "023"})
LEGACY_FOREST_CODES = frozenset({"031", "032", "033"})

DEFAULT_FARM_DLBM = "0101"
DEFAULT_FOREST_DLBM = "0301"

_CURRENT_SWAPPABLE_CODES = CURRENT_FARMLAND_BASE_CODES | CURRENT_FOREST_BASE_CODES
_LEGACY_SWAPPABLE_CODES = LEGACY_FARMLAND_CODES | LEGACY_FOREST_CODES
_BARRIER_TWO_DIGIT_CLASSES = frozenset({"10", "11", "20"})


class LandUseCodeError(ValueError):
    """Raised when land-use codes cannot safely drive Paper9 optimization."""


@dataclass(frozen=True)
class LandUseCodeReport:
    scheme: str
    feature_count: int
    code_counts: dict[str, int]
    category_counts: dict[str, int]
    scheme_counts: dict[str, int]
    unrecognized_code_counts: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        if self.scheme == CURRENT_LAND_USE_SCHEME:
            standard = "GB/T 21010-2017 / Third National Land Survey"
        elif self.scheme == LEGACY_LAND_USE_SCHEME:
            standard = "legacy Paper9 three-digit test data"
        else:
            standard = "unrecognized"
        return {
            "standard": standard,
            "scheme": self.scheme,
            "feature_count": self.feature_count,
            "code_counts": self.code_counts,
            "category_counts": self.category_counts,
            "scheme_counts": self.scheme_counts,
            "unrecognized_code_counts": self.unrecognized_code_counts,
        }


def normalise_land_use_code(value: object) -> str:
    """Return a stripped code without changing its significant leading zero."""
    if value is None:
        return ""
    if isinstance(value, Integral):
        return str(int(value))
    if isinstance(value, Real):
        numeric = float(value)
        if not math.isfinite(numeric):
            return ""
        return str(int(numeric)) if numeric.is_integer() else str(value).strip()
    text = str(value).strip()
    if text.casefold() in {"", "nan", "none", "null", "<na>"}:
        return ""
    if re.fullmatch(r"\d+\.0+", text):
        return text.split(".", 1)[0]
    return text


def _current_base(code: str) -> str | None:
    if len(code) not in {4, 5}:
        return None
    base = code[:4]
    if base in (
        CURRENT_FARMLAND_BASE_CODES
        | CURRENT_FOREST_BASE_CODES
        | CURRENT_ORCHARD_BASE_CODES
    ):
        return base
    return None


def land_use_code_scheme(value: object) -> str:
    """Identify the scheme only when the code belongs to a known class."""
    code = normalise_land_use_code(value)
    if _current_base(code) is not None:
        return CURRENT_LAND_USE_SCHEME
    if code in (
        LEGACY_FARMLAND_CODES | LEGACY_FOREST_CODES | LEGACY_ORCHARD_CODES
    ):
        return LEGACY_LAND_USE_SCHEME
    return UNKNOWN_LAND_USE_SCHEME


def classify_land_use(value: object) -> str:
    """Classify one DLBM as farmland, forest, orchard, barrier, or other."""
    code = normalise_land_use_code(value)
    current_base = _current_base(code)
    if current_base in CURRENT_FARMLAND_BASE_CODES or code in LEGACY_FARMLAND_CODES:
        return "farmland"
    if current_base in CURRENT_FOREST_BASE_CODES or code in LEGACY_FOREST_CODES:
        return "forest"
    if current_base in CURRENT_ORCHARD_BASE_CODES or code in LEGACY_ORCHARD_CODES:
        return "orchard"
    if code[:2] in _BARRIER_TWO_DIGIT_CLASSES:
        return "barrier"
    return "other"


def analyse_land_use_codes(
    values: Iterable[object],
    *,
    require_farmland: bool = False,
    require_forest: bool = False,
    reject_mixed_swappable_schemes: bool = True,
) -> LandUseCodeReport:
    """Summarize codes and enforce the swappable-code contract."""
    codes = [normalise_land_use_code(value) for value in values]
    code_counts = Counter(codes)
    categories = [classify_land_use(code) for code in codes]
    category_counts = Counter(categories)

    current_swappable_count = sum(
        count
        for code, count in code_counts.items()
        if _current_base(code) in _CURRENT_SWAPPABLE_CODES
    )
    legacy_swappable_count = sum(
        count for code, count in code_counts.items() if code in _LEGACY_SWAPPABLE_CODES
    )
    if (
        reject_mixed_swappable_schemes
        and current_swappable_count
        and legacy_swappable_count
    ):
        raise LandUseCodeError(
            "DLBM contains mixed current four-digit and legacy three-digit "
            "farmland/forest codes; use one code scheme for the entire dataset."
        )

    if current_swappable_count:
        scheme = CURRENT_LAND_USE_SCHEME
    elif legacy_swappable_count:
        scheme = LEGACY_LAND_USE_SCHEME
    else:
        scheme = UNKNOWN_LAND_USE_SCHEME

    if require_farmland and not category_counts["farmland"]:
        raise LandUseCodeError(
            "DLBM has no recognized farmland codes. Expected current codes "
            "0101/0102/0103 or legacy test codes 011/012/013."
        )
    if require_forest and not category_counts["forest"]:
        raise LandUseCodeError(
            "DLBM has no recognized forest codes. Expected current codes "
            "0301-0307 or legacy test codes 031/032/033."
        )

    unrecognized = Counter(
        code for code, category in zip(codes, categories) if category == "other"
    )
    return LandUseCodeReport(
        scheme=scheme,
        feature_count=len(codes),
        code_counts=dict(sorted(code_counts.items())),
        category_counts=dict(sorted(category_counts.items())),
        scheme_counts={
            CURRENT_LAND_USE_SCHEME: current_swappable_count,
            LEGACY_LAND_USE_SCHEME: legacy_swappable_count,
        },
        unrecognized_code_counts=dict(sorted(unrecognized.items())),
    )
