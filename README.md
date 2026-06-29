<p align="center">
  <img src="assets/airt-logo.png" alt="Astronomical Image Reduction Tool logo" width="260">
</p>

# Astronomical Image Reduction Tool

Python desktop application for calibrating, aligning, stacking and generating RGB images from FITS files.

This project was inspired by an earlier Colab workflow, then reorganized as a local desktop tool with a graphical interface.

## Expected Folder Structure

Select the folders used by the reduction:

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
  output/
```

The object folder can also use the target name, and each folder is selected independently in the app:

```text
my_project/
  bias/
  flat/
  M104/
  M8/
  M83/
  output/
```

In this case, select `bias` as the Bias folder, `flat` as the Flat folder, one target folder such as `M104` as the Object folder, and `output` as the Output folder.

The tool creates this folder automatically:

```text
my_project/
  output/
    object_reduced.png
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

After the dependencies are installed, you can double-click `AIRT.bat`.

If you want a Windows shortcut with the application icon, run `create_airt_shortcut.ps1` once and then open `AIRT.lnk`. If the environment needs to be recreated, double-click `setup_environment.bat`.

## What The Program Does

1. Finds FITS files in the selected bias, flat and object folders.
2. Automatically counts the available files when the selected folders are ready.
3. Groups flats and object images by the `B`, `V`, `R` and `I` filters.
4. Creates the master bias.
5. Creates master flats for any available `B`, `V` and `R` filters.
6. Calibrates the object images with bias and flat correction.
7. Uses one `V` image as the alignment reference when available, otherwise uses another available filter.
8. Aligns and stacks the images for each filter.
9. Subtracts the sky background.
10. Generates the final image with the available color channels.
11. Saves the PNG result in the `output` folder.

## Notes

- File names must identify the filter, for example `_B_`, `_V_`, `_R_`, or end with `B.FITS`, `V.FITS`, `R.FITS`.
- `R`, `V` and `B` are mapped to red, green and blue. If only one or two filters are available, the missing channels are left empty.
- The `I` filter is scanned, but is not yet used in the RGB composition.
- The automatic scan counts and classifies FITS files by folder and filter. It does not create masters, reduce images, align images or save output files.
- Individual visual inspection will be added in a future version.
