"""
handler_spatiallm.py — RunPod Serverless — SpatialLM Floor Plan Extraction
===========================================================================
Pipeline:
  1. Receive Gaussian Splat .ply (base64 or URL)
  2. Extract XYZ + RGB from GS PLY (SH DC → RGB)
  3. Clean point cloud (outlier removal, voxel downsample)
  4. Rotate to Z-up (nerfstudio Y-up → Z-up)
  5. Run SpatialLM1.1-Qwen-0.5B inference
  6. Parse output: walls, doors, windows, objects
  7. Return structured JSON (2D XY floor plan coordinates in meters)

Input:  { ply_base64: str } OR { ply_url: str }
Output: { walls, doors, windows, objects, bounds }
"""

import runpod
import os
import sys
import math
import base64
import tempfile
import json
import requests
import numpy as np

try:
    import open3d as o3d
    print("[SpatialLM] open3d imported OK")
except Exception as e:
    print(f"[SpatialLM] FATAL: open3d import failed: {e}", file=sys.stderr)
    sys.exit(1)

try:
    from plyfile import PlyData
    print("[SpatialLM] plyfile imported OK")
except Exception as e:
    print(f"[SpatialLM] FATAL: plyfile import failed: {e}", file=sys.stderr)
    sys.exit(1)

# ── Model (loaded once at cold start) ────────────────────────────────────────
_model = None
_tokenizer = None

REPO_DIR = "/workspace/SpatialLM"
MODEL_ID  = "manycore-research/SpatialLM1.1-Qwen-0.5B"


def _ensure_model():
    global _model, _tokenizer
    if _model is not None:
        return
    import sys
    sys.path.insert(0, REPO_DIR)
    import spatiallm
    import spatiallm.model  # triggers AutoConfig.register("spatiallm_qwen", ...)
    from transformers import AutoModelForCausalLM, AutoTokenizer
    print("[SpatialLM] Loading model...")
    _tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    _model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        device_map="cuda",
        torch_dtype="auto",
    )
    print("[SpatialLM] Model ready.")


# ── PLY helpers ───────────────────────────────────────────────────────────────

def _load_ply_path(path: str) -> o3d.geometry.PointCloud:
    """Load GS PLY and return an Open3D point cloud with XYZ + RGB."""
    plydata = PlyData.read(path)
    verts   = plydata["vertex"]
    names   = verts.data.dtype.names

    xyz = np.stack([
        np.asarray(verts["x"], dtype=np.float64),
        np.asarray(verts["y"], dtype=np.float64),
        np.asarray(verts["z"], dtype=np.float64),
    ], axis=1)

    # Prefer standard red/green/blue; fall back to GS SH DC coefficients
    if "red" in names and "green" in names and "blue" in names:
        rgb = np.stack([
            np.asarray(verts["red"],   dtype=np.float64) / 255.0,
            np.asarray(verts["green"], dtype=np.float64) / 255.0,
            np.asarray(verts["blue"],  dtype=np.float64) / 255.0,
        ], axis=1)
    elif "f_dc_0" in names:
        # SH degree-0 coefficient → linear RGB: clamp(0.5 + C0 * sh, 0, 1)
        C0  = 0.28209479177387814
        f_dc = np.stack([
            np.asarray(verts["f_dc_0"], dtype=np.float64),
            np.asarray(verts["f_dc_1"], dtype=np.float64),
            np.asarray(verts["f_dc_2"], dtype=np.float64),
        ], axis=1)
        rgb = np.clip(0.5 + C0 * f_dc, 0.0, 1.0)
    else:
        rgb = np.ones_like(xyz)  # white fallback

    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(xyz)
    pcd.colors = o3d.utility.Vector3dVector(rgb)
    return pcd


def _clean_pcd(pcd: o3d.geometry.PointCloud) -> o3d.geometry.PointCloud:
    """Remove outliers and downsample to a manageable density."""
    pcd, _ = pcd.remove_statistical_outlier(nb_neighbors=20, std_ratio=2.0)
    pcd     = pcd.voxel_down_sample(voxel_size=0.02)   # 2 cm voxels
    return pcd


def _orient_z_up(pcd: o3d.geometry.PointCloud) -> o3d.geometry.PointCloud:
    """
    Rotate so Z is the vertical (up) axis — required by SpatialLM.

    nerfstudio splatfacto typically outputs with Y-up / Z-forward convention.
    Transform: X → X,  Y ↕ (vertical) → new Z,  Z (depth) → new -Y
    If the scene is already Z-up (min-range axis is Z), no rotation is applied.
    """
    pts = np.asarray(pcd.points)
    ranges = pts.max(axis=0) - pts.min(axis=0)   # [Xrange, Yrange, Zrange]
    vertical_axis = int(np.argmin(ranges))         # smallest range = vertical

    if vertical_axis == 2:
        return pcd  # already Z-up

    # Build 3×3 permutation/flip matrix
    if vertical_axis == 1:   # Y is up → swap Y↔Z, flip new-Y
        R = np.array([
            [1,  0,  0],
            [0,  0, -1],
            [0,  1,  0],
        ], dtype=np.float64)
    else:                     # X is up (rare) → cycle axes
        R = np.array([
            [0,  1,  0],
            [0,  0,  1],
            [1,  0,  0],
        ], dtype=np.float64)

    pcd.rotate(R, center=(0, 0, 0))
    return pcd


