from airt.core.bands import band_display_label, normalize_band_name, sort_bands_recommended


def test_normalize_common_bands():
    assert normalize_band_name("Luminance") == "L"
    assert normalize_band_name("Ha") == "HA"
    assert normalize_band_name("H-alpha") == "HA"
    assert normalize_band_name("OIII") == "OIII"
    assert normalize_band_name("SII") == "SII"


def test_display_labels():
    assert band_display_label("HA") == "Hα"
    assert band_display_label("HB") == "Hβ"
    assert band_display_label("-") == "None"


def test_recommended_band_order():
    bands = ["SII", "R", "B", "L", "OIII", "HA", "G"]
    assert sort_bands_recommended(bands) == ["L", "B", "G", "OIII", "R", "HA", "SII"]
