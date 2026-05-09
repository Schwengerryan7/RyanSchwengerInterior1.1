"""
handler_scan.py — RunPod Serverless — Video → Point Cloud
==========================================================
Pipeline:
  1. Decode input frames (base64 JPEG array from browser)
  2. Run COLMAP SfM → sparse colored 3D point cloud
  3. Return PLY (base64) → goes directly to SpatialLM floor plan endpoint

No Gaussian Splatting training — just structure-from-motion.
Fast: 1-2 min for a typical room video.

Input:  { images_base64: [str, ...] }
Output: { ply_base64: str, point_count: int }
"""

import runpod, base64, os, io, tempfile, subprocess
import numpy as np
from PIL import Image
import struct


def run_colmap(image_dir, workspace):
    db     = os.path.join(workspace, "db.db")
    sparse = os.path.join(workspace, "sparse")
    os.makedirs(sparse, exist_ok=True)

    subprocess.run([
        "colmap", "feature_extractor",
        "--database_path", db,
        "--image_path", image_dir,
        "--ImageReader.single_camera", "1",
        "--SiftExtraction.use_gpu", "1",
    ], check=True, capture_output=True)

    subprocess.run([
        "colmap", "exhaustive_matcher",
        "--database_path", db,
        "--SiftMatching.use_gpu", "1",
    ], check=True, capture_output=True)

    subprocess.run([
        "colmap", "mapper",
        "--database_path", db,
        "--image_path", image_dir,
        "--output_path", sparse,
        "--Mapper.num_threads", "4",
    ], check=True, capture_output=True)

    # Convert to text for easy parsing
    recon_dir = os.path.join(sparse, "0")
    subprocess.run([
        "colmap", "model_converter",
        "--input_path", recon_dir,
        "--output_path", recon_dir,
        "--output_type", "TXT",
    ], check=True, capture_output=True)

    return recon_dir


def extract_colored_points(sparse_dir, image_dir):
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
            img = img.resize((960, 720))  # standardise resolution
            img.save(os.path.join(image_dir, f"{i:04d}.jpg"), quality=90)

        print("[scan] Running COLMAP SfM…")
        try:
            sparse_dir = run_colmap(image_dir, workspace)
        except subprocess.CalledProcessError as e:
            return {"error": f"COLMAP failed: {e.stderr.decode()[:500] if e.stderr else str(e)}"}

        points, colors = extract_colored_points(sparse_dir, image_dir)
        print(f"[scan] {len(points):,} sparse points")

        if len(points) < 50:
            return {"error": "Too few points reconstructed — try a slower, more overlapping video walkthrough"}

        ply_bytes = write_ply(points, colors)
        ply_b64   = base64.b64encode(ply_bytes).decode()

    return {
        "ply_base64":  ply_b64,
        "point_count": len(points),
    }


runpod.serverless.start({"handler": handler})
