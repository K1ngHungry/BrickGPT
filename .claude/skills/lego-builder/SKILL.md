---
name: lego-builder
description: Build LEGO structures from text descriptions using the mesh2brick format. Validates with connectivity checker and renders to PNG. Use when asked to build, design, or generate a LEGO model.
---

## Overview

Build LEGO structures by writing brick layouts in the mesh2brick text format, then validating and rendering them using CLI tools. Write the structure first — do not plan or explain before acting.

**Write first, reason later.** Your first action must be to write a `.txt` file. Do not explain or plan before acting.

Prefer larger bricks (2x4, 2x6, 1x8) to fill space efficiently.

## Brick Format

One brick per line:
```
HxW (X,Y,Z)
```

| Field | Value |
|---|---|
| `HxW` | footprint in studs — see valid bricks below |
| `X,Y` | horizontal stud position; brick must fit within grid (X+H ≤ 20, Y+W ≤ 20) |
| `Z` | vertical layer, 0, 1, 2, ... (each layer is one brick tall) |

A brick `HxW (X,Y,Z)` occupies voxels `x=[X, X+H)`, `y=[Y, Y+W)`, `z=Z` (one layer thick).

## Valid Bricks

Swapping H and W is allowed (same brick, rotated).
Does NOT support comments.

| HxW | Also valid as |
|-----|--------------|
| 1x1 | — |
| 1x2 | 2x1 |
| 1x4 | 4x1 |
| 1x6 | 6x1 |
| 1x8 | 8x1 |
| 2x2 | — |
| 2x4 | 4x2 |
| 2x6 | 6x2 |

## Rules

- No two bricks may overlap
- All bricks must form a single connected structure (`n_components` must be 1)
- Only vertical stacking (studs) counts as a connection — side-by-side bricks at the same layer are not connected

## Output Structure

All files for a build go in `llm/outputs/<object>/`:
- `target_corner_fl.png` etc. — target mesh renders (provided, do not overwrite)
- `v1.txt`, `v2.txt`, ... — brick structure iterations
- `v1_corner_fl.png` etc. — renders of each iteration

## Tools

```bash
# Check for parse errors, collisions, floating bricks, and connectivity
python llm/check_connectivity.py llm/outputs/<object>/v<n>.txt

# Render 4 corner-angle PNGs
python llm/render.py llm/outputs/<object>/v<n>.txt llm/outputs/<object>/v<n>

# Check structural stability (score >= 1.0 means unstable, lower is better)
python llm/check_stability.py llm/outputs/<object>/v<n>.txt
```

## Workflow

1. Write the structure to `llm/outputs/<object>/v1.txt`
2. Always run `render` immediately after writing each version.
3. Use `check_connectivity` and `check_stability` to find and fix issues. If `target_corner_*.png` files exist in the output folder, read them and compare against your renders after each iteration — adjust proportions, silhouette, and key features to better match the target.
4. Fix connectivity errors first (`n_components == 1`), then improve stability. If stability cannot be reasonably improved, finish anyway.
5. Save each iteration to a new numbered file — do not overwrite previous versions.

## Example

A 3-brick column:
```
2x4 (0,0,0)
2x4 (0,0,1)
2x4 (0,0,2)
```
