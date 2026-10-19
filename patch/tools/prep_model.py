"""Prepare a downloaded model for scenes/*/models: one static, decimated, self-contained .glb.

    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup -noaudio --python patch/tools/prep_model.py -- \
        IN OUT.glb [--faces 60000] [--texture 1024]

IN is a .glb, .gltf, .fbx, .obj or .zip (a Sketchfab download; its first .gltf/.glb/.fbx/.obj is used). Rigs are frozen
in their current pose, every mesh is merged into one object, the triangle count is collapsed to at most --faces, images
are shrunk to at most --texture pixels a side, and the result is written with its textures embedded.
"""
import os
import sys
import tempfile
import zipfile

import bpy


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    src, dst = argv[0], argv[1]
    faces = int(argv[argv.index("--faces") + 1]) if "--faces" in argv else 60000
    texture = int(argv[argv.index("--texture") + 1]) if "--texture" in argv else 1024
    return src, dst, faces, texture


def unpack(src):
    if not src.lower().endswith(".zip"):
        return src
    out = tempfile.mkdtemp(prefix="prep_model_")
    with zipfile.ZipFile(src) as z:
        z.extractall(out)
    for ext in (".glb", ".gltf", ".fbx", ".obj"):
        for root, _, files in os.walk(out):
            for f in sorted(files):
                if f.lower().endswith(ext):
                    return os.path.join(root, f)
    raise SystemExit(f"{src}: no model inside")


def load(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    else:
        raise SystemExit(f"{path}: unsupported format")


def main():
    src, dst, faces, texture = args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    load(unpack(src))

    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    # Applies every modifier (an armature's current pose included) and bakes the parent transforms in.
    bpy.ops.object.convert(target="MESH")
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    # The parents' transforms move into the meshes before the parents (empties, armatures) go.
    bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for o in list(bpy.context.scene.objects):
        if o.type != "MESH":
            bpy.data.objects.remove(o, do_unlink=True)
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active

    tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
    if tris > faces:
        mod = obj.modifiers.new("decimate", "DECIMATE")
        mod.ratio = faces / tris
        mod.use_collapse_triangulate = True
        bpy.ops.object.modifier_apply(modifier=mod.name)
    after = sum(len(p.vertices) - 2 for p in obj.data.polygons)

    for img in bpy.data.images:
        if img.size[0] == 0:
            continue
        w, h = img.size
        k = min(1.0, texture / max(w, h))
        if k < 1.0:
            img.scale(max(1, int(w * k)), max(1, int(h * k)))
        img.pack()

    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", use_selection=False, export_animations=False,
                              export_skins=False, export_morph=False, export_apply=True)
    print(f"PREP {src} -> {dst}: {tris} -> {after} triangles, {len(obj.data.materials)} materials")


main()
