"""Detect slope regions in a mesh and output the mesh with slopes highlighted.

Usage:
    python objaverse/detect_slopes.py input.glb output_slopes.glb
    python objaverse/detect_slopes.py input.glb output_slopes.glb --full-mesh output_full.glb
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import open3d as o3d

# Add mesh2brick to path
# tools/analysis/ -> tools/ -> objaverse/ -> brickgpt/ -> src/mesh2brick/src
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src' / 'mesh2brick' / 'src'))

from mesh2brick.mesh2brick import normalize_mesh
from mesh2brick.slopes import SlopeConfig, prepare_slopes
from mesh2brick.slopes.detection import detect_features


def extract_slope_mesh(mesh: o3d.geometry.TriangleMesh, slope_regions: list, color_per_region: bool = True):
    """Extract only the slope region faces from the mesh.

    Args:
        mesh: Input mesh
        slope_regions: List of SlopeRegion objects from detect_features
        color_per_region: If True, color each region differently

    Returns:
        New mesh containing only slope faces
    """
    # Collect all slope face indices
    all_slope_faces = []
    region_colors = []

    # Generate distinct colors for each region
    colors = [
        [1.0, 0.0, 0.0],  # Red
        [0.0, 1.0, 0.0],  # Green
        [0.0, 0.0, 1.0],  # Blue
        [1.0, 1.0, 0.0],  # Yellow
        [1.0, 0.0, 1.0],  # Magenta
        [0.0, 1.0, 1.0],  # Cyan
        [1.0, 0.5, 0.0],  # Orange
        [0.5, 0.0, 1.0],  # Purple
    ]

    for i, region in enumerate(slope_regions):
        all_slope_faces.extend(region.face_indices)
        color = colors[i % len(colors)] if color_per_region else [0.8, 0.2, 0.2]
        region_colors.extend([color] * len(region.face_indices))

    if not all_slope_faces:
        print("No slope regions found - returning empty mesh")
        return o3d.geometry.TriangleMesh()

    # Extract triangles and vertices
    triangles = np.asarray(mesh.triangles)
    vertices = np.asarray(mesh.vertices)

    slope_triangles = triangles[all_slope_faces]

    # Remap vertex indices to only include used vertices
    used_verts = np.unique(slope_triangles)
    vert_map = {old: new for new, old in enumerate(used_verts)}
    new_triangles = np.vectorize(vert_map.get)(slope_triangles)
    new_vertices = vertices[used_verts]

    # Create new mesh
    slope_mesh = o3d.geometry.TriangleMesh()
    slope_mesh.vertices = o3d.utility.Vector3dVector(new_vertices)
    slope_mesh.triangles = o3d.utility.Vector3iVector(new_triangles)

    # Color the faces by region
    if color_per_region:
        slope_mesh.triangle_normals = o3d.utility.Vector3dVector(region_colors)
        slope_mesh.paint_uniform_color([0.5, 0.5, 0.5])  # Fallback

    slope_mesh.compute_vertex_normals()

    return slope_mesh


def colorize_full_mesh(mesh: o3d.geometry.TriangleMesh, slope_regions: list):
    """Color the full mesh with slope regions highlighted.

    Args:
        mesh: Input mesh
        slope_regions: List of SlopeRegion objects

    Returns:
        Mesh with triangle colors (slopes colored, rest gray)
    """
    # Create a deep copy by reconstructing the mesh
    colored_mesh = o3d.geometry.TriangleMesh()
    colored_mesh.vertices = mesh.vertices
    colored_mesh.triangles = mesh.triangles
    if mesh.has_triangle_normals():
        colored_mesh.triangle_normals = mesh.triangle_normals
    if mesh.has_vertex_normals():
        colored_mesh.vertex_normals = mesh.vertex_normals

    # Mark all slope faces
    n_triangles = len(colored_mesh.triangles)
    region_id = np.full(n_triangles, -1, dtype=int)  # -1 = not a slope

    for i, region in enumerate(slope_regions):
        for face_idx in region.face_indices:
            region_id[face_idx] = i

    # Generate colors for each region
    region_colors = [
        [1.0, 0.0, 0.0],  # Red
        [0.0, 1.0, 0.0],  # Green
        [0.0, 0.0, 1.0],  # Blue
        [1.0, 1.0, 0.0],  # Yellow
        [1.0, 0.0, 1.0],  # Magenta
        [0.0, 1.0, 1.0],  # Cyan
        [1.0, 0.5, 0.0],  # Orange
        [0.5, 0.0, 1.0],  # Purple
    ]

    # Assign per-triangle colors (solid colors, no gradients)
    triangle_colors = np.full((n_triangles, 3), 0.7)  # Default gray

    for tri_idx in range(n_triangles):
        rid = region_id[tri_idx]
        if rid >= 0:  # This is a slope face
            triangle_colors[tri_idx] = region_colors[rid % len(region_colors)]

    # Convert triangle colors to vertex colors (replicate each color 3 times for the triangle)
    # This creates solid-colored triangles without interpolation
    vertex_colors = []
    for tri_idx, tri in enumerate(np.asarray(colored_mesh.triangles)):
        color = triangle_colors[tri_idx]
        vertex_colors.extend([color, color, color])

    # Create a new mesh with duplicated vertices (one per triangle corner)
    # This prevents color interpolation across triangle boundaries
    new_vertices = []
    new_triangles = []

    for tri_idx, tri in enumerate(np.asarray(colored_mesh.triangles)):
        vertices = np.asarray(colored_mesh.vertices)
        # Add the three vertices for this triangle
        v0, v1, v2 = vertices[tri]
        base_idx = len(new_vertices)
        new_vertices.extend([v0, v1, v2])
        new_triangles.append([base_idx, base_idx + 1, base_idx + 2])

    # Build the new mesh
    final_mesh = o3d.geometry.TriangleMesh()
    final_mesh.vertices = o3d.utility.Vector3dVector(new_vertices)
    final_mesh.triangles = o3d.utility.Vector3iVector(new_triangles)
    final_mesh.vertex_colors = o3d.utility.Vector3dVector(vertex_colors)
    final_mesh.compute_vertex_normals()

    return final_mesh


def main():
    parser = argparse.ArgumentParser(description="Detect slope regions and output mesh")
    parser.add_argument("input", help="Input mesh file (GLB, OBJ, STL, etc.)")
    parser.add_argument("output", help="Output mesh file for slope regions only")
    parser.add_argument("--full-mesh", "-f", help="Optional: output full mesh with slopes colored")
    parser.add_argument("--deformed-slopes", "-d", help="Optional: output deformed slope regions")
    parser.add_argument("--deformed-full", help="Optional: output deformed full mesh with slopes colored")
    parser.add_argument("--resolution", "-r", type=int, default=20,
                        help="Target resolution for deformation (default: 20)")
    parser.add_argument("--x-rotation", type=float, default=90.0,
                        help="X rotation in degrees (default: 90.0)")

    # Slope detection parameters
    parser.add_argument("--planar-err", type=float, default=10.0,
                        help="Max angle for coplanar faces (default: 10.0)")
    parser.add_argument("--normal-err", type=float, default=1.0,
                        help="Max angle for BFS grouping (default: 1.0)")
    parser.add_argument("--min-area", type=float, default=0.01,
                        help="Min region area as fraction of total (default: 0.01)")

    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}")
        sys.exit(1)

    # Create output directory if needed
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Loading mesh: {input_path}")
    mesh = o3d.io.read_triangle_mesh(str(input_path))
    mesh = normalize_mesh(mesh, x_rotation=args.x_rotation)

    # Detect slopes
    print(f"\nDetecting slopes...")
    print(f"  planar_err: {args.planar_err}°")
    print(f"  normal_err: {args.normal_err}°")
    print(f"  min_area: {args.min_area}")

    cfg = SlopeConfig(
        planar_err=args.planar_err,
        normal_err=args.normal_err,
        min_area=args.min_area,
    )

    features = detect_features(
        mesh,
        planar_err=cfg.planar_err,
        normal_err=cfg.normal_err,
        min_area=cfg.min_area,
        verbose=True,
    )

    regions = features.regions

    print(f"\nFound {len(regions)} slope regions")
    for i, region in enumerate(regions):
        print(f"  Region {i}: {len(region.face_indices)} faces, "
              f"angle={region.angle:.1f}°, dir={region.direction}, "
              f"area={region.area:.4f}")

    # Extract slope mesh
    slope_mesh = extract_slope_mesh(mesh, regions, color_per_region=True)

    if len(regions) > 0:
        o3d.io.write_triangle_mesh(str(output_path), slope_mesh)
        print(f"\n✓ Saved slope regions to: {output_path}")
    else:
        print(f"\n⚠ No slopes detected - not saving output")

    # Optionally save full mesh with colored slopes
    if args.full_mesh and len(regions) > 0:
        full_mesh_path = Path(args.full_mesh)
        full_mesh = colorize_full_mesh(mesh, regions)
        o3d.io.write_triangle_mesh(str(full_mesh_path), full_mesh)
        print(f"✓ Saved full mesh with colored slopes to: {full_mesh_path}")

    # Generate deformed meshes if requested
    if (args.deformed_slopes or args.deformed_full) and len(regions) > 0:
        print(f"\nApplying mesh deformation...")

        # Run prepare_slopes to get deformed mesh
        slope_result = prepare_slopes(mesh, resolution=args.resolution, cfg=cfg)

        deformed_mesh = slope_result.mesh
        deformed_regions = slope_result.regions

        print(f"  Scale: {slope_result.scale:.1f}")
        print(f"  World dim: {slope_result.world_dim}")
        if slope_result.deformation:
            print(f"  Deformation energy: {slope_result.deformation.final_energy:.4f}")

        # Save deformed slope regions
        if args.deformed_slopes:
            deformed_slopes_path = Path(args.deformed_slopes)
            deformed_slope_mesh = extract_slope_mesh(deformed_mesh, deformed_regions, color_per_region=True)
            o3d.io.write_triangle_mesh(str(deformed_slopes_path), deformed_slope_mesh)
            print(f"✓ Saved deformed slope regions to: {deformed_slopes_path}")

        # Save deformed full mesh with colored slopes
        if args.deformed_full:
            deformed_full_path = Path(args.deformed_full)
            deformed_full_mesh = colorize_full_mesh(deformed_mesh, deformed_regions)
            o3d.io.write_triangle_mesh(str(deformed_full_path), deformed_full_mesh)
            print(f"✓ Saved deformed full mesh with colored slopes to: {deformed_full_path}")


if __name__ == "__main__":
    main()
