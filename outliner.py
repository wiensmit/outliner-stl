"""Load an STL, slice a thin layer near one end, preview it, and export as SVG."""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np
import trimesh
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath
from shapely.geometry import Polygon as ShPoly
from shapely.validation import make_valid


AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Outliner STL")
        root.geometry("1000x800")

        self.mesh: trimesh.Trimesh | None = None
        self.section_2d = None
        self.stl_path: Path | None = None
        self.loops: list[np.ndarray] = []
        self.depths: list[int] = []
        self.has_child: list[bool] = []

        row1 = ttk.Frame(root, padding=(8, 8, 8, 2))
        row1.pack(side="top", fill="x")
        ttk.Button(row1, text="Open STL...", command=self.open_stl).pack(side="left")
        ttk.Button(row1, text="Save SVG...", command=self.save_svg).pack(side="right")

        row2 = ttk.Frame(root, padding=(8, 2, 8, 8))
        row2.pack(side="top", fill="x")

        ttk.Label(row2, text="Axis:").pack(side="left")
        self.axis_var = tk.StringVar(value="auto")
        self.axis_combo = ttk.Combobox(
            row2, textvariable=self.axis_var, width=8, state="readonly",
            values=["auto", "X", "Y", "Z"],
        )
        self.axis_combo.pack(side="left", padx=(4, 12))
        self.axis_combo.bind("<<ComboboxSelected>>", lambda _e: self.recompute())

        ttk.Label(row2, text="Position:").pack(side="left")
        self.pos_var = tk.DoubleVar(value=0.5)
        self.pos_scale = ttk.Scale(
            row2, from_=0.0, to=1.0, orient="horizontal",
            variable=self.pos_var, command=self._on_slider_move,
        )
        self.pos_scale.pack(side="left", fill="x", expand=True, padx=4)
        self.pos_scale.bind("<ButtonRelease-1>", lambda _e: self.recompute())

        ttk.Label(row2, text="Coord:").pack(side="left")
        self.coord_var = tk.StringVar(value="")
        coord_entry = ttk.Entry(row2, textvariable=self.coord_var, width=12)
        coord_entry.pack(side="left", padx=4)
        coord_entry.bind("<Return>", lambda _e: self._on_coord_enter())

        ttk.Label(row2, text="Export:").pack(side="left", padx=(12, 0))
        self.filter_var = tk.StringVar(value="all")
        self.filter_combo = ttk.Combobox(
            row2, textvariable=self.filter_var, width=11, state="readonly",
            values=["all", "outermost", "innermost"],
        )
        self.filter_combo.pack(side="left", padx=4)
        self.filter_combo.bind("<<ComboboxSelected>>", lambda _e: self._redraw())

        ttk.Button(row2, text="Recompute", command=self.recompute).pack(
            side="left", padx=8
        )

        self.bounds_label = ttk.Label(root, text="", anchor="w", padding=(8, 0))
        self.bounds_label.pack(side="top", fill="x")

        self.status = ttk.Label(root, text="Open an STL to begin.", anchor="w",
                                padding=(8, 4))
        self.status.pack(side="bottom", fill="x")

        self.fig = Figure(figsize=(6, 6), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_aspect("equal")
        self.canvas = FigureCanvasTkAgg(self.fig, master=root)
        self.canvas.get_tk_widget().pack(side="top", fill="both", expand=True)

    # ------------------------------------------------------------------

    def open_stl(self) -> None:
        path = filedialog.askopenfilename(
            title="Open STL",
            filetypes=[("STL files", "*.stl"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            mesh = trimesh.load(path, force="mesh")
        except Exception as exc:
            messagebox.showerror("Load failed", str(exc))
            return
        if not isinstance(mesh, trimesh.Trimesh) or mesh.is_empty:
            messagebox.showerror("Load failed", "File did not contain a usable mesh.")
            return

        self.mesh = mesh
        self.stl_path = Path(path)

        extents = mesh.extents  # length along X, Y, Z
        bmin, bmax = mesh.bounds
        self.bounds_label.config(
            text=(
                f"Bounds  X: {bmin[0]:.3f} .. {bmax[0]:.3f} (len {extents[0]:.3f})   "
                f"Y: {bmin[1]:.3f} .. {bmax[1]:.3f} (len {extents[1]:.3f})   "
                f"Z: {bmin[2]:.3f} .. {bmax[2]:.3f} (len {extents[2]:.3f})"
            )
        )

        self.pos_var.set(0.5)
        self._sync_coord_from_pos()
        self.recompute()

    # ------------------------------------------------------------------

    def _resolve_axis(self) -> int:
        """Return the numeric axis index for slicing (0=X, 1=Y, 2=Z)."""
        choice = self.axis_var.get()
        if choice == "auto":
            # Thinnest axis — almost always the extrusion direction
            # for an extruded cross-section part.
            return int(np.argmin(self.mesh.extents))
        return AXIS_INDEX[choice]

    def _on_slider_move(self, _value: str) -> None:
        if self.mesh is None:
            return
        self._sync_coord_from_pos()

    def _sync_coord_from_pos(self) -> None:
        if self.mesh is None:
            return
        axis = self._resolve_axis()
        lo, hi = float(self.mesh.bounds[0][axis]), float(self.mesh.bounds[1][axis])
        coord = lo + float(self.pos_var.get()) * (hi - lo)
        self.coord_var.set(f"{coord:.4f}")

    def _on_coord_enter(self) -> None:
        if self.mesh is None:
            return
        try:
            coord = float(self.coord_var.get())
        except ValueError:
            messagebox.showerror("Invalid coord", "Enter a number.")
            return
        axis = self._resolve_axis()
        lo, hi = float(self.mesh.bounds[0][axis]), float(self.mesh.bounds[1][axis])
        frac = 0.0 if hi == lo else (coord - lo) / (hi - lo)
        self.pos_var.set(max(0.0, min(1.0, frac)))
        self.recompute()

    def recompute(self) -> None:
        if self.mesh is None:
            return

        axis = self._resolve_axis()
        self._axis_name = "XYZ"[axis]
        bmin, bmax = self.mesh.bounds
        self._axis_lo, self._axis_hi = float(bmin[axis]), float(bmax[axis])
        coord = self._axis_lo + float(self.pos_var.get()) * (self._axis_hi - self._axis_lo)
        self._coord = coord
        self.coord_var.set(f"{coord:.4f}")

        normal = [0, 0, 0]
        normal[axis] = 1
        origin = [0, 0, 0]
        origin[axis] = coord

        section = self.mesh.section(plane_origin=origin, plane_normal=normal)

        if section is None:
            self.section_2d = None
            self.loops = []
            self.depths = []
            self.has_child = []
            self.ax.clear()
            self.ax.set_aspect("equal")
            self.ax.grid(True, linestyle=":", alpha=0.4)
            self.status.config(
                text=f"No intersection at {self._axis_name}={coord:.4f} "
                     f"(bounds {self._axis_lo:.4f} .. {self._axis_hi:.4f}). "
                     f"Move slider inward."
            )
            self.canvas.draw()
            return

        planar, _ = section.to_2D()
        self.section_2d = planar

        self.loops = [np.asarray(l) for l in planar.discrete if len(l) >= 3]
        self.depths, self.has_child = self._classify(self.loops)
        self._redraw()

    def _classify(self, loops: list[np.ndarray]) -> tuple[list[int], list[bool]]:
        """Compute nesting depth (0 = outermost) and has_child for each loop."""
        n = len(loops)
        if n == 0:
            return [], []
        polys: list = []
        for l in loops:
            try:
                p = ShPoly(l)
                if not p.is_valid:
                    p = make_valid(p)
            except Exception:
                p = None
            polys.append(p)
        areas = [p.area if p is not None else 0.0 for p in polys]
        order = sorted(range(n), key=lambda i: -areas[i])
        depth = [0] * n
        has_child = [False] * n
        for idx, i in enumerate(order):
            if polys[i] is None:
                continue
            rep = polys[i].representative_point()
            best_parent = -1
            best_parent_depth = -1
            for j in order[:idx]:
                pj = polys[j]
                if pj is None or not pj.contains(rep):
                    continue
                if depth[j] > best_parent_depth:
                    best_parent = j
                    best_parent_depth = depth[j]
            if best_parent >= 0:
                depth[i] = depth[best_parent] + 1
                has_child[best_parent] = True
        return depth, has_child

    def _selected_indices(self) -> list[int]:
        mode = self.filter_var.get()
        if mode == "outermost":
            return [i for i, d in enumerate(self.depths) if d == 0]
        if mode == "innermost":
            return [i for i, c in enumerate(self.has_child) if not c]
        return list(range(len(self.loops)))

    def _redraw(self) -> None:
        self.ax.clear()
        self.ax.set_aspect("equal")
        self.ax.grid(True, linestyle=":", alpha=0.4)

        if not self.loops:
            self.canvas.draw()
            return

        selected = set(self._selected_indices())
        for i, loop in enumerate(self.loops):
            if i in selected:
                self.ax.plot(loop[:, 0], loop[:, 1],
                             color="#c0392b", linewidth=1.8)
            else:
                self.ax.plot(loop[:, 0], loop[:, 1],
                             color="#888", linewidth=0.8, alpha=0.6)

        all_pts = np.concatenate(self.loops, axis=0)
        pad = 0.02 * max(np.ptp(all_pts[:, 0]), np.ptp(all_pts[:, 1]), 1e-6)
        self.ax.set_xlim(all_pts[:, 0].min() - pad, all_pts[:, 0].max() + pad)
        self.ax.set_ylim(all_pts[:, 1].min() - pad, all_pts[:, 1].max() + pad)

        self.ax.set_title(
            f"Slice at {self._axis_name}={self._coord:.4f}  "
            f"(bounds {self._axis_lo:.4f} .. {self._axis_hi:.4f})"
        )
        self.status.config(
            text=f"Axis {self._axis_name}  |  slice at {self._coord:.4f}  |  "
                 f"loops: {len(self.loops)}  |  selected ({self.filter_var.get()}): "
                 f"{len(selected)}  |  ready to save."
        )
        self.canvas.draw()

    # ------------------------------------------------------------------

    def save_svg(self) -> None:
        selected = self._selected_indices() if self.loops else []
        if not selected:
            messagebox.showinfo("Nothing to save",
                                "No loops match the current Export filter.")
            return
        default_name = (
            self.stl_path.with_suffix(".svg").name if self.stl_path else "slice.svg"
        )
        path = filedialog.asksaveasfilename(
            title="Save SVG",
            defaultextension=".svg",
            initialfile=default_name,
            filetypes=[("SVG files", "*.svg")],
        )
        if not path:
            return

        chosen = [self.loops[i] for i in selected]
        all_pts = np.concatenate(chosen, axis=0)
        minx, miny = all_pts.min(axis=0)
        maxx, maxy = all_pts.max(axis=0)
        w, h = float(maxx - minx), float(maxy - miny)

        path_els = []
        for loop in chosen:
            d = " ".join(
                (("M" if k == 0 else "L") + f" {(x - minx):.4f},{(maxy - y):.4f}")
                for k, (x, y) in enumerate(loop)
            ) + " Z"
            path_els.append(
                f'  <path d="{d}" fill="none" stroke="black" '
                f'stroke-width="0.25"/>'
            )
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {w:.4f} {h:.4f}" '
            f'width="{w:.4f}mm" height="{h:.4f}mm">\n'
            + "\n".join(path_els)
            + "\n</svg>\n"
        )
        Path(path).write_text(svg, encoding="utf-8")
        self.status.config(
            text=f"Saved {len(chosen)} loop(s) ({self.filter_var.get()}): {path}"
        )


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
