import argparse
import io
import sys
from pathlib import Path
from multiprocessing import Process, Queue, Pipe

SCRIPT_DIR = Path(__file__).parent.parent  # scripts/ -> objaverse/
ASSETS_DIR = SCRIPT_DIR / "assets"


def _process_baseline(file_path: Path, resolution: int):
    """Standard Mesh2Brick pipeline without slopes."""
    from mesh2brick.mesh2brick import Mesh2Brick

    converter = Mesh2Brick(world_dim=(resolution, resolution, resolution * 3))
    bricks = converter(str(file_path))
    return bricks


def _process_with_slopes(file_path: Path, resolution: int):
    """Slope detection + deformation + tiling pipeline."""
    import numpy as np
    import open3d as o3d
    from mesh2brick.mesh2brick import normalize_mesh
    from mesh2brick.slopes import prepare_slopes, place_slope_bricks, SlopeConfig
    from mesh2brick.voxel2brick import voxel2brick

    # Load and normalize mesh
    mesh = o3d.io.read_triangle_mesh(str(file_path))
    mesh = normalize_mesh(mesh, x_rotation=90.0)

    # Slope detection and deformation
    cfg = SlopeConfig()
    slope_result = prepare_slopes(mesh, resolution=resolution, cfg=cfg)

    # Log slope detection results
    n_regions = len(slope_result.regions)
    n_assignments = len(slope_result.assignments)
    print(f"Slope detection: {n_regions} regions, {n_assignments} assignments, scale={slope_result.scale:.1f}")

    if n_assignments > 0:
        if slope_result.deformation:
            print(f"Deformation energy: {slope_result.deformation.final_energy:.4f}")
        print(f"Adjusted world_dim: {slope_result.world_dim}")

    # Voxelize the prepared mesh
    voxel_grid = o3d.geometry.VoxelGrid.create_from_triangle_mesh(slope_result.mesh, 1.0)
    voxels = np.zeros(slope_result.world_dim, dtype=np.uint8)
    for voxel in np.asarray(voxel_grid.get_voxels()):
        idx = tuple(np.floor(voxel.grid_index).astype(int))
        if all(0 <= i < d for i, d in zip(idx, slope_result.world_dim)):
            voxels[idx] = 1

    print(f"Voxelized: {voxels.sum()} filled voxels")

    # Place slope bricks if detected
    if slope_result.assignments:
        voxel_origin = np.asarray(voxel_grid.origin)
        slope_bricks, remaining_voxels = place_slope_bricks(
            voxels, slope_result.mesh, slope_result.assignments,
            voxel_origin=voxel_origin
        )
        print(f"Slope bricks placed: {len(slope_bricks)}")
    else:
        slope_bricks = []
        remaining_voxels = voxels
        print("No slopes detected - using standard bricks only")

    # Convert remaining voxels to standard bricks
    bricks = voxel2brick(remaining_voxels)

    # Add slope bricks to structure
    for brick in slope_bricks:
        bricks.add_brick(brick)

    return bricks


def process_single_file(file_path: Path, resolution: int, res_dir: Path, result_queue: Queue, stdout_conn, enable_slopes: bool = True):
    """Worker that captures all stdout and sends it back to the parent via a pipe."""
    captured = io.StringIO()
    sys.stdout = captured
    try:
        if enable_slopes:
            bricks = _process_with_slopes(file_path, resolution)
        else:
            bricks = _process_baseline(file_path, resolution)

        txt_output_path = res_dir / file_path.with_suffix(".txt").name
        with open(txt_output_path, "w") as f:
            f.write(bricks.to_txt())

        ldr_output_path = res_dir / file_path.with_suffix(".ldr").name
        with open(ldr_output_path, "w") as f:
            f.write(bricks.to_ldr())

        result_queue.put(("SUCCESS", file_path.name, ldr_output_path.name))
    except Exception as e:
        result_queue.put(("FAILED", file_path.name, str(e)))
    finally:
        sys.stdout = sys.__stdout__
        stdout_conn.send(captured.getvalue())
        stdout_conn.close()


class TeeWriter:
    """Write to both stdout and a log file."""
    def __init__(self, log_file, original_stdout):
        self.log_file = log_file
        self.original_stdout = original_stdout

    def write(self, text):
        self.original_stdout.write(text)
        self.log_file.write(text)

    def flush(self):
        self.original_stdout.flush()
        self.log_file.flush()


def convert_objaverse_assets(resolution: int, output_dir: str = None, timeout: int = None, enable_slopes: bool = True, assets_dir: str = None):
    input_dir = Path(assets_dir) if assets_dir else ASSETS_DIR
    if not input_dir.exists():
        print(f"Directory not found: {input_dir}")
        return

    glb_files = sorted(input_dir.glob("*.glb"))
    print(f"Found {len(glb_files)} files in {input_dir}")

    if output_dir:
        res_dir = Path(output_dir)
    else:
        res_dir = ASSETS_DIR / f"res_{resolution}"
    res_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {res_dir}")

    log_path = res_dir / "logs.txt"
    log_file = open(log_path, "w")
    tee = TeeWriter(log_file, sys.stdout)

    for file_path in glb_files:
        filename = file_path.name
        tee.write(f"Converting {filename}...\n")
        tee.flush()

        result_queue = Queue()
        parent_conn, child_conn = Pipe(duplex=False)
        p = Process(target=process_single_file, args=(file_path, resolution, res_dir, result_queue, child_conn, enable_slopes))
        p.start()
        child_conn.close()
        p.join(timeout=timeout)

        if p.is_alive():
            p.terminate()
            p.join()
            tee.write(f"SKIPPED {filename}: Timed out after {timeout // 60} minutes\n")
        else:
            # Read captured stdout from subprocess
            if parent_conn.poll():
                subprocess_output = parent_conn.recv()
                if subprocess_output.strip():
                    tee.write(subprocess_output)
                    if not subprocess_output.endswith('\n'):
                        tee.write('\n')

            if not result_queue.empty():
                status, name, detail = result_queue.get()
                if status == "SUCCESS":
                    tee.write(f"Saved to {res_dir.name}/{detail}\n")
                else:
                    tee.write(f"FAILED to convert {name} at resolution {resolution}: {detail}\n")
            else:
                tee.write(f"FAILED to convert {filename}: Unknown error (no result returned)\n")

        parent_conn.close()
        tee.flush()

    log_file.close()
    print(f"Logs saved to {log_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert Objaverse assets to LEGO bricks.")
    parser.add_argument("--resolution", type=int, default=20, help="Voxel resolution (default: 20)")
    parser.add_argument("--assets-dir", type=str, default=None, help="Input directory containing .glb files (default: assets/)")
    parser.add_argument("--output_dir", type=str, default=None, help="Output directory (default: assets/res_<resolution>)")
    parser.add_argument("--timeout", type=int, default=None, help="Timeout in seconds per file (default: no timeout)")
    parser.add_argument("--enable-slopes", action="store_true", default=True, help="Enable slope detection and brick placement (default: True)")
    parser.add_argument("--disable-slopes", action="store_true", help="Disable slopes (use baseline pipeline only)")
    args = parser.parse_args()

    enable_slopes = args.enable_slopes and not args.disable_slopes
    convert_objaverse_assets(args.resolution, args.output_dir, args.timeout, enable_slopes, args.assets_dir)