# ── SpatialLM inference ───────────────────────────────────────────────────────

def _run_spatiallm(pcd: o3d.geometry.PointCloud) -> dict:
    import sys
    sys.path.insert(0, REPO_DIR)
    from inference import generate_layout, preprocess_point_cloud
    from spatiallm import Layout
    import spatiallm

    template = os.path.join(os.path.dirname(os.path.dirname(spatiallm.__file__)), "code_template.txt")

    pts  = np.asarray(pcd.points,  dtype=np.float32)
    cols = np.asarray(pcd.colors,  dtype=np.float32)

    pc_tensor = preprocess_point_cloud(
        points=pts, colors=cols,
        grid_size=8, num_bins=1280,
    )

    layout = generate_layout(
        model=_model,
        point_cloud=pc_tensor,
        tokenizer=_tokenizer,
        code_template_file=template,
        detect_type="all",
        categories=[],
        max_new_tokens=4096,
        top_k=10, top_p=0.95, temperature=0.6, num_beams=1,
    )

    print("[SpatialLM] inference complete")
    return _layout_to_dict(layout)


def _layout_to_dict(layout) -> dict:
    """Convert SpatialLM Layout object → serialisable dict (2D XY, meters)."""
    walls = []
    wall_dirs = {}  # wall_id → angle for door orientation

    for i, w in enumerate(layout.walls):
        wid  = f"wall_{i}"
        sx, sy = float(w.ax), float(w.ay)
        ex, ey = float(w.bx), float(w.by)
        walls.append({
            "id":     wid,
            "start":  [sx, sy],
            "end":    [ex, ey],
            "height": float(w.height),
        })
        wall_dirs[wid] = math.atan2(ey - sy, ex - sx)

    doors = []
    for d in layout.doors:
        wdir = wall_dirs.get(d.wall_id, 0.0)
        door_dir = wdir + math.pi / 2
        doors.append({
            "position": [float(d.position_x), float(d.position_y)],
            "width":    float(d.width),
            "wall_dir": door_dir,
        })

    windows = []
    for win in layout.windows:
        windows.append({
            "position": [float(win.position_x), float(win.position_y)],
            "width":    float(win.width),
        })

    objects = []
    for bbox in layout.bboxes:
        objects.append({
            "class":    bbox.class_name,
            "center":   [float(bbox.position_x), float(bbox.position_y)],
            "rotation": float(bbox.angle_z),
            "scale":    [float(bbox.scale_x), float(bbox.scale_y)],
        })

    # 2-D bounding box over all wall endpoints
    if walls:
        all_x = [w["start"][0] for w in walls] + [w["end"][0] for w in walls]
        all_y = [w["start"][1] for w in walls] + [w["end"][1] for w in walls]
        bounds = {
            "min_x":  min(all_x), "min_y":  min(all_y),
            "max_x":  max(all_x), "max_y":  max(all_y),
            "width":  max(all_x) - min(all_x),
            "height": max(all_y) - min(all_y),
        }
    else:
        bounds = {"min_x": 0, "min_y": 0, "max_x": 10, "max_y": 10, "width": 10, "height": 10}

    return {"walls": walls, "doors": doors, "windows": windows, "objects": objects, "bounds": bounds}


# ── RunPod handler ────────────────────────────────────────────────────────────

def handler(job):
    inp = job["input"]

    with tempfile.NamedTemporaryFile(suffix=".ply", delete=False) as tmp:
        ply_path = tmp.name
        if "ply_base64" in inp:
            tmp.write(base64.b64decode(inp["ply_base64"]))
        elif "ply_url" in inp:
            r = requests.get(inp["ply_url"], timeout=120)
            r.raise_for_status()
            tmp.write(r.content)
        else:
            return {"error": "Provide ply_base64 or ply_url"}

    try:
        _ensure_model()
        print("[SpatialLM] Loading PLY…")
        pcd = _load_ply_path(ply_path)
        print(f"[SpatialLM] {len(pcd.points):,} raw points")

        pcd = _clean_pcd(pcd)
        print(f"[SpatialLM] {len(pcd.points):,} cleaned points")

        pcd = _orient_z_up(pcd)
        result = _run_spatiallm(pcd)

        print(f"[SpatialLM] {len(result['walls'])} walls  "
              f"{len(result['doors'])} doors  "
              f"{len(result['objects'])} objects")
        return result

    finally:
        os.remove(ply_path)


runpod.serverless.start({"handler": handler})
