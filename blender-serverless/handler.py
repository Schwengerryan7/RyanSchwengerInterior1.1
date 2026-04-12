"""
handler.py — RunPod Serverless v54 — OpenClaw Vision Loop Edition
=================================================================
Two-pass intelligent rendering pipeline:

  Pass 1 → Reconstruct mesh → Preview render (128 samples, ~10s)
  Pass 2 → Claude vision analyzes preview → JSON corrections → Final render (512 samples)

Core fix: Face-level material zone assignment on the unified voxel blob.
  Every face is individually classified by Z-height + world-space surface normal:
    SEAT  — upward-facing  (nz > 0.40)  in mid-height zone  (z_norm 0.15–0.72)
    BACK  — near-vertical  (|nz| < 0.55) in upper zone      (z_norm > 0.45)
    FRAME — everything else (legs, base, connectors)

Input A : { ply_base64: str,   prompt: str } — point cloud → voxel remesh → render
Input B : { model_base64: str, prompt: str } — GLB/OBJ → render directly

Requires RunPod env var: ANTHROPIC_API_KEY
Output  : { image_base64: str, status: "ok", claude_notes: [...] }
"""

import runpod
import subprocess
import base64
import os
import json
import tempfile

BLENDER          = os.environ.get("BLENDER_PATH", "blender")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


# ═══════════════════════════════════════════════════════════════════════════════
#  BLENDER SCRIPT
#  Runs inside Blender (headless). Reads /tmp/render_input.json for all params.
# ═══════════════════════════════════════════════════════════════════════════════

