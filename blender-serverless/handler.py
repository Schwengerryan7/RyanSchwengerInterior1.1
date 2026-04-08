"""
handler.py — Unified RunPod Serverless handler (Photorealistic Edition)
========================================================================
Input A:  { ply_base64: str, prompt: str }   — point cloud → reconstruct → render
Input B:  { model_base64: str, prompt: str } — GLB/GLTF → render directly

Pipeline: PLY → Open3D Poisson reconstruction → GLB → Blender Cycles (PBR) → PNG

Output: { image_base64: str, status: "ok" }
"""

import runpod
import subprocess
import base64
import os
import json
import tempfile

import numpy as np
import open3d as o3d

BLENDER = os.environ.get("BLENDER_PATH", "blender")


# ── Step 1: Open3D Reconstruction ────────────────────────────────────────────

def reconstruct_ply(ply_b64: str, tmpdir: str) -> str:
    ply_path = os.path.join(tmpdir, "input.ply")
    with open(ply_path, "wb") as f:
        f.write(base64.b64decode(ply_b64))

    pcd = o3d.io.read_point_cloud(ply_path)
    if len(pcd.points) < 9:
        raise ValueError(f"Point cloud too sparse: {len(pcd.points)} points")

    print(f"[recon] {len(pcd.points)} points loaded")
    pcd.estimate_normals(
        search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=0.15, max_nn=30)
    )
    pcd.orient_normals_consistent_tangent_plane(100)

    mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(pcd, depth=9)
    densities = np.asarray(densities)
    mesh.remove_vertices_by_mask(densities < np.quantile(densities, 0.05))
    mesh.compute_vertex_normals()

    recon_ply = os.path.join(tmpdir, "reconstructed.ply")
    o3d.io.write_triangle_mesh(recon_ply, mesh)
    print(f"[recon] Reconstruction done: {len(mesh.vertices)} vertices")

    glb_path = os.path.join(tmpdir, "reconstructed.glb")
    convert_script = f"""
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_mesh.ply(filepath=r"{recon_ply}")
bpy.ops.export_scene.gltf(filepath=r"{glb_path}", export_format='GLB')
"""
    script_path = os.path.join(tmpdir, "convert.py")
    with open(script_path, "w") as f:
        f.write(convert_script)

    r = subprocess.run(
        [BLENDER, "--background", "--python", script_path],
        capture_output=True, text=True, timeout=120
    )
    if not os.path.exists(glb_path):
        raise RuntimeError(f"PLY→GLB failed:\n{r.stderr[-2000:]}")

    print("[recon] PLY→GLB conversion complete")
    return glb_path


# ── Step 2: Blender Photorealistic Render ─────────────────────────────────────

