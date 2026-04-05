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
  import bpy, json, os, math                                                                                                          
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
              obj.rotation_euler[0] = math.radians(90)                                                                                
      bpy.ops.object.select_all(action='SELECT')
      bpy.ops.object.transform_apply(rotation=True)                                                                                   
      for obj in bpy.context.scene.objects:
          if obj.type == "MESH":                                                                                                      
              bpy.context.view_layer.objects.active = obj                                                                             
              rem = obj.modifiers.new("Remesh", "REMESH")
              rem.mode = 'SMOOTH'                                                                                                     
              rem.octree_depth = 7
              rem.use_smooth_shade = True                                                                                             
              bpy.ops.object.modifier_apply(modifier="Remesh")                                                                        
              sub = obj.modifiers.new("Subdivision", "SUBSURF")
              sub.levels = 2                                                                                                          
              sub.render_levels = 2                                                                                                   
              bpy.ops.object.modifier_apply(modifier="Subdivision")
              bm = _bmesh.new()                                                                                                       
              bm.from_mesh(obj.data)
              _bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
              bm.to_mesh(obj.data)                                                                                                    
              bm.free()
              obj.data.update()                                                                                                       
  else:           
      bpy.ops.mesh.primitive_cube_add(size=2)                                                                                         
                                                                                                                                      
  prompt = data.get("prompt", "").lower()
                                                                                                                                      
  if "gold" in prompt:                                                                                                                
      mat_type = "gold"
      base_color = (0.8, 0.55, 0.1, 1)                                                                                                
      metallic = 1.0
      roughness = 0.15                                                                                                                
  elif "chrome" in prompt:
      mat_type = "chrome"                                                                                                             
      base_color = (0.95, 0.95, 0.95, 1)
      metallic = 1.0                                                                                                                  
      roughness = 0.03
  elif "steel" in prompt or "metal" in prompt or "matte black" in prompt or "black" in prompt:                                        
      mat_type = "metal"                                                                                                              
      base_color = (0.02, 0.02, 0.02, 1) if "black" in prompt else (0.7, 0.7, 0.7, 1)
      metallic = 1.0 if "metal" in prompt or "steel" in prompt else 0.0                                                               
      roughness = 0.05 if "chrome" in prompt else 0.4                                                                                 
  elif "wood" in prompt or "oak" in prompt or "walnut" in prompt:                                                                     
      mat_type = "wood"                                                                                                               
      base_color = (0.25, 0.12, 0.05, 1) if "walnut" in prompt else (0.45, 0.28, 0.1, 1)                                              
      metallic = 0.0                                                                                                                  
      roughness = 0.75                                                                                                                
  elif "linen" in prompt or "fabric" in prompt or "grey" in prompt or "gray" in prompt:                                               
      mat_type = "fabric"                                                                                                             
      base_color = (0.55, 0.55, 0.55, 1)
      metallic = 0.0                                                                                                                  
      roughness = 0.95
  elif "leather" in prompt:                                                                                                           
      mat_type = "leather"
      base_color = (0.22, 0.1, 0.04, 1)
      metallic = 0.0                                                                                                                  
      roughness = 0.65
  elif "marble" in prompt:                                                                                                            
      mat_type = "marble"
      base_color = (0.95, 0.93, 0.90, 1)
      metallic = 0.0                                                                                                                  
      roughness = 0.05
  elif "terracotta" in prompt or "clay" in prompt:                                                                                    
      mat_type = "clay"                                                                                                               
      base_color = (0.72, 0.38, 0.25, 1)
      metallic = 0.0                                                                                                                  
      roughness = 0.95
  else:                                                                                                                               
      mat_type = "default"
      base_color = (0.8, 0.8, 0.8, 1)                                                                                                 
      metallic = 0.0                                                                                                                  
      roughness = 0.8
                                                                                                                                      
  for obj in bpy.context.scene.objects:
      if obj.type == "MESH" and obj.name != "Floor":
          mat = bpy.data.materials.new("Mat_" + obj.name)
          mat.use_nodes = True                                                                                                        
          nodes = mat.node_tree.nodes
          links = mat.node_tree.links                                                                                                 
          nodes.clear()
                                                                                                                                      
          out = nodes.new("ShaderNodeOutputMaterial")
          out.location = (800, 0)
          bsdf = nodes.new("ShaderNodeBsdfPrincipled")                                                                                
          bsdf.location = (400, 0)
          bsdf.inputs["Base Color"].default_value = base_color                                                                        
          bsdf.inputs["Metallic"].default_value = metallic                                                                            
          bsdf.inputs["Roughness"].default_value = roughness
          links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])                                                                      
                                                                                                                                      
          tex_coord = nodes.new("ShaderNodeTexCoord")
          tex_coord.location = (-800, 0)                                                                                              
          mapping = nodes.new("ShaderNodeMapping")                                                                                    
          mapping.location = (-600, 0)
          links.new(tex_coord.outputs["Object"], mapping.inputs["Vector"])                                                            
                                                                                                                                      
          if mat_type == "fabric":
              noise1 = nodes.new("ShaderNodeTexNoise")                                                                                
              noise1.location = (-400, 100)
              noise1.inputs["Scale"].default_value = 80                                                                               
              noise1.inputs["Detail"].default_value = 10
              noise1.inputs["Roughness"].default_value = 0.8                                                                          
              links.new(mapping.outputs["Vector"], noise1.inputs["Vector"])                                                           
              bump = nodes.new("ShaderNodeBump")
              bump.location = (100, -100)                                                                                             
              bump.inputs["Strength"].default_value = 0.4
              bump.inputs["Distance"].default_value = 0.02                                                                            
              links.new(noise1.outputs["Fac"], bump.inputs["Height"])
              links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])                                                                
              noise2 = nodes.new("ShaderNodeTexNoise")                                                                                
              noise2.location = (-400, -150)
              noise2.inputs["Scale"].default_value = 15                                                                               
              noise2.inputs["Detail"].default_value = 4                                                                               
              links.new(mapping.outputs["Vector"], noise2.inputs["Vector"])
              ramp = nodes.new("ShaderNodeValToRGB")                                                                                  
              ramp.location = (-100, -150)                                                                                            
              ramp.color_ramp.elements[0].color = (base_color[0]*0.85, base_color[1]*0.85, base_color[2]*0.85, 1)
              ramp.color_ramp.elements[1].color = base_color                                                                          
              links.new(noise2.outputs["Fac"], ramp.inputs["Fac"])                                                                    
              links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])                                                             
                                                                                                                                      
          elif mat_type == "wood":
              wave = nodes.new("ShaderNodeTexWave")                                                                                   
              wave.location = (-400, 100)
              wave.wave_type = 'RINGS'
              wave.inputs["Scale"].default_value = 6                                                                                  
              wave.inputs["Distortion"].default_value = 3
              wave.inputs["Detail"].default_value = 6                                                                                 
              wave.inputs["Detail Scale"].default_value = 1.5                                                                         
              links.new(mapping.outputs["Vector"], wave.inputs["Vector"])
              ramp = nodes.new("ShaderNodeValToRGB")                                                                                  
              ramp.location = (-100, 100)                                                                                             
              dark = (base_color[0]*0.6, base_color[1]*0.6, base_color[2]*0.6, 1)
              ramp.color_ramp.elements[0].color = dark                                                                                
              ramp.color_ramp.elements[1].color = base_color
              links.new(wave.outputs["Color"], ramp.inputs["Fac"])                                                                    
              links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])                                                             
              bump = nodes.new("ShaderNodeBump")
              bump.location = (100, -100)                                                                                             
              bump.inputs["Strength"].default_value = 0.15                                                                            
              links.new(wave.outputs["Fac"], bump.inputs["Height"])
              links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])                                                                
                                                                                                                                      
          elif mat_type in ("metal", "chrome", "gold"):
              noise = nodes.new("ShaderNodeTexNoise")                                                                                 
              noise.location = (-400, 0)                                                                                              
              noise.inputs["Scale"].default_value = 200
              noise.inputs["Detail"].default_value = 16                                                                               
              noise.inputs["Roughness"].default_value = 0.9
              links.new(mapping.outputs["Vector"], noise.inputs["Vector"])                                                            
              rmap = nodes.new("ShaderNodeMapRange")
              rmap.location = (-100, 0)                                                                                               
              rmap.inputs["From Min"].default_value = 0.0
              rmap.inputs["From Max"].default_value = 1.0                                                                             
              rmap.inputs["To Min"].default_value = max(0, roughness - 0.05)                                                          
              rmap.inputs["To Max"].default_value = min(1, roughness + 0.1)
              links.new(noise.outputs["Fac"], rmap.inputs["Value"])                                                                   
              links.new(rmap.outputs["Result"], bsdf.inputs["Roughness"])
              if mat_type != "chrome":                                                                                                
                  bump = nodes.new("ShaderNodeBump")
                  bump.location = (100, -100)                                                                                         
                  bump.inputs["Strength"].default_value = 0.1                                                                         
                  links.new(noise.outputs["Fac"], bump.inputs["Height"])
                  links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])                                                            
                                                                                                                                      
          elif mat_type == "leather":
              noise = nodes.new("ShaderNodeTexNoise")                                                                                 
              noise.location = (-400, 100)
              noise.inputs["Scale"].default_value = 30
              noise.inputs["Detail"].default_value = 8
              noise.inputs["Roughness"].default_value = 0.7                                                                           
              links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
              bump = nodes.new("ShaderNodeBump")                                                                                      
              bump.location = (100, -100)
              bump.inputs["Strength"].default_value = 0.5                                                                             
              bump.inputs["Distance"].default_value = 0.03
              links.new(noise.outputs["Fac"], bump.inputs["Height"])                                                                  
              links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
              bsdf.inputs["Sheen Weight"].default_value = 0.2                                                                         
              bsdf.inputs["Sheen Roughness"].default_value = 0.5                                                                      
                                                                                                                                      
          elif mat_type == "marble":                                                                                                  
              noise = nodes.new("ShaderNodeTexNoise")
              noise.location = (-500, 0)
              noise.inputs["Scale"].default_value = 4
              noise.inputs["Detail"].default_value = 10                                                                               
              noise.inputs["Roughness"].default_value = 0.65
              links.new(mapping.outputs["Vector"], noise.inputs["Vector"])                                                            
              wave = nodes.new("ShaderNodeTexWave")                                                                                   
              wave.location = (-500, -200)
              wave.inputs["Scale"].default_value = 3                                                                                  
              wave.inputs["Distortion"].default_value = 4                                                                             
              wave.inputs["Detail"].default_value = 8
              links.new(mapping.outputs["Vector"], wave.inputs["Vector"])                                                             
              mix_rgb = nodes.new("ShaderNodeMixRGB")                                                                                 
              mix_rgb.location = (-200, 0)
              mix_rgb.inputs["Color1"].default_value = base_color                                                                     
              mix_rgb.inputs["Color2"].default_value = (0.65, 0.6, 0.55, 1)
              links.new(noise.outputs["Fac"], mix_rgb.inputs["Fac"])                                                                  
              links.new(mix_rgb.outputs["Color"], bsdf.inputs["Base Color"])                                                          
              bump = nodes.new("ShaderNodeBump")                                                                                      
              bump.location = (100, -100)                                                                                             
              bump.inputs["Strength"].default_value = 0.08
              links.new(wave.outputs["Fac"], bump.inputs["Height"])                                                                   
              links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
                                                                                                                                      
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
                                                                                                                                      
      bpy.ops.mesh.primitive_plane_add(size=size*6, location=(center.x, center.y, min_z - 0.001))                                     
      floor = bpy.context.object
      floor.name = "Floor"                                                                                                            
      floor.cycles.is_shadow_catcher = True
      floor_mat = bpy.data.materials.new("FloorMat")                                                                                  
      floor_mat.use_nodes = True
      floor_bsdf = floor_mat.node_tree.nodes.get("Principled BSDF")                                                                   
      if floor_bsdf:                                                                                                                  
          floor_bsdf.inputs["Base Color"].default_value = (0.04, 0.04, 0.04, 1)
          floor_bsdf.inputs["Roughness"].default_value = 0.6                                                                          
      floor.data.materials.append(floor_mat)
                                                                                                                                      
      dist = size * 2.5
      cam_loc = Vector((center.x, center.y - dist, center.z + dist * 0.35))                                                           
      bpy.ops.object.camera_add(location=cam_loc)                                                                                     
      cam = bpy.context.object                                                                                                        
      direction = center - cam_loc                                                                                                    
      rot_quat = direction.to_track_quat("-Z", "Y")                                                                                   
      cam.rotation_euler = rot_quat.to_euler()                                                                                        
      cam.data.lens = 85
      bpy.context.scene.camera = cam                                                                                                  
                  
  NUM_FRAMES = 8                                                                                                                      
  chair_objects = [o for o in bpy.context.scene.objects if o.type == "MESH" and o.name != "Floor"]
  for obj in chair_objects:                                                                                                           
      obj.rotation_euler[2] = 0
      obj.keyframe_insert(data_path="rotation_euler", frame=1)                                                                        
      obj.rotation_euler[2] = math.radians(360)                                                                                       
      obj.keyframe_insert(data_path="rotation_euler", frame=NUM_FRAMES + 1)
      if obj.animation_data and obj.animation_data.action:                                                                            
          for fc in obj.animation_data.action.fcurves:
              for kp in fc.keyframe_points:                                                                                           
                  kp.interpolation = 'LINEAR'
                                                                                                                                      
  world = bpy.context.scene.world
  if not world:                                                                                                                       
      world = bpy.data.worlds.new("World")
      bpy.context.scene.world = world                                                                                                 
  world.use_nodes = True
  nt = world.node_tree                                                                                                                
  bg = nt.nodes.get("Background")
  if not bg:                                                                                                                          
      bg = nt.nodes.new("ShaderNodeBackground")
      out_w = nt.nodes.get("World Output") or nt.nodes.new("ShaderNodeOutputWorld")                                                   
      nt.links.new(bg.outputs["Background"], out_w.inputs["Surface"])                                                                 
  bg.inputs["Color"].default_value = (0.02, 0.02, 0.025, 1)                                                                           
  bg.inputs["Strength"].default_value = 0.2                                                                                           
                                                                                                                                      
  bpy.ops.object.light_add(type="AREA", location=(3, -2, 5))                                                                          
  key = bpy.context.object                                                                                                            
  key.data.energy = 3000                                                                                                              
  key.data.size = 3
  key.rotation_euler = (math.radians(60), 0, math.radians(30))                                                                        
   
  bpy.ops.object.light_add(type="AREA", location=(-4, 1, 3))                                                                          
  fill = bpy.context.object
  fill.data.energy = 800                                                                                                              
  fill.data.size = 8                                                                                                                  
  fill.rotation_euler = (math.radians(50), 0, math.radians(-30))
                                                                                                                                      
  bpy.ops.object.light_add(type="AREA", location=(0, 4, 4))                                                                           
  rim = bpy.context.object
  rim.data.energy = 1200                                                                                                              
  rim.data.size = 3
  rim.rotation_euler = (math.radians(-50), 0, 0)                                                                                      
   
  bpy.ops.object.light_add(type="AREA", location=(0, 0, 6))                                                                           
  top = bpy.context.object
  top.data.energy = 400                                                                                                               
  top.data.size = 10
  top.rotation_euler = (0, 0, 0)
                                                                                                                                      
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
                                                                                                                                      
  scene.cycles.samples = 32
  scene.cycles.use_denoising = True                                                                                                   
  try:                                                                                                                                
      scene.cycles.denoiser = 'OPENIMAGEDENOISE'
  except:                                                                                                                             
      pass        
  scene.render.resolution_x = 512                                                                                                     
  scene.render.resolution_y = 512
  scene.render.image_settings.file_format = "PNG"
  scene.frame_start = 1                                                                                                               
  scene.frame_end = NUM_FRAMES
  scene.render.filepath = os.path.join(data["output_path"], "frame_")                                                                 
  bpy.ops.render.render(animation=True)                                                                                               
  """                                                                                                                                 
                                                                                                                                      
      with open("/tmp/render.py", "w") as f:                                                                                          
          f.write(blender_script)

      result = subprocess.run(                                                                                                        
          ["blender", "--background", "--python", "/tmp/render.py"],
          capture_output=True, text=True                                                                                              
      )           

      import glob
      from PIL import Image
                                                                                                                                      
      frame_files = sorted(glob.glob("/tmp/output/frame_*.png"))
      if frame_files:                                                                                                                 
          images = [Image.open(f).convert("RGBA") for f in frame_files]
          gif_path = "/tmp/output/render.gif"                                                                                         
          images[0].save(
              gif_path,                                                                                                               
              save_all=True,
              append_images=images[1:],                                                                                               
              loop=0,
              duration=150,
              disposal=2
          )
          with open(gif_path, "rb") as f:
              img_b64 = base64.b64encode(f.read()).decode("utf-8")                                                                    
          return {"image_base64": img_b64, "status": "ok", "format": "gif"}
      else:                                                                                                                           
          return {"status": "error", "log": result.stderr[-3000:]}
                                                                                                                                      
  runpod.serverless.start({"handler": handler})           