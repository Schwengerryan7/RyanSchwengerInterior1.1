"""
handler_scan.py — RunPod Serverless — Video → Point Cloud
==========================================================
Pipeline:
  1. Decode input frames (base64 JPEG array from browser)
  2. Run COLMAP SfM → sparse colored 3D point cloud
  3. Return PLY (base64) → SpatialLM floor plan endpoint

Input:  { images_base64: [str, ...] }
Output: { ply_base64: str, point_count: int }
"""

import runpod, base64, os, io, tempfile, subprocess
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


def run_colmap(image_dir, workspace):
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
            stderr=b"Mapper produced no reconstruction - video may move too fast or lack texture."
        )
    recon_dir = os.path.join(sparse, recon_dirs[0])

    run_cmd([
        "colmap", "model_converter",
        "--input_path", recon_dir,
        "--output_path", recon_dir,
        "--output_type", "TXT",
    ], timeout=60, env=env)

    return recon_dir


def extract_colored_points(sparse_dir):
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

        print("[scan] Running COLMAP SfM…")
        try:
            sparse_dir = run_colmap(image_dir, workspace)
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode()[:500] if isinstance(e.stderr, bytes) else str(e.stderr)
            return {"error": f"COLMAP failed: {err}"}

        points, colors = extract_colored_points(sparse_dir)
        print(f"[scan] {len(points):,} sparse points")

        if len(points) < 50:
            return {"error": "Too few points — try a slower, more overlapping video walkthrough"}

        ply_bytes = write_ply(points, colors)
        ply_b64   = base64.b64encode(ply_bytes).decode()

    return {
        "ply_base64":  ply_b64,
        "point_count": len(points),
    }


runpod.serverless.start({"handler": handler})
