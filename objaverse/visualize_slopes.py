"""Visualize slope detection on objaverse assets as an interactive HTML gallery.

Usage:
    uv run objaverse/visualize_slopes.py
    uv run objaverse/visualize_slopes.py --min-area 0.005
    uv run objaverse/visualize_slopes.py -o results/slope_gallery.html

Processes all .glb files in objaverse/assets/, runs slope detection on each,
exports colored meshes as .glb, and generates an interactive HTML gallery
with model-viewer for 3D inspection.

Colors:
    - Gray: horizontal/vertical faces (not sloped)
    - Red/Green/Blue/Yellow: slope regions by direction (+X/+Y/-X/-Y)
    - Dark gray: sloped faces below area threshold (filtered out)
"""

import argparse
import sys
import os
from pathlib import Path

import numpy as np
import open3d as o3d

from mesh2brick.mesh2brick import normalize_mesh
from mesh2brick.slope_detection import (
    compute_optimal_scale,
    detect_slopes,
    get_slope_bricks,
    match_slope_to_bricks,
    _compute_s_min,
)


SCRIPT_DIR = Path(__file__).parent.resolve()
ASSETS_DIR = SCRIPT_DIR / "assets"

DIRECTION_COLORS = {
    0: [0.9, 0.2, 0.2],   # +X = red
    1: [0.2, 0.8, 0.2],   # +Y = green
    2: [0.2, 0.4, 0.9],   # -X = blue
    3: [0.9, 0.8, 0.2],   # -Y = yellow
}
DIR_NAMES = {0: "+X", 1: "+Y", 2: "-X", 3: "-Y"}
DIR_CSS = {0: "#e63946", 1: "#2a9d8f", 2: "#457b9d", 3: "#e9c46a"}
GRAY = [0.7, 0.7, 0.7]
DARK_GRAY = [0.4, 0.4, 0.4]


def process_mesh(
    mesh_path: Path,
    x_rotation: float,
    min_area_fraction: float,
    normal_thresh: float,
    glb_output_dir: Path,
) -> dict:
    """Process one mesh: detect slopes, color it, export GLB, return results."""
    name = mesh_path.stem
    short_name = name[:8]

    mesh = o3d.io.read_triangle_mesh(str(mesh_path))
    if len(mesh.triangles) == 0:
        return {"name": name, "short_name": short_name, "error": "Failed to load mesh"}

    mesh = normalize_mesh(mesh, x_rotation=x_rotation)

    # vertices = np.asarray(mesh.vertices)
    # vertices[:, 2] *= 3.0
    # mesh.vertices = o3d.utility.Vector3dVector(vertices)

    mesh.compute_triangle_normals()
    mesh.compute_vertex_normals()

    n_faces = len(mesh.triangles)
    normals = np.asarray(mesh.triangle_normals)

    up = np.array([0.0, 0.0, 1.0])
    cos_angles = np.abs(normals @ up)
    angle_from_vertical = np.degrees(np.arccos(np.clip(cos_angles, 0, 1)))
    n_horiz = int(np.sum(angle_from_vertical < 10))
    n_vert = int(np.sum(angle_from_vertical > 80))
    n_sloped = int(np.sum((angle_from_vertical >= 10) & (angle_from_vertical <= 80)))

    regions = detect_slopes(
        mesh,
        min_area_fraction=min_area_fraction,
        normal_deg_err=normal_thresh,
    )
    slope_bricks = get_slope_bricks()

    # Compute optimal scale
    optimal_scale, assignments = compute_optimal_scale(
        regions, default_scale=20.0, max_scale=50.0,
    )
    assigned_regions = {id(region) for region, _ in assignments}

    region_info = []
    for region in regions:
        matches = match_slope_to_bricks(region.slope_angle, slope_bricks)
        best = matches[0] if matches else None
        s_min = _compute_s_min(region, slope_bricks)
        is_assigned = id(region) in assigned_regions
        studs_l = region.length * optimal_scale if s_min else 0
        studs_w = region.width * optimal_scale if s_min else 0
        region_info.append({
            "faces": len(region.face_indices),
            "area": region.area,
            "angle": region.slope_angle,
            "direction": region.slope_direction,
            "length": region.length,
            "width": region.width,
            "best_brick": best,
            "s_min": s_min,
            "assigned": is_assigned,
            "studs_l": studs_l,
            "studs_w": studs_w,
        })

    # Color the mesh by slope regions
    face_colors = np.tile(GRAY, (n_faces, 1))
    sloped_mask = (angle_from_vertical > 10) & (angle_from_vertical < 80)
    face_colors[sloped_mask] = DARK_GRAY

    for region in regions:
        color = DIRECTION_COLORS[region.slope_direction]
        for fi in region.face_indices:
            face_colors[fi] = color

    triangles = np.asarray(mesh.triangles)
    vertex_colors = np.zeros((len(mesh.vertices), 3))
    vertex_counts = np.zeros(len(mesh.vertices))
    for fi in range(n_faces):
        for vi in triangles[fi]:
            vertex_colors[vi] += face_colors[fi]
            vertex_counts[vi] += 1
    vertex_counts[vertex_counts == 0] = 1
    vertex_colors /= vertex_counts[:, np.newaxis]
    mesh.vertex_colors = o3d.utility.Vector3dVector(vertex_colors)

    # Export colored mesh
    glb_filename = f"{name}_slopes.glb"
    glb_path = glb_output_dir / glb_filename
    o3d.io.write_triangle_mesh(str(glb_path), mesh, write_vertex_colors=True)

    return {
        "name": name,
        "short_name": short_name,
        "glb_filename": glb_filename,
        "n_faces": n_faces,
        "n_horiz": n_horiz,
        "n_vert": n_vert,
        "n_sloped": n_sloped,
        "n_regions": len(regions),
        "n_assigned": sum(1 for r in region_info if r.get("assigned")),
        "optimal_scale": optimal_scale,
        "regions": region_info,
    }


