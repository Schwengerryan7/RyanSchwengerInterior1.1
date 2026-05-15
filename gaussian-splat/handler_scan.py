"""
handler_scan.py — RunPod Serverless — Video → Dense Point Cloud
===============================================================
Pipeline:
  1. Decode input frames (base64 JPEG array from browser)
  2. Run COLMAP SfM → sparse reconstruction (camera poses)
  3. Run COLMAP MVS → dense depth maps → fused point cloud (50k-300k pts)
  4. Return PLY (base64) → SpatialLM floor plan endpoint

Falls back to sparse SfM if MVS fails (e.g. GPU unavailable).

Input:  { images_base64: [str, ...] }
Output: { ply_base64: str, point_count: int, dense: bool }
"""

import runpod, base64, os, io, tempfile, subprocess, signal
import numpy as np
from PIL import Image
import struct


def run_cmd(cmd, timeout, env):
    """Run a command, hard-killing the process if it exceeds timeout."""
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


def run_colmap_sparse(image_dir, workspace):
    db     = os.path.join(workspace, "db.db")
    sparse = os.path.join(workspace, "sparse")
    os.makedirs(sparse, exist_ok=True)

    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}

    run_cmd([
        "colmap", "feature_extractor",
        "--database_path", db,
        "--image_path", image_dir,
        "--ImageReader.single_camera", "1",
        "--SiftExtraction.use_gpu", "0",
    ], timeout=120, env=env)

    run_cmd([
        "colmap", "sequential_matcher",
        "--database_path", db,
        "--SiftMatching.use_gpu", "0",
        "--SequentialMatching.overlap", "15",
    ], timeout=120, env=env)

    run_cmd([
        "colmap", "mapper",
        "--database_path", db,
        "--image_path", image_dir,
        "--output_path", sparse,
        "--Mapper.num_threads", "4",
    ], timeout=300, env=env)

    recon_dirs = sorted([
        d for d in os.listdir(sparse)
        if os.path.isdir(os.path.join(sparse, d)) and d.isdigit()
    ], key=int)
    if not recon_dirs:
        raise subprocess.CalledProcessError(
            1, "colmap mapper",
            stderr=b"Mapper produced no reconstruction — video may move too fast or lack texture."
        )
    recon_dir = os.path.join(sparse, recon_dirs[0])

    run_cmd([
        "colmap", "model_converter",
        "--input_path", recon_dir,
        "--output_path", recon_dir,
        "--output_type", "TXT",
    ], timeout=60, env=env)

    return recon_dir


def _subsample_image_dir(image_dir, workspace, max_frames=20):
    """Copy at most max_frames evenly-spaced images into a new dir for MVS."""
    import shutil
    imgs = sorted(os.listdir(image_dir))
    if len(imgs) <= max_frames:
        return image_dir
    step = len(imgs) / max_frames
    chosen = [imgs[int(i * step)] for i in range(max_frames)]
    mvs_dir = os.path.join(workspace, "mvs_images")
    os.makedirs(mvs_dir, exist_ok=True)
    for name in chosen:
        shutil.copy(os.path.join(image_dir, name), os.path.join(mvs_dir, name))
    return mvs_dir


def run_colmap_dense(image_dir, workspace, sparse_dir):
    """COLMAP MVS: undistort → patch_match_stereo → stereo_fusion → dense PLY.

    Uses xvfb-run for headless OpenGL, 20 frames at 500px, no geom_consistency
    to stay within memory and time limits on a RunPod serverless worker.
    """
    mvs_image_dir = _subsample_image_dir(image_dir, workspace, max_frames=20)
    dense_dir = os.path.join(workspace, "dense")
    os.makedirs(dense_dir, exist_ok=True)
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}

    print("[scan] MVS 1/3: image undistortion…")
    run_cmd([
        "colmap", "image_undistorter",
        "--image_path", mvs_image_dir,
        "--input_path", sparse_dir,
        "--output_path", dense_dir,
        "--output_type", "COLMAP",
        "--max_image_size", "500",
    ], timeout=120, env=env)

    print("[scan] MVS 2/3: patch match stereo…")
    run_cmd([
        "xvfb-run", "-a",
        "colmap", "patch_match_stereo",
        "--workspace_path", dense_dir,
        "--workspace_format", "COLMAP",
        "--PatchMatchStereo.max_image_size", "500",
        "--PatchMatchStereo.geom_consistency", "false",
        "--PatchMatchStereo.gpu_index", "0",
        "--PatchMatchStereo.depth_min", "0.01",
        "--PatchMatchStereo.depth_max", "20",
    ], timeout=240, env=env)

    print("[scan] MVS 3/3: stereo fusion…")
    fused_path = os.path.join(dense_dir, "fused.ply")
    run_cmd([
        "colmap", "stereo_fusion",
        "--workspace_path", dense_dir,
        "--workspace_format", "COLMAP",
        "--input_type", "photometric",
        "--output_path", fused_path,
        "--StereoFusion.max_reproj_error", "2",
        "--StereoFusion.min_num_pixels", "3",
    ], timeout=180, env=env)

    return fused_path


