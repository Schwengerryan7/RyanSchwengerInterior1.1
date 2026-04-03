        3  import base64
        4  import os
        5  import json
        6 -import numpy as np                                                                                                  
        6  
        7  def handler(job):
        8      job_input = job["input"]
        9      job_type = job_input.get("type", "render")
       11 -                                                                                                                    
       10      os.makedirs("/tmp/output", exist_ok=True)
       13 -                                                                                                                    
       11      if job_type == "mesh":
       12          return handle_mesh(job_input)
       13      else:
       14          return handle_render(job_input)
       15  
       19 -                                                                                                                    
       20 -# ─────────────────────────────────────────────                                                                     
       21 -# MESH: PLY point cloud → GLB via Open3D                                                                            
       22 -# ─────────────────────────────────────────────                                                                     
       16  def handle_mesh(job_input):
       17 +    import numpy as np                                                                                              
       18 +    import open3d as o3d                                                                                            
       19 +                                                                                                                    
       20      ply_b64 = job_input.get("ply_base64")
       21      if not ply_b64:
       26 -        return {"status": "error", "log": "No ply_base64 provided"}                                                 
       22 +        return {"status": "error", "message": "ply_base64 is required"}                                             
       23  
       24      ply_path = "/tmp/input.ply"
       25      with open(ply_path, "wb") as f:
       26          f.write(base64.b64decode(ply_b64))
       27  
       32 -    recon_script = '''                                                                                              
       33 -import open3d as o3d                                                                                                
       34 -import numpy as np                                                                                                  
       35 -import sys                                                                                                          
       28 +    pcd = o3d.io.read_point_cloud(ply_path)                                                                         
       29 +    if len(pcd.points) < 9:                                                                                         
       30 +        return {"status": "error", "message": "Not enough points"}                                                  
       31  
       37 -ply_path = "/tmp/input.ply"                                                                                         
       38 -obj_path = "/tmp/mesh.obj"                                                                                          
       39 -                                                                                                                    
       40 -pcd = o3d.io.read_point_cloud(ply_path)                                                                             
       41 -print(f"Loaded {len(pcd.points)} points", flush=True)                                                               
       42 -                                                                                                                    
       43 -pts = np.asarray(pcd.points)                                                                                        
       44 -bbox_size = pts.max(axis=0) - pts.min(axis=0)                                                                       
       45 -radius = float(np.max(bbox_size)) * 0.015                                                                           
       46 -                                                                                                                    
       47 -pcd.estimate_normals(                                                                                               
       48 -    search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=radius, max_nn=30)                                     
       49 -)                                                                                                                   
       50 -pcd.orient_normals_consistent_tangent_plane(100)                                                                    
       51 -                                                                                                                    
       52 -print("Running Poisson reconstruction...", flush=True)                                                              
       53 -mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(                                        
       54 -    pcd, depth=9                                                                                                    
       55 -)                                                                                                                   
       56 -                                                                                                                    
       57 -vertices_to_remove = densities < np.quantile(densities, 0.05)                                                       
       58 -mesh.remove_vertices_by_mask(vertices_to_remove)                                                                    
       59 -mesh.compute_vertex_normals()                                                                                       
       60 -                                                                                                                    
       61 -print(f"Mesh: {len(mesh.vertices)} vertices, {len(mesh.triangles)} triangles", flush=True)                          
       62 -o3d.io.write_triangle_mesh(obj_path, mesh)                                                                          
       63 -print("Saved OBJ", flush=True)                                                                                      
       64 -'''                                                                                                                 
       65 -                                                                                                                    
       66 -    with open("/tmp/recon.py", "w") as f:                                                                           
       67 -        f.write(recon_script)                                                                                       
       68 -                                                                                                                    
       69 -    result = subprocess.run(                                                                                        
       70 -        ["python3", "/tmp/recon.py"],                                                                               
       71 -        capture_output=True, text=True                                                                              
       32 +    pcd.estimate_normals(                                                                                           
       33 +        search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=0.15, max_nn=30)                                   
       34      )
       35 +    pcd.orient_normals_consistent_tangent_plane(100)                                                                
       36  
       74 -    if result.returncode != 0 or not os.path.exists("/tmp/mesh.obj"):                                               
       75 -        return {"status": "error", "log": result.stderr[-3000:] + result.stdout[-1000:]}                            
       37 +    mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(pcd, depth=8)                       
       38 +    densities = np.asarray(densities)                                                                               
       39 +    mesh.remove_vertices_by_mask(densities < np.quantile(densities, 0.1))                                           
       40  
       77 -    blender_script = '''                                                                                            
       41 +    recon_ply = "/tmp/reconstructed_mesh.ply"                                                                       
       42 +    o3d.io.write_triangle_mesh(recon_ply, mesh)                                                                     
       43 +                                                                                                                    
       44 +    glb_path = "/tmp/reconstructed_mesh.glb"                                                                        
       45 +    convert_script = f"""                                                                                           
       46  import bpy
       47  bpy.ops.wm.read_factory_settings(use_empty=True)
       80 -bpy.ops.import_scene.obj(filepath="/tmp/mesh.obj")                                                                  
       81 -bpy.ops.export_scene.gltf(filepath="/tmp/mesh.glb", export_format="GLB")                                            
       82 -print("GLB exported", flush=True)                                                                                   
       83 -'''                                                                                                                 
       84 -                                                                                                                    
       48 +bpy.ops.import_mesh.ply(filepath="{recon_ply}")                                                                     
       49 +bpy.ops.export_scene.gltf(filepath="{glb_path}", export_format='GLB')                                               
       50 +"""                                                                                                                 
       51      with open("/tmp/convert.py", "w") as f:
       86 -        f.write(blender_script)                                                                                     
       52 +        f.write(convert_script)                                                                                     
       53  
       88 -    result2 = subprocess.run(                                                                                       
       54 +    result = subprocess.run(                                                                                        
       55          ["blender", "--background", "--python", "/tmp/convert.py"],
       56          capture_output=True, text=True
       57      )
       58  
       93 -    glb_path = "/tmp/mesh.glb"                                                                                      
       94 -    if os.path.exists(glb_path):                                                                                    
       95 -        with open(glb_path, "rb") as f:                                                                             
       96 -            mesh_b64 = base64.b64encode(f.read()).decode("utf-8")                                                   
       97 -        return {"mesh_base64": mesh_b64, "status": "ok"}                                                            
       98 -    else:                                                                                                           
       99 -        return {"status": "error", "log": result2.stderr[-3000:]}                                                   
       59 +    if not os.path.exists(glb_path):                                                                                
       60 +        return {"status": "error", "message": "GLB conversion failed", "log": result.stderr[-2000:]}                
       61  
       62 +    with open(glb_path, "rb") as f:                                                                                 
       63 +        glb_b64 = base64.b64encode(f.read()).decode("utf-8")                                                        
       64  
      102 -# ─────────────────────────────────────────────                                                                     
      103 -# RENDER: GLB + material prompt → PNG via Blender Cycles                                                            
      104 -# ─────────────────────────────────────────────                                                                     
      105 -def handle_render(job_input):                                                                                       
       65 +    return {"mesh_base64": glb_b64, "status": "ok"}                                                                 
       66 +                                                                                                                    
       67 +def handle_render(job_input, mesh_path=None):                                                                       
       68      prompt = job_input.get("prompt", "")
       69      model_b64 = job_input.get("model_base64", None)
       70  
      109 -    model_path = None                                                                                               
      110 -    if model_b64:                                                                                                   
      111 -        model_path = "/tmp/model.glb"                                                                               
      112 -        with open(model_path, "wb") as f:                                                                           
       71 +    if mesh_path is None and model_b64:                                                                             
       72 +        mesh_path = "/tmp/model.glb"                                                                                
       73 +        with open(mesh_path, "wb") as f:                                                                            
       74              f.write(base64.b64decode(model_b64))
       75  
       76      with open("/tmp/input.json", "w") as f:
      116 -        json.dump({"mesh_path": model_path, "output_path": "/tmp/output", "prompt": prompt}, f)                     
       77 +        json.dump({"mesh_path": mesh_path, "output_path": "/tmp/output", "prompt": prompt}, f)                      
       78  
      118 -    blender_script = '''                                                                                            
      119 -import bpy, json, os, math                                                                                          
       79 +    blender_script = """                                                                                            
       80 +import bpy, json, os                                                                                                
       81  from mathutils import Vector
       82  
       83  with open("/tmp/input.json") as f:
       84      data = json.load(f)
       85  
       86  bpy.ops.wm.read_factory_settings(use_empty=True)
      126 -                                                                                                                    
       87  mesh_path = data.get("mesh_path")
       88 +                                                                                                                    
       89  if mesh_path and os.path.exists(mesh_path):
      129 -    bpy.ops.import_scene.gltf(filepath=mesh_path)                                                                   
       90 +    if mesh_path.endswith(".glb") or mesh_path.endswith(".gltf"):                                                   
       91 +        bpy.ops.import_scene.gltf(filepath=mesh_path)                                                               
       92 +    elif mesh_path.endswith(".ply"):                                                                                
       93 +        bpy.ops.import_mesh.ply(filepath=mesh_path)                                                                 
       94 +    elif mesh_path.endswith(".obj"):                                                                                
       95 +        bpy.ops.import_scene.obj(filepath=mesh_path)                                                                
       96  else:
       97      bpy.ops.mesh.primitive_cube_add(size=2)
       98  
       99  prompt = data.get("prompt", "").lower()
      134 -                                                                                                                    
      100  metallic = 1.0 if any(x in prompt for x in ["metal","chrome","steel","gold"]) else 0.0
      101  roughness = 0.05 if "chrome" in prompt else 0.3 if "metal" in prompt else 0.8
      102  if "gold" in prompt:
     ...
      104  elif "chrome" in prompt or "steel" in prompt:
      105      color = (0.9, 0.9, 0.9, 1)
      106  elif "wood" in prompt or "oak" in prompt or "walnut" in prompt:
      142 -    color = (0.4, 0.25, 0.1, 1)                                                                                     
      143 -    metallic = 0.0                                                                                                  
      144 -    roughness = 0.8                                                                                                 
      107 +    color = (0.4, 0.25, 0.1, 1); metallic = 0.0; roughness = 0.8                                                    
      108  elif "linen" in prompt or "fabric" in prompt or "grey" in prompt or "gray" in prompt:
      146 -    color = (0.6, 0.6, 0.6, 1)                                                                                      
      147 -    metallic = 0.0                                                                                                  
      148 -    roughness = 0.95                                                                                                
      109 +    color = (0.6, 0.6, 0.6, 1); metallic = 0.0; roughness = 0.95                                                    
      110 +elif "leather" in prompt:                                                                                           
      111 +    color = (0.25, 0.12, 0.05, 1); metallic = 0.0; roughness = 0.7                                                  
      112  elif "marble" in prompt:
      150 -    color = (0.95, 0.93, 0.90, 1)                                                                                   
      151 -    metallic = 0.0                                                                                                  
      152 -    roughness = 0.1                                                                                                 
      113 +    color = (0.95, 0.93, 0.90, 1); metallic = 0.0; roughness = 0.1                                                  
      114  elif "terracotta" in prompt or "clay" in prompt:
      154 -    color = (0.72, 0.38, 0.25, 1)                                                                                   
      155 -    metallic = 0.0                                                                                                  
      156 -    roughness = 0.95                                                                                                
      115 +    color = (0.72, 0.38, 0.25, 1); metallic = 0.0; roughness = 0.95                                                 
      116  else:
      117      color = (0.8, 0.8, 0.8, 1)
      118  
     ...
      132  all_corners = []
      133  for obj in mesh_objects:
      134      for corner in obj.bound_box:
      176 -        world_corner = obj.matrix_world @ Vector(corner)                                                            
      177 -        all_corners.append(world_corner)                                                                            
      135 +        all_corners.append(obj.matrix_world @ Vector(corner))                                                       
      136  
      137  if all_corners:
      180 -    min_x = min(c.x for c in all_corners)                                                                           
      181 -    max_x = max(c.x for c in all_corners)                                                                           
      182 -    min_y = min(c.y for c in all_corners)                                                                           
      183 -    max_y = max(c.y for c in all_corners)                                                                           
      184 -    min_z = min(c.z for c in all_corners)                                                                           
      185 -    max_z = max(c.z for c in all_corners)                                                                           
      186 -                                                                                                                    
      138 +    min_x = min(c.x for c in all_corners); max_x = max(c.x for c in all_corners)                                    
      139 +    min_y = min(c.y for c in all_corners); max_y = max(c.y for c in all_corners)                                    
      140 +    min_z = min(c.z for c in all_corners); max_z = max(c.z for c in all_corners)                                    
      141      center = Vector(((min_x+max_x)/2, (min_y+max_y)/2, (min_z+max_z)/2))
      142      size = max(max_x-min_x, max_y-min_y, max_z-min_z)
      189 -    dist = size * 2.5                                                                                               
      190 -                                                                                                                    
      191 -    cam_loc = Vector((center.x + dist*0.6, center.y - dist, center.z + dist*0.4))                                   
      143 +    dist = size * 2.2                                                                                               
      144 +    cam_loc = Vector((center.x + dist*0.6, center.y - dist, center.z + dist*0.5))                                   
      145      bpy.ops.object.camera_add(location=cam_loc)
      146      cam = bpy.context.object
      147      direction = center - cam_loc
     ...
      149      cam.rotation_euler = rot_quat.to_euler()
      150      bpy.context.scene.camera = cam
      151  
      199 -# World background lighting                                                                                         
      152  world = bpy.context.scene.world
      153  if not world:
      154      world = bpy.data.worlds.new("World")
     ...
      160      bg.inputs["Strength"].default_value = 1.5
      161  
      162  bpy.ops.object.light_add(type="SUN", location=(5, -5, 10))
      211 -sun = bpy.context.object                                                                                            
      212 -sun.data.energy = 8                                                                                                 
      213 -                                                                                                                    
      163 +bpy.context.object.data.energy = 8                                                                                  
      164  bpy.ops.object.light_add(type="AREA", location=(-3, 3, 5))
      215 -fill = bpy.context.object                                                                                           
      216 -fill.data.energy = 1200                                                                                             
      217 -fill.data.size = 6                                                                                                  
      165 +bpy.context.object.data.energy = 1200                                                                               
      166 +bpy.context.object.data.size = 6                                                                                    
      167  
      168  scene = bpy.context.scene
      169  scene.render.engine = "CYCLES"
     ...
      171  scene.render.resolution_x = 1024
      172  scene.render.resolution_y = 1024
      173  scene.render.image_settings.file_format = "PNG"
      225 -output_file = os.path.join(data["output_path"], "render.png")                                                       
      226 -scene.render.filepath = output_file                                                                                 
      174 +scene.render.filepath = os.path.join(data["output_path"], "render.png")                                             
      175  bpy.ops.render.render(write_still=True)
      228 -'''                                                                                                                 
      176 +"""                                                                                                                 
      177  
      178      with open("/tmp/render.py", "w") as f:
      179          f.write(blender_script)
     ...
      191      else:
      192          return {"status": "error", "log": result.stderr[-3000:]}
      193  
      246 -                                                                                                                    
      194  runpod.serverless.start({"handler": handler})