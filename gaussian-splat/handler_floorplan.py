"""
handler_floorplan.py — RunPod Serverless — RoomFormer Floor Plan Extraction
============================================================================
100 % commercially-licensed stack:
  RoomFormer (MIT)  ·  numpy / scipy (BSD)  ·  plyfile (BSD)

Input:  { ply_base64: str } | { ply_url: str }
        Optional: { detected_objects: [{label,x,y,z,w,d}] }
Output: { walls, doors, windows, objects, bounds }
"""

import runpod, os, sys, base64, tempfile, math, types, requests
import numpy as np
from plyfile import PlyData
import torch
from scipy.ndimage import gaussian_filter, sobel, binary_fill_holes, binary_erosion

REPO_DIR     = "/workspace/RoomFormer"
CKPT_PATH    = "/workspace/roomformer_stru3d.pth"
DENSITY_SIZE = 256

_model  = None
_device = None


# ── PLY loading ───────────────────────────────────────────────────────────────

def _load_ply(path):
    plydata = PlyData.read(path)
    verts   = plydata["vertex"]
    return np.stack([
        np.asarray(verts["x"], dtype=np.float32),
        np.asarray(verts["y"], dtype=np.float32),
        np.asarray(verts["z"], dtype=np.float32),
    ], axis=1)


# ── geometry helpers ──────────────────────────────────────────────────────────

def _orient_z_up(xyz):
    """Rotate point cloud so the vertical axis becomes Z."""
    ranges = xyz.max(axis=0) - xyz.min(axis=0)
    axis   = int(np.argmin(ranges))
    if axis == 2:
        R = np.eye(3, dtype=np.float32)
    elif axis == 1:
        R = np.array([[1,0,0],[0,0,-1],[0,1,0]], dtype=np.float32)
    else:
        R = np.array([[0,1,0],[0,0,1],[1,0,0]], dtype=np.float32)
    return (xyz @ R.T), R


def _filter_wall_band(xyz):
    """Keep points between 20–70 % of room height — a tighter midpoint band
    that captures wall surfaces while avoiding floor/ceiling clutter."""
    z  = xyz[:, 2]
    lo = np.percentile(z, 20)
    hi = np.percentile(z, 70)
    band = xyz[(z >= lo) & (z <= hi)]
    if len(band) < 100:
        # Widen band if too few points survive
        lo = np.percentile(z, 5)
        hi = np.percentile(z, 95)
        band = xyz[(z >= lo) & (z <= hi)]
    return band


def _make_density_map(xyz, size=DENSITY_SIZE):
    """Project XY to a top-down log-density image in [0, 1].
    Returns (raw_density, edge_map, min_xy, range_xy).
    edge_map = Sobel-enhanced version for RoomFormer (wall outlines).
    raw_density = filled blob for fallback outline extraction."""
    xy       = xyz[:, :2]
    min_xy   = xy.min(axis=0)
    range_xy = float((xy.max(axis=0) - min_xy).max())

    xi = np.clip(((xy[:, 0] - min_xy[0]) / (range_xy + 1e-6) * (size - 1)).astype(np.int32), 0, size - 1)
    yi = np.clip(((xy[:, 1] - min_xy[1]) / (range_xy + 1e-6) * (size - 1)).astype(np.int32), 0, size - 1)

    raw = np.zeros((size, size), dtype=np.float32)
    np.add.at(raw, (yi, xi), 1.0)
    raw = np.log1p(raw)
    raw /= (raw.max() + 1e-6)

    # Sobel edge detection: turns a filled room blob into wall outlines
    smoothed = gaussian_filter(raw, sigma=2.0)
    sx = sobel(smoothed, axis=0)
    sy = sobel(smoothed, axis=1)
    edges = np.hypot(sx, sy)
    edges /= (edges.max() + 1e-6)

    return raw, edges, min_xy, range_xy


# ── model loading ─────────────────────────────────────────────────────────────

