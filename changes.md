# Changelog - Variable Brick Heights & Refactoring

This document details all changes made to support variable brick heights (e.g., plates, tall bricks) and refactor the `Brick` class to use standardized `l`, `w`, `h` dimensions.

## 1. Data Structures

### `src/mesh2brick/data/brick_structure.py`

#### `Brick` Class

- **Attributes**:
  - Renamed `h` (horizontal dimension) -> `l` (Length).
  - Renamed `height` (vertical dimension) -> `h` (Height).
- **Properties**:
  - `slice`: Updated to return a 3D slice `(x_slice, y_slice, slice(z, z+h))` instead of `(x_slice, y_slice, z_int)`.
  - `brick_id`: Now passes `l, w, h` to `dimensions_to_brick_id`.
  - `ori`: Logic updated to use `l` and `w` (`1` if `l > w` else `0`).
- **Methods**:
  - `from_json()`: Updated to unpack 3 dimensions (`l, w, h`) from library.
  - `from_txt()`: Updated regex to parse `LxWxH` format.
  - `from_ldr()`: Updated to unpack 3 dimensions.

#### `BrickStructure` Class

- **Methods**:
  - `brick_floats()`: Updated "supported from above" check to use `z + h` (top of brick) instead of `z + 1`.

#### `ConnectivityBrickStructure` Class

- **Methods**:
  - `add_brick()`:
    - **Vertical Neighbors**: Updated top check to look at `z + h` instead of `z + 1`.
    - **Horizontal Neighbors**: Updated to loop through **all Z-layers** occupied by the brick (`range(z, z+h)`) to find side-by-side neighbors, instead of just the bottom layer.

## 2. Core Logic

### `src/mesh2brick/voxel2brick.py`

#### Helper Functions

- `valid_brick(l, w, h)`:
  - Added `h` parameter.
  - Removed hardcoded check for `height == 3`.
  - Now verifies existence of dimensions `(l, w, h)` in `brick_library`.
- `get_merged_brick(b1, b2)`:
  - Added strict equality check `b1.h == b2.h` (only merge same-height bricks).
  - Preserves height in the new merged brick instatiation.

#### `Voxel2Brick` Class

- `_brickify_layer_greedy()`:
  - Added `allowed_heights` argument (default `(3,)` for backward compatibility).
  - Updated candidate generation loop to iterate over `allowed_heights`.
  - Updated `Brick` instantiation to pass `h` explicitly.
- `_brickify_voxels_greedy()`:
  - Added `allowed_heights` argument and passes it down.

## 3. Optimization & Analysis

### `src/mesh2brick/stability_analysis/utils.py`

- `construct_world_grid()`:
  - Added inner loop `for k in range(brick_z, brick_z + brick_h)`.
  - This fills voxels for the entire volume of the brick.
  - Stores `int(brick_key)` (ID) in the grid instead of just `1`.

### `src/mesh2brick/stability_analysis/stability_analysis.py`

- `stability_score()`:
  - **Variable Renaming**: Used `l` for length, `w` for width, `h` for height to support variable dimensions clearly.
  - **Volume Iteration**: Updated main force loop to iterate over the full 3D volume (`z` to `z+h`) to capture all horizontal connections.
  - **Neighbor Discovery**:
    - **Horizontal**: Checks `world_grid != 0` to detect neighbors. Uses `force_dict` keys to link force variables between adjacent voxels.
    - **Vertical**: Checks connections at the top (`z+h`) and bottom (`z`) faces.

## 4. Tests

### `src/mesh2brick/tests/test_brick_structure.py`

- Updated usage example strings to `LxWxH` format (e.g., `2x6x3`).
- Updated `test_brick` assertions to check `brick.h`, `brick.l` property names.
- Updated `test_brick` assertion for `slice` to expect a 3-tuple `(slice, slice, slice)`.

### `src/mesh2brick/tests/test_stability.py`
- Added 3D connectivity tests for tall bricks.

## 5. Comparison with Upstream

This implementation diverges from the standard "Upstream" (which assumed uniform brick height, typically 3 units) in several critical ways to support arbitrary heights (l, w, h).

### Architectural Differences

| Feature                 | Upstream (Uniform Height)          | Current (Variable Height)                      |
| :---------------------- | :--------------------------------- | :--------------------------------------------- |
| **Voxel Slice**         | 2D slices at `z` elevation.        | 3D slices using `range(z, z+h)`.               |
| **Collision Detection** | Checked only at the placement `z`. | Checks the entire vertical volume `[z : z+h]`. |
| **Neighbor Graphs**     | Connections only at `z` and `z+1`. | Connections at any layer within `[z : z+h]`.   |
| **Brick Identity**      | Mapped by `(l, w)`.                | Mapped by `(l, w, h)`.                         |

### Algorithmic Changes

#### 1. voxel2brick

- **Upstream**: Iterated layer-by-layer and filled a 2D plane.
- **Current**: While still iterating by `z`, the placement logic considers the brick's **height** during validity checks. A brick placed at `z` with `h=3` now effectively removes voxels at `z+1` and `z+2` from the search space of subsequent iterations. This prevents vertical overlapping of plates and bricks.

#### 2. stability_analysis

- **Volume Integration**: In the original algorithm, side-forces were calculated once per brick because it only occupied one layer. Now, we iterate through the entire **lateral surface area** of the brick volume ($2 \times (l+w) \times h$ voxels).
- **Connectivity Mapping**:
  - **Upstream**: A neighbor was always at exactly the same `z` or `z+1`.
  - **Current**: A neighbor can be adjacent to _any_ of the `h` layers of a brick. The `stability_analysis.py` now loops through `z_offset` from `0` to `h-1` to detect these contacts.
- **Force Equilibrium**:
  - Sum of forces ($\sum F_x, \sum F_y, \sum F_z$) and torques are now computed by aggregating connections across the entire 3D boundary of the brick.
  - **Simplification**: Per user request, torque lever arms for side-forces are currently standardized to `brick_unit_height / 2`, matching the upstream simplification while still accounting for the increased number of connection points provided by the extra height.

#### 3. Data Parsing

- **JSON/Txt/LDR**: All importers have been upgraded from 2-tuple parsing `(l, w)` to 3-tuple parsing `(l, w, h)`. The regex for TXT files now specifically looks for the `LxWxH` pattern.
