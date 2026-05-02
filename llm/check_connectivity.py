#!/usr/bin/env python
"""
Check a brick structure for parse errors, collisions, and floating bricks.

Usage:
    python llm/check_connectivity.py structure.txt
    cat structure.txt | python llm/check_connectivity.py
"""
import json
import sys

import networkx as nx

from mesh2brick.data.brick_structure import BrickStructure, ConnectivityBrickStructure


def check(txt: str) -> dict:
    try:
        bs = BrickStructure.from_txt(txt)
    except ValueError as e:
        return {"valid": False, "error": str(e)}
    except IndexError as e:
        return {"valid": False, "error": f"Brick out of bounds: {e}"}

    floating = [str(b) for b in bs.bricks if bs.brick_floats(b)]

    # Build connectivity graph (only if no collisions, to avoid add_brick errors)
    n_components = None
    if not bs.has_collisions():
        cbs = ConnectivityBrickStructure((bs.world_dim,) * 3)
        for brick in bs.bricks:
            cbs.add_brick(brick)
        n_components = nx.number_connected_components(cbs.connection_graph)

    return {
        "valid": True,
        "n_bricks": len(bs.bricks),
        "has_collisions": bool(bs.has_collisions()),
        "has_floating_bricks": bool(bs.has_floating_bricks()),
        "floating_bricks": floating,
        "n_components": n_components,  # 1 = fully connected, >1 = disconnected pieces
    }


if __name__ == "__main__":
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            txt = f.read()
    else:
        txt = sys.stdin.read()

    print(json.dumps(check(txt), indent=2))
