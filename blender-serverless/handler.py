import runpod
import subprocess
import base64
import os
import json
import tempfile

def handler(job):
    job_input = job["input"]
    prompt = job_input.get("prompt", "")
    model_b64 = job_input.get("model_base64", None)

    # Save model if provided
    if model_b64:
        model_path = "/tmp/model.glb"
        with open(model_path, "wb") as f:
            f.write(base64.b64decode(model_b64))
    else:
        model_path = "/tmp/model.glb"

    # Write input.json
    os.makedirs("/tmp/output", exist_ok=True)
    with open("/tmp/input.json", "w") as f:
        json.dump({
            "mesh_path": model_path,
            "output_path": "/tmp/output",
            "prompt": prompt
        }, f)

    # Write blender script
    blender_script = '''
import bpy, json, os, math

with open("/tmp/input.json") as f:
    data = json.load(f)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=data["mesh_path"])

prompt = data.get("prompt", "").lower()

# Determine material from prompt
metallic = 1.0 if any(x in prompt for x in ["metal","chrome","steel","gold"]) else 0.0
roughness = 0.05 if "chrome" in prompt else 0.3 if "metal" in prompt else 0.8
color = (0.8,0.6,0.1,1) if "gold" in prompt else (0.8,0.8,0.8,1)

for obj in bpy.context.scene.objects:
    if obj.type == "MESH":
        mat = bpy.data.materials.new("Mat")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Roughness"].default_value = roughness
        obj.data.materials.clear()
        obj.data.materials.append(mat)

bpy.ops.object.light_add(type="AREA", location=(0,0,5))
bpy.context.active_object.data.energy = 3000

bpy.ops.object.camera_add(location=(3,-3,2.5))
cam = bpy.context.active_object
cam.rotation_euler = (math.radians(65),0,math.radians(45))
bpy.context.scene.camera = cam

scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.device = "GPU"
scene.cycles.samples = 128
scene.render.resolution_x = 1024
scene.render.resolution_y = 1024
scene.render.filepath = data["output_path"] + "/render.png"
scene.render.image_settings.file_format = "PNG"
bpy.ops.render.render(write_still=True)
'''

    with open("/tmp/render.py", "w") as f:
        f.write(blender_script)

    # Run Blender
    result = subprocess.run(
        ["blender", "--background", "--python", "/tmp/render.py"],
        capture_output=True, text=True
    )

    output_path = "/tmp/output/render.png"
    if os.path.exists(output_path):
        with open(output_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")
        return {"image_base64": img_b64, "status": "ok"}
    else:
        return {"status": "error", "log": result.stderr[-2000:]}

runpod.serverless.start({"handler": handler})
