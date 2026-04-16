"""Debug script: compare baseline mesh2brick vs deformed mesh2brick.

Produces two LDR files side-by-side so you can visually check whether
mesh deformation corrupts the output.

Usage:
    uv run python objaverse/debug_deformation.py objaverse/assets/8ccdacecef714a4bb1e7eaa7075695c7.glb
    uv run python objaverse/debug_deformation.py <path.glb> -o output_dir --resolution 20
"""
import argparse
import math
import time
from collections import deque
from pathlib import Path

import numpy as np
import open3d as o3d

from mesh2brick.mesh2brick import Mesh2Brick, normalize_mesh
from mesh2brick.slopes import prepare_slopes, place_slope_bricks, SlopeConfig
from mesh2brick.slopes.detection import mesh_angle_to_voxel_angle, match_slope_to_bricks
from mesh2brick.data.brick_structure import SlopeBrick, _SLOPE_DIR_TO_ROTATION
from mesh2brick.slopes.utils import (
    build_face_adjacency, compute_areas, normal_angle_diff,
    to_cardinal, compute_region_bounds, slope_run,
)
from mesh2brick.voxel2brick import voxel2brick


def diagnose_slope_detection(
    mesh: o3d.geometry.TriangleMesh,
    cfg: SlopeConfig,
    verbose: bool = False,
) -> None:
    """Replicate detect_features' slope grouping, print every group's fate.

    Mirrors the logic in detection.detect_features so that every slope
    group (accepted or rejected) is printed with the specific filter that
    killed it. Used to diagnose why so few regions are being detected.
    """
    print("\n  SLOPE DETECTION DIAGNOSTICS:")
    print(f"  {'='*56}")

    mesh.compute_triangle_normals()
    normals = np.asarray(mesh.triangle_normals)
    triangles = np.asarray(mesh.triangles)

    if len(triangles) == 0:
        print("  (empty mesh)")
        return

    face_areas = compute_areas(mesh)
    total_area = float(face_areas.sum())
    if total_area == 0:
        print("  (zero-area mesh)")
        return

    cos_angles = np.abs(normals[:, 2])
    angle_from_horiz = np.degrees(np.arccos(np.clip(cos_angles, 0, 1)))
    is_sloped = (angle_from_horiz > cfg.planar_err) & (angle_from_horiz < 90 - cfg.planar_err)
    sloped_faces = set(np.where(is_sloped)[0])
    n_total = len(triangles)
    n_sloped = len(sloped_faces)
    n_flat = int((angle_from_horiz <= cfg.planar_err).sum())
    n_vertical = int((angle_from_horiz >= 90 - cfg.planar_err).sum())

    print(f"  Total faces: {n_total}  "
          f"(flat: {n_flat}, vertical: {n_vertical}, sloped candidates: {n_sloped})")
    print(f"  Total area: {total_area:.4f}  "
          f"min_area threshold: {cfg.min_area*total_area:.4f} "
          f"(= {cfg.min_area:.1%} of total)")
    print(f"  BFS normal_err: {cfg.normal_err:.1f}°")

    if not sloped_faces:
        print("  No sloped faces found.")
        return

    # BFS grouping — exactly mirrors detection.py logic
    adjacency_slopes = build_face_adjacency(triangles, sloped_faces)
    visited_slopes: set[int] = set()
    slope_groups: list[list[int]] = []

    for start_face in sloped_faces:
        if start_face in visited_slopes:
            continue
        queue = deque([start_face])
        visited_slopes.add(start_face)
        group = []
        while queue:
            face = queue.popleft()
            group.append(face)
            for neighbor in adjacency_slopes.get(face, []):
                if neighbor not in visited_slopes:
                    if normal_angle_diff(normals[start_face], normals[neighbor]) < cfg.normal_err:
                        visited_slopes.add(neighbor)
                        queue.append(neighbor)
        slope_groups.append(group)

    print(f"  BFS produced {len(slope_groups)} connected slope groups\n")

    # Sort groups by area descending so the biggest (most likely to be slopes) print first
    groups_by_area = sorted(
        enumerate(slope_groups),
        key=lambda p: -float(face_areas[p[1]].sum()),
    )

    n_accepted = 0
    rejection_counts: dict[str, int] = {}

    for gi, group in groups_by_area:
        group_areas = face_areas[group]
        region_area = float(group_areas.sum())
        area_frac = region_area / total_area

        status = "ACCEPT"
        reason = ""
        extra = ""

        # Filter 1: area threshold
        if region_area < cfg.min_area * total_area:
            status = "REJECT"
            reason = "area_too_small"
            extra = (f"area={region_area:.4f} ({area_frac:.2%}) "
                     f"< min={cfg.min_area*total_area:.4f} ({cfg.min_area:.1%})")
        else:
            weighted_normals = normals[group] * group_areas[:, np.newaxis]
            avg_normal = weighted_normals.sum(axis=0)
            norm = float(np.linalg.norm(avg_normal))
            if norm < 1e-10:
                status = "REJECT"
                reason = "degenerate_normal"
                extra = f"sum of weighted normals has zero length"
            else:
                avg_normal = avg_normal / norm
                if avg_normal[2] < 0:
                    status = "REJECT"
                    reason = "downward_facing"
                    extra = f"n_z={avg_normal[2]:+.3f}"
                else:
                    slope_angle = math.degrees(math.acos(min(abs(avg_normal[2]), 1.0)))
                    direction = np.array([avg_normal[0], avg_normal[1]])
                    if float(np.linalg.norm(direction)) < 1e-10:
                        status = "REJECT"
                        reason = "no_xy_direction"
                        extra = f"avg_normal nearly vertical (n_z={avg_normal[2]:+.3f})"
                    else:
                        slope_direction = to_cardinal(direction)
                        length, width, height = compute_region_bounds(
                            mesh, group, slope_direction)
                        if length < 0.05 or width < 0.05:
                            status = "REJECT"
                            reason = "degenerate_bounds"
                            extra = f"length={length:.4f}, width={width:.4f}"
                        else:
                            extra = (
                                f"angle={slope_angle:.1f}° "
                                f"normal=({avg_normal[0]:+.3f},{avg_normal[1]:+.3f},{avg_normal[2]:+.3f}) "
                                f"dir={slope_direction} length={length:.3f} width={width:.3f}"
                            )
                            n_accepted += 1

        if status == "REJECT":
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
        if verbose:
            print(f"    [{status}] group {gi}: n_faces={len(group)} "
                  f"area={region_area:.4f} ({area_frac:.2%})")
            if status == "REJECT":
                print(f"              reason={reason}: {extra}")
            else:
                print(f"              {extra}")

    print(f"\n  Summary: {n_accepted} accepted, "
          f"{len(slope_groups) - n_accepted} rejected")
    if rejection_counts:
        by_reason = ", ".join(f"{k}={v}" for k, v in sorted(rejection_counts.items()))
        print(f"  Rejection breakdown: {by_reason}")
    print(f"  {'='*56}")


