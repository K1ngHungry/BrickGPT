# Objaverse Evaluation

Scripts and tools to download 3D models from Objaverse, convert them into LEGO brick structures using `mesh2brick`, analyze results, and visualize slope detection.

The tools are organized into:
- **Pipeline scripts** (`scripts/`) - Main conversion workflow
- **Analysis tools** (`tools/analysis/`) - Metrics, galleries, visualization, and rendering
- **Debug tools** (`tools/debug/`) - Diagnostic utilities for development

## Quick Start

### Basic Pipeline

1. **Download models:**
   ```bash
   uv run python objaverse/scripts/download_obj.py \
     objaverse/data/datasets/top-20-single-objects.csv \
     objaverse/data/meshes/general \
     -n 20
   ```

2. **Convert to bricks:**
   ```bash
   # Minimal (uses defaults)
   cd objaverse
   uv run python scripts/mesh2brick_objaverse.py --assets-dir data/meshes/general

   # With custom options
   uv run python scripts/mesh2brick_objaverse.py \
     --assets-dir data/meshes/general \
     --resolution 20 \
     --timeout 600
   ```

3. **Render to images:**
   ```bash
   uv run python objaverse/tools/analysis/render_objaverse.py \
     --input-dir objaverse/assets/current/res_20
   ```

4. **Generate gallery:**
   ```bash
   uv run python objaverse/tools/analysis/generate_gallery.py \
     --assets-dir objaverse/assets/current \
     -o objaverse/results/gallery.html
   ```

## Tools

### Pipeline Scripts (`scripts/`)

#### `mesh2brick_objaverse.py`
Main conversion pipeline: GLB → LEGO bricks (LDR + TXT).

**Minimal usage:**
```bash
cd objaverse
uv run python scripts/mesh2brick_objaverse.py --assets-dir data/meshes/general
# Output: assets/res_20/ (default)
```

**With custom options:**
```bash
uv run python scripts/mesh2brick_objaverse.py \
  --assets-dir data/meshes/general \
  --resolution 32 \
  --timeout 600 \
  --output_dir assets/my_output
```

