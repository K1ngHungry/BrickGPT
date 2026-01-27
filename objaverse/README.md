# Objaverse & Mesh2Brick Evaluation Tools

This folder contains scripts to download 3D models from Objaverse, convert them into LEGO brick structures using `mesh2brick`, and visualize the results in a comparison gallery.

## Pipeline Workflow

### 1. Download Assets

Downloads a subset of Objaverse models specified in the CSV file.

- **Script:** `download_obj.py`
- **Input:** `objaversepp_small.csv`
- **Output:** Saves `.glb` files to `assets/`.
- **Usage:**
  ```bash
  uv run objaverse/download_obj.py
  ```

### 2. Convert to Bricks

Converts all `.glb` files in the `assets/` folder into LEGO structures.

- **Script:** `mesh2brick_objaverse.py`
- **Output:** Generates `.txt` (brick list) and `.ldr` (LDraw) files in `assets/res_<resolution>/` (default) or the specified output directory.
- **Usage:**

  ```bash
  # Default (Resolution 20, Output to assets/res_20)
  uv run objaverse/mesh2brick_objaverse.py

  # Custom Resolution and Output Directory
  uv run objaverse/mesh2brick_objaverse.py --resolution 20 --output_dir path/to/output
  ```

### 3. Generate Gallery

Renders the LEGO models and creates an HTML page to compare the original 3D model vs. the LEGO conversion side-by-side.

- **Script:** `generate_gallery.py`
- **Output:**
  - Renders `.png` images in `assets/`.
  - Generates `gallery.html`.
- **Usage:**
  ```bash
  uv run objaverse/generate_gallery.py
  ```

## Directory Structure

- `assets/`: Stores source models (`.glb`).
- `assets/res_<N>/`: Stores generated results (`.ldr`, `.txt`, `.png`) for resolution N.
- `objaversepp_small.csv`: List of Objaverse UIDs to process (downloaded from Objaverse++).
