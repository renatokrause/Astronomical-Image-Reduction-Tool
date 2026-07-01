<p align="center">
  <img src="assets/airt-logo.svg" alt="Astronomical Image Reduction Tool logo" width="320">
</p>

# Astronomical Image Reduction Tool

Python desktop application for calibrating, aligning, stacking and generating RGB images from FITS files.

This project was inspired by an earlier Colab workflow, then reorganized as a local desktop tool with a graphical interface.

## Screenshots

### Main Window

![Main window](assets/screenshots/main-window.png)

### Object File Filter

![Object file filter](assets/screenshots/object-file-filter.png)

### Manual Band Alignment

![Manual band alignment](assets/screenshots/manual-band-alignment.png)

## Author

- Primary author: [Eric Bairros Krause](https://github.com/ericBK26/)
- Email: bairros.krause@ufrgs.br

See [AUTHORS.md](AUTHORS.md) for authorship information.

## Supported Platforms

Tested:

- Windows 10/11

Expected to work:

- Linux with Python 3.11+ and Tkinter
- macOS with Python 3.11+ and Tkinter

The application is written in Python and uses a Tkinter desktop interface, so the source version is intended to be cross-platform. The Windows `.bat`, `.ps1` and shortcut files are Windows-specific. Linux users can use the `.sh` scripts included in this repository.

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

The final PNG is saved in the selected Output folder. If that folder does not exist, the tool creates it automatically:

```text
my_project/
  output/
    object_reduced.png
```

## How To Run

Install Python 3.11 or newer.

### Windows

Inside this folder:

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

### Linux

Make sure Python 3.11+ and Tkinter are installed. On Debian/Ubuntu, Tkinter is usually installed with:

```bash
sudo apt install python3-tk
```

Then, inside this folder:

```bash
chmod +x setup_environment.sh AIRT.sh create_airt_desktop_entry.sh
./setup_environment.sh
./AIRT.sh
```

If you want a desktop launcher with the application icon, run:

```bash
./create_airt_desktop_entry.sh
```

This creates `AIRT.desktop` in the project folder. Some desktop environments require right-clicking the file and allowing it to launch.

## What The Program Does

1. Finds FITS files in the selected bias, flat and object folders.
2. Automatically counts the available files when the selected folders are ready.
3. Groups flats and object images by the `B`, `V`, `R` and `I` filters.
4. Creates the master bias.
5. Creates master flats for any available `B`, `V` and `R` filters.
6. Calibrates the object images with bias and flat correction.
7. Uses one `V` image as the alignment reference when available, otherwise uses another available filter.
8. Aligns and stacks the images for each filter.
9. Optionally aligns the final stacked bands before RGB composition, depending on the selected alignment mode.
10. Opens a final background-correction preview before saving the image.
11. Optionally removes smooth background gradients independently in each stacked band.
12. Composes a linear RGB image from the corrected bands.
13. Optionally neutralizes the RGB sky background using only unmasked sky pixels.
14. Applies the final stretch for export.
15. Saves the PNG result in the selected Output folder.

## Notes

- File names must identify the filter, for example `_B_`, `_V_`, `_R_`, or end with `B.FITS`, `V.FITS`, `R.FITS`.
- `R`, `V` and `B` are mapped to red, green and blue. If only one or two filters are available, the missing channels are left empty.
- Alignment mode can be set to no band adjustment, automatic band alignment, or manual band adjustment. No band adjustment keeps the previous composition behavior. Automatic mode aligns the final stacked bands before RGB composition, using `V` as the reference when available, otherwise the first available color band. Manual mode starts from the automatic alignment and opens a preview window where each RGB channel can be shifted before saving.
- Background correction defaults to `Off` on the main screen. When it is turned `On`, the final preview uses the same processing functions as the pipeline: per-band background removal, linear RGB composition, RGB background neutralization, and a sky-mask-aware final stretch. Available methods are `median_grid`, `polynomial`, and `hybrid`; the hybrid method can use Photutils internally when available and otherwise falls back to median-grid plus polynomial modeling. The mask protects detected stars and an adjustable elliptical object region, then estimates the background only from unmasked sky pixels. The final stretch sets the black point from unmasked sky pixels and targets a dark but non-clipped background.
- The `I` filter is scanned, but is not yet used in the RGB composition.
- The automatic scan counts and classifies FITS files by folder and filter. It does not create masters, reduce images, align images or save output files.
- Manual band adjustment provides a preview window with per-channel X/Y offsets, arrow controls and reset actions before confirming the alignment. The final save happens after the background-extraction preview.
- The Background Correction window can save debug images for each band original, mask, background model, corrected band, RGB before neutralization, RGB after neutralization, final stretched image, before/after comparison, `stretch_histogram_before_after.png`, and `processing_stats.json`.
