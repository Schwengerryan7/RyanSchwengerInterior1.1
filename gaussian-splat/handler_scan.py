"""
handler_scan.py — RunPod Serverless — Video → Dense Point Cloud
===============================================================
Pipeline:
  1. COLMAP sparse SfM → camera poses + metric scale reference
  2. DepthAnything v2 Small → dense depth map per frame (GPU)
  3. Scale-align relative depth to COLMAP metric using sparse anchor points
  4. Back-project every pixel to world 3D
  5. Voxel downsample → 100k-300k dense colored points
  6. Return PLY → SpatialLM floor plan endpoint

This gives Matterport-quality point clouds from plain iPhone video.

Input:  { images_base64: [str, ...] }
Output: { ply_base64: str, point_count: int }
"""

import runpod, base64, os, io, tempfile, subprocess
import numpy as np
from PIL import Image
import struct
import torch

IMG_W, IMG_H = 960, 720
STRIDE       = 4        # sample every 4th pixel per frame (~43k pts/frame)
MAX_DEPTH    = 8.0      # metres — clip far background
VOXEL_SIZE   = 0.02     # 2 cm voxels
MAX_PTS      = 300_000  # final cap before returning

_da_model     = None
_da_processor = None


# ─── subprocess helper ───────────────────────────────────────────────────────

def run_cmd(cmd, timeout, env):
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, cmd, stdout, stderr)
        return stdout, stderr
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise subprocess.CalledProcessError(-1, cmd, b'', b'timeout')


# ─── COLMAP SfM ──────────────────────────────────────────────────────────────

def run_colmap(image_dir, workspace):
    db     = os.path.join(workspace, "db.db")
    sparse = os.path.join(workspace, "sparse")
    os.makedirs(sparse, exist_ok=True)
    env    = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}

    run_cmd(["colmap", "feature_extractor",
             "--database_path", db, "--image_path", image_dir,
             "--ImageReader.single_camera", "1",
             "--SiftExtraction.use_gpu", "0"],
            timeout=120, env=env)

    run_cmd(["colmap", "sequential_matcher",
             "--database_path", db,
             "--SiftMatching.use_gpu", "0",
             "--SequentialMatching.overlap", "15"],
            timeout=120, env=env)

    run_cmd(["colmap", "mapper",
             "--database_path", db, "--image_path", image_dir,
             "--output_path", sparse, "--Mapper.num_threads", "4"],
            timeout=300, env=env)

    recon_dirs = sorted(
        [d for d in os.listdir(sparse)
         if os.path.isdir(os.path.join(sparse, d)) and d.isdigit()],
        key=int)
    if not recon_dirs:
        raise subprocess.CalledProcessError(
            1, "colmap mapper",
            stderr=b"Mapper produced no reconstruction - try a slower walkthrough.")
    recon_dir = os.path.join(sparse, recon_dirs[0])

    run_cmd(["colmap", "model_converter",
             "--input_path", recon_dir, "--output_path", recon_dir,
             "--output_type", "TXT"],
            timeout=60, env=env)

    return recon_dir


def extract_sparse_points(sparse_dir):
    pts, clr = [], []
    with open(os.path.join(sparse_dir, "points3D.txt")) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            p = line.split()
            pts.append([float(p[1]), float(p[2]), float(p[3])])
            clr.append([int(p[4]), int(p[5]), int(p[6])])
    return np.array(pts, dtype=np.float32), np.array(clr, dtype=np.uint8)


# ─── COLMAP text format parsers ──────────────────────────────────────────────

def parse_cameras(cameras_txt):
    """Return {cam_id: {fx, fy, cx, cy}}"""
    cams = {}
    with open(cameras_txt) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            p = line.split()
            cid, model = int(p[0]), p[1]
            params = list(map(float, p[4:]))
            if model == "PINHOLE":
                fx, fy, cx, cy = params[0], params[1], params[2], params[3]
            else:
                fx = fy = params[0]; cx, cy = params[1], params[2]
            cams[cid] = dict(fx=fx, fy=fy, cx=cx, cy=cy)
    return cams


def quat_to_rot(qw, qx, qy, qz):
    return np.array([
        [1-2*(qy**2+qz**2),  2*(qx*qy-qw*qz),  2*(qx*qz+qw*qy)],
        [2*(qx*qy+qw*qz),  1-2*(qx**2+qz**2),  2*(qy*qz-qw*qx)],
        [2*(qx*qz-qw*qy),  2*(qy*qz+qw*qx),  1-2*(qx**2+qy**2)],
    ], dtype=np.float32)


