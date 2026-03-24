"""Debug script: compare baseline mesh2brick vs deformed mesh2brick.

Produces two LDR files side-by-side so you can visually check whether
mesh deformation corrupts the output.

Usage:
    uv run python objaverse/debug_deformation.py objaverse/assets/8ccdacecef714a4bb1e7eaa7075695c7.glb
    uv run python objaverse/debug_deformation.py <path.glb> -o output_dir --resolution 20
"""
import argparse
import time
from pathlib import Path

import numpy as np
import open3d as o3d

from mesh2brick.mesh2brick import Mesh2Brick, normalize_mesh
from mesh2brick.slopes import detect_features, compute_optimal_scale, deform_mesh, apply_scale, place_slope_bricks, SlopeConfig
from mesh2brick.voxel2brick import voxel2brick


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
                 cfg: SlopeConfig = None) -> dict:
    """Deformation pipeline — detect slopes, deform, then standard voxel2brick."""
    if cfg is None:
        cfg = SlopeConfig()
    print("=" * 60)
    print("DEFORMED (slope detection + deformation + standard voxel2brick)")
    print("=" * 60)
    t0 = time.time()

    mesh = o3d.io.read_triangle_mesh(mesh_path)
    mesh = normalize_mesh(mesh, x_rotation=x_rotation)

    features = detect_features(mesh, planar_deg_err=cfg.planar_deg_err,
                               normal_deg_err=cfg.normal_deg_err,
                               min_area_fraction=cfg.min_area_fraction)
    regions = features.regions
    from mesh2brick.slopes.detection import iso_to_voxel_angle, match_slope_to_bricks
    for i, region in enumerate(regions):
        voxel_angle = iso_to_voxel_angle(region.slope_angle)
        matched = match_slope_to_bricks(voxel_angle)
        s_min = None
        if matched and region.length > 0 and region.width > 0:
            s_min = min(max(b['length'] / region.length, b['width'] / region.width) for b in matched)
        
        print(f"  Region {i}: dir={region.slope_direction}, iso_angle={region.slope_angle:.1f}°, "
              f"voxel_angle={voxel_angle:.1f}°, length={region.length:.3f}, width={region.width:.3f}, "
              f"s_min={s_min}, matched_angles={[b['angle'] for b in matched[:3]]}")
    optimal_scale, assignments = compute_optimal_scale(
        regions, default_scale=resolution,
    )
    s = int(optimal_scale)
    world_dim = (s, s, s * 3)
    print(f"  Regions: {len(regions)}, Assignments: {len(assignments)}, "
          f"Scale: {optimal_scale:.1f}, World dim: {world_dim}")

    # Deformation (or just scale if no slopes)
    energy = 0.0
    if assignments:
        result = deform_mesh(mesh, scale=optimal_scale, assignments=assignments, flat_planes=features.planes)
        triangles = np.asarray(mesh.triangles)

        # Diagnostic: compare deformed vs simply-scaled positions
        scaled_verts = np.asarray(mesh.vertices) * optimal_scale
        deformed_verts = result.deformed_vertices
        displacement = deformed_verts - scaled_verts
        disp_norms = np.linalg.norm(displacement, axis=1)
        n_moved = np.sum(disp_norms > 1e-6)
        print(f"  Split vertices (index+positional): {len(result.split_vertices)}")
        print(f"  Flat planes: {len(result.flat_planes)}")
        print(f"  Vertices moved: {n_moved}/{len(deformed_verts)}")
        print(f"  Max displacement: {disp_norms.max():.4f}")
        print(f"  Mean displacement (moved only): {disp_norms[disp_norms > 1e-6].mean():.4f}" if n_moved > 0 else "  No vertices moved")

        mesh = o3d.geometry.TriangleMesh()
        mesh.vertices = o3d.utility.Vector3dVector(result.deformed_vertices)
        mesh.triangles = o3d.utility.Vector3iVector(triangles)
        mesh.compute_vertex_normals()
        energy = result.final_energy
        print(f"  Deformation energy: {energy:.4f}")
    else:
        mesh = apply_scale(mesh, optimal_scale)
        print("  No slopes — using apply_scale only")

    # Z-scale for plate height compensation
    vertices = np.asarray(mesh.vertices)
    vertices[:, 2] *= 3.0
    mesh.vertices = o3d.utility.Vector3dVector(vertices)

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
        voxel_origin = np.asarray(voxel_grid.origin)
        slope_bricks, remaining_voxels = place_slope_bricks(
            voxels, mesh, assignments, voxel_origin=voxel_origin)
        print(f"  Slope bricks placed: {len(slope_bricks)}")
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
                        default="objaverse/assets/8ccdacecef714a4bb1e7eaa7075695c7.glb",
                        help="Path to input GLB file")
    parser.add_argument("-o", "--output-dir", default="objaverse/assets/slope_test/",
                        help="Output directory for LDR files")
    parser.add_argument("--resolution", type=int, default=20,
                        help="Target resolution (default 20)")
    parser.add_argument("--x-rotation", type=float, default=90.0,
                        help="X rotation in degrees (default 90.0)")
    
    _defaults = SlopeConfig()
    parser.add_argument("--planar-deg-err", type=float, default=_defaults.planar_deg_err,
                        help=f"Faces within this angle of horizontal/vertical are excluded (default {_defaults.planar_deg_err})")
    parser.add_argument("--normal-deg-err", type=float, default=_defaults.normal_deg_err,
                        help=f"Max angular difference for BFS grouping (default {_defaults.normal_deg_err})")
    parser.add_argument("--min-area-fraction", type=float, default=_defaults.min_area_fraction,
                        help=f"Minimum region area as fraction of total mesh area (default {_defaults.min_area_fraction})")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    model_id = Path(args.mesh).stem

    # Run both pipelines
    baseline = run_baseline(args.mesh, args.resolution)
    print()
    cfg = SlopeConfig(
        planar_deg_err=args.planar_deg_err,
        normal_deg_err=args.normal_deg_err,
        min_area_fraction=args.min_area_fraction
    )
    deformed = run_deformed(args.mesh, args.resolution, x_rotation=args.x_rotation, cfg=cfg)

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