def run_baseline(mesh_path: str, resolution: int) -> dict:
    """Standard pipeline — no deformation."""
    print("=" * 60)
    print("BASELINE (standard Mesh2Brick)")
    print("=" * 60)
    t0 = time.time()
    converter = Mesh2Brick(world_dim=(resolution, resolution, resolution * 3))
    bricks = converter(mesh_path)
    elapsed = time.time() - t0
    return {"bricks": bricks, "time": elapsed, "label": "baseline"}


def run_deformed(mesh_path: str, resolution: int,
                 x_rotation: float = 90.0,
                 cfg: SlopeConfig = None,
                 verbose: bool = False) -> dict:
    """Deformation pipeline — detect slopes, deform, then standard voxel2brick."""
    if cfg is None:
        cfg = SlopeConfig()
    print("=" * 60)
    print("DEFORMED (slope detection + deformation + standard voxel2brick)")
    print("=" * 60)
    t0 = time.time()

    mesh = o3d.io.read_triangle_mesh(mesh_path)
    mesh = normalize_mesh(mesh, x_rotation=x_rotation)

    # Apply Z-scaling to match what prepare_slopes does internally
    vertices = np.asarray(mesh.vertices)
    vertices[:, 2] *= 3.0
    mesh.vertices = o3d.utility.Vector3dVector(vertices)

    # Pre-deformation diagnostics: explain why each slope group is accepted/rejected
    diagnose_slope_detection(mesh, cfg, verbose=verbose)

    # Note: prepare_slopes will apply Z-scaling again, so we need to undo it first
    vertices = np.asarray(mesh.vertices)
    vertices[:, 2] /= 3.0
    mesh.vertices = o3d.utility.Vector3dVector(vertices)

    slope_result = prepare_slopes(mesh, resolution=resolution, cfg=cfg)
    mesh = slope_result.mesh
    regions = slope_result.regions
    assignments = slope_result.assignments
    optimal_scale = slope_result.scale
    world_dim = slope_result.world_dim
    energy = slope_result.deformation.final_energy if slope_result.deformation else 0.0

    # Print per-region diagnostics
    # Note: regions were detected on the pre-deformation mesh, but `mesh` here
    # is the deformed mesh. Triangle indices are preserved by prepare_slopes,
    # so face_indices still refer to the same faces.
    mesh.compute_triangle_normals()
    deformed_face_normals = np.asarray(mesh.triangle_normals)
    _cardinals = np.array([[1, 0], [0, 1], [-1, 0], [0, -1]], dtype=float)
    _cardinal_names = ["+X", "+Y", "-X", "-Y"]
    for i, region in enumerate(regions):
        voxel_angle = mesh_angle_to_voxel_angle(region.angle)
        matched = match_slope_to_bricks(voxel_angle)
        s_min = None
        min_steps = 2  # Default from compute_optimal_scale
        if matched and region.length > 0 and region.width > 0:
            s_min = min(max(min_steps * b['length'] / region.length, b['width'] / region.width) for b in matched)
        print(f"  Region {i}: dir={region.direction}, iso_angle={region.angle:.1f}°, "
              f"voxel_angle={voxel_angle:.1f}°, length={region.length:.3f}, width={region.width:.3f}, "
              f"s_min={s_min}, matched_angles={[b['angle'] for b in matched[:3]]}")

        # Raw average XY normal and cardinal fit (region.avg_normal is pre-deformation)
        xy = region.avg_normal[:2]
        xy_norm = float(np.linalg.norm(xy))
        xy_unit = xy / xy_norm if xy_norm > 1e-10 else xy
        dots = _cardinals @ xy_unit
        best_idx = int(np.argmax(dots))
        cardinal_fit = float(dots[best_idx])
        misalign_deg = float(np.degrees(np.arccos(np.clip(cardinal_fit, -1.0, 1.0))))
        print(f"    avg_normal=({region.avg_normal[0]:+.3f}, {region.avg_normal[1]:+.3f}, "
              f"{region.avg_normal[2]:+.3f})  xy_unit=({xy_unit[0]:+.3f}, {xy_unit[1]:+.3f})  "
              f"nearest={_cardinal_names[best_idx]}  cardinal_fit={cardinal_fit:.3f}  "
              f"misalign={misalign_deg:.1f}°")

        # Per-face normal spread on the DEFORMED mesh
        # (if deformation warped the surface, face normals will no longer cluster)
        face_normals = deformed_face_normals[region.face_indices]
        if len(face_normals) > 0:
            mean_n = face_normals.mean(axis=0)
            mean_n /= np.linalg.norm(mean_n) + 1e-12
            face_dots = face_normals @ mean_n
            face_angles = np.degrees(np.arccos(np.clip(face_dots, -1.0, 1.0)))
            # Also compute pre-deformation face normal spread (faces in original mesh)
            max_dev = float(face_angles.max())
            mean_dev = float(face_angles.mean())
            std_dev = float(face_angles.std())
            # Fraction of faces within 5° of the mean (well-clustered)
            clustered_frac = float((face_angles < 5.0).mean())

            # Deformed XY direction
            mean_xy = mean_n[:2]
            mean_xy_norm = float(np.linalg.norm(mean_xy))
            mean_xy_unit = mean_xy / mean_xy_norm if mean_xy_norm > 1e-10 else mean_xy
            dots_d = _cardinals @ mean_xy_unit
            d_fit = float(dots_d.max())
            d_misalign = float(np.degrees(np.arccos(np.clip(d_fit, -1.0, 1.0))))

            print(f"    n_faces={len(face_normals)}  "
                  f"deformed_mean_n=({mean_n[0]:+.3f}, {mean_n[1]:+.3f}, {mean_n[2]:+.3f})  "
                  f"deformed_cardinal_fit={d_fit:.3f}  deformed_misalign={d_misalign:.1f}°")
            print(f"    face_normal_spread: max={max_dev:.1f}°  mean={mean_dev:.1f}°  "
                  f"std={std_dev:.1f}°  within_5°={clustered_frac:.1%}")
    print(f"  Regions: {len(regions)}, Assignments: {len(assignments)}, "
          f"Scale: {optimal_scale:.1f}")
    if energy > 0:
        print(f"  Deformation energy: {energy:.4f}")
    elif not assignments:
        print("  No slopes — using apply_scale only")
    print(f"  World dim: {world_dim}")

    # Voxelize directly at voxel_size=1.0
    voxel_grid = o3d.geometry.VoxelGrid.create_from_triangle_mesh(mesh, 1.0)
    voxels = np.zeros(world_dim, dtype=np.uint8)
    for voxel in np.asarray(voxel_grid.get_voxels()):
        idx = tuple(np.floor(voxel.grid_index).astype(int))
        if all(0 <= i < d for i, d in zip(idx, world_dim)):
            voxels[idx] = 1
    print(f"  Voxelized: {voxels.sum()} filled voxels")
    print(f"  Voxel grid origin: {np.asarray(voxel_grid.origin)}")
    print(f"  Mesh min bound: {np.asarray(mesh.get_min_bound())}")
    print(f"  Mesh max bound: {np.asarray(mesh.get_max_bound())}")

    # Slope tiling: place slope bricks first, then regular bricks on remainder
    if assignments:
        print(f"\n  SLOPE TILING DIAGNOSTICS:")
        print(f"  {'='*56}")
        voxel_origin = np.asarray(voxel_grid.origin)

        from mesh2brick.slopes.tiling import _region_voxel_bounds

        for region_idx, (region, matched_bricks) in enumerate(assignments):
            best_brick = min(matched_bricks, key=lambda b: b['length'] * b['width'])
            brick_l, brick_w, brick_h = best_brick['length'], best_brick['width'], best_brick['height']
            rotation = _SLOPE_DIR_TO_ROTATION[region.direction]
            dim_x, dim_y = SlopeBrick.rotated_dim(brick_l, brick_w, rotation)

            x_min, x_max, y_min, y_max, z_min, z_max = _region_voxel_bounds(mesh, region, voxel_origin)

            # Check actual voxel density in this region
            region_voxels = voxels[x_min:x_max+1, y_min:y_max+1, z_min:z_max+1]
            voxels_in_region = region_voxels.sum()
            region_volume = (x_max - x_min + 1) * (y_max - y_min + 1) * (z_max - z_min + 1)
            density = voxels_in_region / region_volume if region_volume > 0 else 0

            run = slope_run(brick_l, brick_h)
            step_x, step_y = SlopeBrick.rotated_dim(run, brick_w, rotation)

            n_x = max(1, round((x_max - x_min + 1) / step_x))
            n_y = max(1, round((y_max - y_min + 1) / step_y))
            n_z = max(1, round((z_max - z_min + 1) / brick_h))

            if region.direction in (0, 2):
                n_z = min(n_z, n_x)
            else:
                n_z = min(n_z, n_y)

            expected_bricks = n_x * n_y * n_z if region.direction in (0, 2) else n_x * n_y * n_z

            print(f"  Region {region_idx}: dir={region.direction}, brick={brick_l}x{brick_w}x{brick_h}")
            print(f"    Voxel bounds: x=[{x_min},{x_max}], y=[{y_min},{y_max}], z=[{z_min},{z_max}]")
            print(f"    Voxels: {voxels_in_region}/{region_volume} (density={density:.2%})")
            print(f"    Grid: {n_x}x{n_y}x{n_z} = ~{expected_bricks} candidate bricks")

        slope_bricks, remaining_voxels = place_slope_bricks(
            voxels, mesh, assignments, voxel_origin=voxel_origin, verbose=verbose,
)
        print(f"\n  {'='*56}")
        print(f"  Total slope bricks placed: {len(slope_bricks)}")
        print(f"  Voxels remaining: {remaining_voxels.sum()} / {voxels.sum()}")

        # Check for voxel-level overlaps between slope bricks
        slope_voxel_grid = np.zeros(world_dim, dtype=np.uint8)
        overlap_count = 0
        for brick in slope_bricks:
            if slope_voxel_grid[brick.slice].any():
                overlap_count += 1
            slope_voxel_grid[brick.slice] = 1

        if overlap_count > 0:
            print(f"  WARNING: {overlap_count} slope bricks have voxel-level overlaps")
        else:
            print(f"  No slope brick overlaps")
    else:
        slope_bricks = []
        remaining_voxels = voxels

    bricks = voxel2brick(remaining_voxels)
    # Check for voxel-level overlap before combining
    overlap_count = 0
    for sb in slope_bricks:
        overlap_count += bricks.voxel_occupancy[sb.slice].sum()
    if overlap_count > 0:
        print(f"  WARNING: {overlap_count} voxels overlap between slope and regular bricks")
    else:
        print(f"  No voxel overlap between slope and regular bricks")
    for brick in slope_bricks:
        bricks.add_brick(brick)
    elapsed = time.time() - t0

    return {
        "bricks": bricks,
        "time": elapsed,
        "label": "deformed",
        "scale": optimal_scale,
        "n_regions": len(regions),
        "n_assignments": len(assignments),
        "energy": energy,
        "slope_bricks": slope_bricks,
        "mesh": mesh,
        "assignments": assignments,
        "world_dim": world_dim,
    }