BLENDER_SCRIPT = r"""
import bpy, json, os, math
from mathutils import Vector

with open("/tmp/render_input.json") as f:
    data = json.load(f)

mesh_path  = data["mesh_path"]
prompt     = data.get("prompt", "grey fabric").lower()
output_png = data["output_png"]
os.makedirs(os.path.dirname(output_png), exist_ok=True)

def parse_material(desc):
    d = desc.lower()
    if "gold" in d:
        return ("metal",   (0.80, 0.55, 0.10, 1), 1.0, 0.15, 0.5)
    if "chrome" in d:
        return ("metal",   (0.95, 0.95, 0.95, 1), 1.0, 0.03, 1.0)
    if "steel" in d or ("metal" in d and "matte" not in d):
        return ("metal",   (0.72, 0.72, 0.72, 1), 1.0, 0.35, 0.3)
    if "matte black" in d or ("black" in d and "metal" in d):
        return ("metal",   (0.02, 0.02, 0.02, 1), 1.0, 0.55, 0.0)
    if "walnut" in d:
        return ("wood",    (0.22, 0.10, 0.04, 1), 0.0, 0.75, 0.15)
    if "oak" in d or "wood" in d:
        return ("wood",    (0.52, 0.32, 0.12, 1), 0.0, 0.75, 0.10)
    if "marble" in d:
        return ("marble",  (0.95, 0.93, 0.90, 1), 0.0, 0.05, 0.90)
    if "leather" in d:
        return ("leather", (0.22, 0.10, 0.04, 1), 0.0, 0.60, 0.35)
    if "velvet" in d:
        return ("fabric",  (0.40, 0.10, 0.25, 1), 0.0, 0.98, 0.0)
    if "linen" in d or "fabric" in d or "upholst" in d:
        return ("fabric",  (0.75, 0.72, 0.65, 1), 0.0, 0.95, 0.0)
    if "terracotta" in d or "clay" in d:
        return ("clay",    (0.72, 0.38, 0.25, 1), 0.0, 0.95, 0.0)
    if "plastic" in d:
        return ("plastic", (0.80, 0.80, 0.80, 1), 0.0, 0.40, 0.6)
    if "yellow" in d:
        return ("diffuse", (0.95, 0.82, 0.05, 1), 0.0, 0.70, 0.0)
    if "red" in d:
        return ("diffuse", (0.80, 0.06, 0.06, 1), 0.0, 0.70, 0.0)
    if "blue" in d:
        return ("diffuse", (0.06, 0.22, 0.80, 1), 0.0, 0.70, 0.0)
    if "green" in d:
        return ("diffuse", (0.08, 0.50, 0.15, 1), 0.0, 0.70, 0.0)
    if "white" in d:
        return ("diffuse", (0.95, 0.95, 0.95, 1), 0.0, 0.65, 0.0)
    if "black" in d:
        return ("diffuse", (0.02, 0.02, 0.02, 1), 0.0, 0.70, 0.0)
    if "grey" in d or "gray" in d:
        return ("fabric",  (0.55, 0.55, 0.55, 1), 0.0, 0.95, 0.0)
    return ("diffuse",     (0.80, 0.80, 0.80, 1), 0.0, 0.80, 0.0)

parts     = prompt.split(" with ", 1)
frame_mat = parse_material(parts[0])
seat_mat  = parse_material(parts[1]) if len(parts) > 1 else frame_mat

def build_material(name, mat_type, base_color, metallic, roughness, coat, tex_scale=1.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out  = nodes.new("ShaderNodeOutputMaterial"); out.location  = (900, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (500, 0)
    bsdf.inputs["Base Color"].default_value = base_color
    bsdf.inputs["Metallic"].default_value   = metallic
    bsdf.inputs["Roughness"].default_value  = roughness
    try:
        bsdf.inputs["Coat Weight"].default_value    = coat
        bsdf.inputs["Coat Roughness"].default_value = roughness * 0.4
    except: pass
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    tc = nodes.new("ShaderNodeTexCoord"); tc.location = (-1000, 0)
    mp = nodes.new("ShaderNodeMapping");  mp.location = (-800, 0)
    mp.inputs["Scale"].default_value = (tex_scale, tex_scale, tex_scale)
    links.new(tc.outputs["Object"], mp.inputs["Vector"])

    def noise(loc, scale, detail, rough):
        n = nodes.new("ShaderNodeTexNoise"); n.location = loc
        n.inputs["Scale"].default_value     = scale
        n.inputs["Detail"].default_value    = detail
        n.inputs["Roughness"].default_value = rough
        links.new(mp.outputs["Vector"], n.inputs["Vector"])
        return n

    def bump(loc, strength, dist=0.02):
        b = nodes.new("ShaderNodeBump"); b.location = loc
        b.inputs["Strength"].default_value = strength
        b.inputs["Distance"].default_value = dist
        links.new(b.outputs["Normal"], bsdf.inputs["Normal"])
        return b

    if mat_type == "fabric":
        n1 = noise((-600, 150),  60 * tex_scale, 12, 0.80)
        n2 = noise((-600, -100), 12 * tex_scale,  4, 0.60)
        b  = bump((200, -100), 0.45, 0.015)
        links.new(n1.outputs["Fac"], b.inputs["Height"])
        ramp = nodes.new("ShaderNodeValToRGB"); ramp.location = (-300, -100)
        ramp.color_ramp.elements[0].color = (base_color[0]*0.80, base_color[1]*0.80, base_color[2]*0.80, 1)
        ramp.color_ramp.elements[1].color = base_color
        links.new(n2.outputs["Fac"], ramp.inputs["Fac"])
        links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
        try:
            bsdf.inputs["Sheen Weight"].default_value    = 0.5
            bsdf.inputs["Sheen Roughness"].default_value = 0.5
        except: pass

    elif mat_type == "wood":
        wave = nodes.new("ShaderNodeTexWave"); wave.location = (-600, 100)
        wave.wave_type = "RINGS"
        wave.inputs["Scale"].default_value            = 5 * tex_scale
        wave.inputs["Distortion"].default_value       = 4.5
        wave.inputs["Detail"].default_value           = 8
        wave.inputs["Detail Scale"].default_value     = 2.0
        wave.inputs["Detail Roughness"].default_value = 0.6
        links.new(mp.outputs["Vector"], wave.inputs["Vector"])
        ramp = nodes.new("ShaderNodeValToRGB"); ramp.location = (-300, 100)
        dark = (base_color[0]*0.55, base_color[1]*0.55, base_color[2]*0.55, 1)
        ramp.color_ramp.elements[0].color = dark
        ramp.color_ramp.elements[1].color = base_color
        links.new(wave.outputs["Color"], ramp.inputs["Fac"])
        links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
        b = bump((200, -100), 0.12, 0.01)
        links.new(wave.outputs["Fac"], b.inputs["Height"])

    elif mat_type == "metal":
        n = noise((-600, 0), 180 * tex_scale, 16, 0.90)
        rmap = nodes.new("ShaderNodeMapRange"); rmap.location = (-300, 0)
        rmap.inputs["From Min"].default_value = 0.0
        rmap.inputs["From Max"].default_value = 1.0
        rmap.inputs["To Min"].default_value   = max(0.0, roughness - 0.04)
        rmap.inputs["To Max"].default_value   = min(1.0, roughness + 0.08)
        links.new(n.outputs["Fac"], rmap.inputs["Value"])
        links.new(rmap.outputs["Result"], bsdf.inputs["Roughness"])
        if roughness > 0.1:
            b = bump((200, -100), 0.08, 0.005)
            links.new(n.outputs["Fac"], b.inputs["Height"])

    elif mat_type == "leather":
        n = noise((-600, 100), 28 * tex_scale, 8, 0.70)
        b = bump((200, -100), 0.55, 0.025)
        links.new(n.outputs["Fac"], b.inputs["Height"])
        ramp = nodes.new("ShaderNodeValToRGB"); ramp.location = (-300, 100)
        ramp.color_ramp.elements[0].color = (base_color[0]*0.75, base_color[1]*0.75, base_color[2]*0.75, 1)
        ramp.color_ramp.elements[1].color = (base_color[0]*1.10, base_color[1]*1.10, base_color[2]*1.10, 1)
        links.new(n.outputs["Fac"], ramp.inputs["Fac"])
        links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
        try:
            bsdf.inputs["Sheen Weight"].default_value    = 0.25
            bsdf.inputs["Sheen Roughness"].default_value = 0.45
        except: pass

    elif mat_type == "marble":
        n = noise((-700, 0), 3.5 * tex_scale, 12, 0.65)
        wave = nodes.new("ShaderNodeTexWave"); wave.location = (-700, -200)
        wave.inputs["Scale"].default_value      = 2.8 * tex_scale
        wave.inputs["Distortion"].default_value = 5.0
        wave.inputs["Detail"].default_value     = 10
        links.new(mp.outputs["Vector"], wave.inputs["Vector"])
        mix = nodes.new("ShaderNodeMixRGB"); mix.location = (-350, 0)
        mix.inputs["Color1"].default_value = base_color
        mix.inputs["Color2"].default_value = (0.60, 0.55, 0.50, 1)
        links.new(n.outputs["Fac"], mix.inputs["Fac"])
        links.new(mix.outputs["Color"], bsdf.inputs["Base Color"])
        b = bump((200, -100), 0.06, 0.008)
        links.new(wave.outputs["Fac"], b.inputs["Height"])

    elif mat_type == "plastic":
        n = noise((-600, 0), 300 * tex_scale, 8, 0.5)
        rmap = nodes.new("ShaderNodeMapRange"); rmap.location = (-300, 0)
        rmap.inputs["To Min"].default_value = roughness - 0.02
        rmap.inputs["To Max"].default_value = roughness + 0.02
        links.new(n.outputs["Fac"], rmap.inputs["Value"])
        links.new(rmap.outputs["Result"], bsdf.inputs["Roughness"])

    elif mat_type == "clay":
        n = noise((-600, 0), 40 * tex_scale, 6, 0.85)
        b = bump((200, -100), 0.35, 0.02)
        links.new(n.outputs["Fac"], b.inputs["Height"])

    else:
        n = noise((-600, 0), 80 * tex_scale, 4, 0.6)
        b = bump((200, -100), 0.12, 0.008)
        links.new(n.outputs["Fac"], b.inputs["Height"])

    return mat

# Load mesh
bpy.ops.wm.read_factory_settings(use_empty=True)
if os.path.exists(mesh_path):
    ext = mesh_path.lower()
    if ext.endswith((".glb", ".gltf")):
        bpy.ops.import_scene.gltf(filepath=mesh_path)
    elif ext.endswith(".ply"):
        bpy.ops.import_mesh.ply(filepath=mesh_path)
    elif ext.endswith(".obj"):
        bpy.ops.import_scene.obj(filepath=mesh_path)

    import bmesh as _bmesh
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            obj.rotation_euler[0] = math.radians(90)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.transform_apply(rotation=True)

    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.shade_smooth()
            rem = obj.modifiers.new("Remesh", "REMESH")
            rem.mode = "SMOOTH"
            rem.octree_depth = 7
            rem.use_smooth_shade = True
            bpy.ops.object.modifier_apply(modifier="Remesh")
            sub = obj.modifiers.new("Subdivision", "SUBSURF")
            sub.levels = 1
            sub.render_levels = 2
            bpy.ops.object.modifier_apply(modifier="Subdivision")
            bm = _bmesh.new()
            bm.from_mesh(obj.data)
            _bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            bm.to_mesh(obj.data)
            bm.free()
            obj.data.update()
else:
    bpy.ops.mesh.primitive_cube_add(size=2)

# Scene bounds
mesh_objects = [o for o in bpy.context.scene.objects if o.type == "MESH"]
all_corners  = [obj.matrix_world @ Vector(c) for obj in mesh_objects for c in obj.bound_box]
if not all_corners:
    all_corners = [Vector((0,0,0))]

min_x = min(c.x for c in all_corners); max_x = max(c.x for c in all_corners)
min_y = min(c.y for c in all_corners); max_y = max(c.y for c in all_corners)
min_z = min(c.z for c in all_corners); max_z = max(c.z for c in all_corners)
center = Vector(((min_x+max_x)/2, (min_y+max_y)/2, (min_z+max_z)/2))
size   = max(max_x-min_x, max_y-min_y, max_z-min_z, 0.01)
height = max(max_z - min_z, 0.01)
tex_scale = max(0.5, min(4.0, 1.0 / size))

def classify(obj):
    name = obj.name.lower()
    if any(k in name for k in ("leg","frame","rail","support","arm","base","strut","rod")):
        return "frame"
    if any(k in name for k in ("seat","cushion","pad","upholst","bottom")):
        return "seat"
    if any(k in name for k in ("back","backrest","head","spine")):
        return "back"
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    ox = [c.x for c in corners]; oy = [c.y for c in corners]; oz = [c.z for c in corners]
    dx = max(ox)-min(ox); dy = max(oy)-min(oy); dz = max(oz)-min(oz)
    dims = sorted([dx, dy, dz])
    thin_ratio   = dims[0] / max(dims[2], 0.001)
    obj_center_z = (max(oz)+min(oz)) / 2
    z_norm       = (obj_center_z - min_z) / height
    if thin_ratio < 0.12: return "frame"
    if z_norm < 0.55:     return "seat"
    return "back"

# Apply materials
for obj in mesh_objects:
    role = classify(obj)
    m_type, b_col, mtl, rgh, ct = frame_mat if role == "frame" else seat_mat
    mat = build_material(f"Mat_{role}_{obj.name}", m_type, b_col, mtl, rgh, ct, tex_scale)
    obj.data.materials.clear()
    obj.data.materials.append(mat)

# Floor
bpy.ops.mesh.primitive_plane_add(size=size*8, location=(center.x, center.y, min_z - 0.001))
floor = bpy.context.object; floor.name = "Floor"
floor.cycles.is_shadow_catcher = True
fm = bpy.data.materials.new("FloorMat"); fm.use_nodes = True
floor_bsdf = fm.node_tree.nodes.get("Principled BSDF")
if floor_bsdf:
    floor_bsdf.inputs["Base Color"].default_value = (0.96, 0.96, 0.96, 1)
    floor_bsdf.inputs["Roughness"].default_value  = 0.55
floor.data.materials.append(fm)

# Camera
dist    = size * 2.8
cam_loc = Vector((center.x + dist*0.55, center.y - dist*1.0, center.z + dist*0.45))
bpy.ops.object.camera_add(location=cam_loc)
cam = bpy.context.object
cam.rotation_euler          = (center - cam_loc).to_track_quat("-Z","Y").to_euler()
cam.data.lens               = 85
cam.data.dof.use_dof        = True
cam.data.dof.focus_distance = (cam_loc - center).length
cam.data.dof.aperture_fstop = 11.0
bpy.context.scene.camera    = cam

# World — Physical Sky
world = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
bpy.context.scene.world = world
world.use_nodes = True
nt = world.node_tree; nt.nodes.clear()
out_w   = nt.nodes.new("ShaderNodeOutputWorld");  out_w.location   = (600, 0)
bg_node = nt.nodes.new("ShaderNodeBackground");   bg_node.location = (300, 0)
sky     = nt.nodes.new("ShaderNodeTexSky");        sky.location     = (0, 0)
tc_w    = nt.nodes.new("ShaderNodeTexCoord");      tc_w.location    = (-300, 0)
try:
    sky.sky_type      = "NISHITA"
    sky.sun_elevation = math.radians(42)
    sky.sun_rotation  = math.radians(215)
    sky.air_density   = 1.0
    sky.dust_density  = 0.05
    sky.ozone_density = 1.0
except:
    sky.sky_type  = "PREETHAM"
    sky.turbidity = 2.5
nt.links.new(tc_w.outputs["Generated"], sky.inputs["Vector"])
nt.links.new(sky.outputs["Color"],      bg_node.inputs["Color"])
bg_node.inputs["Strength"].default_value = 0.35
nt.links.new(bg_node.outputs["Background"], out_w.inputs["Surface"])

# Studio lights
def area_light(loc, energy, size_x, size_y, rx, ry, rz, color=(1,1,1)):
    bpy.ops.object.light_add(type="AREA", location=loc)
    l = bpy.context.object
    l.data.energy = energy; l.data.size = size_x; l.data.size_y = size_y
    l.data.color  = color;  l.data.use_soft_falloff = True
    l.rotation_euler = (math.radians(rx), math.radians(ry), math.radians(rz))

s = size
area_light((center.x-s*1.8, center.y-s*0.6, center.z+s*2.0), 3800, s*1.6, s*1.2,  60, 0, -35, (1.00,0.97,0.92))
area_light((center.x+s*2.2, center.y+s*0.4, center.z+s*1.2),  900, s*2.0, s*1.8,  45, 0,  50, (0.90,0.94,1.00))
area_light((center.x+s*0.5, center.y+s*2.0, center.z+s*1.5), 1600, s*0.6, s*1.6, -55, 0,  20, (1.00,0.98,0.95))
area_light((center.x,       center.y,       center.z+s*2.8),   500, s*3.0, s*3.0,   0, 0,   0, (0.95,0.97,1.00))
area_light((center.x,       center.y,       min_z-s*0.4),      200, s*4.0, s*4.0, 180, 0,   0, (0.98,0.97,0.95))

# Render settings
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.device = "GPU"
try:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "CUDA"
    prefs.get_devices()
    for d in prefs.devices: d.use = True
    print("[render] GPU (CUDA) enabled")
except Exception as e:
    print(f"[render] GPU unavailable, using CPU: {e}")

scene.cycles.use_adaptive_sampling   = True
scene.cycles.adaptive_threshold      = 0.008
scene.cycles.samples                 = 512
scene.cycles.adaptive_min_samples    = 64
scene.cycles.use_denoising           = True
try:
    scene.cycles.denoiser               = "OPENIMAGEDENOISE"
    scene.cycles.denoising_input_passes = "RGB_ALBEDO_NORMAL"
except: pass
scene.cycles.max_bounces             = 12
scene.cycles.diffuse_bounces         = 6
scene.cycles.glossy_bounces          = 6
scene.cycles.transmission_bounces    = 8
scene.cycles.volume_bounces          = 2
scene.cycles.caustics_reflective     = False
scene.cycles.caustics_refractive     = False
scene.render.resolution_x            = 1280
scene.render.resolution_y            = 1280
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.render.filepath                = output_png
scene.frame_current                  = 1
print("[render] Starting Blender Cycles render...")
bpy.ops.render.render(write_still=True)
print(f"[render] Saved to {output_png}")
"""