def parse_images_txt(images_txt):
    """Return {image_name: {cam_id, R(3x3), T(3)}}"""
    result = {}
    with open(images_txt) as f:
        lines = [l for l in f if not l.startswith("#") and l.strip()]
    i = 0
    while i + 1 < len(lines):
        p = lines[i].split()
        qw, qx, qy, qz = float(p[1]), float(p[2]), float(p[3]), float(p[4])
        tx, ty, tz     = float(p[5]), float(p[6]), float(p[7])
        cam_id, name   = int(p[8]), p[9]
        result[name] = dict(
            cam_id=cam_id,
            R=quat_to_rot(qw, qx, qy, qz),
            T=np.array([tx, ty, tz], dtype=np.float32),
        )
        i += 2   # skip the POINTS2D line
    return result


# ─── DepthAnything v2 ────────────────────────────────────────────────────────

def ensure_depth_model():
    global _da_model, _da_processor
    if _da_model is not None:
        return
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation
    print("[scan] Loading DepthAnything v2 Small…")
    _da_processor = AutoImageProcessor.from_pretrained(
        "depth-anything/Depth-Anything-V2-Small-hf")
    _da_model = AutoModelForDepthEstimation.from_pretrained(
        "depth-anything/Depth-Anything-V2-Small-hf",
        torch_dtype=torch.float16,
    ).to("cuda").eval()
    print("[scan] DepthAnything ready.")


def estimate_depth(img_pil):
    """Return HxW float32 relative depth (0-1 normalized)."""
    inputs = _da_processor(images=img_pil, return_tensors="pt")
    inputs = {k: v.to("cuda", dtype=torch.float16) for k, v in inputs.items()}
    with torch.no_grad():
        depth = _da_model(**inputs).predicted_depth.squeeze().cpu().float().numpy()
    d_min, d_max = depth.min(), depth.max()
    return (depth - d_min) / (d_max - d_min + 1e-6)


# ─── Scale alignment ─────────────────────────────────────────────────────────

def align_scale(da_depth, cam, R, T, sparse_pts):
    """
    Fit: metric_depth = s * da_value + t
    using sparse COLMAP points projected into this camera as anchors.
    Returns (s, t) or (None, None) if not enough anchor points.
    """
    da_h, da_w = da_depth.shape
    fx, fy, cx, cy = cam["fx"], cam["fy"], cam["cx"], cam["cy"]
    da_vals, metric_vals = [], []

    for pt in sparse_pts:
        pt_cam = R @ pt + T
        if pt_cam[2] <= 0.1:
            continue
        u = fx * pt_cam[0] / pt_cam[2] + cx
        v = fy * pt_cam[1] / pt_cam[2] + cy
        if not (0 <= u < IMG_W and 0 <= v < IMG_H):
            continue
        u_da = int(u * da_w / IMG_W)
        v_da = int(v * da_h / IMG_H)
        da_vals.append(da_depth[v_da, u_da])
        metric_vals.append(pt_cam[2])

    if len(da_vals) < 5:
        return None, None

    A = np.stack([np.array(da_vals), np.ones(len(da_vals))], axis=1)
    (s, t), *_ = np.linalg.lstsq(A, np.array(metric_vals), rcond=None)
    return (float(s), float(t)) if s > 0 else (None, None)


# ─── Back-projection ─────────────────────────────────────────────────────────

def backproject_frame(da_depth, img_pil, cam, R, T, s, t):
    """
    Project depth map pixels to world 3D.
    COLMAP: x_cam = R @ x_world + T  →  x_world = R.T @ (x_cam - T)
    Sample every STRIDE pixels to keep point count manageable.
    """
    fx, fy, cx, cy = cam["fx"], cam["fy"], cam["cx"], cam["cy"]
    da_h, da_w = da_depth.shape

    v_s, u_s = np.mgrid[0:IMG_H:STRIDE, 0:IMG_W:STRIDE].astype(np.float32)

    # Scale relative depth to metric
    u_da = (u_s * da_w / IMG_W).astype(int).clip(0, da_w-1)
    v_da = (v_s * da_h / IMG_H).astype(int).clip(0, da_h-1)
    z = (s * da_depth[v_da, u_da] + t).astype(np.float32)

    # Camera-space coords
    x_c = (u_s - cx) * z / fx
    y_c = (v_s - cy) * z / fy
    pts_cam = np.stack([x_c.ravel(), y_c.ravel(), z.ravel()], axis=1)

    # World-space coords
    pts_world = (R.T @ (pts_cam - T).T).T

    # Colors — sample same grid from image
    rgb_arr = np.array(img_pil)
    rgb = rgb_arr[v_s.astype(int).ravel().clip(0, IMG_H-1),
                  u_s.astype(int).ravel().clip(0, IMG_W-1)]

    valid = (z.ravel() > 0.1) & (z.ravel() < MAX_DEPTH)
    return pts_world[valid].astype(np.float32), rgb[valid]