def _ensure_model():
    global _model, _device
    if _model is not None:
        return

    # diff_ras is only used by the training loss — stub it out for inference.
    # Use MagicMock (auto-creates any attribute) with __path__ so Python treats
    # it as a package and `from diff_ras.polygon import SoftPolygon` succeeds.
    from unittest.mock import MagicMock
    for mod in ("diff_ras", "diff_ras.polygon", "diff_ras.polygon_rasterize"):
        if mod not in sys.modules:
            m = MagicMock()
            m.__path__ = []
            sys.modules[mod] = m

    # Compile the deformable attention CUDA extension at first startup.
    # Done here (runtime) rather than at Docker build time because CI runners
    # have no GPU. The .so is cached in the worker container for its lifetime.
    import glob, subprocess
    ops_dir = os.path.join(REPO_DIR, "models", "ops")
    if not glob.glob(os.path.join(ops_dir, "MultiScaleDeformableAttention*.so")):
        print("[FP] Compiling MultiScaleDeformableAttention CUDA extension…")
        subprocess.run(
            [sys.executable, "setup.py", "build_ext", "--inplace"],
            cwd=ops_dir, check=True,
            env={**os.environ, "TORCH_CUDA_ARCH_LIST": "8.0;8.6;8.9+PTX"},
        )
        print("[FP] CUDA extension compiled.")

    # models/ops must be on sys.path so the compiled .so is importable
    ops_dir = os.path.join(REPO_DIR, "models", "ops")
    if ops_dir not in sys.path:
        sys.path.insert(0, ops_dir)

    # Add vendored detectron2 that ships inside RoomFormer repo
    det2_path = os.path.join(REPO_DIR, "detectron2")
    if os.path.isdir(det2_path) and det2_path not in sys.path:
        sys.path.insert(0, det2_path)

    sys.path.insert(0, REPO_DIR)
    from models import build_model

    args = types.SimpleNamespace(
        # backbone
        backbone            = "resnet50",
        dilation            = False,
        lr_backbone         = 0,
        # transformer
        position_embedding  = "sine",
        num_feature_levels  = 4,
        hidden_dim          = 256,
        nheads              = 8,
        enc_layers          = 6,
        dec_layers          = 6,
        dim_feedforward     = 1024,
        dropout             = 0.1,
        enc_n_points        = 4,
        dec_n_points        = 4,
        # room queries
        num_queries         = 800,
        num_polys           = 20,
        query_pos_type      = "sine",
        with_poly_refine    = True,
        masked_attn         = False,
        semantic_classes    = -1,
        # loss coefficients (build_model reads these even at inference)
        cls_loss_coef       = 1.0,
        room_cls_loss_coef  = 1.0,
        coords_loss_coef    = 5.0,
        raster_loss_coef    = 1.0,
        # misc flags
        masks               = False,
        aux_loss            = False,
        two_stage           = False,
        pre_norm            = False,
        with_grad_checkpoint= False,
        device              = "cuda" if torch.cuda.is_available() else "cpu",
    )

    _device = torch.device(args.device)
    print("[FP] Building RoomFormer model…")
    model = build_model(args, train=False)

    ckpt = torch.load(CKPT_PATH, map_location="cpu")
    model.load_state_dict(ckpt["model"], strict=False)
    model.to(_device).eval()
    _model = model
    print("[FP] RoomFormer ready.")


# ── inference ─────────────────────────────────────────────────────────────────

def _run_roomformer(edge_map):
    """Run RoomFormer on a (H, W) Sobel edge map.
    Returns a list of polygon arrays, each (N, 2) in pixel coordinates."""
    from shapely.geometry import Polygon as ShapePoly

    # ResNet-50 backbone expects 3-channel input
    img = torch.tensor(edge_map, dtype=torch.float32)           # (H, W)
    img = img.unsqueeze(0).expand(3, -1, -1).contiguous()       # (3, H, W)

    # Use RoomFormer's NestedTensor helper (handles padding + mask for the model)
    try:
        from util.misc import nested_tensor_from_tensor_list
        samples = nested_tensor_from_tensor_list([img]).to(_device)
    except Exception as e:
        print(f"[FP] nested_tensor fallback ({e}): wrapping manually")
        # Manual fallback: NestedTensor-like structure the model also accepts
        samples = img.unsqueeze(0).to(_device)  # (1, 3, H, W)

    with torch.no_grad():
        outputs = _model(samples)

    pred_logits = outputs["pred_logits"][0]   # (num_polys, num_q, 1)
    pred_coords = outputs["pred_coords"][0]   # (num_polys, num_q, 2)

    polys = []
    for room_logits, room_coords in zip(pred_logits, pred_coords):
        fg = torch.sigmoid(room_logits.squeeze(-1)) > 0.5
        if fg.sum() < 3:
            continue
        corners = np.array((room_coords[fg] * (DENSITY_SIZE - 1)).cpu().tolist(), dtype=np.float32)
        corners = np.around(corners).astype(np.int32)
        if len(corners) >= 4:
            area = ShapePoly(corners).area
            # Require at least 0.5% of map area to filter noise
            if area >= DENSITY_SIZE * DENSITY_SIZE * 0.005:
                polys.append(corners)

    return polys


# ── coordinate conversion ─────────────────────────────────────────────────────