def read_dense_ply(path):
    """Read x,y,z,r,g,b from COLMAP stereo_fusion PLY (binary_little_endian)."""
    from plyfile import PlyData
    pd = PlyData.read(path)
    v  = pd["vertex"]
    points = np.stack([
        np.asarray(v["x"], dtype=np.float32),
        np.asarray(v["y"], dtype=np.float32),
        np.asarray(v["z"], dtype=np.float32),
    ], axis=1)
    colors = np.stack([
        np.asarray(v["red"],   dtype=np.uint8),
        np.asarray(v["green"], dtype=np.uint8),
        np.asarray(v["blue"],  dtype=np.uint8),
    ], axis=1)
    return points, colors


def extract_sparse_points(sparse_dir):
    """Extract 3D points with colors from COLMAP points3D.txt."""
    points, colors = [], []
    with open(os.path.join(sparse_dir, "points3D.txt")) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            p = line.split()
            points.append([float(p[1]), float(p[2]), float(p[3])])
            colors.append([int(p[4]), int(p[5]), int(p[6])])
    return np.array(points, dtype=np.float32), np.array(colors, dtype=np.uint8)


def write_ply(points, colors):
    """Write colored point cloud as binary PLY."""
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


def handler(job):
    images_b64 = job["input"]["images_base64"]
    print(f"[scan] {len(images_b64)} frames received")

    with tempfile.TemporaryDirectory() as workspace:
        image_dir = os.path.join(workspace, "images")
        os.makedirs(image_dir)

        for i, b64 in enumerate(images_b64):
            img = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
            img = img.resize((960, 720))
            img.save(os.path.join(image_dir, f"{i:04d}.jpg"), quality=90)

        print("[scan] Running COLMAP sparse SfM…")
        try:
            sparse_dir = run_colmap_sparse(image_dir, workspace)
        except subprocess.CalledProcessError as e:
            return {"error": f"COLMAP failed: {e.stderr.decode()[:500] if e.stderr else str(e)}"}

        sparse_pts, sparse_clr = extract_sparse_points(sparse_dir)
        print(f"[scan] Sparse SfM: {len(sparse_pts):,} points")

        if len(sparse_pts) < 50:
            return {"error": "Too few points — try a slower, more overlapping video walkthrough"}

        # Dense MVS: 50k-300k points vs 1k-10k sparse — needed for furniture detection
        points, colors, dense_ok = sparse_pts, sparse_clr, False
        try:
            dense_ply = run_colmap_dense(image_dir, workspace, sparse_dir)
            d_pts, d_clr = read_dense_ply(dense_ply)
            print(f"[scan] Dense MVS: {len(d_pts):,} points")
            if len(d_pts) > len(sparse_pts):
                points, colors, dense_ok = d_pts, d_clr, True
        except Exception as e:
            print(f"[scan] Dense MVS unavailable ({type(e).__name__}: {e}), using sparse")

        ply_bytes = write_ply(points, colors)
        ply_b64   = base64.b64encode(ply_bytes).decode()

    return {
        "ply_base64":  ply_b64,
        "point_count": len(points),
        "dense":       dense_ok,
    }


runpod.serverless.start({"handler": handler})