BLENDER_SCRIPT = r"""
import bpy, json, os, math
import bmesh as _bmesh
from mathutils import Vector

with open("/tmp/render_input.json") as f:
    data = json.load(f)

mesh_path   = data["mesh_path"]
prompt      = data.get("prompt", "grey fabric chair").lower()
output_png  = data["output_png"]
do_recon    = data.get("do_recon", False)
samples     = data.get("samples", 512)
corrections = data.get("corrections", {})
os.makedirs(os.path.dirname(output_png), exist_ok=True)

print(f"[blender] prompt={prompt!r}  samples={samples}  corrections={corrections}")

# ── Material parser ────────────────────────────────────────────────────────────
#
#  Two-step approach: detect COLOR and MATERIAL TYPE independently,
#  then combine them.  This means any color + any material just works:
#    "pink fur"        → fur shader  + pink color
#    "grey fabric"     → fabric shader + grey color
#    "orange velvet"   → velvet shader + orange color
#    "chrome"          → chrome shader (color implicit in material)
#    "all black chair" → diffuse + black color applied to every zone
#
# ─────────────────────────────────────────────────────────────────────────────

# Colours — detected by keyword, override the material's default base_color
COLOUR_TABLE = [
    # Multi-word first so "hot pink" beats "pink"
    ("hot pink",   (0.99, 0.08, 0.58, 1)),
    ("light blue", (0.55, 0.75, 0.95, 1)),
    ("light grey", (0.78, 0.78, 0.78, 1)),
    ("light gray", (0.78, 0.78, 0.78, 1)),
    ("dark grey",  (0.18, 0.18, 0.18, 1)),
    ("dark gray",  (0.18, 0.18, 0.18, 1)),
    ("dark green", (0.04, 0.28, 0.08, 1)),
    ("dark blue",  (0.03, 0.06, 0.35, 1)),
    ("dark red",   (0.45, 0.02, 0.02, 1)),
    ("dark brown", (0.22, 0.10, 0.03, 1)),
    # Single-word
    ("pink",       (0.95, 0.42, 0.62, 1)),
    ("purple",     (0.45, 0.10, 0.65, 1)),
    ("lavender",   (0.72, 0.60, 0.88, 1)),
    ("orange",     (0.90, 0.42, 0.05, 1)),
    ("teal",       (0.05, 0.62, 0.58, 1)),
    ("mint",       (0.58, 0.92, 0.72, 1)),
    ("coral",      (0.95, 0.38, 0.28, 1)),
    ("beige",      (0.85, 0.78, 0.65, 1)),
    ("brown",      (0.38, 0.20, 0.07, 1)),
    ("tan",        (0.72, 0.53, 0.30, 1)),
    ("caramel",    (0.65, 0.38, 0.12, 1)),
    ("charcoal",   (0.12, 0.12, 0.12, 1)),
    ("navy",       (0.04, 0.09, 0.40, 1)),
    ("yellow",     (0.95, 0.82, 0.05, 1)),
    ("red",        (0.80, 0.06, 0.06, 1)),
    ("blue",       (0.06, 0.22, 0.80, 1)),
    ("green",      (0.08, 0.50, 0.15, 1)),
    ("white",      (0.95, 0.95, 0.95, 1)),
    ("black",      (0.02, 0.02, 0.02, 1)),
    ("grey",       (0.55, 0.55, 0.55, 1)),
    ("gray",       (0.55, 0.55, 0.55, 1)),
    ("cream",      (0.96, 0.92, 0.82, 1)),
    ("ivory",      (0.95, 0.93, 0.85, 1)),
    ("silver",     (0.80, 0.80, 0.80, 1)),
]

# Material types — (keyword, mat_type, default_color, metallic, roughness, coat)
# Checked in order; first match wins. Multi-word keywords listed before single-word.
MAT_TABLE = [
    # ── Soft / fabric ──────────────────────────────────────────────────────────
    ("shearling",  "fabric",  (0.88, 0.84, 0.76, 1), 0.0, 0.97, 0.0),
    ("sherpa",     "fabric",  (0.92, 0.90, 0.85, 1), 0.0, 0.97, 0.0),
    ("fur",        "fabric",  (0.85, 0.82, 0.78, 1), 0.0, 0.98, 0.0),
    ("velvet",     "fabric",  (0.40, 0.10, 0.25, 1), 0.0, 0.98, 0.0),
    ("bouclé",     "fabric",  (0.88, 0.85, 0.78, 1), 0.0, 0.97, 0.0),
    ("boucle",     "fabric",  (0.88, 0.85, 0.78, 1), 0.0, 0.97, 0.0),
    ("chenille",   "fabric",  (0.70, 0.55, 0.45, 1), 0.0, 0.96, 0.0),
    ("tweed",      "fabric",  (0.55, 0.52, 0.45, 1), 0.0, 0.92, 0.0),
    ("linen",      "fabric",  (0.82, 0.78, 0.68, 1), 0.0, 0.93, 0.0),
    ("cotton",     "fabric",  (0.90, 0.88, 0.84, 1), 0.0, 0.92, 0.0),
    ("wool",       "fabric",  (0.80, 0.76, 0.68, 1), 0.0, 0.95, 0.0),
    ("upholstery", "fabric",  (0.75, 0.72, 0.65, 1), 0.0, 0.92, 0.0),
    ("fabric",     "fabric",  (0.75, 0.72, 0.65, 1), 0.0, 0.92, 0.0),
    # ── Leather ────────────────────────────────────────────────────────────────
    ("suede",      "leather", (0.52, 0.38, 0.28, 1), 0.0, 0.88, 0.05),
    ("leather",    "leather", (0.28, 0.13, 0.05, 1), 0.0, 0.60, 0.35),
    # ── Wood ───────────────────────────────────────────────────────────────────
    ("walnut",     "wood",    (0.22, 0.10, 0.04, 1), 0.0, 0.75, 0.15),
    ("mahogany",   "wood",    (0.35, 0.08, 0.04, 1), 0.0, 0.70, 0.20),
    ("oak",        "wood",    (0.52, 0.32, 0.12, 1), 0.0, 0.75, 0.10),
    ("pine",       "wood",    (0.70, 0.55, 0.28, 1), 0.0, 0.82, 0.05),
    ("bamboo",     "wood",    (0.78, 0.72, 0.40, 1), 0.0, 0.80, 0.08),
    ("rattan",     "wood",    (0.72, 0.58, 0.32, 1), 0.0, 0.85, 0.05),
    ("wood",       "wood",    (0.52, 0.32, 0.12, 1), 0.0, 0.75, 0.10),
    # ── Stone / ceramic ────────────────────────────────────────────────────────
    ("marble",     "marble",  (0.95, 0.93, 0.90, 1), 0.0, 0.05, 0.90),
    ("concrete",   "clay",    (0.60, 0.60, 0.58, 1), 0.0, 0.90, 0.0),
    ("terracotta", "clay",    (0.72, 0.38, 0.25, 1), 0.0, 0.95, 0.0),
    ("clay",       "clay",    (0.72, 0.38, 0.25, 1), 0.0, 0.95, 0.0),
    # ── Metal ──────────────────────────────────────────────────────────────────
    ("chrome",     "metal",   (0.95, 0.95, 0.95, 1), 1.0, 0.03, 1.0),
    ("brass",      "metal",   (0.78, 0.62, 0.22, 1), 1.0, 0.20, 0.6),
    ("gold",       "metal",   (0.80, 0.55, 0.10, 1), 1.0, 0.15, 0.5),
    ("steel",      "metal",   (0.72, 0.72, 0.72, 1), 1.0, 0.35, 0.3),
    ("iron",       "metal",   (0.60, 0.60, 0.60, 1), 1.0, 0.50, 0.2),
    ("metal",      "metal",   (0.72, 0.72, 0.72, 1), 1.0, 0.35, 0.3),
    # ── Plastic / acrylic ──────────────────────────────────────────────────────
    ("acrylic",    "plastic", (0.92, 0.92, 0.98, 1), 0.0, 0.08, 0.9),
    ("plastic",    "plastic", (0.80, 0.80, 0.80, 1), 0.0, 0.40, 0.6),
]

def parse_material(desc):
    """
    Parse any natural-language material description into shader params.
    Steps:
      1. Scan for a material TYPE keyword  → determines shader behaviour
      2. Scan for a COLOR keyword          → overrides that material's default color
      3. If only a color found (no type)   → plain diffuse with that color
    """
    d = desc.lower().strip()

    # Step 1 — material type
    found_type = None
    for keyword, mat_type, default_color, metallic, roughness, coat in MAT_TABLE:
        if keyword in d:
            found_type = (mat_type, list(default_color), metallic, roughness, coat)
            break

    # Step 2 — color override (multi-word checked first via table order)
    found_color = None
    for color_name, color_val in COLOUR_TABLE:
        if color_name in d:
            found_color = color_val
            break

    # Step 3 — combine
    if found_type:
        mat_type, base_color, metallic, roughness, coat = found_type
        if found_color:
            base_color = found_color
        return (mat_type, tuple(base_color), metallic, roughness, coat)

    if found_color:
        # Color only, no material keyword → soft diffuse with that color
        return ("diffuse", found_color, 0.0, 0.72, 0.0)

    # Absolute fallback
    return ("diffuse", (0.80, 0.80, 0.80, 1), 0.0, 0.80, 0.0)

# ── Prompt → per-zone material assignments ────────────────────────────────────
import re
p = prompt

frame_mat = seat_mat = back_mat = None

# Try explicit structural role phrases
fm       = re.search(r'([\w\s]+?)\s+(?:frame|legs?|base|structure|rod|rail)', p)
sm       = re.search(r'([\w\s]+?)\s+(?:seat|cushion|pad|upholst\w*|bottom)', p)
bm_match = re.search(r'([\w\s]+?)\s+(?:back(?:rest)?|spine|headrest)', p)
if fm:       frame_mat = parse_material(fm.group(1))
if sm:       seat_mat  = parse_material(sm.group(1))
if bm_match: back_mat  = parse_material(bm_match.group(1))

# "X with Y" / "X and Y" split — handles "oak frame with leather seat" etc.
if not frame_mat or not seat_mat:
    parts = re.split(r'\s+with\s+|\s+and\s+', p, maxsplit=1)
    if len(parts) == 2:
        frame_mat = frame_mat or parse_material(parts[0])
        seat_mat  = seat_mat  or parse_material(parts[1])
    else:
        # Single description → same material on all zones
        base = parse_material(p)
        frame_mat = seat_mat = back_mat = base

frame_mat = frame_mat or parse_material(p)
seat_mat  = seat_mat  or frame_mat
back_mat  = back_mat  or seat_mat

print(f"[mat] frame={frame_mat[0]} {frame_mat[1][:3]}  seat={seat_mat[0]} {seat_mat[1][:3]}  back={back_mat[0]}")

# Apply Claude's brightness / roughness corrections
def apply_corrections(mat_def, brightness_mult, roughness_adj):
    mat_type, base_color, metallic, roughness, coat = mat_def
    bc = base_color
    new_color = (
        min(1.0, bc[0] * brightness_mult),
        min(1.0, bc[1] * brightness_mult),
        min(1.0, bc[2] * brightness_mult),
        bc[3]
    )
    new_rough = max(0.0, min(1.0, roughness + roughness_adj))
    return (mat_type, new_color, metallic, new_rough, coat)

frame_mat = apply_corrections(
    frame_mat,
    corrections.get("frame_brightness_mult", 1.0),
    corrections.get("frame_roughness_adj", 0.0)
)
seat_mat = apply_corrections(
    seat_mat,
    corrections.get("seat_brightness_mult", 1.0),
    corrections.get("seat_roughness_adj", 0.0)
)
back_mat = apply_corrections(
    back_mat,
    corrections.get("back_brightness_mult", 1.0),
    corrections.get("back_roughness_adj", 0.0)
)

# ── PBR material builder ───────────────────────────────────────────────────────
def build_material(name, mat_type, base_color, metallic, roughness, coat, tex_scale=1.0, mat_hint=""):
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
        n.inputs["Scale"].default_value   = scale
        n.inputs["Detail"].default_value  = detail
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
        is_fur = any(k in mat_hint for k in ("fur","sherpa","shearling","velvet","chenille"))
        n1 = noise((-600,150),  60*tex_scale, 16 if is_fur else 12, 0.85 if is_fur else 0.80)
        n2 = noise((-600,-100), 12*tex_scale,  4, 0.60)
        bump_str = 0.70 if is_fur else 0.45
        b  = bump((200,-100), bump_str, 0.018 if is_fur else 0.015)
        links.new(n1.outputs["Fac"], b.inputs["Height"])
        ramp = nodes.new("ShaderNodeValToRGB"); ramp.location = (-300,-100)
        ramp.color_ramp.elements[0].color = (base_color[0]*0.75,base_color[1]*0.75,base_color[2]*0.75,1)
        ramp.color_ramp.elements[1].color = base_color
        links.new(n2.outputs["Fac"], ramp.inputs["Fac"])
        links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
        try:
            sheen = 0.90 if is_fur else 0.50
            bsdf.inputs["Sheen Weight"].default_value    = sheen
            bsdf.inputs["Sheen Roughness"].default_value = 0.35 if is_fur else 0.50
        except: pass

    elif mat_type == "wood":
        wave = nodes.new("ShaderNodeTexWave"); wave.location = (-600,100)
        wave.wave_type = "RINGS"
        wave.inputs["Scale"].default_value            = 5*tex_scale
        wave.inputs["Distortion"].default_value       = 4.5
        wave.inputs["Detail"].default_value           = 8
        wave.inputs["Detail Scale"].default_value     = 2.0
        wave.inputs["Detail Roughness"].default_value = 0.6
        links.new(mp.outputs["Vector"], wave.inputs["Vector"])
        ramp = nodes.new("ShaderNodeValToRGB"); ramp.location = (-300,100)
        dark = (base_color[0]*0.55, base_color[1]*0.55, base_color[2]*0.55, 1)
        ramp.color_ramp.elements[0].color = dark
        ramp.color_ramp.elements[1].color = base_color
        links.new(wave.outputs["Color"], ramp.inputs["Fac"])
        links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
        b = bump((200,-100), 0.12, 0.01)
        links.new(wave.outputs["Fac"], b.inputs["Height"])

    elif mat_type == "metal":
        n = noise((-600,0), 180*tex_scale, 16, 0.90)
        rmap = nodes.new("ShaderNodeMapRange"); rmap.location = (-300,0)
        rmap.inputs["From Min"].default_value = 0.0
        rmap.inputs["From Max"].default_value = 1.0
        rmap.inputs["To Min"].default_value   = max(0.0, roughness-0.04)
        rmap.inputs["To Max"].default_value   = min(1.0, roughness+0.08)
        links.new(n.outputs["Fac"], rmap.inputs["Value"])
        links.new(rmap.outputs["Result"], bsdf.inputs["Roughness"])
        if roughness > 0.1:
            b = bump((200,-100), 0.08, 0.005)
            links.new(n.outputs["Fac"], b.inputs["Height"])

    elif mat_type == "leather":
        n = noise((-600,100), 28*tex_scale, 8, 0.70)
        b = bump((200,-100), 0.55, 0.025)
        links.new(n.outputs["Fac"], b.inputs["Height"])
        ramp = nodes.new("ShaderNodeValToRGB"); ramp.location = (-300,100)
        ramp.color_ramp.elements[0].color = (base_color[0]*0.72,base_color[1]*0.72,base_color[2]*0.72,1)
        ramp.color_ramp.elements[1].color = (min(1,base_color[0]*1.15),min(1,base_color[1]*1.15),min(1,base_color[2]*1.15),1)
        links.new(n.outputs["Fac"], ramp.inputs["Fac"])
        links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
        try:
            bsdf.inputs["Sheen Weight"].default_value    = 0.25
            bsdf.inputs["Sheen Roughness"].default_value = 0.45
        except: pass

    elif mat_type == "marble":
        n = noise((-700,0), 3.5*tex_scale, 12, 0.65)
        wave = nodes.new("ShaderNodeTexWave"); wave.location = (-700,-200)
        wave.inputs["Scale"].default_value      = 2.8*tex_scale
        wave.inputs["Distortion"].default_value = 5.0
        wave.inputs["Detail"].default_value     = 10
        links.new(mp.outputs["Vector"], wave.inputs["Vector"])
        mix = nodes.new("ShaderNodeMixRGB"); mix.location = (-350,0)
        mix.inputs["Color1"].default_value = base_color
        mix.inputs["Color2"].default_value = (0.60,0.55,0.50,1)
        links.new(n.outputs["Fac"], mix.inputs["Fac"])
        links.new(mix.outputs["Color"], bsdf.inputs["Base Color"])
        b = bump((200,-100), 0.06, 0.008)
        links.new(wave.outputs["Fac"], b.inputs["Height"])

    elif mat_type == "plastic":
        n = noise((-600,0), 300*tex_scale, 8, 0.5)
        rmap = nodes.new("ShaderNodeMapRange"); rmap.location = (-300,0)
        rmap.inputs["To Min"].default_value = roughness-0.02
        rmap.inputs["To Max"].default_value = roughness+0.02
        links.new(n.outputs["Fac"], rmap.inputs["Value"])
        links.new(rmap.outputs["Result"], bsdf.inputs["Roughness"])

    elif mat_type == "clay":
        n = noise((-600,0), 40*tex_scale, 6, 0.85)
        b = bump((200,-100), 0.35, 0.02)
        links.new(n.outputs["Fac"], b.inputs["Height"])

    else:
        n = noise((-600,0), 80*tex_scale, 4, 0.6)
        b = bump((200,-100), 0.12, 0.008)
        links.new(n.outputs["Fac"], b.inputs["Height"])

    return mat

# ── Load scene ─────────────────────────────────────────────────────────────────
bpy.ops.wm.read_factory_settings(use_empty=True)

if os.path.exists(mesh_path):
    ext = mesh_path.lower()
    if ext.endswith((".glb",".gltf")):
        bpy.ops.import_scene.gltf(filepath=mesh_path)
    elif ext.endswith(".ply"):
        try:   bpy.ops.wm.ply_import(filepath=mesh_path)
        except: bpy.ops.import_mesh.ply(filepath=mesh_path)
    elif ext.endswith(".obj"):
        bpy.ops.import_scene.obj(filepath=mesh_path)
else:
    bpy.ops.mesh.primitive_cube_add(size=2)

# ── Voxel remesh (point cloud → solid surface) ────────────────────────────────
if do_recon:
    print("[recon] Voxel remesh...")
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            dims = [obj.dimensions.x, obj.dimensions.y, obj.dimensions.z]
            max_dim = max(dims) if max(dims) > 0 else 1.0
            voxel_size = max_dim / 100.0   # finer voxels = more detail preserved
            mod = obj.modifiers.new("Remesh","REMESH")
            mod.mode = "VOXEL"
            mod.voxel_size = voxel_size
            mod.adaptivity = 0.0
            bpy.ops.object.modifier_apply(modifier="Remesh")
            bpy.ops.object.shade_smooth()
            print(f"[recon] voxel_size={voxel_size:.4f}")
            break

# ── Fix rotation ───────────────────────────────────────────────────────────────
for obj in bpy.context.scene.objects:
    if obj.type == "MESH":
        obj.rotation_euler[0] = math.radians(90)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.transform_apply(rotation=True)

# ── Smooth + subdivide ─────────────────────────────────────────────────────────
for obj in bpy.context.scene.objects:
    if obj.type == "MESH":
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.shade_smooth()
        sub = obj.modifiers.new("Subdivision","SUBSURF")
        sub.levels = 1; sub.render_levels = 2
        bpy.ops.object.modifier_apply(modifier="Subdivision")
        bm = _bmesh.new()
        bm.from_mesh(obj.data)
        _bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(obj.data); bm.free(); obj.data.update()

# ── Scene bounds ───────────────────────────────────────────────────────────────
mesh_objects = [o for o in bpy.context.scene.objects if o.type=="MESH"]
all_corners  = [obj.matrix_world @ Vector(c) for obj in mesh_objects for c in obj.bound_box]
if not all_corners: all_corners = [Vector((0,0,0))]

min_x=min(c.x for c in all_corners); max_x=max(c.x for c in all_corners)
min_y=min(c.y for c in all_corners); max_y=max(c.y for c in all_corners)
min_z=min(c.z for c in all_corners); max_z=max(c.z for c in all_corners)
center    = Vector(((min_x+max_x)/2,(min_y+max_y)/2,(min_z+max_z)/2))
size      = max(max_x-min_x, max_y-min_y, max_z-min_z, 0.01)
height    = max(max_z-min_z, 0.01)
tex_scale = max(0.5, min(4.0, 1.0/size))

# ════════════════════════════════════════════════════════════════════════════════
#  FACE-LEVEL ZONE ASSIGNMENT  ← THE CORE FIX
#
#  The voxel remesh produces ONE unified object.  The old per-object classify()
#  ran once and painted everything with one material.
#
#  This loop classifies EVERY FACE individually using:
#    z_norm  — where the face sits vertically (0=floor, 1=top of object)
#    nz      — world-space normal Z component (+1=up, 0=sideways, -1=down)
#
#  Rules (tuned for typical chairs):
#    SEAT  : nz >  0.40  AND  0.15 < z_norm < 0.72   → upward face in mid zone
#    BACK  : |nz| < 0.55  AND  z_norm > 0.45          → vertical face in upper zone
#    FRAME : everything else                           → legs, base, connectors
# ════════════════════════════════════════════════════════════════════════════════

for obj in mesh_objects:
    # Build the 3 material slots on this object
    obj.data.materials.clear()
    mat_fr = build_material("Mat_frame", *frame_mat, tex_scale, mat_hint=prompt)
    mat_se = build_material("Mat_seat",  *seat_mat,  tex_scale, mat_hint=prompt)
    mat_ba = build_material("Mat_back",  *back_mat,  tex_scale, mat_hint=prompt)
    obj.data.materials.append(mat_fr)   # slot 0 — frame
    obj.data.materials.append(mat_se)   # slot 1 — seat
    obj.data.materials.append(mat_ba)   # slot 2 — back

    # Normal matrix handles non-uniform object scale correctly
    normal_mat = obj.matrix_world.to_3x3().inverted_safe().transposed()

    bm = _bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()

    n_seat = n_back = n_frame = 0

    for face in bm.faces:
        # World-space face centre
        world_pos = obj.matrix_world @ face.calc_center_median()
        z_norm    = (world_pos.z - min_z) / height   # 0=bottom, 1=top

        # World-space face normal
        wn = (normal_mat @ face.normal).normalized()
        nz = wn.z   # +1 = straight up

        # --- classify ---
        if nz > 0.40 and 0.15 < z_norm < 0.72:
            face.material_index = 1; n_seat  += 1
        elif abs(nz) < 0.55 and z_norm > 0.45:
            face.material_index = 2; n_back  += 1
        else:
            face.material_index = 0; n_frame += 1

    print(f"[zone] obj={obj.name!r}  frame={n_frame}  seat={n_seat}  back={n_back}")

    # Safety: if seat zone is completely empty the heuristics missed — broaden it
    if n_seat == 0:
        print("[zone] WARN: no seat faces — applying z_norm 0.30-0.65 fallback")
        for face in bm.faces:
            world_pos = obj.matrix_world @ face.calc_center_median()
            z_norm    = (world_pos.z - min_z) / height
            if 0.30 < z_norm < 0.65:
                face.material_index = 1

    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()

# ── Floor (shadow catcher) ─────────────────────────────────────────────────────
bpy.ops.mesh.primitive_plane_add(size=size*10, location=(center.x,center.y,min_z-0.001))
floor = bpy.context.object; floor.name = "Floor"
floor.cycles.is_shadow_catcher = True
fm = bpy.data.materials.new("FloorMat"); fm.use_nodes = True
fb = fm.node_tree.nodes.get("Principled BSDF")
if fb:
    fb.inputs["Base Color"].default_value = (0.97,0.97,0.97,1)
    fb.inputs["Roughness"].default_value  = 0.50
floor.data.materials.append(fm)

# ── Camera (3/4 product-photo angle, 85mm) ─────────────────────────────────────
cam_dist_mult = corrections.get("camera_distance_mult", 1.0)
dist    = size * 2.8 * cam_dist_mult
cam_loc = Vector((center.x+dist*0.55, center.y-dist*1.0, center.z+dist*0.45))
bpy.ops.object.camera_add(location=cam_loc)
cam = bpy.context.object
cam.rotation_euler          = (center-cam_loc).to_track_quat("-Z","Y").to_euler()
cam.data.lens               = 85
cam.data.dof.use_dof        = True
cam.data.dof.focus_distance = (cam_loc-center).length
cam.data.dof.aperture_fstop = 11.0
bpy.context.scene.camera    = cam

# ── World — Nishita physical sky ───────────────────────────────────────────────
world = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
bpy.context.scene.world = world
world.use_nodes = True
nt = world.node_tree; nt.nodes.clear()
out_w   = nt.nodes.new("ShaderNodeOutputWorld"); out_w.location   = (600,0)
bg_node = nt.nodes.new("ShaderNodeBackground");  bg_node.location = (300,0)
sky     = nt.nodes.new("ShaderNodeTexSky");       sky.location     = (0,0)
tc_w    = nt.nodes.new("ShaderNodeTexCoord");     tc_w.location    = (-300,0)
try:
    sky.sky_type="NISHITA"; sky.sun_elevation=math.radians(42)
    sky.sun_rotation=math.radians(215); sky.air_density=1.0
    sky.dust_density=0.05; sky.ozone_density=1.0
except:
    try: sky.sky_type="PREETHAM"; sky.turbidity=2.5
    except: pass
try:
    nt.links.new(tc_w.outputs["Generated"], sky.inputs["Vector"])
    nt.links.new(sky.outputs["Color"], bg_node.inputs["Color"])
except:
    bg_node.inputs["Color"].default_value = (0.6,0.7,0.9,1)
bg_node.inputs["Strength"].default_value = 0.35
nt.links.new(bg_node.outputs["Background"], out_w.inputs["Surface"])

# ── Studio lighting rig ────────────────────────────────────────────────────────
key_mult  = corrections.get("key_light_mult",  1.0)
fill_mult = corrections.get("fill_light_mult", 1.0)
rim_mult  = corrections.get("rim_light_mult",  1.0)

def area_light(loc, energy, sx, sy, rx, ry, rz, color=(1,1,1)):
    bpy.ops.object.light_add(type="AREA", location=loc)
    l = bpy.context.object
    l.data.energy=energy; l.data.size=sx; l.data.size_y=sy
    l.data.color=color; l.data.use_soft_falloff=True
    l.rotation_euler=(math.radians(rx),math.radians(ry),math.radians(rz))

s = size
area_light((center.x-s*1.8, center.y-s*0.6, center.z+s*2.0), 3800*key_mult,  s*1.6,s*1.2, 60,0,-35,(1.00,0.97,0.92))
area_light((center.x+s*2.2, center.y+s*0.4, center.z+s*1.2),  900*fill_mult, s*2.0,s*1.8, 45,0, 50,(0.90,0.94,1.00))
area_light((center.x+s*0.5, center.y+s*2.0, center.z+s*1.5), 1600*rim_mult,  s*0.6,s*1.6,-55,0, 20,(1.00,0.98,0.95))
area_light((center.x,       center.y,       center.z+s*2.8),   500,            s*3.0,s*3.0,  0,0,  0,(0.95,0.97,1.00))
area_light((center.x,       center.y,       min_z-s*0.4),      200,            s*4.0,s*4.0,180,0,  0,(0.98,0.97,0.95))

# ── Render settings ────────────────────────────────────────────────────────────
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.device = "GPU"
try:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "CUDA"
    prefs.get_devices()
    for d in prefs.devices: d.use = True
    print("[render] CUDA GPU enabled")
except Exception as e:
    print(f"[render] GPU unavailable, CPU fallback: {e}")

scene.cycles.use_adaptive_sampling   = True
scene.cycles.adaptive_threshold      = 0.008
scene.cycles.samples                 = samples
scene.cycles.adaptive_min_samples    = min(64, samples)
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

print(f"[render] samples={samples}  Starting Cycles render...")
bpy.ops.render.render(write_still=True)
print(f"[render] Saved → {output_png}")
"""


