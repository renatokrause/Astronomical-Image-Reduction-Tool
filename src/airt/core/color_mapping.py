from __future__ import annotations

import re
from dataclasses import dataclass

from airt.core.bands import band_display_label, normalize_band_name, sort_bands_recommended


@dataclass(frozen=True)
class BandColorMapping:
    band: str
    normalized_band: str
    color_name: str
    hex_color: str
    channel: str


PHOTOMETRIC_COLORS = {
    "L": ("White", "#FFFFFF", "L"),
    "U": ("Violet", "#7B2CBF", "B"),
    "B": ("Blue", "#1E5BFF", "B"),
    "G": ("Green-cyan", "#00A88F", "G"),
    "V": ("Green", "#2EAD4A", "G"),
    "HB": ("Light blue", "#3FA7FF", "B"),
    "OIII": ("Blue-cyan", "#00B7FF", "B"),
    "R": ("Red", "#E53935", "R"),
    "HA": ("Red", "#D92525", "R"),
    "SII": ("Deep red", "#8B0000", "R"),
    "I": ("Dark red", "#8B1E1E", "R"),
    "Unknown": ("Medium gray", "#808080", "-"),
}


SMART_DEFAULT_COLORS = {
    "L": ("White", "#FFFFFF", "L"),
    "U": ("Violet", "#7B2CBF", "B"),
    "B": ("Blue", "#1E5BFF", "B"),
    "G": ("Green-cyan", "#00A88F", "G"),
    "V": ("Green", "#2EAD4A", "G"),
    "HB": ("Light blue", "#3FA7FF", "B"),
    "OIII": ("Blue-cyan", "#00B7FF", "G+B"),
    "R": ("Red", "#E53935", "R"),
    "HA": ("Red", "#D92525", "R"),
    "SII": ("Deep red", "#8B0000", "R"),
    "I": ("Dark red", "#8B1E1E", "R"),
    "Unknown": ("Medium gray", "#808080", "-"),
}


SHO_COLORS = {
    "SII": ("Red", "#8B0000", "R"),
    "HA": ("Green", "#2EAD4A", "G"),
    "OIII": ("Blue", "#00B7FF", "B"),
}


HOO_COLORS = {
    "HA": ("Red", "#D92525", "R"),
    "OIII": ("Cyan", "#00B7FF", "G+B"),
}


CHROMATIC_PALETTE = [
    ("Blue", "#1E5BFF", "B"),
    ("Cyan", "#00B7FF", "B"),
    ("Green", "#2EAD4A", "G"),
    ("Dark orange", "#A05A1F", "R"),
    ("Red", "#E53935", "R"),
]


def _mapping_from_dict(band: str, table: dict[str, tuple[str, str, str]]) -> BandColorMapping:
    normalized = normalize_band_name(band)
    key = normalized if normalized in table else "Unknown"
    color_name, hex_color, channel = table[key]

    return BandColorMapping(
        band=band,
        normalized_band=band_display_label(normalized),
        color_name=color_name,
        hex_color=hex_color,
        channel=channel,
    )


def photometric_mapping(bands: list[str]) -> list[BandColorMapping]:
    return [_mapping_from_dict(band, PHOTOMETRIC_COLORS) for band in sort_bands_recommended(bands)]


def smart_default_mapping(bands: list[str]) -> list[BandColorMapping]:
    return [_mapping_from_dict(band, SMART_DEFAULT_COLORS) for band in sort_bands_recommended(bands)]


def sho_mapping(bands: list[str]) -> list[BandColorMapping]:
    result = []

    for band in sort_bands_recommended(bands):
        normalized = normalize_band_name(band)

        if normalized in SHO_COLORS:
            color_name, hex_color, channel = SHO_COLORS[normalized]
        else:
            color_name, hex_color, channel = SMART_DEFAULT_COLORS.get(
                normalized,
                SMART_DEFAULT_COLORS["Unknown"],
            )

        result.append(
            BandColorMapping(
                band=band,
                normalized_band=band_display_label(normalized),
                color_name=color_name,
                hex_color=hex_color,
                channel=channel,
            )
        )

    return result


def hoo_mapping(bands: list[str]) -> list[BandColorMapping]:
    result = []

    for band in sort_bands_recommended(bands):
        normalized = normalize_band_name(band)

        if normalized in HOO_COLORS:
            color_name, hex_color, channel = HOO_COLORS[normalized]
        else:
            color_name, hex_color, channel = SMART_DEFAULT_COLORS.get(
                normalized,
                SMART_DEFAULT_COLORS["Unknown"],
            )

        result.append(
            BandColorMapping(
                band=band,
                normalized_band=band_display_label(normalized),
                color_name=color_name,
                hex_color=hex_color,
                channel=channel,
            )
        )

    return result


def chromatic_order_mapping(bands: list[str]) -> list[BandColorMapping]:
    ordered = sort_bands_recommended(bands)

    if not ordered:
        return []

    if len(ordered) == 1:
        band = ordered[0]
        color_name, hex_color, channel = CHROMATIC_PALETTE[2]
        return [
            BandColorMapping(
                band=band,
                normalized_band=band_display_label(band),
                color_name=color_name,
                hex_color=hex_color,
                channel=channel,
            )
        ]

    result = []

    for index, band in enumerate(ordered):
        palette_index = round(index * (len(CHROMATIC_PALETTE) - 1) / (len(ordered) - 1))
        color_name, hex_color, channel = CHROMATIC_PALETTE[palette_index]

        result.append(
            BandColorMapping(
                band=band,
                normalized_band=band_display_label(band),
                color_name=color_name,
                hex_color=hex_color,
                channel=channel,
            )
        )

    return result


def custom_mapping(
    bands: list[str],
    saved_custom: dict[str, dict[str, str]] | None = None,
) -> list[BandColorMapping]:
    saved_custom = saved_custom or {}
    defaults = {item.band: item for item in smart_default_mapping(bands)}

    result = []

    for band in sort_bands_recommended(bands):
        default = defaults[band]
        saved = saved_custom.get(band, {})

        result.append(
            BandColorMapping(
                band=band,
                normalized_band=saved.get("normalized_band", default.normalized_band),
                color_name=saved.get("color_name", default.color_name),
                hex_color=saved.get("hex_color", default.hex_color),
                channel=saved.get("channel", default.channel),
            )
        )

    return result


def build_color_mapping(
    bands: list[str],
    mode: str,
    saved_custom: dict[str, dict[str, str]] | None = None,
) -> list[BandColorMapping]:
    mode = mode or "photometric"

    if mode == "photometric":
        return photometric_mapping(bands)

    if mode == "chromatic_order":
        return chromatic_order_mapping(bands)

    if mode == "sho":
        return sho_mapping(bands)

    if mode == "hoo":
        return hoo_mapping(bands)

    if mode == "custom":
        return custom_mapping(bands, saved_custom)

    return photometric_mapping(bands)


def mapping_to_project_dict(mapping: list[BandColorMapping]) -> dict[str, dict[str, str]]:
    return {
        item.band: {
            "band": item.band,
            "normalized_band": item.normalized_band,
            "color_name": item.color_name,
            "hex_color": item.hex_color,
            "channel": item.channel,
        }
        for item in mapping
    }


def is_valid_hex_color(value: str) -> bool:
    return bool(re.fullmatch(r"#[0-9A-Fa-f]{6}", value.strip()))