**Options:**
- `--resolution` - Voxel resolution (default: **20**)
- `--assets-dir` - Input directory with `.glb` files (default: **assets/**)
- `--output_dir` - Output directory (default: **assets/res_\<resolution\>**)
- `--timeout` - Timeout in seconds per file (default: **none**)
- `--enable-slopes` - Enable slope detection (default: **True**)
- `--disable-slopes` - Disable slopes (use baseline only)

#### `download_obj.py`
Download 3D models from Objaverse using a CSV file.

```bash
uv run python objaverse/scripts/download_obj.py \
  objaverse/data/datasets/top-20-single-objects.csv \
  objaverse/data/meshes/general \
  -n 20
```

**Arguments:**
- `csv_path` - Path to CSV file with UID column
- `output_dir` - Destination directory (default: `assets`)
- `-n, --max-count` - Max number to download (default: 15)

### Analysis Tools (`tools/analysis/`)

#### `visualize_slopes.py`
Generate interactive HTML gallery showing slope detection results with colored 3D models.

```bash
uv run python objaverse/tools/analysis/visualize_slopes.py \
  --assets-dir objaverse/data/meshes/buildings \
  --results-dir objaverse/experiments/slopes/buildings \
  -o objaverse/results/slope_gallery.html \
  -s
```

**Options:**
- `--assets-dir` - Input GLB directory (default: `data/meshes/buildings`)
- `--results-dir` - Results with logs.txt (default: `experiments/slopes/buildings`)
- `-o, --output` - Output HTML path (default: `results/slope_gallery.html`)
- `-s, --run-detection` - Re-run slope detection (exports colored meshes)
- `--min-area` - Min region area fraction (default: 0.01)
- `--normal-err` - Max angle for BFS grouping (default: 1.0°)
- `--planar-err` - Max angle for horizontal/vertical exclusion (default: 10.0°)

**Output:**
- Colored meshes (if `-s` used): `experiments/slopes/detection/*.glb`
- HTML gallery: Specified by `-o` flag

#### `render_objaverse.py`
Render `.ldr` files to `.png` images using the render_bricks tool.

```bash
uv run python objaverse/tools/analysis/render_objaverse.py \
  --input-dir objaverse/assets/current/mesh-results \
  --force
```

**Options:**
- `--input-dir` - Directory with `.ldr` files (default: `assets/current/mesh-results`)
- `--force` - Re-render existing PNGs

#### `render_slopes.py`
Render slope-specific `.ldr` files to `.png`.

```bash
uv run python objaverse/tools/analysis/render_slopes.py --force
```

**Options:**
- `--force` - Re-render existing PNGs

**Default input:** `experiments/slopes/buildings/`

#### `detect_slopes.py`
Standalone slope detection tool - exports colored meshes showing slope regions.

```bash
uv run python objaverse/tools/analysis/detect_slopes.py \
  input.glb \
  output_slopes.glb \
  --full-mesh output_full.glb \
  --deformed-slopes deformed_slopes.glb \
  --resolution 20
```

**Arguments:**
- `input` - Input mesh file (GLB, OBJ, STL, etc.)
- `output` - Output mesh with slope regions only
- `--full-mesh` - Optional: full mesh with slopes colored
- `--deformed-slopes` - Optional: deformed slope regions
- `--deformed-full` - Optional: deformed full mesh with slopes colored
- `--resolution` - Target resolution for deformation (default: 20)
- `--x-rotation` - X rotation in degrees (default: 90.0)

#### `update_metrics.py`
Generate comparison metrics HTML from conversion logs.

```bash
uv run python objaverse/tools/analysis/update_metrics.py \
  --resolutions 20 32 \
  --assets-dir objaverse/assets/current \
  --meshes-dir objaverse/data/meshes/general \
  -o objaverse/results/metrics.html
```

**Options:**
- `--resolutions` - Filter by specific resolutions
- `--assets-dir` - Directory with logs.txt (default: `assets`)
- `--meshes-dir` - Directory with .glb files (default: `data/meshes/general`)
- `--results-dir` - Results output directory (default: `results`)
- `-o, --output` - Output HTML path (default: `results/comparison_metrics.html`)

#### `generate_gallery.py`
Generate interactive comparison gallery with original models and LEGO conversions.

```bash
uv run python objaverse/tools/analysis/generate_gallery.py \
  --resolutions 20 \
  --assets-dir objaverse/assets/current \
  --results-dir objaverse/results \
  -o objaverse/results/gallery.html
```

**Options:**
- `--resolutions` - Filter by specific resolutions
- `--assets-dir` - Assets directory with renders (default: `assets`)
- `--results-dir` - Results directory (default: `results`)
- `-o, --output` - Output HTML path (default: `results/gallery.html`)

### Debug Tools (`tools/debug/`)

#### `debug_deformation.py`
Debug mesh deformation by comparing baseline vs. deformed mesh2brick pipelines.

```bash
uv run python objaverse/tools/debug/debug_deformation.py \
  objaverse/data/meshes/general/model.glb \
  -o objaverse/experiments/slopes/test/ \
  --resolution 20 \
  -v
```

**Arguments:**
- `mesh` - Input GLB file path (default: sample model in `data/meshes/general`)
- `-o, --output-dir` - Output directory for LDR files (default: `experiments/slopes/test/`)
- `--resolution` - Target resolution (default: 20)
- `--x-rotation` - X rotation in degrees (default: 90.0)
- `-v, --verbose` - Enable verbose output

## Directory Structure

```
objaverse/
├── README.md
├── scripts/                    # Pipeline scripts
│   ├── mesh2brick_objaverse.py # Main conversion pipeline
│   └── download_obj.py         # Download Objaverse models
├── tools/
│   ├── analysis/               # Analysis & visualization (6 tools)
│   │   ├── detect_slopes.py
│   │   ├── generate_gallery.py
│   │   ├── render_objaverse.py
│   │   ├── render_slopes.py
│   │   ├── update_metrics.py
│   │   └── visualize_slopes.py
│   └── debug/                  # Debugging utilities
│       └── debug_deformation.py
├── data/                       # Input data
│   ├── datasets/               # CSV files (model lists)
│   │   ├── objaverse_houses.csv
│   │   ├── top-20-single-objects.csv
│   │   ├── top-100-single-objects.csv
│   │   └── objaversepp_small.csv
│   ├── reference/              # Reference data (captions, etc.)
│   │   └── pali_captions.csv
│   └── meshes/
│       ├── general/            # Downloaded GLB files
│       └── buildings/          # Building-specific meshes
├── experiments/                # Experiment results
│   ├── priority/               # Priority algorithm experiments
│   │   ├── alignment-20/
│   │   ├── baseline-20/
│   │   ├── height-20/
│   │   └── ...
│   ├── slopes/                 # Slope integration experiments
│   │   ├── buildings/
│   │   ├── detection/
│   │   └── test/
│   └── archive/                # Archived experiments
├── assets/
│   └── current/                # Active working outputs
│       ├── mesh-res-20/
│       └── mesh-results/
├── results/                    # Generated visualizations
│   ├── gallery.html
│   ├── comparison_metrics.html
│   └── slope_gallery.html
└── docs/
    └── comparison_metrics.md
```

## Tool Reference

| Tool | Location | Purpose |
|------|----------|---------|
| mesh2brick_objaverse.py | scripts/ | Convert GLB → LDR bricks (main pipeline) |
| download_obj.py | scripts/ | Download models from Objaverse |
| visualize_slopes.py | tools/analysis/ | Generate slope detection gallery |
| render_objaverse.py | tools/analysis/ | Render LDR → PNG (general) |
| render_slopes.py | tools/analysis/ | Render LDR → PNG (slopes) |
| detect_slopes.py | tools/analysis/ | Standalone slope detection |
| update_metrics.py | tools/analysis/ | Generate metrics HTML |
| generate_gallery.py | tools/analysis/ | Generate comparison gallery |
| debug_deformation.py | tools/debug/ | Debug mesh deformation pipeline |

## Common Workflows

### Evaluate New Models

1. Add UIDs to a CSV in `data/datasets/`
2. Download: `python scripts/download_obj.py your_file.csv data/meshes/general`
3. Convert: `python scripts/mesh2brick_objaverse.py --assets-dir data/meshes/general`
4. Generate gallery: `python tools/analysis/generate_gallery.py`

### Slope Analysis on Buildings

1. Place building GLBs in `data/meshes/buildings/`
2. Run slope visualization:
   ```bash
   python tools/analysis/visualize_slopes.py \
     --assets-dir data/meshes/buildings \
     -s -o results/buildings_slopes.html
   ```
3. View results at `results/buildings_slopes.html`

### Debug Single Model

```bash
# Quick test on one model
python tools/debug/debug_deformation.py \
  data/meshes/general/your_model.glb \
  -v -o experiments/slopes/test/
```

## Notes

- All commands assume you're running from the project root (`brickgpt/`)
- Use `uv run` to ensure correct Python environment
- GLB files are the primary input format (downloaded from Objaverse)
- LDR files are LEGO brick structure outputs
- PNG files are rendered images of brick structures
- Results are organized by resolution (20, 32, 50, etc.)