# ═══════════════════════════════════════════════════════════════════════════════
#  PYTHON FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def run_blender(mesh_path: str, prompt: str, tmpdir: str,
                do_recon: bool, samples: int,
                corrections: dict | None = None,
                output_name: str = "render.png") -> str | None:
    """
    Run the Blender script. Returns path to output PNG or None on failure.
    """
    output_png = os.path.join(tmpdir, "output", output_name)
    os.makedirs(os.path.dirname(output_png), exist_ok=True)

    with open("/tmp/render_input.json", "w") as f:
        json.dump({
            "mesh_path":   mesh_path,
            "prompt":      prompt,
            "output_png":  output_png,
            "do_recon":    do_recon,
            "samples":     samples,
            "corrections": corrections or {},
        }, f)

    script_path = os.path.join(tmpdir, "render.py")
    with open(script_path, "w") as f:
        f.write(BLENDER_SCRIPT)

    result = subprocess.run(
        [BLENDER, "--background", "--python", script_path],
        capture_output=True, text=True, timeout=600
    )
    print(result.stdout[-3000:])
    if result.stderr:
        print("[stderr]", result.stderr[-1500:])

    return output_png if os.path.exists(output_png) else None


def analyze_with_claude(image_path: str, prompt: str) -> dict:
    """
    Send the preview render to Claude vision.
    Returns a corrections dict that the final Blender render will apply.
    """
    if not ANTHROPIC_API_KEY:
        print("[claude] No ANTHROPIC_API_KEY — skipping vision analysis")
        return {}

    try:
        import anthropic

        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode()

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        system_prompt = """You are an expert 3D furniture rendering director and product photographer.
You review low-sample preview renders of 3D chair models and return precise technical corrections
to achieve photorealistic product photography quality.

You respond ONLY with a valid JSON object — no markdown fences, no explanation.

JSON schema (all fields optional, omit fields that need no correction):
{
  "issues": ["brief description of each visual problem you see"],
  "seat_brightness_mult":  1.0,   // >1 = brighter,  <1 = darker  (range 0.5–2.0)
  "seat_roughness_adj":    0.0,   // add to roughness, range -0.3 to +0.3
  "frame_brightness_mult": 1.0,
  "frame_roughness_adj":   0.0,
  "back_brightness_mult":  1.0,
  "back_roughness_adj":    0.0,
  "key_light_mult":        1.0,   // multiply key light energy
  "fill_light_mult":       1.0,
  "rim_light_mult":        1.0,
  "camera_distance_mult":  1.0    // >1 = pull back (use if chair is cropped)
}"""

        user_text = (
            f"This is a preview render of a chair. Material prompt: \"{prompt}\"\n\n"
            "Analyze the render for photorealism issues. Consider:\n"
            "• Are the seat/back materials visually distinct from the frame/legs?\n"
            "• Does leather look like real leather (dark, slightly glossy)?\n"
            "• Does wood show visible grain contrast?\n"
            "• Is the lighting flattering for a product photo?\n"
            "• Is the chair fully in frame?\n\n"
            "Return the corrections JSON only."
        )

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type":       "base64",
                            "media_type": "image/png",
                            "data":       image_b64,
                        }
                    },
                    {"type": "text", "text": user_text}
                ]
            }]
        )

        raw = response.content[0].text.strip()
        print(f"[claude] response: {raw}")
        corrections = json.loads(raw)
        print(f"[claude] issues: {corrections.get('issues', [])}")
        return corrections

    except json.JSONDecodeError as e:
        print(f"[claude] JSON parse error: {e} — using no corrections")
        return {}
    except Exception as e:
        print(f"[claude] error: {e} — using no corrections")
        return {}


