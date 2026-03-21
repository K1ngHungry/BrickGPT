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
from mesh2brick.mesh_deformation import deform_mesh, apply_scale
from mesh2brick.slope_detection import detect_slopes, compute_optimal_scale
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


def run_deformed(mesh_path: str, resolution: int) -> dict:
    """Deformation pipeline — detect slopes, deform, then standard voxel2brick."""
    print("=" * 60)
    print("DEFORMED (slope detection + deformation + standard voxel2brick)")
    print("=" * 60)
    t0 = time.time()

    mesh = o3d.io.read_triangle_mesh(mesh_path)
    mesh = normalize_mesh(mesh)

    # Slope detection on isotropic mesh
    regions = detect_slopes(mesh)
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
        result = deform_mesh(mesh, scale=optimal_scale, assignments=assignments)
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

    # Voxelize directly at voxel_size=1.0 (mesh is already at stud-scale)
    voxel_grid = o3d.geometry.VoxelGrid.create_from_triangle_mesh(mesh, 1.0)
    voxels = np.zeros(world_dim, dtype=np.uint8)
    for voxel in np.asarray(voxel_grid.get_voxels()):
        idx = tuple(np.floor(voxel.grid_index).astype(int))
        if all(0 <= i < d for i, d in zip(idx, world_dim)):
            voxels[idx] = 1
    print(f"  Voxelized: {voxels.sum()} filled voxels")

    # Standard voxel2brick (no slope tiling)
    bricks = voxel2brick(voxels)
    elapsed = time.time() - t0

    return {
        "bricks": bricks,
        "time": elapsed,
        "label": "deformed",
        "scale": optimal_scale,
        "n_regions": len(regions),
        "n_assignments": len(assignments),
        "energy": energy,
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
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    model_id = Path(args.mesh).stem

    # Run both pipelines
    baseline = run_baseline(args.mesh, args.resolution)
    print()
    deformed = run_deformed(args.mesh, args.resolution)

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


if __name__ == "__main__":
    main()
