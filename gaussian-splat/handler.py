"""
handler.py — RunPod Serverless — Gaussian Splatting via gsplat
==============================================================
Pipeline:
  1. Decode input images (base64 array, minimum 10-20 recommended)
  2. Run COLMAP for camera pose estimation
  3. Initialize 3D Gaussians from COLMAP sparse point cloud
  4. Train with gsplat differentiable rasterizer
  5. Export 3DGS-format PLY + preview render PNG

Input:  { images_base64: [str, ...], iterations: int (default 3000) }
Output: { splat_base64: str, preview_base64: str, point_count: int, status: "ok" }
"""
import runpod, base64, os, io, tempfile, subprocess
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def run_colmap(image_dir, workspace):
    db = os.path.join(workspace, "db.db")
    sparse = os.path.join(workspace, "sparse")
    os.makedirs(sparse, exist_ok=True)

    subprocess.run([
        "colmap", "feature_extractor",
        "--database_path", db,
        "--image_path", image_dir,
        "--ImageReader.single_camera", "1",
    ], check=True, capture_output=True)

    subprocess.run([
        "colmap", "exhaustive_matcher",
        "--database_path", db,
    ], check=True, capture_output=True)

    subprocess.run([
        "colmap", "mapper",
        "--database_path", db,
        "--image_path", image_dir,
        "--output_path", sparse,
    ], check=True, capture_output=True)

    recon_dir = os.path.join(sparse, "0")
    subprocess.run([
        "colmap", "model_converter",
        "--input_path", recon_dir,
        "--output_path", recon_dir,
        "--output_type", "TXT",
    ], check=True, capture_output=True)

    return recon_dir


def quat_to_rot(qw, qx, qy, qz):
    return np.array([
        [1 - 2*(qy**2 + qz**2),  2*(qx*qy - qz*qw),  2*(qx*qz + qy*qw)],
        [    2*(qx*qy + qz*qw),  1 - 2*(qx**2 + qz**2),  2*(qy*qz - qx*qw)],
        [    2*(qx*qz - qy*qw),  2*(qy*qz + qx*qw),  1 - 2*(qx**2 + qy**2)],
    ])


def parse_colmap_text(sparse_dir, image_dir):
    # ── cameras.txt ────────────────────────────────────────────────────────────
    intrinsics = {}
    with open(os.path.join(sparse_dir, "cameras.txt")) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            p = line.split()
            cam_id = int(p[0])
            w, h = int(p[2]), int(p[3])
            fx = float(p[4])
            fy = float(p[5]) if p[1] == "PINHOLE" else float(p[4])
            cx = float(p[6]) if p[1] == "PINHOLE" else float(p[5])
            cy = float(p[7]) if p[1] == "PINHOLE" else float(p[6])
            intrinsics[cam_id] = {"fx": fx, "fy": fy, "cx": cx, "cy": cy, "w": w, "h": h}

    # ── images.txt ─────────────────────────────────────────────────────────────
    cameras = []
    with open(os.path.join(sparse_dir, "images.txt")) as f:
        lines = [l for l in f if not l.startswith("#") and l.strip()]
    i = 0
    while i < len(lines):
        p = lines[i].split()
        qw, qx, qy, qz = float(p[1]), float(p[2]), float(p[3]), float(p[4])
        tx, ty, tz      = float(p[5]), float(p[6]), float(p[7])
        cam_id = int(p[8])
        name   = p[9]
        i += 2  # skip point-observation line

        K = intrinsics[cam_id]
        R = quat_to_rot(qw, qx, qy, qz)
        t = np.array([tx, ty, tz])

        viewmat      = np.eye(4, dtype=np.float32)
        viewmat[:3, :3] = R
        viewmat[:3, 3]  = t
        Kmat = np.array([[K["fx"], 0, K["cx"]], [0, K["fy"], K["cy"]], [0, 0, 1]], dtype=np.float32)

        img = Image.open(os.path.join(image_dir, name)).convert("RGB").resize((K["w"], K["h"]))
        img_t = torch.tensor(np.array(img) / 255.0, dtype=torch.float32).to(DEVICE)

        cameras.append({
            "viewmat": torch.tensor(viewmat).to(DEVICE),
            "K":       torch.tensor(Kmat).to(DEVICE),
            "image":   img_t,
            "width":   K["w"],
            "height":  K["h"],
        })

    # ── points3D.txt ───────────────────────────────────────────────────────────
    points, colors_init = [], []
    with open(os.path.join(sparse_dir, "points3D.txt")) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            p = line.split()
            points.append([float(p[1]), float(p[2]), float(p[3])])
            colors_init.append([int(p[4]) / 255, int(p[5]) / 255, int(p[6]) / 255])

    return cameras, np.array(points, dtype=np.float32), np.array(colors_init, dtype=np.float32)


