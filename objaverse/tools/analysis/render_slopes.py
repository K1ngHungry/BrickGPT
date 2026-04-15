import os
import subprocess
from pathlib import Path
import argparse

SCRIPT_DIR = Path(__file__).parent.parent.parent.resolve()  # tools/visualization/ -> objaverse/
ASSETS_DIR = SCRIPT_DIR / "assets"
SLOPE_BUILDINGS_DIR = SCRIPT_DIR / "experiments" / "slopes" / "buildings"


def render_slopes(force_all=False):
    if not SLOPE_BUILDINGS_DIR.exists():
        print(f"Error: directory not found at {SLOPE_BUILDINGS_DIR}")
        return

    # Find all .ldr files in slope_buildings directory
    ldr_files = sorted(list(SLOPE_BUILDINGS_DIR.glob("*.ldr")))
    print(f"Found {len(ldr_files)} LDR files in {SLOPE_BUILDINGS_DIR} to check for rendering.")

    # Prepare environment with local ldraw library
    env = os.environ.copy()
    ldraw_path = SCRIPT_DIR.parent / "ldraw"
    if ldraw_path.exists():
        env["LDRAW_LIBRARY_PATH"] = str(ldraw_path)

    count = 0

    for ldr_path in ldr_files:
        png_path = ldr_path.with_suffix(".png")

        if png_path.exists() and not force_all:
            print(f"[SKIP] {png_path.name}")
            continue

        print(f"[RENDER] {ldr_path.name}...")

        cmd = [
            "uv", "run", "render_bricks",
            "--in_file", str(ldr_path),
            "--out_file", str(png_path)
        ]

        try:
            subprocess.run(cmd, check=True, cwd=SCRIPT_DIR.parent, env=env, stdout=subprocess.DEVNULL)
            print(f"  -> Success")
            count += 1
        except subprocess.CalledProcessError as e:
            print(f"  -> FAILED: {e}")
        except KeyboardInterrupt:
            print("\nAborted by user.")
            return

    print(f"\nRendered {count} new images.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Render slope buildings LDR files to PNG.")
    parser.add_argument("--force", action="store_true", help="Force re-rendering of existing PNGs")
    args = parser.parse_args()

    render_slopes(force_all=args.force)
