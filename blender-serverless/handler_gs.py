import runpod
import os
import subprocess
import base64
import tempfile
import shutil
import json

def log(msg):
    print(f"[GS] {msg}", flush=True)

def run_cmd(cmd, cwd=None):
    log(f"Running: {cmd}")
    result = subprocess.run(
        cmd, shell=True, cwd=cwd,
        capture_output=True, text=True
    )
    if result.stdout: log(result.stdout[-2000:])
    if result.stderr: log(result.stderr[-2000:])
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}\n{result.stderr[-1000:]}")
    return result

def handler(job):
    job_input = job.get("input", {})

    # — Get video from input (base64 encoded)
    video_b64 = job_input.get("video_b64")
    prompt    = job_input.get("prompt", "")
    filename  = job_input.get("filename", "room.mp4")

    if not video_b64:
        return {"error": "No video provided. Send video as base64 in 'video_b64' field."}

    log(f"Job started — file: {filename}, prompt: {prompt}")

    # — Create working directory
    workdir = tempfile.mkdtemp(prefix="gs_job_")
    video_path  = os.path.join(workdir, filename)
    frames_dir  = os.path.join(workdir, "images")
    colmap_dir  = os.path.join(workdir, "colmap")
    output_dir  = os.path.join(workdir, "output")

    os.makedirs(frames_dir, exist_ok=True)
    os.makedirs(colmap_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    try:
        # ── Step 1: Decode and save video
        log("Step 1/5: Saving video...")
        video_bytes = base64.b64decode(video_b64)
        with open(video_path, "wb") as f:
            f.write(video_bytes)
        size_mb = os.path.getsize(video_path) / 1024 / 1024
        log(f"Video saved: {size_mb:.1f} MB")

        # ── Step 2: Extract frames with FFmpeg
        log("Step 2/5: Extracting frames...")
        run_cmd(
            f'ffmpeg -i "{video_path}" '
            f'-vf "fps=2,scale=1920:-1" '
            f'-q:v 1 '
            f'"{frames_dir}/frame_%04d.jpg"'
        )
        frames = [f for f in os.listdir(frames_dir) if f.endswith('.jpg')]
        log(f"Extracted {len(frames)} frames")

        if len(frames) < 15:
            return {"error": f"Too few frames extracted ({len(frames)}). Video may be too short or dark. Aim for 30-60 seconds."}

        # ── Step 3: Run COLMAP (Structure from Motion)
        log("Step 3/5: Running COLMAP...")
        db_path     = os.path.join(colmap_dir, "database.db")
        sparse_dir  = os.path.join(colmap_dir, "sparse")
        os.makedirs(sparse_dir, exist_ok=True)

        # Feature extraction
        run_cmd(
            f'colmap feature_extractor '
            f'--database_path "{db_path}" '
            f'--image_path "{frames_dir}" '
            f'--ImageReader.single_camera 1 '
            f'--ImageReader.camera_model PINHOLE '
            f'--SiftExtraction.use_gpu 1'
        )

        # Sequential matching (best for video)
        run_cmd(
            f'colmap sequential_matcher '
            f'--database_path "{db_path}" '
            f'--SequentialMatching.overlap 10'
        )

        # Sparse reconstruction
        run_cmd(
            f'colmap mapper '
            f'--database_path "{db_path}" '
            f'--image_path "{frames_dir}" '
            f'--output_path "{sparse_dir}"'
        )

        # Check reconstruction succeeded
        sparse_model = os.path.join(sparse_dir, "0")
        if not os.path.exists(sparse_model):
            return {"error": "COLMAP reconstruction failed. Try recording more slowly with better overlap between frames."}

        log("COLMAP reconstruction complete")

        # ── Step 4: Train Gaussian Splat with Nerfstudio
        log("Step 4/5: Training Gaussian Splat...")

        # Convert COLMAP to nerfstudio format
        ns_data_dir = os.path.join(workdir, "ns_data")
        run_cmd(
            f'ns-process-data images '
            f'--data "{frames_dir}" '
            f'--output-dir "{ns_data_dir}" '
            f'--colmap-model-path "{sparse_model}"'
        )

        # Train splatfacto
        ns_output_dir = os.path.join(workdir, "ns_output")
        run_cmd(
            f'ns-train splatfacto '
            f'--data "{ns_data_dir}" '
            f'--output-dir "{ns_output_dir}" '
            f'--max-num-iterations 10000 '
            f'--pipeline.model.cull-alpha-thresh 0.005 '
            f'--vis none'
        )

        # ── Step 5: Export .ply file
        log("Step 5/5: Exporting Gaussian Splat...")

        # Find the trained model config
        config_path = None
        for root, dirs, files in os.walk(ns_output_dir):
            for f in files:
                if f == "config.yml":
                    config_path = os.path.join(root, f)
                    break

        if not config_path:
            return {"error": "Training completed but config not found"}

        ply_output = os.path.join(output_dir, "gaussian_splat.ply")
        run_cmd(
            f'ns-export gaussian-splat '
            f'--load-config "{config_path}" '
            f'--output-dir "{output_dir}"'
        )

        # Find the exported PLY
        ply_files = [f for f in os.listdir(output_dir) if f.endswith('.ply')]
        if not ply_files:
            return {"error": "PLY export failed — no .ply file found"}

        ply_path = os.path.join(output_dir, ply_files[0])
        ply_size = os.path.getsize(ply_path) / 1024 / 1024
        log(f"PLY exported: {ply_size:.1f} MB")

        # Encode PLY as base64 to return
        with open(ply_path, "rb") as f:
            ply_b64 = base64.b64encode(f.read()).decode("utf-8")

        log("Job complete!")

        return {
            "success": True,
            "ply_b64": ply_b64,
            "ply_size_mb": round(ply_size, 1),
            "frame_count": len(frames),
            "prompt": prompt,
            "message": f"Gaussian Splat generated from {len(frames)} frames"
        }

    except Exception as e:
        log(f"Error: {str(e)}")
        return {"error": str(e)}

    finally:
        # Clean up working directory
        shutil.rmtree(workdir, ignore_errors=True)
        log("Cleaned up temp files")


runpod.serverless.start({"handler": handler})