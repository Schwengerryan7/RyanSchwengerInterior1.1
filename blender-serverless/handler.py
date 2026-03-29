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
                                                                                                                    
      pointcloud_data = job_input.get("pointcloud", {})
      prompt = job_input.get("prompt", "")                                                                          
                                                                                                                    
      samples = pointcloud_data.get("samples", [{}])
      positions = samples[0].get("pointPositions", [])                                                              
                                                                                                                    
      if len(positions) < 9:
          return {"status": "error", "message": "Not enough points"}                                                
                  
      points = np.array(positions, dtype=np.float64).reshape(-1, 3)                                                 
   
      pcd = o3d.geometry.PointCloud()                                                                               
      pcd.points = o3d.utility.Vector3dVector(points)
                                                                                                                    
      pcd.estimate_normals(
          search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=0.15, max_nn=30)
      )                                                                                                             
      pcd.orient_normals_consistent_tangent_plane(100)
                                                                                                                    
      mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(pcd, depth=8)                     
   
      densities = np.asarray(densities)                                                                             
      vertices_to_remove = densities < np.quantile(densities, 0.1)
      mesh.remove_vertices_by_mask(vertices_to_remove)                                                              
                                                                                                                    
      mesh_path = "/tmp/reconstructed_mesh.ply"                                                                     
      o3d.io.write_triangle_mesh(mesh_path, mesh)                                                                   
                                                                                                                    
      return handle_render(job_input, mesh_path=mesh_path)

  def handle_render(job_input, mesh_path=None):                                                                     
      prompt = job_input.get("prompt", "")
      model_b64 = job_input.get("model_base64", None)                                                               
                                                                                                                    
      if mesh_path is None and model_b64:
          mesh_path = "/tmp/model.glb"                                                                              
          with open(mesh_path, "wb") as f:                                                                          
              f.write(base64.b64decode(model_b64))
                                                                                                                    
      with open("/tmp/input.json", "w") as f:                                                                       
          json.dump({"mesh_path": mesh_path, "output_path": "/tmp/output", "prompt": prompt}, f)
                                                                                                                    
      blender_script = '''
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
  else:                                                                                                             
      bpy.ops.mesh.primitive_cube_add(size=2)
                                                                                                                    
  prompt = data.get("prompt", "").lower()
  metallic = 1.0 if any(x in prompt for x in ["metal","chrome","steel","gold"]) else 0.0                            
  roughness = 0.05 if "chrome" in prompt else 0.3 if "metal" in prompt else 0.8                                     
  if "gold" in prompt: color = (0.8, 0.6, 0.1, 1)                                                                   
  elif "chrome" in prompt or "steel" in prompt: color = (0.9, 0.9, 0.9, 1)                                          
  elif "wood" in prompt or "oak" in prompt or "walnut" in prompt: color = (0.4, 0.25, 0.1, 1); metallic = 0.0;      
  roughness = 0.8                                                                                                   
  elif "linen" in prompt or "fabric" in prompt: color = (0.9, 0.85, 0.75, 1); metallic = 0.0; roughness = 0.95      
  elif "leather" in prompt: color = (0.25, 0.12, 0.05, 1); metallic = 0.0; roughness = 0.7                          
  else: color = (0.8, 0.8, 0.8, 1)                                                                                  
                                                                                                                    
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

      result = subprocess.run(["blender", "--background", "--python", "/tmp/render.py"], capture_output=True,       
  text=True)
                                                                                                                    
      output_path = "/tmp/output/render.png"                                                                        
      if os.path.exists(output_path):
          with open(output_path, "rb") as f:                                                                        
              img_b64 = base64.b64encode(f.read()).decode("utf-8")
          return {"image_base64": img_b64, "status": "ok"}                                                          
      else:                                                                                                         
          return {"status": "error", "log": result.stderr[-3000:]}                                                  
                                                                                                                    
  runpod.serverless.start({"handler": handler})