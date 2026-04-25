"""
Spatial Studio - Gaussian Splatting Handler v15
Fix: added --SiftMatching.use_gpu 0 to sequential_matcher
(was crashing with OpenGLContextManager SIGABRT)
"""
import runpod
import os
import sys
import subprocess
import base64
import tempfile
import shutil

print(f"[GS] Python {sys.version}", flush=True)
print(f"[GS] Spatial Studio GS Pipeline v15 starting...", flush=True)

# Check all dependencies on startup
for cmd in ["ffmpeg", "colmap", "ns-train", "ns-process-data", "ns-export"]:
    r = subprocess.run(f"which {cmd}", shell=True, capture_output=True, text=True)
    status = "✓" if r.returncode == 0 else "✗ MISSING"
    print(f"[GS] {status} {cmd}: {r.stdout.strip() or 'not found'}", flush=True)

# Critical: force software OpenGL so COLMAP never needs a display
ENV = os.environ.copy()
ENV.update({
    "QT_QPA_PLATFORM":            "offscreen",
    "DISPLAY":                    "",
    "LIBGL_ALWAYS_SOFTWARE":      "1",
    "MESA_GL_VERSION_OVERRIDE":   "3.3",
    "MESA_GLSL_VERSION_OVERRIDE": "330",
})

def log(msg):
    print(f"[GS] {msg}", flush=True)

def run(cmd, cwd=None, timeout=3600):
    log(f"$ {cmd[:100]}")
    r = subprocess.run(
        cmd, shell=True, cwd=cwd,
        capture_output=True, text=True,
        env=ENV, timeout=timeout
    )
    if r.stdout: log(r.stdout[-1500:])
    if r.stderr: log(r.stderr[-1500:])
    if r.returncode != 0:
        raise RuntimeError(f"Failed [{r.returncode}]: {r.stderr[-600:]}")
    return r

def handler(job):
    inp       = job.get("input", {})
    video_b64 = inp.get("video_b64")
    prompt    = inp.get("prompt", "")
    filename  = inp.get("filename", "room.mp4")
    quality   = inp.get("quality", "high")
    iterations = 30000 if quality == "high" else 10000

    if not video_b64:
        return {"error": "No video provided"}

    w       = tempfile.mkdtemp(prefix="spatial_")
    video   = os.path.join(w, filename)
    frames  = os.path.join(w, "images")
    colmap  = os.path.join(w, "colmap")
    sparse  = os.path.join(colmap, "sparse")
    ns_data = os.path.join(w, "ns_data")
    ns_out  = os.path.join(w, "ns_out")
    ply_out = os.path.join(w, "ply_out")
    for d in [frames, colmap, sparse, ns_data, ns_out, ply_out]:
        os.makedirs(d, exist_ok=True)

    try:
        # Step 1: Save video
        log("Step 1: Saving video...")
        with open(video, "wb") as f:
            f.write(base64.b64decode(video_b64))
        log(f"Saved: {os.path.getsize(video)/1024/1024:.1f} MB")

        # Step 2: Extract frames at high quality
        log("Step 2: Extracting frames...")
        run(f'ffmpeg -i "{video}" -vf "fps=3,scale=1920:-1" -q:v 1 "{frames}/frame_%04d.jpg"')
        frame_list = [f for f in os.listdir(frames) if f.endswith('.jpg')]
        log(f"Extracted {len(frame_list)} frames")
        if len(frame_list) < 15:
            return {"error": f"Too few frames ({len(frame_list)}). Record a longer video."}

        # Step 3: COLMAP high quality
        log("Step 3: COLMAP feature extraction...")
        db = os.path.join(colmap, "database.db")
        run(
            f'colmap feature_extractor '
            f'--database_path "{db}" '
            f'--image_path "{frames}" '
            f'--ImageReader.single_camera 1 '
            f'--SiftExtraction.use_gpu 0 '
            f'--SiftExtraction.max_num_features 8192 '
            f'--SiftExtraction.max_image_size 1600'
        )

        log("COLMAP matching...")
        run(
            f'colmap sequential_matcher '
            f'--database_path "{db}" '
            f'--SequentialMatching.overlap 20 '
            f'--SiftMatching.use_gpu 0'
        )

        log("COLMAP reconstruction...")
        run(
            f'colmap mapper '
            f'--database_path "{db}" '
            f'--image_path "{frames}" '
            f'--output_path "{sparse}" '
            f'--Mapper.multiple_models 0'
        )

        sparse_0 = os.path.join(sparse, "0")
        if not os.path.exists(sparse_0):
            models = [d for d in os.listdir(sparse) if os.path.isdir(os.path.join(sparse, d))]
            if not models:
                return {"error": "COLMAP failed. Try moving slower with better lighting."}
            sparse_0 = os.path.join(sparse, sorted(models)[0])
        log(f"COLMAP complete: {sparse_0}")

        # Step 4: Convert format
        log("Step 4: Converting to Nerfstudio format...")
        run(
            f'ns-process-data images '
            f'--data "{frames}" '
            f'--output-dir "{ns_data}" '
            f'--skip-colmap '
            f'--colmap-model-path "{sparse_0}" '
            f'--num-downscales 0'
        )

        # Step 5: Train (Luma-quality settings)
        log(f"Step 5: Training {iterations} iterations (Luma-quality)...")
        run(
            f'ns-train splatfacto '
            f'--data "{ns_data}" '
            f'--output-dir "{ns_out}" '
            f'--max-num-iterations {iterations} '
            f'--vis none '
            f'--pipeline.model.cull-alpha-thresh 0.005 '
            f'--pipeline.model.use-scale-regularization True '
            f'--pipeline.model.densify-grad-thresh 0.0008',
            timeout=3600
        )

        # Step 6: Export
        log("Step 6: Exporting PLY...")
        config_path = None
        for root, _, files in os.walk(ns_out):
            for f in files:
                if f == "config.yml":
                    config_path = os.path.join(root, f)
                    break
            if config_path: break

        if not config_path:
            return {"error": "No config.yml found after training"}

        run(f'ns-export gaussian-splat --load-config "{config_path}" --output-dir "{ply_out}"')

        plys = [f for f in os.listdir(ply_out) if f.endswith('.ply')]
        if not plys:
            return {"error": "No PLY file exported"}

        ply_path = os.path.join(ply_out, plys[0])
        ply_mb   = os.path.getsize(ply_path) / 1024 / 1024
        with open(ply_path, "rb") as f:
            ply_b64 = base64.b64encode(f.read()).decode()

        log(f"SUCCESS! {len(frame_list)} frames | {iterations} iters | {ply_mb:.1f} MB PLY")
        return {
            "success":     True,
            "ply_b64":     ply_b64,
            "ply_size_mb": round(ply_mb, 1),
            "frame_count": len(frame_list),
            "iterations":  iterations,
            "prompt":      prompt,
            "message":     f"Gaussian Splat complete. {len(frame_list)} frames, {iterations} iterations."
        }

    except Exception as e:
        log(f"ERROR: {e}")
        return {"error": str(e)[:3000]}
    finally:
        shutil.rmtree(w, ignore_errors=True)

print("[GS] Ready for jobs!", flush=True)
runpod.serverless.start({"handler": handler})