def _polys_to_walls(polys, min_xy, range_xy, room_height):
    walls = []
    wid   = 0
    size  = DENSITY_SIZE - 1
    for poly in polys:
        n = len(poly)
        for i in range(n):
            p1 = poly[i]
            p2 = poly[(i + 1) % n]
            sx = float(p1[0]) / size * range_xy + float(min_xy[0])
            sy = float(p1[1]) / size * range_xy + float(min_xy[1])
            ex = float(p2[0]) / size * range_xy + float(min_xy[0])
            ey = float(p2[1]) / size * range_xy + float(min_xy[1])
            if math.hypot(ex - sx, ey - sy) < 0.05:
                continue
            walls.append({
                "id":     f"wall_{wid}",
                "start":  [sx, sy],
                "end":    [ex, ey],
                "height": float(room_height),
            })
            wid += 1
    return walls


def _compute_bounds(walls, min_xy, range_xy):
    if walls:
        all_x = [w["start"][0] for w in walls] + [w["end"][0] for w in walls]
        all_y = [w["start"][1] for w in walls] + [w["end"][1] for w in walls]
        return {
            "min_x": min(all_x), "min_y": min(all_y),
            "max_x": max(all_x), "max_y": max(all_y),
            "width": max(all_x) - min(all_x),
            "height": max(all_y) - min(all_y),
        }
    mx = float(min_xy[0]) + range_xy
    my = float(min_xy[1]) + range_xy
    return {
        "min_x": float(min_xy[0]), "min_y": float(min_xy[1]),
        "max_x": mx, "max_y": my,
        "width": range_xy, "height": range_xy,
    }


