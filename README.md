# Astronomical Image Reduction Tool

Python desktop application for calibrating, aligning, stacking and generating RGB images from FITS files.

This project was inspired by an earlier Colab workflow, then reorganized as a local desktop tool with a graphical interface.

## Expected Folder Structure

For full calibration, select a project folder containing:

```text
my_project/
  bias/
    *.fits
  flat/
    *_B_*.fits
    *_V_*.fits
    *_R_*.fits
  object/
    *_B_*.fits
    *_V_*.fits
    *_R_*.fits
```

For quick RGB composition from science images only, use only the `object` folder:

```text
my_project/
  object/
    cluster_ExpAst_1_band_B.fits
    cluster_ExpAst_1_band_R.fits
    cluster_ExpAst_1_band_V.fits
    cluster_ExpAst_2_band_B.fits
    cluster_ExpAst_2_band_R.fits
    cluster_ExpAst_2_band_V.fits
```

You can also select a folder that contains the science FITS files directly:

```text
my_project/
  cluster_ExpAst_1_band_B.fits
  cluster_ExpAst_1_band_R.fits
  cluster_ExpAst_1_band_V.fits
  cluster_ExpAst_2_band_B.fits
  cluster_ExpAst_2_band_R.fits
  cluster_ExpAst_2_band_V.fits
```

The tool creates this folder automatically:

```text
my_project/
  output/
    object_reduced.png
    object_quick_rgb.png
```

## How To Run

Install Python 3.11 or newer. Then, inside this folder:

```powershell
& "$env:LocalAppData\Programs\Python\Python312\python.exe" -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

If Python is already available in your terminal as `python`, this shorter version also works:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

After the dependencies are installed, you can double-click `run_app.bat`.

If the environment needs to be recreated, double-click `setup_environment.bat`.

## What The Program Does

In full calibration mode:

1. Finds FITS files in the `bias`, `flat` and `object` folders.
2. Groups flats and object images by the `B`, `V`, `R` and `I` filters.
3. Creates the master bias.
4. Creates master flats for the `B`, `V` and `R` filters.
5. Calibrates the object images with bias and flat correction.
6. Uses one `V` image as the alignment reference.
7. Aligns and stacks the images for each filter.
8. Subtracts the sky background.
9. Generates the final RGB image with `make_lupton_rgb`.
10. Saves the PNG result in the `output` folder.

In quick RGB mode:

1. Finds FITS files in the `object` folder.
2. Groups object images by the `B`, `V`, `R` and `I` filters.
3. Uses one `V` image as the alignment reference.
4. Aligns and stacks the `R`, `V` and `B` images.
5. Subtracts the sky background.
6. Generates a quick RGB composition.
7. Saves the PNG result in the `output` folder.

## Notes

- File names must identify the filter, for example `_B_`, `_V_`, `_R_`, or end with `B.FITS`, `V.FITS`, `R.FITS`.
- The first version generates RGB images from the `R`, `V` and `B` filters.
- The `I` filter is scanned, but is not yet used in the RGB composition.
- Quick RGB mode does not perform bias or flat calibration. It is useful when only science/object frames are available.
- Quick RGB mode automatically crops slightly different image dimensions to the smallest common area before stacking.
- Individual visual inspection will be added in a future version.
