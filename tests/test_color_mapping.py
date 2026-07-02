from airt.core.color_mapping import build_color_mapping


def test_build_color_mapping_photometric_basic():
    mapping = build_color_mapping(["L", "R", "G", "B"], mode="photometric")
    by_band = {item.band: item for item in mapping}

    assert by_band["L"].channel == "L"
    assert by_band["R"].channel == "R"
    assert by_band["G"].channel == "G"
    assert by_band["B"].channel == "B"


def test_build_color_mapping_custom_preserves_saved_values():
    saved = {
        "HA": {
            "hex_color": "#ff0000",
            "channel": "R",
            "color_name": "Custom red",
        }
    }

    mapping = build_color_mapping(["HA"], mode="custom", saved_custom=saved)
    assert mapping[0].hex_color == "#ff0000"
    assert mapping[0].channel == "R"
