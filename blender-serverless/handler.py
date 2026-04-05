import runpod                                                                                                                       
import subprocess                                                                                                                   
import base64
import os                                                                                                                           
import json
                                                                                                                                    
def handler(job):                                                                                                                   
    job_input = job["input"]
    job_type = job_input.get("type", "render")                                                                                      
    os.makedirs("/tmp/output", exist_ok=True)
    if job_type == "mesh":                                                                                                          
        return handle_mesh(job_input)
    else:                                                                                                                           
        return handle_render(job_input)                                                                                             
 
def handle_mesh(job_input):                                                                                                         
    import numpy as np
    import open3d as o3d

    ply_b64 = job_input.get("ply_base64")                                                                                           
    if not ply_b64:
        return {"status": "error", "message": "ply_base64 is required"}                                                             
                                                                                                                                    
    ply_path = "/tmp/input.ply"
    with open(ply_path, "wb") as f:                                                                                                 
        f.write(base64.b64decode(ply_b64))
                                                                                                                                    
    pcd = o3d.io.read_point_cloud(ply_path)
    if len(pcd.points) < 9:                                                                                                         
        return {"status": "error", "message": "Not enough points"}                                                                  
 
    pcd.estimate_normals(                                                                                                           
        search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=0.15, max_nn=30)
    )                                                                                                                               
    pcd.orient_normals_consistent_tangent_plane(100)                                                                                
                                                                                                                                    
    mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(pcd, depth=8)                                       
    densities = np.asarray(densities)
    mesh.remove_vertices_by_mask(densities < np.quantile(densities, 0.1))                                                           
                                                                                                                                    
    recon_ply = "/tmp/reconstructed_mesh.ply"                                                                                       
    o3d.io.write_triangle_mesh(recon_ply, mesh)                                                                                     
                                                                                                                                    
    glb_path = "/tmp/reconstructed_mesh.glb"                                                                                        
    convert_script = f"""
import bpy                                                                                                                          
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_mesh.ply(filepath="{recon_ply}")                                                                                     
bpy.ops.export_scene.gltf(filepath="{glb_path}", export_format='GLB')                                                               
"""                                                                                                                                 
    with open("/tmp/convert.py", "w") as f:                                                                                         
        f.write(convert_script)                                                                                                     
                
    result = subprocess.run(                                                                                                        
        ["blender", "--background", "--python", "/tmp/convert.py"],
        capture_output=True, text=True                                                                                              
    )           

    if not os.path.exists(glb_path):                                                                                                
        return {"status": "error", "message": "GLB conversion failed", "log": result.stderr[-2000:]}
                                                                                                                                    
    with open(glb_path, "rb") as f:
        glb_b64 = base64.b64encode(f.read()).decode("utf-8")                                                                        
                                                                                                                                    
    return {"mesh_base64": glb_b64, "status": "ok"}
                                                                                                                                    
