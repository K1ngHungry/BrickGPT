import argparse
import io
import sys
from pathlib import Path
from multiprocessing import Process, Queue, Pipe

SCRIPT_DIR = Path(__file__).parent
ASSETS_DIR = SCRIPT_DIR / "assets"


def process_single_file(file_path: Path, resolution: int, res_dir: Path, result_queue: Queue, stdout_conn):
    """Worker that captures all stdout and sends it back to the parent via a pipe."""
    captured = io.StringIO()
    sys.stdout = captured
    try:
        from mesh2brick.mesh2brick import Mesh2Brick

        converter = Mesh2Brick(world_dim=(resolution, resolution, resolution * 3))
        bricks = converter(str(file_path))

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


def convert_objaverse_assets(resolution: int, output_dir: str = None, timeout: int = None):
    if not ASSETS_DIR.exists():
        print(f"Directory not found: {ASSETS_DIR}")
        return

    glb_files = sorted(ASSETS_DIR.glob("*.glb"))
    print(f"Found {len(glb_files)} files in {ASSETS_DIR}")

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
        p = Process(target=process_single_file, args=(file_path, resolution, res_dir, result_queue, child_conn))
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
    parser.add_argument("--output_dir", type=str, default=None, help="Output directory (default: assets/res_<resolution>)")
    parser.add_argument("--timeout", type=int, default=None, help="Timeout in seconds per file (default: no timeout)")
    args = parser.parse_args()

    convert_objaverse_assets(args.resolution, args.output_dir, args.timeout)
