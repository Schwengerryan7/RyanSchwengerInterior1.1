import runpod, os, subprocess, base64, tempfile, shutil

def log(msg):
    print(f"[GS] {msg}", flush=True)

env = os.environ.copy()
env["QT_QPA_PLATFORM"] = "offscreen"
env["DISPLAY"] = ""
env["MESA_GL_VERSION_OVERRIDE"] = "3.3"

def run_cmd(cmd, cwd=None):
    log(f"$ {cmd}")
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, env=env)
    if r.stdout: log(r.stdout[-2000:])
    if r.stderr: log(r.stderr[-2000:])
    if r.returncode != 0:
        raise RuntimeError(f"FAILED: {r.stderr[-1000:]}")
    return r

def handler(job):
    inp = job.get("input", {})
    video_b64 = inp.get("video_b64")
    prompt = inp.get("prompt", "")
    filename = inp.get("filename", "room.mp4")
    if not video_b64:
        return {"error": "No video"}

    w = tempfile.mkdtemp(prefix="gs_")
    video = os.path.join(w, filename)
    frames = os.path.join(w, "images")
    colmap_dir = os.path.join(w, "colmap")
    sparse = os.path.join(colmap_dir, "sparse")
    ns_data = os.path.join(w, "ns_data")
    ns_out = os.path.join(w, "ns_out")
    ply_out = os.path.join(w, "ply")
    for d in [frames, colmap_dir, sparse, ns_data, ns_out, ply_out]:
        os.makedirs(d, exist_ok=True)

    try:
        # Save video
        log("Saving video...")
        with open(video, "wb") as f:
            f.write(base64.b64decode(video_b64))

        # Extract frames
        log("Extracting frames...")
        run_cmd(f'ffmpeg -i "{video}" -vf "fps=2,scale=960:-1" -q:v 2 "{frames}/frame_%04d.jpg"')
        frame_list = [f for f in os.listdir(frames) if f.endswith('.jpg')]
        log(f"{len(frame_list)} frames extracted")
        if len(frame_list) < 10:
            return {"error": f"Too few frames: {len(frame_list)}"}

        # COLMAP - feature extraction (CPU, no GPU/display)
        log("COLMAP feature extraction...")
        db = os.path.join(colmap_dir, "db.db")
        run_cmd(f'colmap feature_extractor --database_path "{db}" --image_path "{frames}" --ImageReader.single_camera 1 --SiftExtraction.use_gpu 0 --SiftExtraction.max_image_size 1000')

        # COLMAP - matching
        log("COLMAP matching...")
        run_cmd(f'colmap sequential_matcher --database_path "{db}" --SequentialMatching.overlap 10')

        # COLMAP - reconstruction
        log("COLMAP reconstruction...")
        run_cmd(f'colmap mapper --database_path "{db}" --image_path "{frames}" --output_path "{sparse}"')

        sparse_0 = os.path.join(sparse, "0")
        if not os.path.exists(sparse_0):
            return {"error": "COLMAP reconstruction failed - no sparse model"}
        log("COLMAP done!")

        # Convert to nerfstudio format
        log("Converting to nerfstudio format...")
        run_cmd(f'ns-process-data images --data "{frames}" --output-dir "{ns_data}" --skip-colmap --colmap-model-path "{sparse_0}" --num-downscales 1')

        # Train
        log("Training splatfacto...")
        run_cmd(f'ns-train splatfacto --data "{ns_data}" --output-dir "{ns_out}" --max-num-iterations 5000 --vis none --pipeline.model.cull-alpha-thresh 0.005')

        # Export
        log("Exporting PLY...")
        config = None
        for root, _, files in os.walk(ns_out):
            for f in files:
                if f == "config.yml":
                    config = os.path.join(root, f)
        if not config:
            return {"error": "No config.yml found"}

        run_cmd(f'ns-export gaussian-splat --load-config "{config}" --output-dir "{ply_out}"')

        plys = [f for f in os.listdir(ply_out) if f.endswith('.ply')]
        if not plys:
            return {"error": "No PLY exported"}

        ply_path = os.path.join(ply_out, plys[0])
        size_mb = os.path.getsize(ply_path) / 1024 / 1024
        with open(ply_path, "rb") as f:
            ply_b64 = base64.b64encode(f.read()).decode()

        log(f"SUCCESS! PLY: {size_mb:.1f} MB")
        return {"success": True, "ply_b64": ply_b64, "ply_size_mb": round(size_mb,1), "frames": len(frame_list), "prompt": prompt}

    except Exception as e:
        log(f"ERROR: {e}")
        return {"error": str(e)[:2000]}
    finally:
        shutil.rmtree(w, ignore_errors=True)

runpod.serverless.start({"handler": handler})