def handle_render(job_input, mesh_path=None):                                                                                       
    prompt = job_input.get("prompt", "")
    model_b64 = job_input.get("model_base64", None)                                                                                 
                                                                                                                                    
    if mesh_path is None and model_b64:
        mesh_path = "/tmp/model.glb"                                                                                                
        with open(mesh_path, "wb") as f:                                                                                            
            f.write(base64.b64decode(model_b64))
                                                                                                                                    
    with open("/tmp/input.json", "w") as f:                                                                                         
        json.dump({"mesh_path": mesh_path, "output_path": "/tmp/output", "prompt": prompt}, f)
                                                                                                                                    
    blender_script = """                                                                                                            
import bpy, json, os
from mathutils import Vector                                                                                                        
                
with open("/tmp/input.json") as f:                                                                                                  
    data = json.load(f)
                                                                                                                                    
bpy.ops.wm.read_factory_settings(use_empty=True)
mesh_path = data.get("mesh_path")
                                                                                                                                    
if mesh_path and os.path.exists(mesh_path):
    if mesh_path.endswith(".glb") or mesh_path.endswith(".gltf"):                                                                   
        bpy.ops.import_scene.gltf(filepath=mesh_path)                                                                               
    elif mesh_path.endswith(".ply"):
        bpy.ops.import_mesh.ply(filepath=mesh_path)                                                                                 
    elif mesh_path.endswith(".obj"):
        bpy.ops.import_scene.obj(filepath=mesh_path)                                                                                
    import bmesh as _bmesh                                                                                                          
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":                                                                                                      
            bm = _bmesh.new()                                                                                                       
            bm.from_mesh(obj.data)
            _bmesh.ops.recalc_face_normals(bm, faces=bm.faces)                                                                      
            bm.to_mesh(obj.data)                                                                                                    
            bm.free()
            obj.data.update()                                                                                                       
else:           
    bpy.ops.mesh.primitive_cube_add(size=2)                                                                                         
                                                                                                                                    
prompt = data.get("prompt", "").lower()
metallic = 1.0 if any(x in prompt for x in ["metal","chrome","steel","gold"]) else 0.0                                              
roughness = 0.05 if "chrome" in prompt else 0.3 if "metal" in prompt else 0.8                                                       
if "gold" in prompt:                                                                                                                
    color = (0.8, 0.6, 0.1, 1)                                                                                                      
elif "chrome" in prompt or "steel" in prompt:                                                                                       
    color = (0.9, 0.9, 0.9, 1)
elif "wood" in prompt or "oak" in prompt or "walnut" in prompt:                                                                     
    color = (0.4, 0.25, 0.1, 1); metallic = 0.0; roughness = 0.8                                                                    
elif "linen" in prompt or "fabric" in prompt or "grey" in prompt or "gray" in prompt:                                               
    color = (0.6, 0.6, 0.6, 1); metallic = 0.0; roughness = 0.95                                                                    
elif "leather" in prompt:                                                                                                           
    color = (0.25, 0.12, 0.05, 1); metallic = 0.0; roughness = 0.7                                                                  
elif "marble" in prompt:                                                                                                            
    color = (0.95, 0.93, 0.90, 1); metallic = 0.0; roughness = 0.1
elif "terracotta" in prompt or "clay" in prompt:                                                                                    
    color = (0.72, 0.38, 0.25, 1); metallic = 0.0; roughness = 0.95
else:                                                                                                                               
    color = (0.8, 0.8, 0.8, 1)
                                                                                                                                    
for obj in bpy.context.scene.objects:                                                                                               
    if obj.type == "MESH":
        mat = bpy.data.materials.new("Mat")                                                                                         
        mat.use_nodes = True                                                                                                        
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:                                                                                                                    
            bsdf.inputs["Base Color"].default_value = color
            bsdf.inputs["Metallic"].default_value = metallic                                                                        
            bsdf.inputs["Roughness"].default_value = roughness
        obj.data.materials.clear()                                                                                                  
        obj.data.materials.append(mat)
                                                                                                                                    
mesh_objects = [o for o in bpy.context.scene.objects if o.type == "MESH"]                                                           
all_corners = []
for obj in mesh_objects:                                                                                                            
    for corner in obj.bound_box:
        all_corners.append(obj.matrix_world @ Vector(corner))                                                                       
 
if all_corners:                                                                                                                     
    min_x = min(c.x for c in all_corners); max_x = max(c.x for c in all_corners)
    min_y = min(c.y for c in all_corners); max_y = max(c.y for c in all_corners)                                                    
    min_z = min(c.z for c in all_corners); max_z = max(c.z for c in all_corners)
    center = Vector(((min_x+max_x)/2, (min_y+max_y)/2, (min_z+max_z)/2))                                                            
    size = max(max_x-min_x, max_y-min_y, max_z-min_z)                                                                               
    dist = size * 2.2                                                                                                               
    cam_loc = Vector((center.x + dist*0.6, center.y - dist, center.z + dist*0.5))                                                   
    bpy.ops.object.camera_add(location=cam_loc)                                                                                     
    cam = bpy.context.object
    direction = center - cam_loc                                                                                                    
    rot_quat = direction.to_track_quat("-Z", "Y")                                                                                   
    cam.rotation_euler = rot_quat.to_euler()                                                                                        
    bpy.context.scene.camera = cam                                                                                                  
                                                                                                                                    
world = bpy.context.scene.world                                                                                                     
if not world:
    world = bpy.data.worlds.new("World")                                                                                            
    bpy.context.scene.world = world                                                                                                 
world.use_nodes = True
nt = world.node_tree                                                                                                                
bg = nt.nodes.get("Background")
if not bg:
    bg = nt.nodes.new("ShaderNodeBackground")                                                                                       
    out = nt.nodes.get("World Output") or nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])                                                                   
bg.inputs["Color"].default_value = (0.8, 0.8, 0.8, 1)                                                                               
bg.inputs["Strength"].default_value = 1.5                                                                                           
                                                                                                                                    
bpy.ops.object.light_add(type="SUN", location=(5, -5, 10))                                                                          
bpy.context.object.data.energy = 8                                                                                                  
bpy.ops.object.light_add(type="AREA", location=(-3, 3, 5))                                                                          
bpy.context.object.data.energy = 1200                                                                                               
bpy.context.object.data.size = 6                                                                                                    
                                                                                                                                    
scene = bpy.context.scene                                                                                                           
scene.render.engine = "CYCLES"
scene.cycles.device = "GPU"                                                                                                         
try:
    prefs = bpy.context.preferences.addons["cycles"].preferences                                                                    
    prefs.compute_device_type = "CUDA"
    prefs.get_devices()                                                                                                             
    for d in prefs.devices:
        d.use = True                                                                                                                
except Exception as e:                                                                                                              
    print("GPU setup failed, falling back to CPU:", e)
scene.cycles.samples = 8                                                                                                           
scene.render.resolution_x = 256
scene.render.resolution_y = 256                                                                                                     
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = os.path.join(data["output_path"], "render.png")                                                             
bpy.ops.render.render(write_still=True)
"""                                                                                                                                 
                
    with open("/tmp/render.py", "w") as f:                                                                                          
        f.write(blender_script)

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
        return {"status": "error", "log": result.stderr[-3000:]}                                                                    
                
runpod.serverless.start({"handler": handler})  