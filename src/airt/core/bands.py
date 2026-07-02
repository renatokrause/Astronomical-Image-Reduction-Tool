from __future__ import annotations

import re
from collections.abc import Iterable

BAND_ALIASES = {
    "l": "L",
    "lum": "L",
    "luminance": "L",
    "clear": "L",
    "c": "L",
    "u": "U",
    "b": "B",
    "blue": "B",
    "g": "G",
    "green": "G",
    "v": "V",
    "r": "R",
    "red": "R",
    "ha": "HA",
    "h-alpha": "HA",
    "halpha": "HA",
    "h_alpha": "HA",
    "h α": "HA",
    "hα": "HA",
    "hb": "HB",
    "h-beta": "HB",
    "hbeta": "HB",
    "h_beta": "HB",
    "h β": "HB",
    "hβ": "HB",
    "oiii": "OIII",
    "o iii": "OIII",
    "o-iii": "OIII",
    "o_iii": "OIII",
    "[oiii]": "OIII",
    "[o iii]": "OIII",
    "oxygen iii": "OIII",
    "sii": "SII",
    "s ii": "SII",
    "s-ii": "SII",
    "s_ii": "SII",
    "[sii]": "SII",
    "[s ii]": "SII",
    "sulfur ii": "SII",
    "sulphur ii": "SII",
    "i": "I",
    "ir": "I",
    "infrared": "I",
}


RECOMMENDED_BAND_ORDER = {
    "L": 0,
    "U": 10,
    "B": 20,
    "G": 30,
    "V": 35,
    "HB": 40,
    "OIII": 45,
    "R": 50,
    "HA": 60,
    "SII": 70,
    "I": 80,
}


DISPLAY_LABELS = {
    "-": "None",
    "UNKNOWN": "None",
    "L": "L",
    "U": "U",
    "B": "B",
    "G": "G",
    "V": "V",
    "HB": "Hβ",
    "OIII": "OIII",
    "R": "R",
    "HA": "Hα",
    "SII": "SII",
    "I": "I",
}


def _clean_band_text(raw_band: str | None) -> str:
    if raw_band is None:
        return ""

    text = str(raw_band).strip()

    if not text or text == "-":
        return ""

    text = text.replace("FILTER_", "")
    text = text.replace("FILT_", "")
    text = text.replace("BAND_", "")

    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_band_name(raw_band: str | None) -> str:
    text = _clean_band_text(raw_band)

    if not text:
        return "UNKNOWN"

    lower = text.lower().strip()

    direct = BAND_ALIASES.get(lower)
    if direct:
        return direct

    compact = lower.replace(" ", "").replace("-", "").replace("_", "")

    compact_aliases = {
        "halpha": "HA",
        "hα": "HA",
        "hbeta": "HB",
        "hβ": "HB",
        "oiii": "OIII",
        "[oiii]": "OIII",
        "sii": "SII",
        "[sii]": "SII",
    }

    if compact in compact_aliases:
        return compact_aliases[compact]

    upper = text.upper().strip()

    if upper in RECOMMENDED_BAND_ORDER:
        return upper

    return text


def band_display_label(raw_band: str | None) -> str:
    normalized = normalize_band_name(raw_band)

    if normalized in DISPLAY_LABELS:
        return DISPLAY_LABELS[normalized]

    return str(raw_band).strip() if raw_band not in {None, ""} else "None"


def recommended_band_sort_key(raw_band: str | None) -> tuple[int, str]:
    normalized = normalize_band_name(raw_band)
    weight = RECOMMENDED_BAND_ORDER.get(normalized, 999)

    if weight == 999:
        return (weight, str(normalized).casefold())

    return (weight, normalized)


def sort_bands_recommended(bands: Iterable[str]) -> list[str]:
    unique = list(dict.fromkeys(bands))
    return sorted(unique, key=recommended_band_sort_key)
