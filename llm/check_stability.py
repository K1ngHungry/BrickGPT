#!/usr/bin/env python
"""
Check structural stability of a brick structure.

Usage:
    python llm/check_stability.py llm/outputs/<name>.txt
    cat structure.txt | python llm/check_stability.py
"""
import json
import sys

import numpy as np

from mesh2brick.data.brick_structure import BrickStructure


def check(txt: str) -> dict:
    try:
        bs = BrickStructure.from_txt(txt)
    except ValueError as e:
        return {"valid": False, "error": str(e)}
    except IndexError as e:
        return {"valid": False, "error": f"Brick out of bounds: {e}"}

    if bs.has_collisions():
        return {"valid": False, "error": "Structure has colliding bricks — fix collisions before checking stability."}
    if bs.has_floating_bricks():
        return {"valid": False, "error": "Structure has floating bricks — fix floating bricks before checking stability."}

    try:
        scores = bs.stability_scores()
    except Exception as e:
        return {"valid": True, "error": f"Stability solver failed: {e}"}

    scores = np.asarray(scores)
    return {
        "valid": True,
        "is_stable": bool(bs.is_stable()),
        "max_score": round(float(scores.max()), 3),
        "mean_score": round(float(scores.mean()), 3),
        "brick_scores": [
            {"brick": str(brick), "score": round(float(scores[brick.slice].max()), 3)}
            for brick in bs.bricks
        ],
    }


if __name__ == "__main__":
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            txt = f.read()
    else:
        txt = sys.stdin.read()

    print(json.dumps(check(txt), indent=2))