def run_blender_render(mesh_path: str, prompt: str, tmpdir: str) -> dict:
    output_png = os.path.join(tmpdir, "output", "render.png")
    os.makedirs(os.path.dirname(output_png), exist_ok=True)

    with open("/tmp/render_input.json", "w") as f:
        json.dump({"mesh_path": mesh_path, "prompt": prompt, "output_png": output_png}, f)

    script_path = os.path.join(tmpdir, "render.py")
    with open(script_path, "w") as f:
        f.write(BLENDER_SCRIPT)

    result = subprocess.run(
        [BLENDER, "--background", "--python", script_path],
        capture_output=True, text=True, timeout=600
    )

    if not os.path.exists(output_png):
        return {"error": "Blender produced no output", "stderr": result.stderr[-4000:]}

    with open(output_png, "rb") as f:
        return {"image_base64": base64.b64encode(f.read()).decode(), "status": "ok"}


def handler(job):
    job_input = job.get("input", {})
    prompt    = job_input.get("prompt", "grey fabric chair")
    ply_b64   = job_input.get("ply_base64")
    model_b64 = job_input.get("model_base64")

    if not ply_b64 and not model_b64:
        return {"error": "Provide ply_base64 or model_base64"}

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            if ply_b64:
                print("[pipeline] Step 1/2 — Open3D Poisson reconstruction")
                mesh_path = reconstruct_ply(ply_b64, tmpdir)
            else:
                print("[pipeline] GLB provided — skipping reconstruction")
                mesh_path = os.path.join(tmpdir, "model.glb")
                with open(mesh_path, "wb") as f:
                    f.write(base64.b64decode(model_b64))

            print(f"[pipeline] Step 2/2 — Blender render | prompt: {prompt!r}")
            return run_blender_render(mesh_path, prompt, tmpdir)

        except subprocess.TimeoutExpired:
            return {"error": "Timed out (600s limit)"}
        except Exception as e:
            return {"error": str(e)}


runpod.serverless.start({"handler": handler})
