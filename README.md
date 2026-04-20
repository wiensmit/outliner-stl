# Outliner STL

A small desktop tool for turning 3D models (STL) into 2D outlines (SVG).

Load an STL, pick a slicing axis and position, preview the cross-section, and
export the outlines to an SVG ready for laser cutters, plotters, CAD import,
or illustration work.

## Features

- Open any binary or ASCII STL file.
- Slice along **X**, **Y**, or **Z** — or let "auto" pick the thinnest axis
  (usually the extrusion direction for flat parts).
- Scrub the slice position with a slider, or type an exact coordinate.
- Live preview of every closed loop found in the slice plane.
- Nesting-aware export filter:
  - **all** — every loop in the slice.
  - **outermost** — only the top-level silhouette(s).
  - **innermost** — only the deepest holes / pockets.
- One-click SVG export. Units are millimetres, coordinates are preserved
  relative to the slice, and Y is flipped so the result matches how the
  part reads on screen.

## Install

### Option 1 — Prebuilt binary

Grab the latest build for your platform from the
[Releases page](https://github.com/wiensmit/outliner-stl/releases/latest):

- **Windows:** `Outliner.exe` — double-click to run.
- **macOS (Apple Silicon):** `Outliner-macos-arm64.zip` — unzip and run `Outliner.app`.
- **macOS (Intel):** `Outliner-macos-x86_64.zip` — unzip and run `Outliner.app`.

No Python, no dependencies, nothing to install.

> On macOS the `.app` is unsigned. First launch: right-click →
> **Open** → **Open** to bypass Gatekeeper.

### Option 2 — Run from source

Requires Python 3.11+.

```
pip install -r requirements.txt
python outliner.py
```

On Windows you can also double-click `launch.bat`.

## Usage

1. **Open STL...** — load your model. The bounds of the mesh are shown
   at the top so you can sanity-check units.
2. Pick an **Axis**. "auto" works well for extruded / laser-cut style parts.
3. Move the **Position** slider, or type a value into **Coord** and press
   Enter, to place the slicing plane.
4. Choose an **Export** filter (all / outermost / innermost).
5. **Save SVG...** — done.

The status bar at the bottom shows the current axis, coordinate, number of
loops found, and how many of them are currently selected for export.

## Building the standalone executable

The repo ships with a working PyInstaller spec. To rebuild:

```
pip install pyinstaller
pyinstaller --noconfirm --windowed --onefile --name Outliner ^
  --collect-all trimesh --collect-all shapely --collect-all matplotlib ^
  outliner.py
```

The output lands in `dist/Outliner.exe`. The `build/` folder and the
`.spec` file are intermediate artefacts.

## How it works

Under the hood:

- **trimesh** loads the STL and computes the plane/mesh intersection.
- The resulting 3D section is projected to 2D.
- **shapely** is used to classify loop nesting (who contains whom) so the
  "outermost" and "innermost" export filters know what to pick.
- **matplotlib** draws the live preview inside a Tk window.
- SVG is written by hand — no extra export dependency.

## Layout

```
outliner.py                   # the whole app
launch.bat                    # Windows shortcut for running from source
requirements.txt              # Python dependencies
Outliner.spec                 # PyInstaller build spec
.github/workflows/build.yml   # CI for Windows + macOS release builds
```
