#!/usr/bin/env python
"""
Render a target mesh (.obj) from multiple angles to PNG files.

Usage:
    python llm/render_mesh.py mesh.obj llm/outputs/target
    # Produces: target_front.png, target_side.png, target_top.png
"""
import math
import os
import sys
from contextlib import contextmanager
from pathlib import Path

import bpy
import mathutils


VIEWS = {
    "corner_fl": (45,  20),   # (azimuth_deg, elevation_deg)
    "corner_fr": (315, 20),
    "corner_br": (225, 20),
    "corner_bl": (135, 20),
}


def look_at(camera, target):
    direction = target - camera.location
    rot = direction.to_track_quat('-Z', 'Y')
    camera.rotation_euler = rot.to_euler()


def render_mesh(obj_path: str, out_prefix: str, img_resolution: int = 512) -> list[str]:
    obj_path = os.path.abspath(obj_path)
    out_paths = []

    with stdout_redirected(os.devnull):
        bpy.data.scenes[0].render.engine = 'CYCLES'
        if sys.platform == 'darwin':
            bpy.context.preferences.addons['cycles'].preferences.compute_device_type = 'METAL'
        else:
            bpy.context.preferences.addons['cycles'].preferences.compute_device_type = 'CUDA'
        bpy.context.scene.cycles.device = 'GPU'
        bpy.context.scene.cycles.samples = 128
        bpy.context.preferences.addons['cycles'].preferences.get_devices()
        for d in bpy.context.preferences.addons['cycles'].preferences.devices:
            d['use'] = 1 if (d['name'].startswith('NVIDIA') or d['name'].startswith('Apple')) else 0

    # Clear scene
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()

    # Import mesh (OBJ or GLB/GLTF)
    ext = Path(obj_path).suffix.lower()
    with stdout_redirected(os.devnull):
        if ext in ('.glb', '.gltf'):
            bpy.ops.import_scene.gltf(filepath=obj_path)
        else:
            bpy.ops.wm.obj_import(filepath=obj_path)

    # Get imported meshes and center the group as a whole
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    bpy.context.view_layer.update()
    bbox = [o.matrix_world @ mathutils.Vector(c) for o in meshes for c in o.bound_box]
    center = sum(bbox, mathutils.Vector()) / len(bbox)
    offset = -center
    for o in meshes:
        o.location += offset
    bpy.context.view_layer.update()
    bbox = [o.matrix_world @ mathutils.Vector(c) for o in meshes for c in o.bound_box]
    center = mathutils.Vector((0, 0, 0))
    radius = max((v - center).length for v in bbox) if bbox else 1.0
    distance = radius * 3.5

    # Add camera and light
    bpy.ops.object.camera_add()
    camera = bpy.context.active_object
    bpy.context.scene.camera = camera

    bpy.ops.object.light_add(type='SUN', location=(0, 0, distance * 2))
    sun = bpy.context.active_object
    sun.data.energy = 3

    # Render settings
    bpy.context.scene.render.resolution_x = img_resolution
    bpy.context.scene.render.resolution_y = img_resolution
    bpy.context.scene.render.image_settings.file_format = 'PNG'

    for view_name, (azimuth_deg, elevation_deg) in VIEWS.items():
        az = math.radians(azimuth_deg)
        el = math.radians(elevation_deg)
        x = -distance * math.cos(el) * math.cos(az)
        y = distance * math.cos(el) * math.sin(az)
        z = distance * math.sin(el)
        camera.location = mathutils.Vector((x, y, z)) + center
        look_at(camera, center)

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
        print("Usage: python render_mesh.py <mesh.obj> <out_prefix>", file=sys.stderr)
        sys.exit(1)

    obj_path, out_prefix = sys.argv[1], sys.argv[2]
    paths = render_mesh(obj_path, out_prefix)
    print(f"Done: {paths}")
