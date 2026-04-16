"""Visualize slope detection on objaverse assets as an interactive HTML gallery.

Usage:
    uv run objaverse/visualize_slopes.py
    uv run objaverse/visualize_slopes.py --min-area-fraction 0.005
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
from mesh2brick.slopes import prepare_slopes, SlopeConfig
from mesh2brick.slopes.detection import get_slope_bricks, match_slope_to_bricks, mesh_angle_to_voxel_angle


SCRIPT_DIR = Path(__file__).parent.parent.parent.resolve()  # tools/visualization/ -> objaverse/
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
    slope_cfg: SlopeConfig,
    glb_output_dir: Path,
    png_path: Path | None = None,
    metrics: dict | None = None,
    run_detection: bool = False,
    results_dir: Path | None = None,
) -> dict:
    """Process one mesh: detect slopes, color it, export GLB, return results."""
    name = mesh_path.stem
    short_name = name[:8]

    result = {
        "name": name,
        "short_name": short_name,
    }

    # Add PNG render path if available
    if png_path:
        result["png_filename"] = png_path.name

    # Add metrics if available
    if metrics:
        result["metrics"] = metrics

    # If not running detection, return early with basic info
    if not run_detection:
        mesh = o3d.io.read_triangle_mesh(str(mesh_path))
        if len(mesh.triangles) == 0:
            result["error"] = "Failed to load mesh"
            return result

        result["n_faces"] = len(mesh.triangles)
        result["n_horiz"] = 0
        result["n_vert"] = 0
        result["n_sloped"] = 0
        result["n_regions"] = 0
        result["n_assigned"] = 0
        result["optimal_scale"] = metrics.get("scale", 20) if metrics else 20
        result["regions"] = []
        result["original_glb_path"] = mesh_path
        return result

    # Run detection mode below
    mesh = o3d.io.read_triangle_mesh(str(mesh_path))
    if len(mesh.triangles) == 0:
        result["error"] = "Failed to load mesh"
        return result

    mesh = normalize_mesh(mesh, x_rotation=x_rotation)
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

    # Run slope detection + deformation pipeline
    slope_result = prepare_slopes(mesh, resolution=20, cfg=slope_cfg)
    regions = slope_result.regions
    assignments = slope_result.assignments
    optimal_scale = slope_result.scale

    slope_bricks = get_slope_bricks()
    assigned_regions = {id(region) for region, _ in assignments}

    region_info = []
    for region in regions:
        voxel_angle = mesh_angle_to_voxel_angle(region.angle)
        matches = match_slope_to_bricks(voxel_angle, slope_bricks)
        best = matches[0] if matches else None
        
        s_min = None
        if matches and region.length > 0 and region.width > 0:
            s_min = min(max(b['length'] / region.length, b['width'] / region.width) for b in matches)
        is_assigned = id(region) in assigned_regions
        studs_l = region.length * optimal_scale if s_min else 0
        studs_w = region.width * optimal_scale if s_min else 0
        region_info.append({
            "faces": len(region.face_indices),
            "area": region.area,
            "angle": region.angle,
            "direction": region.direction,
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
        color = DIRECTION_COLORS[region.direction]
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

    # Export deformed mesh if available
    deform_info = None
    deformed_glb_filename = None
    if slope_result.deformation is not None:
        try:
            result = slope_result.deformation

            # Build deformed mesh for export (undo Z-scale from prepare_slopes)
            deformed_verts = np.asarray(slope_result.mesh.vertices).copy()
            deformed_verts[:, 2] /= 3.0
            deformed_mesh = o3d.geometry.TriangleMesh()
            deformed_mesh.vertices = o3d.utility.Vector3dVector(deformed_verts)
            deformed_mesh.triangles = mesh.triangles
            deformed_mesh.compute_vertex_normals()
            deformed_mesh.vertex_colors = mesh.vertex_colors

            deformed_glb_filename = f"{name}_deformed.glb"
            deformed_glb_path = glb_output_dir / deformed_glb_filename
            o3d.io.write_triangle_mesh(str(deformed_glb_path), deformed_mesh, write_vertex_colors=True)

            # Compute corner snap quality
            corner_verts = result.deformed_vertices[result.slope_corner_indices]
            frac_parts = np.abs(corner_verts - np.round(corner_verts))
            avg_frac = float(frac_parts.mean()) if len(corner_verts) > 0 else 0.0

            deform_info = {
                "energy": result.final_energy,
                "n_corners": len(result.slope_corner_indices),
                "n_flat_planes": len(result.flat_planes),
                "n_splits": len(result.split_vertices),
                "avg_corner_frac": avg_frac,
            }
        except Exception as e:
            deform_info = {"error": str(e)}

    result.update({
        "glb_filename": glb_filename,
        "deformed_glb_filename": deformed_glb_filename,
        "n_faces": n_faces,
        "n_horiz": n_horiz,
        "n_vert": n_vert,
        "n_sloped": n_sloped,
        "n_regions": len(regions),
        "n_assigned": sum(1 for r in region_info if r.get("assigned")),
        "optimal_scale": optimal_scale,
        "deform_info": deform_info,
        "regions": region_info,
    })

    return result


def generate_html(results: list[dict], output_path: Path, params: dict):
    """Generate an interactive HTML gallery."""
    # Sort: models with most regions first (or most bricks if no regions)
    results_sorted = sorted(results, key=lambda r: (
        r.get("n_regions", 0),
        r.get("metrics", {}).get("total_bricks", 0)
    ), reverse=True)

    mesh_dir = params.get("mesh_dir")
    results_dir = params.get("results_dir")

    rel_mesh_dir = ""
    if mesh_dir:
        rel_mesh_dir = os.path.relpath(mesh_dir, output_path.parent)

    rel_results_dir = ""
    if results_dir:
        rel_results_dir = os.path.relpath(results_dir, output_path.parent)

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
            if reg.get("assigned"):
                status_cls = "assigned"
                status_str = "&#10003; assigned"
            else:
                status_cls = "discarded"
                status_str = "&#10007; discarded"
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

        # Original GLB viewer (always shown)
        # If detection was run, show colored GLB from mesh_output_dir
        # Otherwise, show original GLB from assets_dir
        original_viewer = ""
        if "glb_filename" in r:
            # Detection mode: show colored GLB
            src_url = f"{rel_mesh_dir}/{r['glb_filename']}" if mesh_dir else r['glb_filename']
            original_viewer = f"""
                <div class="viewer-container">
                    <div class="viewer-label">Original (colored)</div>
                    <model-viewer
                        src="{src_url}"
                        camera-controls
                        auto-rotate
                        shadow-intensity="0.5"
                        environment-image="neutral"
                        interaction-prompt="none"
                        style="width:100%;height:100%">
                    </model-viewer>
                </div>"""
        elif "original_glb_path" in r:
            # Default mode: show original GLB from assets
            original_path = r["original_glb_path"]
            rel_original = os.path.relpath(original_path, output_path.parent)
            original_viewer = f"""
                <div class="viewer-container">
                    <div class="viewer-label">Original</div>
                    <model-viewer
                        src="{rel_original}"
                        camera-controls
                        auto-rotate
                        shadow-intensity="0.5"
                        environment-image="neutral"
                        interaction-prompt="none"
                        style="width:100%;height:100%">
                    </model-viewer>
                </div>"""

        # Build PNG render viewer if available
        png_viewer = ""
        if r.get("png_filename"):
            png_url = f"{rel_results_dir}/{r['png_filename']}" if results_dir else r['png_filename']
            png_viewer = f"""
                <div class="viewer-container">
                    <div class="viewer-label">Legolized</div>
                    <img src="{png_url}" alt="LEGO render" style="width:100%;height:100%;object-fit:contain;">
                </div>"""

        # Build deformation viewer + stats if available
        deform_viewer = ""
        deform_stats = ""
        di = r.get("deform_info")
        deformed_glb = r.get("deformed_glb_filename")
        if deformed_glb and di and "error" not in di:
            deformed_url = f"{rel_mesh_dir}/{deformed_glb}" if mesh_dir else deformed_glb
            deform_viewer = f"""
                <div class="viewer-container">
                    <div class="viewer-label">Deformed</div>
                    <model-viewer
                        src="{deformed_url}"
                        camera-controls
                        auto-rotate
                        shadow-intensity="0.5"
                        environment-image="neutral"
                        interaction-prompt="none"
                        style="width:100%;height:100%">
                    </model-viewer>
                </div>"""
            snap_pct = (1.0 - di['avg_corner_frac']) * 100
            deform_stats = f"""
                    <div class="deform-stats">
                        <h3>Deformation</h3>
                        <table>
                            <tr><td>Energy</td><td>{di['energy']:.3f}</td></tr>
                            <tr><td>Corners</td><td>{di['n_corners']}</td></tr>
                            <tr><td>Flat planes</td><td>{di['n_flat_planes']}</td></tr>
                            <tr><td>Split verts</td><td>{di['n_splits']}</td></tr>
                            <tr><td>Corner snap</td><td>{snap_pct:.0f}%</td></tr>
                        </table>
                    </div>"""
        elif di and "error" in di:
            deform_stats = f'<p class="error-msg" style="font-size:0.8em">Deform error: {di["error"]}</p>'

        # Build metrics display if available
        metrics_html = ""
        if r.get("metrics"):
            m = r["metrics"]
            slope_pct = (m.get('slope_bricks', 0) / m.get('total_bricks', 1)) * 100 if m.get('total_bricks') else 0
            metrics_html = f"""
                    <div class="metrics-stats">
                        <h3>Build Metrics</h3>
                        <table>
                            <tr><td>Time</td><td>{m.get('time', '?'):.2f} s</td></tr>
                            <tr><td>Total bricks</td><td>{m.get('total_bricks', '?')}</td></tr>
                            <tr><td>Slope bricks</td><td>{m.get('slope_bricks', 0)} ({slope_pct:.1f}%)</td></tr>
                            <tr><td>Components</td><td>{m.get('connected_components', '?')}</td></tr>
                            <tr><td>Voxels</td><td>{m.get('voxels', '?')}</td></tr>
                            <tr><td>Stability</td><td>{m.get('stability', '?'):.3f}</td></tr>
                        </table>
                    </div>"""

        cards.append(f"""
        <div class="card">
            <div class="card-header">
                <h2>{r['short_name']}</h2>
                <span class="face-stats">{r['n_faces']} faces &mdash;
                    H:{r['n_horiz']} V:{r['n_vert']} S:{r['n_sloped']}</span>
                <span class="region-count">{r['n_regions']} slope(s), scale={r.get('optimal_scale', 20):.0f}</span>
            </div>
            <div class="card-body">
                {original_viewer}{deform_viewer}{png_viewer}
                <div class="details">
                    {"<h3>Slope Regions</h3><table><thead><tr><th>#</th><th>Faces</th><th>Angle</th><th>Dir</th><th>Best Brick</th><th>s_min</th><th>Studs</th><th>Status</th></tr></thead><tbody>" + region_rows + "</tbody></table>" if r.get("regions") else ""}{deform_stats}{metrics_html}
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
    .viewer-container {{ flex: 0 0 280px; height: 400px; background: #fafafa; position: relative; }}
    .viewer-label {{ position: absolute; top: 8px; left: 8px; z-index: 1; background: rgba(0,0,0,0.5);
                     color: white; padding: 2px 8px; border-radius: 3px; font-size: 0.75em; }}
    .details {{ flex: 1; padding: 16px; overflow-x: auto; min-width: 300px; }}
    .metrics-stats {{ margin-top: 12px; }}
    .metrics-stats h3 {{ font-size: 0.95em; margin: 0 0 6px; }}
    .metrics-stats table {{ font-size: 0.8em; }}
    .details h3 {{ margin: 0 0 10px; font-size: 1em; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.85em; }}
    th {{ background: #f5f5f5; padding: 6px 10px; text-align: left; border-bottom: 2px solid #ddd; }}
    td {{ padding: 6px 10px; border-bottom: 1px solid #eee; }}
    .empty {{ text-align: center; color: #999; padding: 20px; }}
    .dir-badge {{ display: inline-block; padding: 2px 8px; border-radius: 3px; color: white;
                  font-size: 0.85em; font-weight: 600; }}
    .uid-full {{ font-size: 0.75em; color: #999; margin-top: 12px; word-break: break-all; }}
    .deform-stats {{ margin-top: 12px; }}
    .deform-stats h3 {{ font-size: 0.95em; margin: 0 0 6px; }}
    .deform-stats table {{ font-size: 0.8em; }}
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
<div class="params">min_area={params['min_area']}, normal_err={params['normal_err']}&deg;,
    planar_err={params['planar_err']}&deg;, x_rotation={params['x_rotation']}&deg;</div>
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


def parse_logs(log_path: Path) -> dict:
    """Parse logs.txt and return dict mapping uid -> metrics."""
    import re

    # Regex patterns
    CONVERTING_PATTERN = re.compile(r"Converting ([a-f0-9]+)\.glb")
    SLOPE_DETECTION_PATTERN = re.compile(r"Slope detection: (\d+) regions, (\d+) assignments, scale=([\d\.]+)")
    DEFORMATION_PATTERN = re.compile(r"Deformation energy: ([\d\.]+)")
    VOXELS_PATTERN = re.compile(r"Voxelized: (\d+) filled voxels")
    SLOPE_BRICKS_PATTERN = re.compile(r"Slope bricks placed: (\d+)")
    FINISHED_PATTERN = re.compile(r"Finished in time: ([\d\.]+) s \| "
                                  r"# bricks: (\d+) \| "
                                  r"# connected components: (\d+) \| "
                                  r"# min connected components possible: (\d+) \| "
                                  r"Stability: ([\d\.]+)")

    metrics = {}

    if not log_path.exists():
        return metrics

    with open(log_path, 'r') as f:
        lines = f.readlines()

    current_uid = None
    current_data = {}

    for line in lines:
        # Check for new conversion start
        conv_match = CONVERTING_PATTERN.search(line)
        if conv_match:
            current_uid = conv_match.group(1)
            current_data = {}
            continue

        if not current_uid:
            continue

        # Parse slope detection
        slope_match = SLOPE_DETECTION_PATTERN.search(line)
        if slope_match:
            current_data['regions'] = int(slope_match.group(1))
            current_data['assignments'] = int(slope_match.group(2))
            current_data['scale'] = float(slope_match.group(3))
            continue

        # Parse deformation energy
        deform_match = DEFORMATION_PATTERN.search(line)
        if deform_match:
            current_data['deformation_energy'] = float(deform_match.group(1))
            continue

        # Parse voxel count
        voxels_match = VOXELS_PATTERN.search(line)
        if voxels_match:
            current_data['voxels'] = int(voxels_match.group(1))
            continue

        # Parse slope bricks
        slope_bricks_match = SLOPE_BRICKS_PATTERN.search(line)
        if slope_bricks_match:
            current_data['slope_bricks'] = int(slope_bricks_match.group(1))
            continue

        # Parse finished line
        fin_match = FINISHED_PATTERN.search(line)
        if fin_match:
            time_val, bricks, comps, min_comps, stability = fin_match.groups()
            current_data['time'] = float(time_val)
            current_data['total_bricks'] = int(bricks)
            current_data['connected_components'] = int(comps)
            current_data['min_components'] = int(min_comps)
            current_data['stability'] = float(stability)

            # Store metrics for this model
            metrics[current_uid] = current_data
            current_uid = None
            current_data = {}

    return metrics


def main():
    parser = argparse.ArgumentParser(description="Slope detection gallery for objaverse assets")
    parser.add_argument("-o", "--output", default=None,
                        help="Output HTML path (default: objaverse/slope_gallery.html)")
    parser.add_argument("--assets-dir", type=str, default=None,
                        help="Directory containing .glb files (default: assets/buildings)")
    parser.add_argument("--results-dir", type=str, default=None,
                        help="Directory containing .png renders and logs.txt (default: assets/slope_buildings)")
    parser.add_argument("-s", "--run-detection", action="store_true",
                        help="Re-run slope detection on GLB files")
    parser.add_argument("--x-rotation", type=float, default=90.0,
                        help="X rotation in degrees (default: 90)")
    _defaults = SlopeConfig()
    parser.add_argument("--min-area", type=float, default=_defaults.min_area,
                        help=f"Min region area as fraction of total mesh area (default: {_defaults.min_area})")
    parser.add_argument("--normal-err", type=float, default=_defaults.normal_err,
                        help=f"Max normal angle diff for BFS grouping in degrees (default: {_defaults.normal_err})")
    parser.add_argument("--planar-err", type=float, default=_defaults.planar_err,
                        help=f"Faces within this angle of horizontal/vertical are excluded (default: {_defaults.planar_err})")
    args = parser.parse_args()

    output_path = Path(args.output).resolve() if args.output else SCRIPT_DIR / "results" / "slope_gallery.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Set up directories
    assets_dir = Path(args.assets_dir).resolve() if args.assets_dir else SCRIPT_DIR / "data" / "meshes" / "buildings"
    results_dir = Path(args.results_dir).resolve() if args.results_dir else SCRIPT_DIR / "experiments" / "slopes" / "buildings"

    # Mesh output directory (for colored meshes when -s flag is used)
    mesh_output_dir = SCRIPT_DIR / "experiments" / "slopes" / "detection"
    mesh_output_dir.mkdir(parents=True, exist_ok=True)

    # Find all .glb assets
    glb_files = sorted(assets_dir.glob("*.glb"))

    if not glb_files:
        print(f"No .glb files found in {assets_dir}")
        sys.exit(1)

    print(f"Found {len(glb_files)} models in {assets_dir}")

    slope_cfg = SlopeConfig(
        planar_err=args.planar_err,
        normal_err=args.normal_err,
        min_area=args.min_area,
    )

    # Parse logs once
    logs_data = parse_logs(results_dir / "logs.txt")

    results = []
    for i, glb_path in enumerate(glb_files, 1):
        uid = glb_path.stem
        short = uid[:8]
        print(f"[{i}/{len(glb_files)}] {short}...", end=" ", flush=True)

        # Find corresponding PNG render
        png_path = results_dir / f"{uid}.png"
        png_path = png_path if png_path.exists() else None

        # Get metrics for this model
        metrics_data = logs_data.get(uid)

        result = process_mesh(
            glb_path,
            x_rotation=args.x_rotation,
            slope_cfg=slope_cfg,
            glb_output_dir=mesh_output_dir,
            png_path=png_path,
            metrics=metrics_data,
            run_detection=args.run_detection,
            results_dir=results_dir,
        )

        # Print progress based on mode
        if args.run_detection:
            n_regions = result.get("n_regions", 0)
            scale = result.get("optimal_scale", 20)
            n_assigned = result.get("n_assigned", 0)
            print(f"{result.get('n_faces', 0)} faces, {n_regions} regions "
                  f"({n_assigned} assigned), scale={scale:.0f}")
        else:
            if metrics_data:
                print(f"{result.get('n_faces', 0)} faces, "
                      f"{metrics_data.get('total_bricks', '?')} bricks, "
                      f"{metrics_data.get('slope_bricks', 0)} slopes")
            else:
                print(f"{result.get('n_faces', 0)} faces (no metrics)")

        results.append(result)

    generate_html(results, output_path, {
        "min_area": args.min_area,
        "normal_err": args.normal_err,
        "planar_err": args.planar_err,
        "x_rotation": args.x_rotation,
        "mesh_dir": mesh_output_dir,
        "results_dir": results_dir,
    })


if __name__ == "__main__":
    main()
