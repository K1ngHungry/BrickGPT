import argparse
import os
from pathlib import Path
from multiprocessing import Process, Queue

SCRIPT_DIR = Path(__file__).parent
OBJAVERSE_DIR = SCRIPT_DIR / "assets"


def process_single_file(file_path: Path, resolution: int, res_dir: Path, result_queue: Queue):
    """
    Worker function that runs in a separate process.
    Imports are done inside to avoid pickle issues.
    """
    try:
        from mesh2brick.mesh2brick import Mesh2Brick
        
        converter = Mesh2Brick(world_dim=(resolution, resolution, resolution * 3))
        bricks = converter(str(file_path))
        
        # 1. Save TXT
        txt_output_path = res_dir / file_path.with_suffix(".txt").name
        txt_content = bricks.to_txt()
        with open(txt_output_path, "w") as f:
            f.write(txt_content)
        
        # 2. Save LDR
        ldr_output_path = res_dir / file_path.with_suffix(".ldr").name
        ldr_content = bricks.to_ldr()
        with open(ldr_output_path, "w") as f:
            f.write(ldr_content)
        
        result_queue.put(("SUCCESS", file_path.name, ldr_output_path.name))
    except Exception as e:
        result_queue.put(("FAILED", file_path.name, str(e)))

def convert_objaverse_assets(resolution: int, output_dir: str = None):
    if not OBJAVERSE_DIR.exists():
        print(f"Directory not found: {OBJAVERSE_DIR}")
        return

    glb_files = list(OBJAVERSE_DIR.glob("*.glb"))
    print(f"Found {len(glb_files)} files in {OBJAVERSE_DIR}")

    print(f"\n--- Processing resolution: {resolution} ---")
    
    # Create output directory
    if output_dir:
        res_dir = SCRIPT_DIR / output_dir
    else:
        res_dir = OBJAVERSE_DIR / f"res_{resolution}"
    
    res_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {res_dir}")

    for file_path in glb_files:
        filename = file_path.name
        print(f"Converting {filename}...")
        
        result_queue = Queue()
        p = Process(target=process_single_file, args=(file_path, resolution, res_dir, result_queue))
        p.start()
        p.join(timeout=TIMEOUT_SECONDS)
        
        if p.is_alive():
            # Process is still running after timeout - kill it
            p.terminate()
            p.join()  # Wait for it to actually terminate
            print(f"SKIPPED {filename}: Timed out after {TIMEOUT_SECONDS // 60} minutes")
        else:
            # Process finished - check the result
            if not result_queue.empty():
                status, name, detail = result_queue.get()
                if status == "SUCCESS":
                    print(f"Saved to {res_dir.name}/{detail}")
                else:
                    print(f"FAILED to convert {name} at resolution {resolution}: {detail}")
            else:
                print(f"FAILED to convert {filename}: Unknown error (no result returned)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert Objaverse assets to LEGO bricks.")
    parser.add_argument("--resolution", type=int, default=20, help="Voxel resolution (world_dim)")
    parser.add_argument("--output_dir", type=str, default=None, help="Directory to save output files")
    parser.add_argument("--timeout", type=int, default=None, help="Timeout in seconds per file (default: no timeout)")
    args = parser.parse_args()

    convert_objaverse_assets(args.resolution, args.output_dir, args.timeout)
