#!/usr/bin/env python
"""
Render a brick structure (.txt) from 4 corner angles to PNG files.

Usage:
    python llm/render.py llm/outputs/<name>.txt llm/outputs/<name>
    # Produces: <name>_corner_fl.png, <name>_corner_fr.png,
    #           <name>_corner_br.png, <name>_corner_bl.png
"""
import math
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

import bpy
import mathutils

ROOT_DIR = Path(__file__).parent.parent
sys.path.append(str(ROOT_DIR))

import ImportLDraw
from ImportLDraw.loadldraw.loadldraw import Options, Configure, loadFromFile, FileSystem

VIEWS = {
    "corner_fl": (45,  20),
    "corner_fr": (135, 20),
    "corner_br": (225, 20),
    "corner_bl": (315, 20),
}


def render(txt: str, out_prefix: str, img_resolution: int = 512) -> list[str]:
    from mesh2brick.data.brick_structure import BrickStructure

    ldr = BrickStructure.from_txt(txt).to_ldr()
    with tempfile.NamedTemporaryFile(suffix=".ldr", delete=False, mode="w") as f:
        f.write(ldr)
        ldr_path = f.name

    try:
        out_paths = _render_ldr(os.path.abspath(ldr_path), out_prefix, img_resolution)
    finally:
        os.unlink(ldr_path)

    return out_paths


def _render_ldr(ldr_path: str, out_prefix: str, img_resolution: int) -> list[str]:
    plugin_path = Path(ImportLDraw.__file__).parent
    ldraw_lib_path = os.environ.get('LDRAW_LIBRARY_PATH')
    if not ldraw_lib_path or not os.path.exists(ldraw_lib_path):
        ldraw_lib_path = str(ROOT_DIR / 'ldraw')
    ldraw_lib_path = os.path.abspath(ldraw_lib_path)

    # Exact same setup as render_bricks.py
    with stdout_redirected(os.devnull):
        bpy.data.scenes[0].render.engine = 'CYCLES'
        if sys.platform == 'darwin':
            bpy.context.preferences.addons['cycles'].preferences.compute_device_type = 'METAL'
        else:
            bpy.context.preferences.addons['cycles'].preferences.compute_device_type = 'CUDA'
        bpy.context.scene.cycles.device = 'GPU'
        bpy.context.scene.cycles.samples = 512
        bpy.context.preferences.addons['cycles'].preferences.get_devices()
        for d in bpy.context.preferences.addons['cycles'].preferences.devices:
            d['use'] = 0
            if d['name'].startswith('NVIDIA') or d['name'].startswith('Apple'):
                d['use'] = 1

    bpy.ops.object.select_all(action='DESELECT')
    bpy.ops.object.select_by_type(type='MESH')
    bpy.ops.object.delete()

    Options.ldrawDirectory = ldraw_lib_path
    Options.instructionsLook = False
    Options.useLogoStuds = True
    Options.useUnofficialParts = True
    Options.gaps = True
    Options.studLogoDirectory = os.path.join(plugin_path, 'studs')
    Options.LSynthDirectory = os.path.join(plugin_path, 'lsynth')
    Options.verbose = 0
    Options.overwriteExistingMaterials = True
    Options.overwriteExistingMeshes = True
    Options.scale = 0.01
    Options.createInstances = True
    Options.removeDoubles = True
    Options.positionObjectOnGroundAtOrigin = True
    Options.flattenHierarchy = False
    Options.edgeSplit = True
    Options.addBevelModifier = True
    Options.bevelWidth = 0.5
    Options.addEnvironmentTexture = True
    Options.scriptDirectory = os.path.join(plugin_path, 'loadldraw')
    Options.addWorldEnvironmentTexture = True
    Options.addGroundPlane = True
    Options.setRenderSettings = True
    Options.removeDefaultObjects = True
    Options.positionCamera = True
    Options.cameraBorderPercent = 0.05

    Configure()
    loadFromFile(None, FileSystem.locate(ldr_path))

    bpy.context.scene.render.resolution_x = img_resolution
    bpy.context.scene.render.resolution_y = img_resolution
    bpy.context.scene.camera.data.angle = math.radians(45)
    bpy.context.scene.render.image_settings.file_format = 'PNG'

    # Derive orbit center and distance from ImportLDraw's auto-positioned camera.
    # Model is centered at (0,0) in XY; find where the camera's forward ray hits X=0.
    camera = bpy.context.scene.camera
    cam_pos = camera.location.copy()
    cam_fwd = (camera.matrix_world.to_3x3() @ mathutils.Vector((0, 0, -1))).normalized()
    t = -cam_pos.x / cam_fwd.x if abs(cam_fwd.x) > 1e-4 else -cam_pos.y / cam_fwd.y
    look_at = cam_pos + cam_fwd * t
    distance = t

    out_paths = []
    for view_name, (azimuth_deg, elevation_deg) in VIEWS.items():
        az = math.radians(azimuth_deg)
        el = math.radians(elevation_deg)
        camera.location = look_at + mathutils.Vector((
            distance * math.cos(el) * math.cos(az),
            distance * math.cos(el) * math.sin(az),
            distance * math.sin(el),
        ))
        direction = look_at - camera.location
        camera.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()

        out_path = os.path.abspath(f"{out_prefix}_{view_name}.png")
        bpy.context.scene.render.filepath = out_path
        with stdout_redirected(os.devnull):
            bpy.ops.render.render(write_still=True)
        out_paths.append(out_path)
        print(f"Rendered {view_name} -> {out_path}")

    return out_paths


@contextmanager
def stdout_redirected(to: str):
    fd = sys.stdout.fileno()

    def _redirect_stdout(to_file):
        sys.stdout.close()
        os.dup2(to_file.fileno(), fd)
        sys.stdout = os.fdopen(fd, 'w')

    with os.fdopen(os.dup(fd), 'w') as old_stdout:
        with open(to, 'w') as file:
            _redirect_stdout(file)
        try:
            yield
        finally:
            _redirect_stdout(old_stdout)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python render.py <structure.txt> <out_prefix>", file=sys.stderr)
        sys.exit(1)

    txt_path, out_prefix = sys.argv[1], sys.argv[2]
    with open(txt_path) as f:
        txt = f.read()

    paths = render(txt, out_prefix)
    print(f"Done: {paths}")