def generate_html(results: list[dict], output_path: Path, params: dict):
    """Generate an interactive HTML gallery."""
    # Sort: models with most regions first
    results_sorted = sorted(results, key=lambda r: r.get("n_regions", 0), reverse=True)

    mesh_dir = params.get("mesh_dir")
    rel_mesh_dir = ""
    if mesh_dir:
        rel_mesh_dir = os.path.relpath(mesh_dir, output_path.parent)

    cards = []
    for r in results_sorted:
        if "error" in r:
            cards.append(f"""
            <div class="card error">
                <div class="card-header"><h2>{r['short_name']}</h2></div>
                <p class="error-msg" style="padding:16px">{r['error']}</p>
            </div>""")
            continue

        region_rows = ""
        for i, reg in enumerate(r["regions"]):
            dir_name = DIR_NAMES[reg["direction"]]
            dir_color = DIR_CSS[reg["direction"]]
            brick_str = "&mdash;"
            if reg["best_brick"]:
                b = reg["best_brick"]
                brick_str = (f"ID {b['brick_id']} "
                             f"({b['length']}&times;{b['width']}&times;{b['height']}, "
                             f"{b['angle']:.1f}&deg;)")
            s_min_str = f"{reg['s_min']:.1f}" if reg.get("s_min") else "&mdash;"
            status_cls = "assigned" if reg.get("assigned") else "discarded"
            status_str = "&#10003;" if reg.get("assigned") else "&#10007; fallback"
            studs_str = (f"{reg['studs_l']:.1f}&times;{reg['studs_w']:.1f}"
                         if reg.get("s_min") else "&mdash;")
            region_rows += f"""
                <tr class="{status_cls}">
                    <td>{i+1}</td>
                    <td>{reg['faces']}</td>
                    <td>{reg['angle']:.1f}&deg;</td>
                    <td><span class="dir-badge" style="background:{dir_color}">{dir_name}</span></td>
                    <td>{brick_str}</td>
                    <td>{s_min_str}</td>
                    <td>{studs_str}</td>
                    <td class="status-{status_cls}">{status_str}</td>
                </tr>"""

        if not r["regions"]:
            region_rows = '<tr><td colspan="8" class="empty">No slope regions detected</td></tr>'

        src_url = f"{rel_mesh_dir}/{r['glb_filename']}" if mesh_dir else r['glb_filename']

        cards.append(f"""
        <div class="card">
            <div class="card-header">
                <h2>{r['short_name']}</h2>
                <span class="face-stats">{r['n_faces']} faces &mdash;
                    H:{r['n_horiz']} V:{r['n_vert']} S:{r['n_sloped']}</span>
                <span class="region-count">{r['n_regions']} slope(s), scale={r.get('optimal_scale', 20):.0f}</span>
            </div>
            <div class="card-body">
                <div class="viewer-container">
                    <model-viewer
                        src="{src_url}"
                        camera-controls
                        auto-rotate
                        shadow-intensity="0.5"
                        environment-image="neutral"
                        interaction-prompt="none"
                        style="width:100%;height:100%">
                    </model-viewer>
                </div>
                <div class="details">
                    <h3>Slope Regions</h3>
                    <table>
                        <thead>
                            <tr><th>#</th><th>Faces</th><th>Angle</th><th>Dir</th><th>Best Brick</th><th>s_min</th><th>Studs</th><th>Status</th></tr>
                        </thead>
                        <tbody>{region_rows}</tbody>
                    </table>
                    <p class="uid-full" title="{r['name']}">{r['name']}</p>
                </div>
            </div>
        </div>""")

    summary_total = len(results)
    summary_with_slopes = sum(1 for r in results if r.get("n_regions", 0) > 0)
    summary_total_regions = sum(r.get("n_regions", 0) for r in results)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Slope Detection Gallery</title>