def train_splat(cameras, points_xyz, colors_xyz, iterations):
    from gsplat import rasterization
    import torch.nn as nn

    N = len(points_xyz)
    means          = nn.Parameter(torch.tensor(points_xyz, device=DEVICE))
    quats          = nn.Parameter(torch.zeros(N, 4, device=DEVICE))
    quats.data[:, 0] = 1.0
    log_scales     = nn.Parameter(torch.full((N, 3), -4.0, device=DEVICE))
    logit_opacities = nn.Parameter(torch.zeros(N, device=DEVICE))
    colors         = nn.Parameter(torch.tensor(colors_xyz, device=DEVICE))

    optimizer = torch.optim.Adam([
        {"params": [means],             "lr": 1.6e-4},
        {"params": [quats],             "lr": 1.0e-3},
        {"params": [log_scales],        "lr": 5.0e-3},
        {"params": [logit_opacities],   "lr": 5.0e-2},
        {"params": [colors],            "lr": 2.5e-3},
    ])

    for step in range(iterations):
        cam = cameras[step % len(cameras)]
        renders, _, _ = rasterization(
            means=means,
            quats=F.normalize(quats, dim=-1),
            scales=log_scales.exp(),
            opacities=torch.sigmoid(logit_opacities),
            colors=torch.sigmoid(colors),
            viewmats=cam["viewmat"][None],
            Ks=cam["K"][None],
            width=cam["width"],
            height=cam["height"],
            packed=False,
        )
        loss = torch.abs(renders[0] - cam["image"]).mean()
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        if step % 500 == 0:
            print(f"[gsplat] step {step}/{iterations}  loss={loss.item():.4f}")

    return (
        means.detach(),
        F.normalize(quats.detach(), dim=-1),
        log_scales.detach().exp(),
        torch.sigmoid(logit_opacities.detach()),
        torch.sigmoid(colors.detach()),
    )


def export_ply(means, quats, scales, opacities, colors, path):
    N   = len(means)
    xyz = means.cpu().numpy()
    rot = quats.cpu().numpy()
    sc  = np.log(scales.cpu().numpy() + 1e-8)
    op  = np.log(opacities.cpu().numpy() / (1 - opacities.cpu().numpy() + 1e-8) + 1e-8)
    sh  = colors.cpu().numpy()

    dtype = [
        ("x", "f4"), ("y", "f4"), ("z", "f4"),
        ("nx", "f4"), ("ny", "f4"), ("nz", "f4"),
        ("f_dc_0", "f4"), ("f_dc_1", "f4"), ("f_dc_2", "f4"),
        ("opacity", "f4"),
        ("scale_0", "f4"), ("scale_1", "f4"), ("scale_2", "f4"),
        ("rot_0",   "f4"), ("rot_1",   "f4"), ("rot_2",   "f4"), ("rot_3", "f4"),
    ]
    arr = np.zeros(N, dtype=dtype)
    arr["x"], arr["y"], arr["z"]         = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    arr["f_dc_0"], arr["f_dc_1"], arr["f_dc_2"] = sh[:, 0], sh[:, 1], sh[:, 2]
    arr["opacity"]                        = op
    arr["scale_0"], arr["scale_1"], arr["scale_2"] = sc[:, 0], sc[:, 1], sc[:, 2]
    arr["rot_0"],   arr["rot_1"],   arr["rot_2"],   arr["rot_3"] = rot[:, 0], rot[:, 1], rot[:, 2], rot[:, 3]

    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {N}\n"
        + "".join(f"property float {n}\n" for n, _ in dtype)
        + "end_header\n"
    )
    with open(path, "wb") as f:
        f.write(header.encode())
        f.write(arr.tobytes())


def render_preview(cameras, means, quats, scales, opacities, colors):
    from gsplat import rasterization
    cam = cameras[len(cameras) // 2]
    with torch.no_grad():
        renders, _, _ = rasterization(
            means=means, quats=quats, scales=scales,
            opacities=opacities, colors=colors,
            viewmats=cam["viewmat"][None], Ks=cam["K"][None],
            width=cam["width"], height=cam["height"], packed=False,
        )
    img_np = (renders[0].clamp(0, 1).cpu().numpy() * 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(img_np).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def handler(job):
    job_input    = job["input"]
    images_b64   = job_input["images_base64"]
    iterations   = job_input.get("iterations", 3000)

    with tempfile.TemporaryDirectory() as workspace:
        image_dir = os.path.join(workspace, "images")
        os.makedirs(image_dir)

        for i, b64 in enumerate(images_b64):
            img = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
            img.save(os.path.join(image_dir, f"{i:04d}.jpg"))

        print(f"[gsplat] COLMAP on {len(images_b64)} images...")
        sparse_dir = run_colmap(image_dir, workspace)

        print("[gsplat] Parsing COLMAP output...")
        cameras, points_xyz, colors_xyz = parse_colmap_text(sparse_dir, image_dir)
        print(f"[gsplat] {len(cameras)} cameras | {len(points_xyz)} sparse points")

        print(f"[gsplat] Training {iterations} iterations on {DEVICE}...")
        means, quats, scales, opacities, colors = train_splat(
            cameras, points_xyz, colors_xyz, iterations
        )

        splat_path = os.path.join(workspace, "output.ply")
        export_ply(means, quats, scales, opacities, colors, splat_path)
        with open(splat_path, "rb") as f:
            splat_b64 = base64.b64encode(f.read()).decode()

        preview_b64 = render_preview(cameras, means, quats, scales, opacities, colors)

    return {
        "splat_base64":  splat_b64,
        "preview_base64": preview_b64,
        "point_count":   len(points_xyz),
        "status":        "ok",
    }


runpod.serverless.start({"handler": handler})
