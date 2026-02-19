# Objaverse Evaluation

Scripts to download 3D models from Objaverse, convert them into LEGO brick structures using `mesh2brick`, and visualize the results.

## Pipeline

### 1. Download Assets

```bash
uv run python objaverse/download_obj.py
```

Downloads models from `objaversepp_small.csv` into `assets/`.

### 2. Convert to Bricks

```bash
uv run python objaverse/mesh2brick_objaverse.py --resolution 20 --timeout 600
```

Converts all `.glb` files in `assets/` to `.txt` and `.ldr` files in `assets/res_<resolution>/`.

### 3. Render

```bash
uv run python objaverse/render_objaverse.py
```

Renders all `.ldr` files in `assets/` to `.png`. Use `--force` to re-render existing images.

### 4. Metrics

```bash
uv run python objaverse/update_metrics.py
```

Generates `results/comparison_metrics.html` from logs in `assets/res_*/logs.txt`.

### 5. Gallery

```bash
uv run python objaverse/generate_gallery.py
```

Generates `results/gallery.html` comparing original models with LEGO conversions.

## Directory Structure

```
objaverse/
├── assets/              # Source .glb models + res_* output dirs
├── results/             # gallery.html, comparison_metrics.html
├── mesh2brick_objaverse.py
├── render_objaverse.py
├── update_metrics.py
├── generate_gallery.py
└── download_obj.py
```