# ─── Voxel downsample ────────────────────────────────────────────────────────

def voxel_downsample(pts, clr, voxel_size=VOXEL_SIZE):
    vids = np.floor(pts / voxel_size).astype(np.int32)
    _, idx = np.unique(vids, axis=0, return_index=True)
    return pts[idx], clr[idx]


# ─── PLY writer ──────────────────────────────────────────────────────────────

def write_ply(points, colors):
    N = len(points)
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {N}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\n"
        "end_header\n"
    )
    buf = io.BytesIO()
    buf.write(header.encode())
    for i in range(N):
        buf.write(struct.pack('<fff', *points[i]))
        buf.write(struct.pack('<BBB', *colors[i]))
    return buf.getvalue()


# ─── Handler ─────────────────────────────────────────────────────────────────

def handler(job):
    images_b64 = job["input"]["images_base64"]
    print(f"[scan] {len(images_b64)} frames received")

    with tempfile.TemporaryDirectory() as workspace:
        image_dir = os.path.join(workspace, "images")
        os.makedirs(image_dir)

        frames = []
        for i, b64 in enumerate(images_b64):
            img = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
            img = img.resize((IMG_W, IMG_H))
            name = f"{i:04d}.jpg"
            img.save(os.path.join(image_dir, name), quality=90)
            frames.append((name, img))

        # Step 1 — COLMAP sparse SfM (camera poses + metric scale anchors)
        print("[scan] COLMAP sparse SfM…")
        try:
            sparse_dir = run_colmap(image_dir, workspace)
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode()[:500] if isinstance(e.stderr, bytes) else str(e)
            return {"error": f"COLMAP failed: {err}"}

        sparse_pts, _ = extract_sparse_points(sparse_dir)
        cameras        = parse_cameras(os.path.join(sparse_dir, "cameras.txt"))
        images_data    = parse_images_txt(os.path.join(sparse_dir, "images.txt"))
        print(f"[scan] COLMAP: {len(sparse_pts):,} sparse pts, {len(images_data)} registered frames")

        if len(images_data) < 5 or len(sparse_pts) < 50:
            return {"error": "Too few frames registered by COLMAP - try a slower walkthrough"}

        # Step 2 — DepthAnything dense depth estimation
        try:
            ensure_depth_model()
        except Exception as e:
            return {"error": f"Failed to load DepthAnything: {e}"}

        all_pts, all_clr = [], []
        aligned, skipped = 0, 0

        for name, img_pil in frames:
            if name not in images_data:
                continue
            d = images_data[name]
            cam, R, T = cameras[d["cam_id"]], d["R"], d["T"]

            da_depth = estimate_depth(img_pil)
            s, t = align_scale(da_depth, cam, R, T, sparse_pts)
            if s is None:
                skipped += 1
                continue

            pts, clr = backproject_frame(da_depth, img_pil, cam, R, T, s, t)
            all_pts.append(pts)
            all_clr.append(clr)
            aligned += 1

        print(f"[scan] {aligned} frames depth-aligned, {skipped} skipped")

        if not all_pts:
            # Fallback: return sparse points so pipeline doesn't die
            print("[scan] Depth alignment failed — returning sparse fallback")
            ply_bytes = write_ply(sparse_pts, np.ones((len(sparse_pts), 3), dtype=np.uint8) * 180)
            return {"ply_base64": base64.b64encode(ply_bytes).decode(),
                    "point_count": len(sparse_pts)}

        pts_all = np.concatenate(all_pts, axis=0)
        clr_all = np.concatenate(all_clr, axis=0)
        print(f"[scan] Raw merged: {len(pts_all):,} points")

        pts_ds, clr_ds = voxel_downsample(pts_all, clr_all)
        print(f"[scan] After {int(VOXEL_SIZE*100)}cm voxel: {len(pts_ds):,} points")

        if len(pts_ds) > MAX_PTS:
            idx = np.random.choice(len(pts_ds), MAX_PTS, replace=False)
            pts_ds, clr_ds = pts_ds[idx], clr_ds[idx]
            print(f"[scan] Capped to {MAX_PTS:,} points")

        ply_bytes = write_ply(pts_ds, clr_ds)
        ply_b64   = base64.b64encode(ply_bytes).decode()

    return {"ply_base64": ply_b64, "point_count": len(pts_ds)}


runpod.serverless.start({"handler": handler})
