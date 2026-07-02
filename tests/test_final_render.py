import numpy as np

from airt.core.final_render import normalize_master, rgb_to_qimage


def test_normalize_master_handles_nan_and_inf():
    data = np.array([[0.0, 1.0], [np.nan, np.inf]], dtype=np.float32)
    result = normalize_master(data)

    assert result.shape == data.shape
    assert np.isfinite(result).all()
    assert result.min() >= 0
    assert result.max() <= 1


def test_rgb_to_qimage_accepts_rgb_float_array():
    rgb = np.zeros((8, 10, 3), dtype=np.float32)
    qimage = rgb_to_qimage(rgb)

    assert qimage.width() == 10
    assert qimage.height() == 8
