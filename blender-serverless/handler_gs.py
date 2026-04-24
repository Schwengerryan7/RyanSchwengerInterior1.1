import runpod
import os
import subprocess
import base64
import tempfile
import shutil
import json
import threading

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

# ─────────────────────────────────────────────
# GEMMA SCENE INTELLIGENCE
# Runs in parallel with Gaussian Splatting
# Analyzes every 10th frame to build a full
# scene inventory of every object in the room
# ─────────────────────────────────────────────
def analyze_scene_with_gemma(frames_dir, workdir):
    """
    Uses Gemma 4 to analyze video frames and identify
    every object in the room with position and attributes.
    Returns a scene_map.json with full object inventory.
    """
    try:
        log("Gemma: Starting scene analysis...")
        from transformers import pipeline, AutoProcessor, AutoModelForImageTextToText
        from PIL import Image
        import torch

        # Load Gemma 4 12B — fits on A40 48GB
        MODEL_ID = "google/gemma-3-12b-it"

        log("Gemma: Loading model...")
        processor = AutoProcessor.from_pretrained(MODEL_ID)
        model = AutoModelForImageTextToText.from_pretrained(
            MODEL_ID,
            torch_dtype=torch.bfloat16,
            device_map="auto"
        )

        # Get every 10th frame for analysis
        all_frames = sorted([
            f for f in os.listdir(frames_dir) if f.endswith('.jpg')
        ])
        sample_frames = all_frames[::10]  # every 10th frame
        log(f"Gemma: Analyzing {len(sample_frames)} sample frames...")

        all_objects = {}

        for i, frame_file in enumerate(sample_frames):
            frame_path = os.path.join(frames_dir, frame_file)
            image = Image.open(frame_path).convert("RGB")

            messages = [{
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": """You are analyzing a room scan frame for an interior design app.
                    
List every distinct object you can see in this image.
For each object return JSON like this:
{
  "objects": [
    {
      "label": "armchair",
      "color": "dark brown",
      "material": "leather",
      "position": "center-left",
      "size": "medium",
      "condition": "good"
    }
  ]
}

Be specific. Include furniture, lighting, decor, electronics, plants, rugs — everything visible.
Return ONLY valid JSON, no other text."""
                    }
                ]
            }]

            inputs = processor.apply_chat_template(
                messages,
                add_generation_prompt=True,
                tokenize=True,
                return_dict=True,
                return_tensors="pt"
            ).to(model.device)

            with torch.no_grad():
                output = model.generate(**inputs, max_new_tokens=512)

            response = processor.decode(output[0], skip_special_tokens=True)

            # Extract JSON from response
            try:
                json_start = response.rfind('{')
                json_end   = response.rfind('}') + 1
                if json_start != -1:
                    parsed = json.loads(response[json_start:json_end])
                    for obj in parsed.get("objects", []):
                        label = obj.get("label", "").lower()
                        if label and label not in all_objects:
                            all_objects[label] = obj
                            log(f"Gemma found: {label} ({obj.get('color','')}, {obj.get('position','')})")
            except Exception as e:
                log(f"Gemma: JSON parse error on frame {i}: {e}")
                continue

        # Build final scene map
        scene_map = {
            "object_count": len(all_objects),
            "objects": list(all_objects.values()),
            "room_summary": f"Room contains {len(all_objects)} identified objects: {', '.join(all_objects.keys())}"
        }

        # Save scene map
        scene_path = os.path.join(workdir, "scene_map.json")
        with open(scene_path, "w") as f:
            json.dump(scene_map, f, indent=2)

        log(f"Gemma: Scene analysis complete — {len(all_objects)} objects identified")
        log(f"Gemma: {scene_map['room_summary']}")
        return scene_map

    except Exception as e:
        log(f"Gemma: Analysis failed — {str(e)}")
        return {"error": str(e), "objects": [], "object_count": 0}


# ─────────────────────────────────────────────
# MAIN RUNPOD HANDLER
# ─────────────────────────────────────────────
def handler(job):
    job_input = job.get("input", {})

    video_b64 = job_input.get("video_b64")
    prompt    = job_input.get("prompt", "")
    filename  = job_input.get("filename", "room.mp4")

    if not video_b64:
        return {"error": "No video provided. Send video as base64 in 'video_b64' field."}

    log(f"Job started — file: {filename}, prompt: {prompt}")

    workdir    = tempfile.mkdtemp(prefix="gs_job_")
    video_path = os.path.join(workdir, filename)
    frames_dir = os.path.join(workdir, "images")
    colmap_dir = os.path.join(workdir, "colmap")
    output_dir = os.path.join(workdir, "output")

    os.makedirs(frames_dir, exist_ok=True)
    os.makedirs(colmap_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    try:
        # ── Step 1: Save video
        log("Step 1/5: Saving video...")
        video_bytes = base64.b64decode(video_b64)
        with open(video_path, "wb") as f:
            f.write(video_bytes)
        size_mb = os.path.getsize(video_path) / 1024 / 1024
        log(f"Video saved: {size_mb:.1f} MB")

        # ── Step 2: Extract frames
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
            return {"error": f"Too few frames ({len(frames)}). Video may be too short."}

        # ── Step 3: Launch Gemma scene analysis in parallel thread
        log("Step 3/5: Launching Gemma scene intelligence in parallel...")
        scene_result = {}

        def run_gemma():
            result = analyze_scene_with_gemma(frames_dir, workdir)
            scene_result.update(result)

        gemma_thread = threading.Thread(target=run_gemma)
        gemma_thread.start()

        # ── Step 4: Run COLMAP + Nerfstudio (main thread)
        log("Step 4/5: Running COLMAP...")
        db_path    = os.path.join(colmap_dir, "database.db")
        sparse_dir = os.path.join(colmap_dir, "sparse")
        os.makedirs(sparse_dir, exist_ok=True)

        run_cmd(
            f'colmap feature_extractor '
            f'--database_path "{db_path}" '
            f'--image_path "{frames_dir}" '
            f'--ImageReader.single_camera 1 '
            f'--ImageReader.camera_model PINHOLE '
            f'--SiftExtraction.use_gpu 1'
        )
        run_cmd(
            f'colmap sequential_matcher '
            f'--database_path "{db_path}" '
            f'--SequentialMatching.overlap 10'
        )
        run_cmd(
            f'colmap mapper '
            f'--database_path "{db_path}" '
            f'--image_path "{frames_dir}" '
            f'--output_path "{sparse_dir}"'
        )

        sparse_model = os.path.join(sparse_dir, "0")
        if not os.path.exists(sparse_model):
            return {"error": "COLMAP failed. Try recording more slowly with better lighting."}

        log("COLMAP complete. Training Gaussian Splat...")

        ns_data_dir   = os.path.join(workdir, "ns_data")
        ns_output_dir = os.path.join(workdir, "ns_output")

        run_cmd(
            f'ns-process-data images '
            f'--data "{frames_dir}" '
            f'--output-dir "{ns_data_dir}" '
            f'--colmap-model-path "{sparse_model}"'
        )
        run_cmd(
            f'ns-train splatfacto '
            f'--data "{ns_data_dir}" '
            f'--output-dir "{ns_output_dir}" '
            f'--max-num-iterations 10000 '
            f'--vis none'
        )

        # ── Step 5: Export PLY
        log("Step 5/5: Exporting Gaussian Splat...")
        config_path = None
        for root, dirs, files in os.walk(ns_output_dir):
            for f in files:
                if f == "config.yml":
                    config_path = os.path.join(root, f)
                    break

        if not config_path:
            return {"error": "Training complete but config not found"}

        run_cmd(
            f'ns-export gaussian-splat '
            f'--load-config "{config_path}" '
            f'--output-dir "{output_dir}"'
        )

        ply_files = [f for f in os.listdir(output_dir) if f.endswith('.ply')]
        if not ply_files:
            return {"error": "PLY export failed"}

        ply_path = os.path.join(output_dir, ply_files[0])
        ply_size = os.path.getsize(ply_path) / 1024 / 1024

        with open(ply_path, "rb") as f:
            ply_b64 = base64.b64encode(f.read()).decode("utf-8")

        # ── Wait for Gemma to finish
        log("Waiting for Gemma scene analysis to complete...")
        gemma_thread.join(timeout=120)  # max 2 min wait

        log("Job complete!")

        return {
            "success":      True,
            "ply_b64":      ply_b64,
            "ply_size_mb":  round(ply_size, 1),
            "frame_count":  len(frames),
            "prompt":       prompt,

            # Gemma scene intelligence output
            "scene_map":    scene_result,
            "objects_found": scene_result.get("object_count", 0),
            "room_summary": scene_result.get("room_summary", ""),

            "message": f"Gaussian Splat + scene intelligence complete. {scene_result.get('object_count', 0)} objects identified."
        }

    except Exception as e:
        log(f"Error: {str(e)}")
        return {"error": str(e)}

    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        log("Cleaned up temp files")


runpod.serverless.start({"handler": handler})