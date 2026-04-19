"""Load an STL, slice a thin layer near one end, preview it, and export as SVG."""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np
import trimesh
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.patches import Circle, PathPatch, Rectangle
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

        self.shape_center: tuple[float, float] | None = None
        self._shape_patch = None
        self._dragging = False
        self._drag_offset = (0.0, 0.0)
        self._view_bounds: tuple[float, float, float, float] | None = None
        self._last_axis: int | None = None

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

        row3 = ttk.Frame(root, padding=(8, 2, 8, 6))
        row3.pack(side="top", fill="x")

        ttk.Label(row3, text="Shape:").pack(side="left")
        self.shape_var = tk.StringVar(value="none")
        self.shape_combo = ttk.Combobox(
            row3, textvariable=self.shape_var, width=8, state="readonly",
            values=["none", "circle", "square"],
        )
        self.shape_combo.pack(side="left", padx=(4, 12))
        self.shape_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_shape_change())

        ttk.Label(row3, text="Size:").pack(side="left")
        self.size_var = tk.DoubleVar(value=10.0)
        self.size_scale = ttk.Scale(
            row3, from_=0.1, to=100.0, orient="horizontal",
            variable=self.size_var, command=lambda _v: self._on_size_change(),
        )
        self.size_scale.pack(side="left", fill="x", expand=True, padx=4)

        self.size_entry = ttk.Entry(row3, width=8)
        self.size_entry.insert(0, "10.0")
        self.size_entry.pack(side="left", padx=4)
        self.size_entry.bind("<Return>", lambda _e: self._on_size_entry())

        ttk.Label(row3, text="X:").pack(side="left", padx=(12, 0))
        self.pos_x_entry = ttk.Entry(row3, width=9)
        self.pos_x_entry.pack(side="left", padx=4)
        self.pos_x_entry.bind("<Return>", lambda _e: self._on_pos_entry())

        ttk.Label(row3, text="Y:").pack(side="left")
        self.pos_y_entry = ttk.Entry(row3, width=9)
        self.pos_y_entry.pack(side="left", padx=4)
        self.pos_y_entry.bind("<Return>", lambda _e: self._on_pos_entry())

        ttk.Button(row3, text="Center shape", command=self._center_shape).pack(
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

        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_release_event", self._on_release)

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
        self.shape_center = None
        self._last_axis = None

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
        if self._last_axis is not None and self._last_axis != axis:
            # 2D frame changes with the slicing axis — previous shape
            # position no longer has meaning in the new frame.
            self.shape_center = None
        self._last_axis = axis

        self._axis_name = "XYZ"[axis]
        bmin, bmax = self.mesh.bounds
        self._axis_lo, self._axis_hi = float(bmin[axis]), float(bmax[axis])
        coord = self._axis_lo + float(self.pos_var.get()) * (self._axis_hi - self._axis_lo)
        self._coord = coord
        self.coord_var.set(f"{coord:.4f}")

        other_axes = [i for i in range(3) if i != axis]
        self._view_bounds = (
            float(bmin[other_axes[0]]), float(bmin[other_axes[1]]),
            float(bmax[other_axes[0]]), float(bmax[other_axes[1]]),
        )

        normal = [0, 0, 0]
        normal[axis] = 1
        origin = [0, 0, 0]
        origin[axis] = coord

        section = self.mesh.section(plane_origin=origin, plane_normal=normal)

        self.section_2d = section
        self.loops = []
        if section is not None:
            for loop3d in section.discrete:
                arr = np.asarray(loop3d)
                if len(arr) >= 3:
                    self.loops.append(arr[:, other_axes])
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
        if self.mesh is None:
            return
        self.ax.clear()
        self.ax.set_aspect("equal")
        self.ax.grid(True, linestyle=":", alpha=0.4)

        selected = set(self._selected_indices())
        for i, loop in enumerate(self.loops):
            if i in selected:
                self.ax.plot(loop[:, 0], loop[:, 1],
                             color="#c0392b", linewidth=1.8)
            else:
                self.ax.plot(loop[:, 0], loop[:, 1],
                             color="#888", linewidth=0.8, alpha=0.6)

        self._apply_view_limits()
        self._configure_size_scale()
        self._shape_patch = None
        self._draw_shape()

        if self.loops:
            self.ax.set_title(
                f"Slice at {self._axis_name}={self._coord:.4f}  "
                f"(bounds {self._axis_lo:.4f} .. {self._axis_hi:.4f})"
            )
            self.status.config(
                text=f"Axis {self._axis_name}  |  slice at {self._coord:.4f}  |  "
                     f"loops: {len(self.loops)}  |  selected ({self.filter_var.get()}): "
                     f"{len(selected)}  |  ready to save."
            )
        else:
            self.ax.set_title(
                f"Slice at {self._axis_name}={self._coord:.4f}  (no intersection)"
            )
            self.status.config(
                text=f"No intersection at {self._axis_name}={self._coord:.4f} "
                     f"(bounds {self._axis_lo:.4f} .. {self._axis_hi:.4f})."
            )
        self.canvas.draw()

    def _apply_view_limits(self) -> None:
        if self._view_bounds is None:
            return
        minx, miny, maxx, maxy = self._view_bounds
        pad = 0.02 * max(maxx - minx, maxy - miny, 1e-6)
        self.ax.set_xlim(minx - pad, maxx + pad)
        self.ax.set_ylim(miny - pad, maxy + pad)

    # ------------------------------------------------------------------

    def _configure_size_scale(self) -> None:
        if self._view_bounds is None:
            return
        minx, miny, maxx, maxy = self._view_bounds
        span = float(max(maxx - minx, maxy - miny, 1.0))
        self.size_scale.configure(from_=span * 0.01, to=span)
        if self.size_var.get() > span or self.size_var.get() < span * 0.005:
            self.size_var.set(span * 0.1)
            self._sync_size_entry()

    def _sync_size_entry(self) -> None:
        self.size_entry.delete(0, "end")
        self.size_entry.insert(0, f"{self.size_var.get():.3f}")

    def _sync_pos_entries(self) -> None:
        self.pos_x_entry.delete(0, "end")
        self.pos_y_entry.delete(0, "end")
        if self.shape_center is not None:
            self.pos_x_entry.insert(0, f"{self.shape_center[0]:.3f}")
            self.pos_y_entry.insert(0, f"{self.shape_center[1]:.3f}")

    def _on_pos_entry(self) -> None:
        try:
            x = float(self.pos_x_entry.get())
            y = float(self.pos_y_entry.get())
        except ValueError:
            return
        self.shape_center = (x, y)
        if self.shape_var.get() == "none":
            self.shape_var.set("circle")
            self._draw_shape()
        else:
            self._update_shape_patch()
        self.canvas.draw_idle()

    def _on_size_entry(self) -> None:
        try:
            v = float(self.size_entry.get())
        except ValueError:
            return
        if v <= 0:
            return
        self.size_var.set(v)
        self._update_shape_patch()
        self.canvas.draw_idle()

    def _on_size_change(self) -> None:
        self._sync_size_entry()
        self._update_shape_patch()
        self.canvas.draw_idle()

    def _on_shape_change(self) -> None:
        if self.shape_var.get() != "none" and self.shape_center is None:
            self._center_shape(redraw=False)
        self._sync_pos_entries()
        self._draw_shape()
        self.canvas.draw_idle()

    def _center_shape(self, redraw: bool = True) -> None:
        if self._view_bounds is None:
            return
        minx, miny, maxx, maxy = self._view_bounds
        self.shape_center = (0.5 * (minx + maxx), 0.5 * (miny + maxy))
        self._sync_pos_entries()
        if redraw:
            self._draw_shape()
            self.canvas.draw_idle()

    def _draw_shape(self) -> None:
        if self._shape_patch is not None:
            try:
                self._shape_patch.remove()
            except Exception:
                pass
            self._shape_patch = None
        kind = self.shape_var.get()
        if kind == "none" or self.shape_center is None:
            return
        size = float(self.size_var.get())
        cx, cy = self.shape_center
        if kind == "circle":
            patch = Circle((cx, cy), size / 2.0, fill=False,
                           edgecolor="#2980b9", linewidth=1.8)
        else:  # square
            patch = Rectangle((cx - size / 2.0, cy - size / 2.0), size, size,
                              fill=False, edgecolor="#2980b9", linewidth=1.8)
        self.ax.add_patch(patch)
        self._shape_patch = patch

    def _update_shape_patch(self) -> None:
        if self._shape_patch is None or self.shape_center is None:
            return
        size = float(self.size_var.get())
        cx, cy = self.shape_center
        if isinstance(self._shape_patch, Circle):
            self._shape_patch.center = (cx, cy)
            self._shape_patch.set_radius(size / 2.0)
        else:
            self._shape_patch.set_xy((cx - size / 2.0, cy - size / 2.0))
            self._shape_patch.set_width(size)
            self._shape_patch.set_height(size)

    def _on_press(self, event) -> None:
        if event.inaxes != self.ax or self._shape_patch is None:
            return
        if event.button != 1 or event.xdata is None:
            return
        contains, _ = self._shape_patch.contains(event)
        if not contains or self.shape_center is None:
            return
        self._dragging = True
        self._drag_offset = (
            event.xdata - self.shape_center[0],
            event.ydata - self.shape_center[1],
        )

    def _on_motion(self, event) -> None:
        if not self._dragging or event.inaxes != self.ax:
            return
        if event.xdata is None or event.ydata is None:
            return
        self.shape_center = (
            float(event.xdata - self._drag_offset[0]),
            float(event.ydata - self._drag_offset[1]),
        )
        self._update_shape_patch()
        self._sync_pos_entries()
        self.canvas.draw_idle()

    def _on_release(self, _event) -> None:
        self._dragging = False

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
        if self._view_bounds is not None:
            minx, miny, maxx, maxy = self._view_bounds
        else:
            all_pts = np.concatenate(chosen, axis=0)
            minx, miny = all_pts.min(axis=0)
            maxx, maxy = all_pts.max(axis=0)

        shape_kind = self.shape_var.get()
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

        if shape_kind != "none" and self.shape_center is not None:
            cx, cy = self.shape_center
            s = float(self.size_var.get())
            svg_cx = cx - minx
            svg_cy = maxy - cy
            if shape_kind == "circle":
                path_els.append(
                    f'  <circle cx="{svg_cx:.4f}" cy="{svg_cy:.4f}" '
                    f'r="{s / 2.0:.4f}" fill="none" stroke="black" '
                    f'stroke-width="0.25"/>'
                )
            else:  # square
                path_els.append(
                    f'  <rect x="{svg_cx - s / 2.0:.4f}" '
                    f'y="{svg_cy - s / 2.0:.4f}" '
                    f'width="{s:.4f}" height="{s:.4f}" '
                    f'fill="none" stroke="black" stroke-width="0.25"/>'
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