# ═══════════════════════════════════════════════════════════════════════════════
#  RUNPOD HANDLER
# ═══════════════════════════════════════════════════════════════════════════════

def handler(job):
    job_input = job.get("input", {})
    prompt    = job_input.get("prompt", "grey fabric chair")
    ply_b64   = job_input.get("ply_base64")
    model_b64 = job_input.get("model_base64")

    if not ply_b64 and not model_b64:
        return {"error": "Provide ply_base64 or model_base64"}

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            # ── Save mesh file ───────────────────────────────────────────────
            if ply_b64:
                print("[pipeline] PLY input — voxel remesh inside Blender")
                mesh_path = os.path.join(tmpdir, "input.ply")
                do_recon  = True
            else:
                print("[pipeline] GLB/model input — rendering directly")
                mesh_path = os.path.join(tmpdir, "model.glb")
                do_recon  = False

            raw_b64 = ply_b64 or model_b64
            with open(mesh_path, "wb") as f:
                f.write(base64.b64decode(raw_b64))

            # ── PASS 1: Preview render (128 samples, fast ~10s) ──────────────
            print(f"[pipeline] PASS 1 — preview render | prompt: {prompt!r}")
            preview_path = run_blender(
                mesh_path, prompt, tmpdir,
                do_recon=do_recon,
                samples=128,
                corrections={},
                output_name="preview.png"
            )

            # ── Claude vision analysis ───────────────────────────────────────
            corrections = {}
            if preview_path:
                print("[pipeline] Sending preview to Claude vision...")
                corrections = analyze_with_claude(preview_path, prompt)
            else:
                print("[pipeline] WARN: preview render failed — skipping Claude analysis")

            # ── PASS 2: Final render (512 samples, full quality) ─────────────
            print(f"[pipeline] PASS 2 — final render | corrections={corrections}")
            final_path = run_blender(
                mesh_path, prompt, tmpdir,
                do_recon=do_recon,
                samples=512,
                corrections=corrections,
                output_name="final.png"
            )

            if not final_path:
                return {
                    "error":  "Blender produced no final output",
                    "issues": corrections.get("issues", [])
                }

            with open(final_path, "rb") as f:
                return {
                    "image_base64": base64.b64encode(f.read()).decode(),
                    "status":       "ok",
                    "claude_notes": corrections.get("issues", []),
                }

        except subprocess.TimeoutExpired:
            return {"error": "Timed out (600s limit)"}
        except Exception as e:
            import traceback
            return {"error": str(e), "traceback": traceback.format_exc()}


runpod.serverless.start({"handler": handler})