def _outline_to_walls(raw_density, min_xy, range_xy, room_height):
    """Extract room shapes from the density blob using OpenCV contours.
    Processes ALL significant contours so multi-room scans render correctly."""
    try:
        import cv2
    except ImportError:
        return None

    size = DENSITY_SIZE
    occupied = (raw_density > 0.05).astype(np.uint8) * 255
    occupied = binary_fill_holes(occupied > 0).astype(np.uint8) * 255

    # Morphological closing to connect nearby blobs within ~1 pixel gap
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    occupied = cv2.morphologyEx(occupied, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(occupied, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    # Keep all contours above 1% of total map area (filters noise specks)
    min_area = size * size * 0.01
    significant = [c for c in contours if cv2.contourArea(c) >= min_area]
    if not significant:
        # Fall back to just the largest
        significant = [max(contours, key=cv2.contourArea)]

    print(f"[FP] Outline fallback: {len(significant)} region(s) from contour extraction")

    s    = float(size - 1)
    walls = []
    wid  = 0
    for contour in significant:
        peri   = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.015 * peri, True)
        pts    = approx.squeeze()
        if pts.ndim != 2 or len(pts) < 3:
            continue
        for i in range(len(pts)):
            p1 = pts[i]
            p2 = pts[(i + 1) % len(pts)]
            sx = float(p1[0]) / s * range_xy + float(min_xy[0])
            sy = float(p1[1]) / s * range_xy + float(min_xy[1])
            ex = float(p2[0]) / s * range_xy + float(min_xy[0])
            ey = float(p2[1]) / s * range_xy + float(min_xy[1])
            if math.hypot(ex - sx, ey - sy) < 0.05:
                continue
            walls.append({
                "id":     f"wall_{wid}",
                "start":  [sx, sy],
                "end":    [ex, ey],
                "height": float(room_height),
            })
            wid += 1
    return walls if walls else None


def _bounding_box_walls(min_xy, range_xy, room_height):
    """Last-resort fallback: rectangular room outline from point cloud extents."""
    x0, y0 = float(min_xy[0]), float(min_xy[1])
    x1, y1 = x0 + range_xy, y0 + range_xy
    h = float(room_height)
    return [
        {"id": "wall_0", "start": [x0, y0], "end": [x1, y0], "height": h},
        {"id": "wall_1", "start": [x1, y0], "end": [x1, y1], "height": h},
        {"id": "wall_2", "start": [x1, y1], "end": [x0, y1], "height": h},
        {"id": "wall_3", "start": [x0, y1], "end": [x0, y0], "height": h},
    ]


# ── room polygon output ───────────────────────────────────────────────────────

ROOM_RULES = [
    ("Bathroom",    ["toilet", "bathtub", "shower", "bath", "sink"]),
    ("Kitchen",     ["refrigerator", "fridge", "oven", "stove", "microwave", "counter"]),
    ("Bedroom",     ["bed"]),
    ("Living Room", ["sofa", "couch", "tv", "television", "coffee"]),
    ("Dining Room", ["dining"]),
    ("Office",      ["desk", "computer", "monitor", "bookshelf"]),
]


def _classify_room(poly_m, objects, idx):
    from shapely.geometry import Polygon as ShapePoly, Point
    try:
        sp = ShapePoly(poly_m)
    except Exception:
        return f"Room {idx + 1}"

    inside_labels = []
    for o in objects:
        try:
            pt = Point(o["center"][0], o["center"][1])
            if sp.contains(pt) or sp.distance(pt) < 0.5:
                inside_labels.append(o["class"].lower())
        except Exception:
            pass

    for label, keys in ROOM_RULES:
        if any(k in lbl for k in keys for lbl in inside_labels):
            return label
    return f"Room {idx + 1}"


def _polys_to_rooms(polys, min_xy, range_xy, objects):
    """Convert RoomFormer pixel polygons to rooms JSON (metres)."""
    from shapely.geometry import Polygon as ShapePoly
    rooms = []
    size  = float(DENSITY_SIZE - 1)
    for idx, poly_px in enumerate(polys):
        poly_m = [
            [float(pt[0]) / size * range_xy + float(min_xy[0]),
             float(pt[1]) / size * range_xy + float(min_xy[1])]
            for pt in poly_px
        ]
        if len(poly_m) < 3:
            continue
        try:
            area_m2 = max(1, round(ShapePoly(poly_m).area))
        except Exception:
            area_m2 = 1
        rooms.append({
            "label": _classify_room(poly_m, objects, idx),
            "poly":  poly_m,
            "area":  area_m2,
        })

    # If 2+ bedrooms, promote largest to Master Bedroom
    beds = [r for r in rooms if r["label"] == "Bedroom"]
    if len(beds) >= 2:
        largest = max(beds, key=lambda r: r["area"])
        largest["label"] = "Master Bedroom"

    return rooms


# ── handler ───────────────────────────────────────────────────────────────────

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

        xyz = _load_ply(ply_path)
        print(f"[FP] {len(xyz):,} raw points")
        if len(xyz) < 100:
            return {"error": f"Point cloud too sparse ({len(xyz)} pts)"}

        xyz, orient_R = _orient_z_up(xyz)

        # Room height (clip to plausible range)
        room_height = float(np.clip(xyz[:, 2].max() - xyz[:, 2].min(), 2.0, 4.0))
        print(f"[FP] room_height={room_height:.2f}m  total_z_span={xyz[:,2].max()-xyz[:,2].min():.2f}")

        # Tighter wall band (20–70% of Z) for cleaner mid-height cross-section
        xyz_walls = _filter_wall_band(xyz)
        print(f"[FP] {len(xyz_walls):,} points in wall band")

        raw_density, edge_map, min_xy, range_xy = _make_density_map(xyz_walls)
        print(f"[FP] Density map: {(raw_density > 0.05).sum()} occupied px, "
              f"range_xy={range_xy:.2f}m")
        print("[FP] Running RoomFormer on edge-enhanced map…")

        polys = _run_roomformer(edge_map)
        print(f"[FP] {len(polys)} room polygon(s) found")

        walls = _polys_to_walls(polys, min_xy, range_xy, room_height)

        if not walls:
            print("[FP] RoomFormer found no walls — trying contour outline fallback…")
            walls = _outline_to_walls(raw_density, min_xy, range_xy, room_height)

        if not walls:
            print("[FP] Contour fallback failed — using bounding-box fallback")
            walls = _bounding_box_walls(min_xy, range_xy, room_height)

        bounds = _compute_bounds(walls, min_xy, range_xy)

        # Merge Grounding DINO objects from the scan step
        scan_objects = inp.get("detected_objects", [])
        objects = []
        b = bounds
        margin_x = (b["max_x"] - b["min_x"]) * 0.2
        margin_y = (b["max_y"] - b["min_y"]) * 0.2
        for o in scan_objects:
            pos   = np.array([o["x"], o["y"], o["z"]], dtype=np.float32)
            pos_r = orient_R @ pos
            fx, fy = float(pos_r[0]), float(pos_r[1])
            if not (b["min_x"] - margin_x <= fx <= b["max_x"] + margin_x and
                    b["min_y"] - margin_y <= fy <= b["max_y"] + margin_y):
                continue
            objects.append({
                "class":    o["label"],
                "center":   [fx, fy],
                "rotation": 0.0,
                "scale":    [o.get("w", 0.5), o.get("d", 0.5)],
            })

        # Build room polygons from RoomFormer output (preferred by frontend over DCEL fallback)
        rooms = _polys_to_rooms(polys, min_xy, range_xy, objects) if polys else []

        print(f"[FP] {len(rooms)} rooms  {len(walls)} walls  {len(objects)} objects")
        return {
            "rooms":   rooms,
            "walls":   walls,
            "doors":   [],
            "windows": [],
            "objects": objects,
            "bounds":  bounds,
        }

    finally:
        os.remove(ply_path)


runpod.serverless.start({"handler": handler})