<script type="module" src="https://ajax.googleapis.com/ajax/libs/model-viewer/3.4.0/model-viewer.min.js"></script>
<style>
    body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #f0f2f5; padding: 20px; color: #333; margin: 0; }}
    h1 {{ text-align: center; margin: 20px 0 10px; }}
    .params {{ text-align: center; color: #666; margin-bottom: 10px; font-size: 0.9em; }}
    .summary {{ text-align: center; color: #444; margin-bottom: 20px; font-size: 0.95em; }}
    .summary b {{ color: #2c3e50; }}
    .legend {{ text-align: center; margin-bottom: 30px; }}
    .legend span {{ display: inline-block; padding: 4px 12px; border-radius: 4px; margin: 0 4px;
                    font-size: 0.85em; color: white; }}
    .card {{ background: white; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.06);
             margin: 0 auto 30px; max-width: 1000px; overflow: hidden; border: 1px solid #e0e0e0; }}
    .card.error {{ }}
    .error-msg {{ color: #c0392b; }}
    .card-header {{ background: #2c3e50; color: white; padding: 12px 20px; display: flex;
                    justify-content: space-between; align-items: center; gap: 12px; }}
    .card-header h2 {{ margin: 0; font-size: 1.1em; font-family: monospace; }}
    .face-stats {{ font-size: 0.85em; opacity: 0.8; }}
    .region-count {{ font-size: 0.85em; background: rgba(255,255,255,0.15); padding: 3px 10px;
                     border-radius: 4px; }}
    .card-body {{ display: flex; gap: 0; }}
    .viewer-container {{ flex: 0 0 450px; height: 400px; background: #fafafa; }}
    .details {{ flex: 1; padding: 16px; overflow-x: auto; }}
    .details h3 {{ margin: 0 0 10px; font-size: 1em; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.85em; }}
    th {{ background: #f5f5f5; padding: 6px 10px; text-align: left; border-bottom: 2px solid #ddd; }}
    td {{ padding: 6px 10px; border-bottom: 1px solid #eee; }}
    .empty {{ text-align: center; color: #999; padding: 20px; }}
    .dir-badge {{ display: inline-block; padding: 2px 8px; border-radius: 3px; color: white;
                  font-size: 0.85em; font-weight: 600; }}
    .uid-full {{ font-size: 0.75em; color: #999; margin-top: 12px; word-break: break-all; }}
    tr.discarded {{ opacity: 0.5; }}
    .status-assigned {{ color: #27ae60; font-weight: 600; }}
    .status-discarded {{ color: #c0392b; font-size: 0.85em; }}
    @media (max-width: 700px) {{
        .card-body {{ flex-direction: column; }}
        .viewer-container {{ flex: none; height: 300px; }}
    }}
</style>
</head>
<body>
<h1>Slope Detection Results</h1>
<div class="params">min_area={params['min_area']}, normal_thresh={params['normal_thresh']}&deg;,
    x_rotation={params['x_rotation']}&deg;</div>
<div class="summary"><b>{summary_total}</b> models &mdash;
    <b>{summary_with_slopes}</b> with slopes &mdash;
    <b>{summary_total_regions}</b> total regions</div>
<div class="legend">
    <span style="background:#b0b0b0">Gray: H/V</span>
    <span style="background:#666">Dark: filtered</span>
    <span style="background:{DIR_CSS[0]}">+X</span>
    <span style="background:{DIR_CSS[1]}">+Y</span>
    <span style="background:{DIR_CSS[2]}">&minus;X</span>
    <span style="background:{DIR_CSS[3]}">&minus;Y</span>
</div>
{''.join(cards)}
<footer style="text-align:center;margin-top:50px;color:#888">Generated by BrickGPT slope detection</footer>
</body>
</html>"""

    output_path.write_text(html)
    print(f"\nGallery written to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Slope detection gallery for objaverse assets")
    parser.add_argument("-o", "--output", default=None,
                        help="Output HTML path (default: objaverse/slope_gallery.html)")
    parser.add_argument("--x-rotation", type=float, default=90.0,
                        help="X rotation in degrees (default: 90)")
    parser.add_argument("--min-area", type=float, default=0.01,
                        help="Min region area as fraction of total mesh area (default: 0.01)")
    parser.add_argument("--normal-thresh", type=float, default=15.0,
                        help="Max normal angle diff for BFS grouping in degrees (default: 15)")
    args = parser.parse_args()

    output_path = Path(args.output).resolve() if args.output else SCRIPT_DIR / "results" / "slope_gallery.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Mesh output directory
    mesh_output_dir = ASSETS_DIR / "slope_detection"
    mesh_output_dir.mkdir(parents=True, exist_ok=True)

    # Find all .glb assets (exclude the slope_detection dir itself if it's inside assets)
    # glob is not recursive by default so equal to assets/*.glb is fine.
    glb_files = sorted(ASSETS_DIR.glob("*.glb"))
    if not glb_files:
        print(f"No .glb files found in {ASSETS_DIR}")
        sys.exit(1)

    print(f"Found {len(glb_files)} models in {ASSETS_DIR}")

    results = []
    for i, glb_path in enumerate(glb_files, 1):
        short = glb_path.stem[:8]
        print(f"[{i}/{len(glb_files)}] {short}...", end=" ", flush=True)
        result = process_mesh(
            glb_path,
            x_rotation=args.x_rotation,
            min_area_fraction=args.min_area,
            normal_thresh=args.normal_thresh,
            glb_output_dir=mesh_output_dir,
        )
        n_regions = result.get("n_regions", 0)
        scale = result.get("optimal_scale", 20)
        n_assigned = result.get("n_assigned", 0)
        print(f"{result.get('n_faces', 0)} faces, {n_regions} regions "
              f"({n_assigned} assigned), scale={scale:.0f}")
        results.append(result)

    generate_html(results, output_path, {
        "min_area": args.min_area,
        "normal_thresh": args.normal_thresh,
        "x_rotation": args.x_rotation,
        "mesh_dir": mesh_output_dir,
    })


if __name__ == "__main__":
    main()
