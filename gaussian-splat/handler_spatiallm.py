"""
handler_spatiallm.py — RunPod Serverless — SpatialLM Floor Plan Extraction
===========================================================================
Input:  { ply_base64: str } OR { ply_url: str }
Output: { walls, doors, windows, objects, bounds }
"""

import runpod
import os
import sys
import math
import base64
import tempfile
import requests
import numpy as np
from plyfile import PlyData

_model = None
_tokenizer = None

REPO_DIR = "/workspace/SpatialLM"
MODEL_ID  = "manycore-research/SpatialLM1.1-Llama-1B"


def _ensure_model():
    global _model, _tokenizer
    if _model is not None:
        return
    sys.path.insert(0, REPO_DIR)
    import spatiallm
    import spatiallm.model  # registers spatiallm_qwen with AutoConfig
    from transformers import AutoModelForCausalLM, AutoTokenizer
    print("[SpatialLM] Loading model...")
    _tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    _model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        device_map="cuda",
        torch_dtype="auto",
    )
    print("[SpatialLM] Model ready.")


def _load_ply(path: str):
    plydata = PlyData.read(path)
    verts = plydata["vertex"]
    names = verts.data.dtype.names

    xyz = np.stack([
        np.asarray(verts["x"], dtype=np.float32),
        np.asarray(verts["y"], dtype=np.float32),
        np.asarray(verts["z"], dtype=np.float32),
    ], axis=1)

    if "red" in names and "green" in names and "blue" in names:
        rgb = np.stack([
            np.asarray(verts["red"],   dtype=np.float32) / 255.0,
            np.asarray(verts["green"], dtype=np.float32) / 255.0,
            np.asarray(verts["blue"],  dtype=np.float32) / 255.0,
        ], axis=1)
    elif "f_dc_0" in names:
        C0 = 0.28209479177387814
        f_dc = np.stack([
            np.asarray(verts["f_dc_0"], dtype=np.float32),
            np.asarray(verts["f_dc_1"], dtype=np.float32),
            np.asarray(verts["f_dc_2"], dtype=np.float32),
        ], axis=1)
        rgb = np.clip(0.5 + C0 * f_dc, 0.0, 1.0)
    else:
        rgb = np.ones_like(xyz)

    return xyz, rgb


def _clean_pcd(xyz: np.ndarray, rgb: np.ndarray):
    """Statistical outlier removal + voxel downsampling in pure numpy."""
    from scipy.spatial import KDTree

    # Statistical outlier removal
    tree = KDTree(xyz)
    dists, _ = tree.query(xyz, k=21)
    mean_dists = dists[:, 1:].mean(axis=1)
    threshold = mean_dists.mean() + 2.0 * mean_dists.std()
    mask = mean_dists < threshold
    xyz, rgb = xyz[mask], rgb[mask]

    # Voxel downsampling at 2 cm
    voxel_size = 0.02
    voxel_ids = np.floor(xyz / voxel_size).astype(np.int32)
    _, unique_idx = np.unique(voxel_ids, axis=0, return_index=True)
    return xyz[unique_idx], rgb[unique_idx]


def _orient_z_up(xyz: np.ndarray, rgb: np.ndarray):
    ranges = xyz.max(axis=0) - xyz.min(axis=0)
    vertical_axis = int(np.argmin(ranges))

    if vertical_axis == 2:
        return xyz, rgb

    if vertical_axis == 1:
        R = np.array([[1,0,0],[0,0,-1],[0,1,0]], dtype=np.float32)
    else:
        R = np.array([[0,1,0],[0,0,1],[1,0,0]], dtype=np.float32)

    return (xyz @ R.T), rgb


def _run_spatiallm(xyz: np.ndarray, rgb: np.ndarray) -> dict:
    sys.path.insert(0, REPO_DIR)
    from inference import generate_layout, preprocess_point_cloud
    import spatiallm

    template = os.path.join(os.path.dirname(os.path.dirname(spatiallm.__file__)), "code_template.txt")

    pc_tensor = preprocess_point_cloud(
        points=xyz, colors=rgb,
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
    walls = []
    wall_dirs = {}

    for i, w in enumerate(layout.walls):
        wid = f"wall_{i}"
        sx, sy = float(w.ax), float(w.ay)
        ex, ey = float(w.bx), float(w.by)
        walls.append({"id": wid, "start": [sx, sy], "end": [ex, ey], "height": float(w.height)})
        wall_dirs[wid] = math.atan2(ey - sy, ex - sx)

    doors = []
    for d in layout.doors:
        wdir = wall_dirs.get(d.wall_id, 0.0)
        doors.append({
            "position": [float(d.position_x), float(d.position_y)],
            "width":    float(d.width),
            "wall_dir": wdir + math.pi / 2,
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

    if walls:
        all_x = [w["start"][0] for w in walls] + [w["end"][0] for w in walls]
        all_y = [w["start"][1] for w in walls] + [w["end"][1] for w in walls]
        bounds = {"min_x": min(all_x), "min_y": min(all_y),
                  "max_x": max(all_x), "max_y": max(all_y),
                  "width": max(all_x)-min(all_x), "height": max(all_y)-min(all_y)}
    else:
        bounds = {"min_x": 0, "min_y": 0, "max_x": 10, "max_y": 10, "width": 10, "height": 10}

    return {"walls": walls, "doors": doors, "windows": windows, "objects": objects, "bounds": bounds}


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
        print("[SpatialLM] Loading PLY...")
        xyz, rgb = _load_ply(ply_path)
        print(f"[SpatialLM] {len(xyz):,} raw points")

        xyz, rgb = _clean_pcd(xyz, rgb)
        print(f"[SpatialLM] {len(xyz):,} cleaned points")

        xyz, rgb = _orient_z_up(xyz, rgb)
        result = _run_spatiallm(xyz, rgb)

        print(f"[SpatialLM] {len(result['walls'])} walls  "
              f"{len(result['doors'])} doors  "
              f"{len(result['objects'])} objects")
        return result

    finally:
        os.remove(ply_path)


runpod.serverless.start({"handler": handler})