def print_stats(result: dict) -> None:
    bricks = result["bricks"]
    n_bricks = len(bricks.bricks)
    print(f"  Bricks: {n_bricks}")
    print(f"  Time: {result['time']:.2f}s")
    if "scale" in result:
        print(f"  Scale: {result['scale']:.1f}")
        print(f"  Regions: {result['n_regions']}, Assignments: {result['n_assignments']}")
        print(f"  Deformation energy: {result['energy']:.4f}")


def main():
    parser = argparse.ArgumentParser(description="Debug: compare baseline vs deformed mesh2brick")
    parser.add_argument("mesh", nargs="?",
                        default="objaverse/data/meshes/general/8ccdacecef714a4bb1e7eaa7075695c7.glb",
                        help="Path to input GLB file")
    parser.add_argument("-o", "--output-dir", default="objaverse/experiments/slopes/test/",
                        help="Output directory for LDR files")
    parser.add_argument("--resolution", "-r", type=int, default=20,
                        help="Target resolution (default 20)")
    parser.add_argument("--x-rotation", type=float, default=90.0,
                        help="X rotation in degrees (default 90.0)")
    
    _defaults = SlopeConfig()
    parser.add_argument("--planar-err", type=float, default=_defaults.planar_err,
                        help=f"Faces within this angle of horizontal/vertical are excluded (default {_defaults.planar_err})")
    parser.add_argument("--normal-err", type=float, default=_defaults.normal_err,
                        help=f"Max angular difference for BFS grouping (default {_defaults.normal_err})")
    parser.add_argument("--min-area", type=float, default=_defaults.min_area,
                        help=f"Minimum region area as fraction of total mesh area (default {_defaults.min_area})")

    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable verbose diagnostic output")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    model_id = Path(args.mesh).stem

    # Run both pipelines
    baseline = run_baseline(args.mesh, args.resolution)
    print()
    cfg = SlopeConfig(
        planar_err=args.planar_err,
        normal_err=args.normal_err,
        min_area=args.min_area,
    )
    deformed = run_deformed(args.mesh, args.resolution, x_rotation=args.x_rotation, cfg=cfg,
                          verbose=args.verbose)

    # Print comparison
    print()
    print("=" * 60)
    print("COMPARISON")
    print("=" * 60)
    print(f"\nBaseline:")
    print_stats(baseline)
    print(f"\nDeformed:")
    print_stats(deformed)

    # Save LDR files
    baseline_path = output_dir / f"{model_id}_baseline.ldr"
    deformed_path = output_dir / f"{model_id}_deformed.ldr"

    with open(baseline_path, "w") as f:
        f.write(baseline["bricks"].to_ldr())
    print(f"\nSaved baseline: {baseline_path}")

    with open(deformed_path, "w") as f:
        f.write(deformed["bricks"].to_ldr())
    print(f"Saved deformed: {deformed_path}")

    # Save slopes-only LDR
    slope_bricks = deformed.get("slope_bricks", [])
    if slope_bricks:
        from mesh2brick.data.brick_structure import BrickStructure
        slope_struct = BrickStructure(slope_bricks, world_dim=deformed["world_dim"])
        slopes_ldr_path = output_dir / f"{model_id}_slopes_only.ldr"
        with open(slopes_ldr_path, "w") as f:
            f.write(slope_struct.to_ldr())
        print(f"Saved slopes-only LDR: {slopes_ldr_path}")

    # Save mesh with only the slope region faces
    assignments = deformed.get("assignments", [])
    deformed_mesh = deformed.get("mesh")
    if assignments and deformed_mesh is not None:
        all_face_indices = []
        for region, _ in assignments:
            all_face_indices.extend(region.face_indices)
        all_face_indices = sorted(set(all_face_indices))

        triangles = np.asarray(deformed_mesh.triangles)
        vertices = np.asarray(deformed_mesh.vertices)
        slope_triangles = triangles[all_face_indices]

        # Remap vertex indices to only include used vertices
        used_verts = np.unique(slope_triangles)
        vert_map = {old: new for new, old in enumerate(used_verts)}
        new_triangles = np.vectorize(vert_map.get)(slope_triangles)
        new_vertices = vertices[used_verts]

        slope_mesh = o3d.geometry.TriangleMesh()
        slope_mesh.vertices = o3d.utility.Vector3dVector(new_vertices)
        slope_mesh.triangles = o3d.utility.Vector3iVector(new_triangles)
        slope_mesh.compute_vertex_normals()

        slope_mesh_path = output_dir / f"{model_id}_slope_regions.glb"
        o3d.io.write_triangle_mesh(str(slope_mesh_path), slope_mesh)
        print(f"Saved slope regions mesh: {slope_mesh_path}")


if __name__ == "__main__":
    main()
