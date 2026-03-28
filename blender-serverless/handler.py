  import runpod                                                                                                                                        
  import subprocess
  import base64
  import os
  import json
  import numpy as np
                                                                                                                                                       
  def handler(job):
      job_input = job["input"]                                                                                                                         
      job_type = job_input.get("type", "render")
      os.makedirs("/tmp/output", exist_ok=True)
      if job_type == "mesh":                                                                                                                           
          return handle_mesh(job_input)
      else:                                                                                                                                            
          return handle_render(job_input)
                                                                                                                                                       
   
  def handle_mesh(job_input):                                                                                                                          
      ply_b64 = job_input.get("ply_base64")
      if not ply_b64:                                                                                                                                  
          return {"status": "error", "log": "No ply_base64 provided"}
                                                                                                                                                       
      with open("/tmp/input.ply", "wb") as f:                                                                                                          
          f.write(base64.b64decode(ply_b64))
                                                                                                                                                       
      recon_script = '''
  import open3d as o3d
  import numpy as np
                                                                                                                                                       
  pcd = o3d.io.read_point_cloud("/tmp/input.ply")
  print(f"Loaded {len(pcd.points)} points", flush=True)                                                                                                
                                                                                                                                                       
  pts = np.asarray(pcd.points)
  bbox_size = pts.max(axis=0) - pts.min(axis=0)                                                                                                        
  radius = float(np.max(bbox_size)) * 0.02                                                                                                             
                                                                                                                                                       
  pcd.estimate_normals(                                                                                                                                
      search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=radius, max_nn=30)                                                                      
  )                                                                                                                                                    
  pcd.orient_normals_consistent_tangent_plane(100)
                                                                                                                                                       
  print("Running Poisson reconstruction...", flush=True)                                                                                               
  mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(pcd, depth=8)                                                            
                                                                                                                                                       
  vertices_to_remove = densities < np.quantile(densities, 0.05)                                                                                        
  mesh.remove_vertices_by_mask(vertices_to_remove)                                                                                                     
  mesh.compute_vertex_normals()                                                                                                                        
                  
  print(f"Mesh: {len(mesh.vertices)} vertices, {len(mesh.triangles)} triangles", flush=True)                                                           
  o3d.io.write_triangle_mesh("/tmp/mesh.obj", mesh)
  print("Saved OBJ", flush=True)                                                                                                                       
  '''             
                                                                                                                                                       
      with open("/tmp/recon.py", "w") as f:
          f.write(recon_script)

      result = subprocess.run(["python3", "/tmp/recon.py"], capture_output=True, text=True)                                                            
   
      if result.returncode != 0 or not os.path.exists("/tmp/mesh.obj"):                                                                                
          return {"status": "error", "log": result.stderr[-3000:] + result.stdout[-1000:]}
                                                                                                                                                       
      blender_script = '''
  import bpy                                                                                                                                           
  bpy.ops.wm.read_factory_settings(use_empty=True)
  bpy.ops.import_scene.obj(filepath="/tmp/mesh.obj")
  bpy.ops.export_scene.gltf(filepath="/tmp/mesh.glb", export_format="GLB")                                                                             
  print("GLB exported", flush=True)                                                                                                                    
  '''                                                                                                                                                  
                                                                                                                                                       
      with open("/tmp/convert.py", "w") as f:                                                                                                          
          f.write(blender_script)
                                                                                                                                                       
      result2 = subprocess.run(
          ["blender", "--background", "--python", "/tmp/convert.py"],
          capture_output=True, text=True
      )

      if os.path.exists("/tmp/mesh.glb"):
          with open("/tmp/mesh.glb", "rb") as f:
              mesh_b64 = base64.b64encode(f.read()).decode("utf-8")
          return {"mesh_base64": mesh_b64, "status": "ok"}                                                                                             
      else:
          return {"status": "error", "log": result2.stderr[-3000:]}                                                                                    
                                                                                                                                                       
   
  def handle_render(job_input):                                                                                                                        
      prompt = job_input.get("prompt", "")
      model_b64 = job_input.get("model_base64", None)

      model_path = None                                                                                                                                
      if model_b64:
          model_path = "/tmp/model.glb"                                                                                                                
          with open(model_path, "wb") as f:
              f.write(base64.b64decode(model_b64))

      with open("/tmp/input.json", "w") as f:                                                                                                          
          json.dump({"mesh_path": model_path, "output_path": "/tmp/output", "prompt": prompt}, f)
                                                                                                                                                       
      blender_script = '''
  import bpy, json, os
  from mathutils import Vector                                                                                                                         
   
  with open("/tmp/input.json") as f:                                                                                                                   
      data = json.load(f)

  bpy.ops.wm.read_factory_settings(use_empty=True)

  mesh_path = data.get("mesh_path")
  if mesh_path and os.path.exists(mesh_path):
      bpy.ops.import_scene.gltf(filepath=mesh_path)                                                                                                    
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
      color = (0.4, 0.25, 0.1, 1)
      metallic = 0.0                                                                                                                                   
      roughness = 0.8
  elif "linen" in prompt or "fabric" in prompt:                                                                                                        
      color = (0.9, 0.85, 0.75, 1)
      metallic = 0.0                                                                                                                                   
      roughness = 0.95
  elif "marble" in prompt:
      color = (0.95, 0.93, 0.90, 1)                                                                                                                    
      metallic = 0.0
      roughness = 0.1                                                                                                                                  
  elif "terracotta" in prompt or "clay" in prompt:                                                                                                     
      color = (0.72, 0.38, 0.25, 1)
      metallic = 0.0                                                                                                                                   
      roughness = 0.95                                                                                                                                 
  elif "leather" in prompt:
      color = (0.25, 0.12, 0.05, 1)                                                                                                                    
      metallic = 0.0
      roughness = 0.7                                                                                                                                  
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
      min_x = min(c.x for c in all_corners)
      max_x = max(c.x for c in all_corners)
      min_y = min(c.y for c in all_corners)                                                                                                            
      max_y = max(c.y for c in all_corners)
      min_z = min(c.z for c in all_corners)                                                                                                            
      max_z = max(c.z for c in all_corners)                                                                                                            
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
                                                                                                                                                       
  bpy.ops.object.light_add(type="SUN", location=(5, -5, 10))                                                                                           
  bpy.context.object.data.energy = 3
  bpy.ops.object.light_add(type="AREA", location=(-3, 3, 5))                                                                                           
  bpy.context.object.data.energy = 800
  bpy.context.object.data.size = 6

  scene = bpy.context.scene
  scene.render.engine = "CYCLES"
  scene.cycles.samples = 128
  scene.render.resolution_x = 1024
  scene.render.resolution_y = 1024                                                                                                                     
  scene.render.image_settings.file_format = "PNG"
  scene.render.filepath = os.path.join(data["output_path"], "render.png")                                                                              
  bpy.ops.render.render(write_still=True)                                                                                                              
  '''
                                                                                                                                                       
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