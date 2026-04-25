import runpod
import os
import subprocess
import base64
import tempfile
import shutil

def log(msg):
    print(f"[GS] {msg}", flush=True)

def run_cmd(cmd, cwd=None):
    log(f"Running: {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if result.stdout: log(f"STDOUT: {result.stdout[-3000:]}")
    if result.stderr: log(f"STDERR: {result.stderr[-3000:]}")
    if result.returncode != 0:
        raise RuntimeError(f"Failed ({result.returncode}): {cmd}\nSTDOUT: {result.stdout[-2000:]}\nSTDERR: {result.stderr[-2000:]}")
    return result

def handler(job):
    job_input = job.get("input", {})
    video_b64 = job_input.get("video_b64")
    prompt    = job_input.get("prompt", "")
    filename  = job_input.get("filename", "room.mp4")

    if not video_b64:
        return {"error": "No video provided"}

    workdir    = tempfile.mkdtemp(prefix="gs_")
    video_path = os.path.join(workdir, filename)
    frames_dir = os.path.join(workdir, "images")
    output_dir = os.path.join(workdir, "output")
    os.makedirs(frames_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    try:
        # Step 1: Save video
        log("Step 1: Saving video...")
        with open(video_path, "wb") as f:
            f.write(base64.b64decode(video_b64))
        log(f"Video saved: {os.path.getsize(video_path)/1024/1024:.1f} MB")

        # Step 2: Extract frames
        log("Step 2: Extracting frames...")
        run_cmd(f'ffmpeg -i "{video_path}" -vf "fps=2,scale=1920:-1" -q:v 1 "{frames_dir}/frame_%04d.jpg"')
        frames = [f for f in os.listdir(frames_dir) if f.endswith('.jpg')]
        log(f"Extracted {len(frames)} frames")
        if len(frames) < 15:
            return {"error": f"Too few frames: {len(frames)}"}

        # Step 3: Check COLMAP is available
        log("Step 3: Checking COLMAP...")
        result = subprocess.run("which colmap && colmap --version", shell=True, capture_output=True, text=True)
        log(f"COLMAP check: {result.stdout} {result.stderr}")

        # Step 4: ns-process-data
        log("Step 4: Running ns-process-data...")
        ns_data_dir = os.path.join(workdir, "ns_data")
        run_cmd(f'ns-process-data images --num-downscales 2 --data "{frames_dir}" --output-dir "{ns_data_dir}" --verbose')

        # Step 5: Train
        log("Step 5: Training Gaussian Splat...")
        ns_output_dir = os.path.join(workdir, "ns_output")
        run_cmd(
            f'ns-train splatfacto '
            f'--data "{ns_data_dir}" '
            f'--output-dir "{ns_output_dir}" '
            f'--max-num-iterations 7000 '
            f'--vis none'
        )

        # Step 6: Export
        log("Step 6: Exporting PLY...")
        config_path = None
        for root, dirs, files in os.walk(ns_output_dir):
            for f in files:
                if f == "config.yml":
                    config_path = os.path.join(root, f)
                    break

        if not config_path:
            return {"error": "Training complete but config not found"}

        run_cmd(f'ns-export gaussian-splat --load-config "{config_path}" --output-dir "{output_dir}"')

        ply_files = [f for f in os.listdir(output_dir) if f.endswith('.ply')]
        if not ply_files:
            return {"error": "PLY export failed"}

        ply_path = os.path.join(output_dir, ply_files[0])
        ply_size = os.path.getsize(ply_path) / 1024 / 1024

        with open(ply_path, "rb") as f:
            ply_b64 = base64.b64encode(f.read()).decode("utf-8")

        log(f"Done! PLY: {ply_size:.1f} MB")
        return {
            "success": True,
            "ply_b64": ply_b64,
            "ply_size_mb": round(ply_size, 1),
            "frame_count": len(frames),
            "prompt": prompt,
            "message": f"Gaussian Splat complete. {len(frames)} frames."
        }

    except Exception as e:
        log(f"EXCEPTION: {str(e)}")
        return {"error": str(e)[:3000]}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

runpod.serverless.start({"handler": handler})
