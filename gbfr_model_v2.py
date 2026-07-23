import bpy
import bmesh
import os
import time
import struct
from math import radians
from collections import defaultdict

from .Entities.MInfo_ModelInfo.ModelInfo import ModelInfo
from .Entities.MInfo_ModelInfo.VertexBufferType import VertexBufferType
from .Entities.ModelSkeleton import ModelSkeleton
from .utils import *

_DEFAULT_SKELETON = object()

def parse_skeleton_file(skeleton_filepath):
	skeleton = None
	if os.path.isfile(skeleton_filepath):
		buf = open(skeleton_filepath, 'rb').read()
		buf = bytearray(buf)
		skeleton = ModelSkeleton.GetRootAs(buf, 0) # Get skeleton info root in byte array
	return skeleton
		
def build_skeleton(skeleton:ModelSkeleton, collection, bone_scale_multiplier = 1.0):
	# Create an armature
	# ================================================
	armature_data = bpy.data.armatures.new("Armature")
	armature_obj = bpy.data.objects.new("Armature", armature_data)
	collection.objects.link(armature_obj)
	bpy.context.view_layer.objects.active = armature_obj
	utils_set_mode('EDIT')
	
	# Build bones from Skeleton file
	# ================================================
	SkelTable = []
	print("skeleton.BodyLength()", skeleton.BodyLength())
	for n in range(skeleton.BodyLength()): # For bone index in skeleton
		bone = skeleton.Body(n) # Get the bone's information
		# Set bone info
		pos = (bone.Position().X(), bone.Position().Y(), bone.Position().Z())
		quat = (bone.Quat().W(), bone.Quat().X(), bone.Quat().Y(), bone.Quat().Z())
		scale = (bone.Scale().X(), bone.Scale().Y(), bone.Scale().Z())
		
		parent_index = bone.ParentId()
		# Append position and rotation dictionary to SkelTable list
		SkelTable.append({"Pos":pos,"Rot":quat, "Scale":scale})
		
		name = bone.Name().decode('ascii') # Decode the bone's name

		# Set up blender bone
		edit_bone = armature_obj.data.edit_bones.new(name) # Add bone to armature
		edit_bone.use_connect = False # Don't connect to parent
		edit_bone.use_inherit_rotation = True
		edit_bone.inherit_scale = 'FULL'
		edit_bone.use_local_location = True
		edit_bone.head = (0, 0, 0)
		edit_bone.tail = (0, 0.05 * bone_scale_multiplier, 0)
		edit_bone['original_name'] = name
		edit_bone['gbfr_original_name'] = name
		
		if parent_index != 65535: # Parent the bone to its parent if it has a parent
			edit_bone.parent = armature_obj.data.edit_bones[parent_index]

		# Set up blender bone collection (Import Only) # Credit to bujyu-uo
		# ================================================
		bone_coll_str = None
		if bone.A1() is not None:
			bone_coll_str = bone.A1().Unk() # A1().Unk() is the bone's bone group
		if bone_coll_str is not None:
			try:
				bone_coll_name = bone_coll_str.to_bytes(4, "little").decode("ASCII").lstrip('\x00')
			except:
				bone_coll_name = "_z"

			if bpy.app.version >= (4, 0, 0):
				if bone_coll_name not in armature_obj.data.collections:
					bone_coll = armature_obj.data.collections.new(bone_coll_name)
				else:
					bone_coll = armature_obj.data.collections[bone_coll_name]

				bone_coll.assign(edit_bone)
			else: # Blender 3 uses bone groups
				SkelTable[n]["BoneGroup"] = bone_coll_name
				print(f"SkelTable[n]['BoneGroup']: {SkelTable[n]['BoneGroup']}")

	# Pose bones based on the position and rotation stored in .skeleton
	# ================================================
	utils_set_mode('POSE')
	for x in range(skeleton.BodyLength()):
		pbone = armature_obj.pose.bones[x]
		ebone = armature_obj.data.bones[x]
		try:
			ebone['gbfr_bone_id'] = int(ebone.name[1:], 16) if ebone.name.startswith('_') else -1
		except ValueError:
			ebone['gbfr_bone_id'] = -1
		ebone['gbfr_original_name'] = ebone.name
		ebone['gbfr_rest_quaternion'] = list(SkelTable[x]['Rot'])
		ebone['gbfr_rest_position'] = list(SkelTable[x]['Pos'])
		ebone['gbfr_rest_scale'] = list(SkelTable[x]['Scale'])
		pbone.rotation_mode = 'QUATERNION'
		pbone.rotation_quaternion = SkelTable[x]["Rot"]
		pbone.location = SkelTable[x]["Pos"]
		pbone.scale = SkelTable[x]["Scale"]

		if bpy.app.version < (4, 0, 0): # Blender 3 assign bones to bone groups instead
			if "BoneGroup" not in SkelTable[x]: continue
			bone_group_name = SkelTable[x]["BoneGroup"]
			if bone_group_name not in armature_obj.pose.bone_groups:
				bone_group = armature_obj.pose.bone_groups.new(name=bone_group_name)
				armature_obj.data.layers[-1] = True
			else:
				bone_group = armature_obj.pose.bone_groups[bone_group_name]
			pbone.bone_group = bone_group
			bone_in_layers = [False]*32
			bone_in_layers[pbone.bone_group_index] = True
			ebone.layers = bone_in_layers

	bpy.ops.pose.armature_apply()
	utils_set_mode('OBJECT')
	return armature_obj # Return the armature


def parse_mesh_info_file(minfo_filepath):
	# Read .minfo file in as byte array
	buf = open(minfo_filepath, 'rb').read()
	buf = bytearray(buf)    
	model_info = ModelInfo.GetRootAs(buf, 0) # Get model info root in byte array
	
	return model_info

def vertex_flags_to_bools(bitmask): # Map flags to bools
	return [
		name for name,value in VertexBufferType.__dict__.items() 
		if not name.startswith("__") and isinstance(value, int) # Skip built-ins
		and bool(bitmask & value) # Flag is True
		]

def byte_to_bool_array(byte_value):
	return [bool(byte_value & (1 << i)) for i in range(8)]

def get_mesh_vertex_data(mmesh_file, vert_count):
	VertTable = [] ; NormalTable = [] ;  UVTable = []
	# TangentTable = [] ; # Unused

	for n in range(vert_count):
		VertTable.append(struct.unpack('<fff', mmesh_file.read(4*3))) # Vertex
		NormalTable.append(struct.unpack('<eee', mmesh_file.read(2*3))) # Normal
		mmesh_file.read(8) # Tangent | Skipped since unused
		# tangent = struct.unpack('<eee', mmesh_file.read(2*3))
		# tangent = (tangent[0], tangent[2], tangent[1])
		# TangentTable.append(tangent)
		mmesh_file.read(2) # Skip 2
		UVTable.append(struct.unpack('<ee', mmesh_file.read(2*2))) # UV

	return VertTable, NormalTable, UVTable

def get_mesh_face_data(mmesh_file, LOD_face_buffer_offset, face_count):
	faceTable = []
	mmesh_file.seek(LOD_face_buffer_offset)
	for n in range(face_count):
		faceTable.append(struct.unpack('<III', mmesh_file.read(4*3)))
	return faceTable


def get_vertex_weight_indices(mmesh_file, LOD, deform_bones_table, vertex_weights_sets:int, lod_buffers_index:int):
	weight_indices_table = [[] for _ in range(LOD.Buffers(lod_buffers_index).Size()//8)] # Pre-allocate
	# Get vertex to bone indices for each vertex weight
	for set in range(vertex_weights_sets): # For each set of vertex weights
		mmesh_file.seek(LOD.Buffers(lod_buffers_index).Offset())
		# print("LOD.Buffers(lod_buffers_index).Offset()", LOD.Buffers(lod_buffers_index).Offset())
		# print("LOD.Buffers(lod_buffers_index).Size()", LOD.Buffers(lod_buffers_index).Size())
		for n in range(LOD.Buffers(lod_buffers_index).Size()//8): # Same as -> for n in range(vert_count):
			i0, i1, i2, i3 = struct.unpack('<HHHH', mmesh_file.read(2*4)) # -> int.from_bytes(f.read(2),byteorder='little')
			try:
				weight_indices = [deform_bones_table[i0],deform_bones_table[i1],deform_bones_table[i2],deform_bones_table[i3]]
				# if len(weight_indices_table) <= n: weight_indices_table.append(weight_indices) # 1st set
				# else: 
				weight_indices_table[n].extend(weight_indices) # 2nd set
				# print(f"weight_indices_table[{n}]:", weight_indices_table[n])
			except Exception as err:
				print(i0, i1, i2, i3) ; print (weight_indices)
				# pass
				raise err
		lod_buffers_index += 1 # Increment for 2nd set
	return weight_indices_table


def get_vertex_weight_values(mmesh_file, LOD, vertex_weights_sets:int, lod_buffers_index:int):
	weight_table = [[] for _ in range(LOD.Buffers(lod_buffers_index).Size()//8)] # Pre-allocate
	for set in range(vertex_weights_sets): # For each weight set
		mmesh_file.seek(LOD.Buffers(lod_buffers_index).Offset())
		for n in range(LOD.Buffers(lod_buffers_index).Size()//8): # Same as -> for n in range(vert_count):
			weight_values = list(struct.unpack('<HHHH', mmesh_file.read(2*4)))
			try:
				# if len(weight_table) <= n: weight_table.append(weight_values) # 1st set
				# else: 
				weight_table[n].extend(weight_values) # 2nd set
			except Exception as err:
				print(weight_values)
				raise err
		lod_buffers_index += 1 # Increment for 2nd set
	return weight_table


def get_vertex_colors(mmesh_file, LOD, lod_buffers_index:int):
	ColorTable = []
	mmesh_file.seek(LOD.Buffers(lod_buffers_index).Offset())
	for v in range(LOD.Buffers(lod_buffers_index).Size()//(4)):
		color = struct.unpack('<BBBB', mmesh_file.read(1*4))
		ColorTable.append((color[0] / 255, color[1]/255, color[2]/255, color[3]/255))
	
	return ColorTable


def get_texcoords(mmesh_file, LOD, lod_buffers_index:int):
	TexCoordsTable = [] # Coords are stored per vertex
	mmesh_file.seek(LOD.Buffers(lod_buffers_index).Offset())
	for v in range(LOD.Buffers(lod_buffers_index).Size()//4):
		try: # TODO: Investigate why this dies with some bg objects (e.g. bg528c)
			tex_coord = struct.unpack('<ee', mmesh_file.read(2*2))
			TexCoordsTable.append(tex_coord)
		except Exception as err:
			print(err)
			pass
	
	return TexCoordsTable


# =======================================================================================================================
# MAIN IMPORT FUNCTION
# =======================================================================================================================
def read_some_data(
	context,
	minfo_filepath,
	mmesh_filepaths,
	import_scale=1.0,
	bone_scale=1.0,
	model_collection=None,
	skeleton_filepath=_DEFAULT_SKELETON,
	return_objects=False,
):
	total_import_timer_start = time.perf_counter() # @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
	model_name = os.path.splitext(os.path.basename(minfo_filepath))[0] # Get model name from filename

	if model_collection is None:
		model_collection = bpy.data.collections.new(f"GBFR Model Collection_{model_name}")
		bpy.context.scene.collection.children.link(model_collection)
	utils_set_mode('OBJECT')
	for obj in bpy.context.selected_objects: 
		obj.select_set(False) #Deselect everything
	
	model_info = parse_mesh_info_file(minfo_filepath) # Parse the mesh info
	if skeleton_filepath is _DEFAULT_SKELETON:
		skeleton_filepath = os.path.splitext(minfo_filepath)[0] + ".skeleton"
	skeleton = parse_skeleton_file(skeleton_filepath) if skeleton_filepath else None
	armature = build_skeleton(skeleton, model_collection, bone_scale) if skeleton else None # Parse the skeleton
	
	if armature is not None: 
		root_object = armature
	else:
		root_object = bpy.data.objects.new("", None)
		root_object.empty_display_size = 0.25
		model_collection.objects.link(root_object)
	root_object.name = f"{model_name}"
	lod_objects = []
	mesh_objects = []
	
	materials_list = []
	materials_by_id = {}
	MaterialsTable = [model_info.Materials(i) for i in range(model_info.MaterialsLength())]
	used_material_ids = set()
	for lod_getter, lod_count in (
		(model_info.Lods, model_info.LodsLength()),
		(model_info.ShadowLods, model_info.ShadowLodsLength()),
	):
		for lod_idx in range(lod_count):
			lod = lod_getter(lod_idx)
			for chunk_idx in range(lod.ChunksLength()):
				used_material_ids.add(lod.Chunks(chunk_idx).MaterialId())
	used_material_ids = sorted(used_material_ids)
	if len(used_material_ids) == len(MaterialsTable):
		MaterialIdsTable = used_material_ids
	else:
		# Most files store only used materials, ordered by their possibly sparse IDs.
		# Fall back to the legacy direct-index convention when the counts disagree.
		MaterialIdsTable = list(range(len(MaterialsTable)))
		print(
			"Material metadata/count mismatch; using direct material indices:",
			len(MaterialsTable), used_material_ids,
		)

	# Build each LOD Mesh
	# ========================================================================================
	for mmesh_filepath in mmesh_filepaths:
		try: 
			mmesh_file = open(mmesh_filepath, 'rb')
			print("mmesh_filepath", mmesh_filepath)
		except Exception as err:
			raise #FileNotFoundError(f"ERROR: Could not find .mmesh file at given path\n{err}")
		
		# Figure out which LOD .mmesh file is
		mmesh_file.seek(0, 2)  # Move to end of file
		mmesh_file_length = mmesh_file.tell()
		print("mmesh_file_length", mmesh_file_length)
		lod_index = -1 ; shadow_lod_index = -1;
		for i in range(model_info.LodsLength()):
			# Use the faces buffer which is always last as the way to compare file size
			face_buffer = model_info.Lods(i).Buffers(model_info.Lods(i).BuffersLength()-1)
			face_buffer_end = face_buffer.Offset() + face_buffer.Size()
			if mmesh_file_length == face_buffer_end:
				print("mmesh_file_length == face_buffer_end", mmesh_file_length, "==", face_buffer_end)
				lod_index = i ; break
		for k in range(model_info.ShadowLodsLength()):
			face_buffer = model_info.ShadowLods(k).Buffers(model_info.ShadowLods(k).BuffersLength()-1)
			face_buffer_end = face_buffer.Offset() + face_buffer.Size()
			if mmesh_file_length == face_buffer_end:
				print("mmesh_file_length == face_buffer_end", mmesh_file_length, "==", face_buffer_end)
				shadow_lod_index = k ; break
		if lod_index == -1 and shadow_lod_index == -1: 
			raise Exception(f".minfo and .mmesh file mismatch.\n{minfo_filepath}\n{mmesh_filepath}")
		is_shadow_lod = shadow_lod_index != -1

		# Get mesh LOD info of LOD at current LOD index
		LOD = model_info.Lods(lod_index) if not is_shadow_lod else model_info.ShadowLods(shadow_lod_index)
		
		mmesh_file.seek(0) # Reset file seek header
		
		#=======================
		# Create LOD root object
		#=======================
		
		lod_name = f"{'shadow' if is_shadow_lod else ''}lod{lod_index if not is_shadow_lod else shadow_lod_index}"
		lod_object = bpy.data.objects.new(lod_name, None)
		lod_objects.append(lod_object)
		lod_object.empty_display_size = 0.25
		model_collection.objects.link(lod_object)
		lod_object.parent = root_object # Parent to root
		
		lod_object["a6"] = byte_to_bool_array(LOD.A6()) # Store extra unknown LOD variable

		#================
		# Get .minfo data
		#================

		# Map buffer_types bitmask to bools
		buffer_type_flags = vertex_flags_to_bools(LOD.BufferTypes())
		print(f"LOD.BufferTypes() {LOD.BufferTypes()}")
		print("buffer_type_flags", buffer_type_flags)
		
		# Counts
		vert_count = LOD.VertexCount()
		face_count = LOD.IndexCount() // 3 # PolyCount X 3
		print(f"vert_count = {vert_count} \n face_count = {face_count} \n LOD.PolyCountX3() = {LOD.IndexCount()}")

		# Get Universal Buffers data (Verts+Normals+UV and Faces)
		VertTable, NormalTable, UV0Table = get_mesh_vertex_data(mmesh_file, vert_count)
		print("VertTable, NormalTable, UV0Table", len(VertTable), len(NormalTable), len(UV0Table))
		LOD_face_buffer_offset = LOD.Buffers(LOD.BuffersLength() - 1).Offset()
		FaceTable = get_mesh_face_data(mmesh_file, LOD_face_buffer_offset, face_count)
		print("len(FaceTable)", len(FaceTable))

		# Get dictionary list of Chunks grouped by mesh ID.
		LodChunksDict = defaultdict(list)
		for chunk_idx in range(LOD.ChunksLength()):
			chunk = LOD.Chunks(chunk_idx)
			LodChunksDict[chunk.MeshId()].append(chunk)
		print("LOD.ChunksLength()", LOD.ChunksLength())

		# ===========================
		# Get Additional Buffers Data
		# ===========================
		#  Bones & Weight
		DeformBonesIndexTable = []
		WeightIndicesTable = []
		WeightValuesTable = []
		if armature is not None: 
			# Get bone weights indices (which bones have weight)
			for n in range(model_info.DeformBoneToBoneIndexTableLength()):
				DeformBonesIndexTable.append(model_info.DeformBoneToBoneIndexTable(n))
			print("len(DeformBonesIndexTable)", len(DeformBonesIndexTable))

			weight_sets_count = 0
			if 'BLENDINDICES' in buffer_type_flags and 'BLENDWEIGHT' in buffer_type_flags:
				weight_sets_count += 1
				if 'BLENDINDICES_2' in buffer_type_flags and 'BLENDWEIGHT_2' in buffer_type_flags:
					weight_sets_count += 1
				
				# Get weight to vertex group indices for each vertex
				lod_buffers_index = buffer_type_flags.index('BLENDINDICES')
				WeightIndicesTable = get_vertex_weight_indices(mmesh_file, LOD, DeformBonesIndexTable, 
												   				weight_sets_count, lod_buffers_index)
				
				# Get weight values for each vertex
				lod_buffers_index = buffer_type_flags.index('BLENDWEIGHT')
				WeightValuesTable = get_vertex_weight_values(mmesh_file, LOD, weight_sets_count, lod_buffers_index)
			print("len(WeightIndicesTable)", len(WeightIndicesTable))
			print("len(WeightValuesTable)", len(WeightValuesTable))

		# Vertex Colours
		ColorTable = []
		if 'COLOR' in buffer_type_flags:
			lod_buffers_index = buffer_type_flags.index('COLOR')
			ColorTable = get_vertex_colors(mmesh_file, LOD, lod_buffers_index)
			print("len(ColorTable)", len(ColorTable))

		# Additional UV Set
		UV1Table = []
		if 'TEXCOORD' in buffer_type_flags:
			lod_buffers_index = buffer_type_flags.index('TEXCOORD')
			UV1Table = get_texcoords(mmesh_file, LOD, lod_buffers_index)
			print("len(UV1Table)", len(UV1Table))

		# ==========================================
		# Iterate through and build each .minfo mesh
		# ==========================================
		for mesh_index in range(model_info.MeshesLength()):
			mesh = model_info.Meshes(mesh_index)
			mesh_name = mesh.Name().decode() ; print(mesh_name)
			mesh_data = bpy.data.meshes.new(mesh_name)
			mesh_obj = bpy.data.objects.new(mesh_name, mesh_data)
			model_collection.objects.link(mesh_obj)
			mesh_objects.append(mesh_obj)
			mesh_obj['gbfr_lod'] = lod_name
			utils_select_active(mesh_obj)
			mesh_obj.parent = lod_object

			vert_index_cache = {}
			VertsCreationOrderList = []

			# Build mesh
			bmesh_data = bmesh.new() # Create bmesh
			normals = []
			UV0_Layer = bmesh_data.loops.layers.uv.new("UV0") # Create UV Layer
			mesh_data.uv_layers.new(name="UV0")
			if UV1Table: 
				UV1_Layer = bmesh_data.loops.layers.uv.new("UV1") # Create UV Layer
				mesh_data.uv_layers.new(name="UV1")

			# Build Mesh Materials first
			for mat_index, mat_data in enumerate(MaterialsTable):
				material_id = MaterialIdsTable[mat_index]
				mat_name = str(mat_data.UniqueNameHash())
				if mat_index < len(materials_list):
					mat = materials_list[mat_index]
				else:
					mat = bpy.data.materials.new(name=f"{model_name}_{mat_name}")
					materials_list.append(mat)
				mat["MaterialID"] = material_id # Preserve the sparse ID used by LOD chunks and .mmat.
				mat["unique_name_hash"] = mat_name
				mat["material_flags"] = byte_to_bool_array(mat_data.MaterialFlags())
				materials_by_id[material_id] = mat

			for chunk_idx, chunk in enumerate(LodChunksDict[mesh_index]):
				# Attach used material to mesh
				material_id = chunk.MaterialId()
				mat = materials_by_id.get(material_id)
				if mat is None:
					# Keep geometry importable even if a malformed file omits material metadata.
					mat = bpy.data.materials.new(name=f"{model_name}_material_{material_id}")
					mat["MaterialID"] = material_id
					materials_by_id[material_id] = mat
					print(f"Missing .minfo material metadata for material ID {material_id}; using a placeholder")
				if not mesh_data.materials.get(mat.name):
					mesh_data.materials.append(mat)
				mat_index = mesh_data.materials.find(mat.name)

				# Build Faces
				# Get verts from vert Table by iterating over Faces Table and its vert index lookup (!!!VERY IMPORTANT!!!)
				for face_idx in range(chunk.Count() // 3):
					try:
						face = FaceTable[(chunk.Offset() // 3) + face_idx]
						# Build Verts
						verts = []
						for v in range(3):
							vert = vert_index_cache.get(face[v])
							if vert is None:
								vert = bmesh_data.verts.new(VertTable[face[v]])
								vert_index_cache[face[v]] = vert # Chache the vert
								VertsCreationOrderList.append(face[v]) # Record when vert created
							verts.append(vert)
						v1 = verts[0] ; v2 = verts[1] ; v3 = verts[2]
						# Build Face
						bmesh_face = bmesh_data.faces.get((v3,v2,v1))
						face_existed = False
						if bmesh_face is None:
							bmesh_face = bmesh_data.faces.new((v3,v2,v1)) # Faces are built counter-clockwise
						else: face_existed = True
						# Build Normals and UVs
						if not face_existed:
							bmesh_face.smooth = True
							vert_idx = 2
							for loop in bmesh_face.loops:
								loop[UV0_Layer].uv = UV0Table[face[vert_idx]]
								if UV1Table:
									uv1_index = face[vert_idx]
									loop[UV1_Layer].uv = UV1Table[uv1_index] if uv1_index < len(UV1Table) else (0.0, 0.0)
								normals.append(NormalTable[face[vert_idx]])
								vert_idx -= 1
							# Assign Materials
							bmesh_face.material_index = mat_index
						# Build Vertex Groups and assign weights
						
					except Exception as err:
						# print(f"{n}: {err}")
						print(len(FaceTable), (chunk.Offset() // 3), face_idx, (chunk.Offset() // 3)+face_idx)
						raise err
			bmesh_data.to_mesh(mesh_data) # Update mesh
			bmesh_data.faces.ensure_lookup_table()

			# Assign Normals | Can't directly assign tangents in blender, so use this instead
			mesh_data.normals_split_custom_set(normals)
			try:
				mesh_data.calc_tangents()
			except Exception as err:
				pass
			if bpy.app.version < (4, 1, 0): mesh_data.use_auto_smooth = True # Turn on smooth shading

			if armature:
				bone_index_to_vgroup = {} # Cache for speedup
				vertex_groups = mesh_obj.vertex_groups
				bone_data = armature.data.bones
			
			if ColorTable: # Create Vertex Color Layer
				mesh_data.color_attributes.new(name=f"COLOR", type='BYTE_COLOR', domain='POINT')

			# Assign additional vertex data buffers
			for v, vert in enumerate(VertsCreationOrderList):
				if ColorTable: # Assign Vertex colors
					mesh_data.color_attributes[f"COLOR"].data[v].color = ColorTable[vert] if vert < len(ColorTable) else (1.0, 1.0, 1.0, 1.0)
				if armature and vert < len(WeightIndicesTable) and vert < len(WeightValuesTable): # Create Vertex groups and assign weights
					for n in range(len(WeightIndicesTable[vert])): # 4 or 8
						try:
							bone_index = WeightIndicesTable[vert][n]
							weight = float(WeightValuesTable[vert][n]) / 65535
							# if weight == 0: continue

							if bone_index not in bone_index_to_vgroup:
								# Uses the WeightsIndicesTable to find the names of vertex groups.
								group_name = bone_data[WeightIndicesTable[vert][n]].name

								# See if a vertex group of that name exists on the mesh or not, add one if not
								if vertex_groups.find(group_name) == -1:
									vertex_group = vertex_groups.new(name = group_name)
								else:
									vertex_group = vertex_groups[vertex_groups.find(group_name)]
								bone_index_to_vgroup[bone_index] = vertex_group
							else:
								vertex_group = bone_index_to_vgroup[bone_index]
							
							# Take the vertex group and add the vertices with their respective weights to it.
							vertex_group.add([v], weight, 'ADD')
						except Exception as err:
							# print(err)
							print(WeightIndicesTable[v][n])
							raise err

			if armature:
				armature_modifier = mesh_obj.modifiers.new("Armature","ARMATURE")
				armature_modifier.object = armature

				# Now Sort Vertex Groups by Bone Hierarchy
				if len(mesh_obj.vertex_groups) > 0: # Some models like weapons might have bones but no vertex weights
					bpy.ops.object.vertex_group_sort(sort_type='BONE_HIERARCHY')
					mesh_obj.vertex_groups.active_index = 0 # Set selected vertex group back to 0
			
			bmesh_data.free() # Free bmesh
		
		mmesh_file.close()
		del mmesh_file

		print(f"LOD{lod_index} Done.\n===========\n\n")

	# ========================================================================================
	# Root/Armature Misc & Cleanup
	# ========================================================================================
	
	# Store extra parameters in root_object object
	# =====================
	root_object["magic"] = model_info.Magic() # Add minfo magic number
	root_object["lod_screen_size_thresholds"] = model_info.LodScreenSizeThresholdsAsNumpy() # LOD Distance parameters list
	root_object["bounding_sphere"] = (
		model_info.BoundingSphere().X(), 
		model_info.BoundingSphere().Y(), 
		model_info.BoundingSphere().Z(), 
		model_info.BoundingSphere().R()
		)
	if model_info.BgReactionData():
		root_object["bg_reaction_data"] = {
			"hit_height": model_info.BgReactionData().HitHeight(),
			"hit_radius": model_info.BgReactionData().HitRadius(),
			"particle_type": model_info.BgReactionData().ParticleType(),
			"play_sound": model_info.BgReactionData().PlaySound()
			}
	root_object["vec3_11"] = (model_info.Vec311().X(), model_info.Vec311().Y(), model_info.Vec311().Z())
	root_object["near_camera_bound_radius"] = model_info.NearCameraBoundRadius()
	root_object["near_camera_detection_scale"] = model_info.NearCameraDetectionScale()
	root_object["fade_out_distance"] = model_info.FadeOutDistance()
	if model_info.F15(): root_object["f15"] = model_info.F15()
	if model_info.F16(): root_object["render_mesh_screen_size_threshold"] = model_info.F16()
	if model_info.F17(): root_object["render_shadow_screen_size_threshold"] = model_info.F17()
	if model_info.F18(): root_object["render_outline_screen_size_threshold"] = model_info.F18()
	if model_info.F19(): root_object["f19"] = model_info.F19()
	if model_info.U20(): 	root_object["u20"] = str(model_info.U20()) # Python only supports int32, not uint32, so store as string
	if model_info.Byte21(): 	root_object["byte21"] = byte_to_bool_array(model_info.Byte21())
	if model_info.SceneGraphMode(): 	root_object["scene_graph_mode"] = byte_to_bool_array(model_info.SceneGraphMode())
	if model_info.UseSceneGraphCache(): 	root_object["use_scene_graph_cache"] = model_info.UseSceneGraphCache()
	if model_info.IsShip(): 	root_object["is_ship"] = model_info.IsShip()
	if model_info.UseBoneBoundsForFade(): 	root_object["use_bone_bounds_for_fade"] = model_info.UseBoneBoundsForFade()
	if model_info.ForceNearFadeEvaluation(): 	root_object["force_near_fade_evaluation"] = model_info.ForceNearFadeEvaluation()
	if model_info.UseMeshAabbForFade(): 	root_object["use_mesh_aabb_for_fade"] = model_info.UseMeshAabbForFade()
	if model_info.RenderFlags(): 	root_object["render_flags"] = byte_to_bool_array(model_info.RenderFlags())
	for i in [24, 28, 29]:
		if getattr(model_info, f"Bool{i}")():
			root_object[f"bool{i}"] = getattr(model_info, f"Bool{i}")() # root_object["bool23"] = mesh_info.Bool23()
	if model_info.Bool26():		root_object["fade_between_lods"] = model_info.Bool26() # Is actually byte
	if model_info.Bool31():		root_object["bool31"] = byte_to_bool_array(model_info.Bool31()) # Is actually byte
	if model_info.CameraNearFadeAabbRadius(): root_object["camera_near_fade_aabb_radius"] = model_info.CameraNearFadeAabbRadius()
	
	# Clean Up
	# =====================

	root_object.rotation_euler = (radians(90),0,0) # Rotate 90 degrees from Y up to Z up
	root_object.select_set(True) # Select the root_object
	root_object.display_type = 'WIRE'
	root_object.show_in_front = True # X-Ray view for root_object
	utils_select_active(root_object)
	
	bpy.context.object.scale = (import_scale, import_scale, import_scale) # Scale the entire model
	bpy.ops.object.transform_apply(location=True, rotation=True, scale=True) # Apply Transforms to model

	for lod_obj in lod_objects: 
		lod_obj.select_set(True)
		bpy.ops.object.transform_apply(location=True, rotation=True, scale=True) # Apply Transforms to lod objects
		lod_obj.select_set(False)

	print(f"Model took: {time.perf_counter() - total_import_timer_start:.6f} seconds to import!")
	if return_objects:
		return {
			'root': root_object,
			'armature': armature,
			'lod_objects': tuple(lod_objects),
			'meshes': tuple(mesh_objects),
		}
	return {'FINISHED'}


# =================================================================================================================================

# =================================================================================================================================


# ImportHelper is a helper class, defines filename and
# invoke() function which calls the file selector.
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty, BoolProperty, FloatProperty, EnumProperty
from bpy.types import Operator

class NavigateToModelFolder(Operator):
	bl_idname = "gbfr.navigate_to_model_folder"
	bl_label = "Go to 'model' Folder"

	@classmethod
	def description(cls, context, properties):
		addon_preferences = context.preferences.addons[__package__].preferences

		if not addon_preferences.extracted_game_data_folder_path:
			return "Set the extracted game data folder path in the addon preferences to enable this button."

		return "Navigate to the extracted game data's model folder."
	
	@classmethod
	def poll(cls, context):
		addon_preferences = context.preferences.addons[__package__].preferences
		return bool(addon_preferences.extracted_game_data_folder_path) # If folder path assigned

	def execute(self, context):
		addon_preferences = context.preferences.addons[__package__].preferences

		context.space_data.params.directory = bpy.path.abspath(
			os.path.join(addon_preferences.extracted_game_data_folder_path,f"model")
			).encode()
			
		return {'FINISHED'}
	
class NavigateToModelStreamingFolder(Operator):
	bl_idname = "gbfr.navigate_to_model_streaming_folder"
	bl_label = "Go to 'model_streaming' Folder"

	@classmethod
	def description(cls, context, properties):
		addon_preferences = context.preferences.addons[__package__].preferences

		if not addon_preferences.extracted_game_data_folder_path:
			return "Set the extracted game data folder path in the addon preferences to enable this button."

		return "Navigate to the extracted game data's model_streaming folder."
	
	@classmethod
	def poll(cls, context):
		addon_preferences = context.preferences.addons[__package__].preferences
		return bool(addon_preferences.extracted_game_data_folder_path) # If folder path assigned

	def execute(self, context):
		addon_preferences = context.preferences.addons[__package__].preferences

		context.space_data.params.directory = bpy.path.abspath(
			os.path.join(addon_preferences.extracted_game_data_folder_path,f"model_streaming")
			).encode()
			
		return {'FINISHED'}

# Save where the user selected each file so when the user imports a model it jumps to the same folders
MINFO_DIRECTORY = ""
MMESH_DIRECTORY = ""

class SelectMInfo(Operator, ImportHelper):
	"""Importer for Granblue Fantasy Relink models"""
	bl_idname = "gbfr.import_mesh"
	bl_label = "Select .minfo"

	# ImportHelper mix-in class uses this.
	filename_ext = ".minfo"
	filter_glob: StringProperty(
		default="*.minfo",
		options={'HIDDEN'},
	)
	import_scale: FloatProperty(name="Model Scale", default=1.0)
	bone_scale: FloatProperty(name="Bone Scale", default=1.0)
	auto_select_mmesh: BoolProperty(name="Auto Select .mmesh(s)", default=True)

	def draw(self, context):
		layout = self.layout
		layout.use_property_split = True

		box = layout.box()
		button = box.row()
		button.operator("gbfr.navigate_to_model_folder", icon='FILE_FOLDER')

		box = layout.box() ; row = box.row()
		row.label(text="Auto Select .mmesh(s)", icon="FILE_NEW") ; row.prop(self, "auto_select_mmesh", text = "")

		box = layout.box()
		box.prop(self, "import_scale")
		box.prop(self, "bone_scale")
		

	def execute(self, context): # On import button pressed
		global MINFO_DIRECTORY
		MINFO_DIRECTORY = self.filepath # Remember for next import
		if not self.auto_select_mmesh:
			bpy.ops.gbfr.select_mmesh('INVOKE_DEFAULT', 
							 minfo_path = self.filepath, 
							 import_scale = self.import_scale,
							 bone_scale = self.bone_scale)
		else:
			bpy.ops.gbfr.select_mmesh_auto('INVOKE_DEFAULT', 
								  minfo_path = self.filepath, 
								  import_scale = self.import_scale,
								  bone_scale = self.bone_scale)
		return {'FINISHED'}

	def invoke(self, context, event): # On dialog open
		global MINFO_DIRECTORY
		if MINFO_DIRECTORY:
			self.filepath = MINFO_DIRECTORY # Go to remembered filepath
		context.window_manager.fileselect_add(self)
		return {'RUNNING_MODAL'}


class SelectMMesh(Operator, ImportHelper):
	"""Importer for Granblue Fantasy Relink models"""
	bl_idname = "gbfr.select_mmesh"
	bl_label = "Select .mmesh & Import Model"

	# ImportHelper mix-in class uses this.
	filename_ext = ".mmesh"
	filter_glob: StringProperty(
		default="*.mmesh",
		options={'HIDDEN'},
	)
	import_scale: FloatProperty(name="Model Scale", default=1.0)
	bone_scale: FloatProperty(name="Bone Scale", default=1.0)
	minfo_path: StringProperty()

	def draw(self, context):
		layout = self.layout
		layout.use_property_split = True

		box = layout.box()
		button = box.row()
		button.operator("gbfr.navigate_to_model_streaming_folder", icon='FILE_FOLDER')

		box = layout.box()
		box.prop(self, "import_scale")
		box.prop(self, "bone_scale")

	def execute(self, context): # On import button pressed
		global MMESH_DIRECTORY
		# Remember for next import
		MMESH_DIRECTORY = self.filepath.rsplit('\\', 1)[0]
		# print("mmesh_directory", mmesh_directory)
		return read_some_data(context, self.minfo_path, [self.filepath], self.import_scale, self.bone_scale) # Run import process

	def invoke(self, context, event): # On dialog open
		global MMESH_DIRECTORY
		if MMESH_DIRECTORY: # Go to remembered filepath
			self.filepath = MMESH_DIRECTORY + '\\' + self.minfo_path.rsplit('\\', 1)[1].replace(".minfo", ".mmesh")
		else:
			self.filepath = self.minfo_path.replace(".minfo", ".mmesh") # Navigate to same folder as .minfo
		context.window_manager.fileselect_add(self)
		return {'RUNNING_MODAL'}
	
class SelectMMeshAuto(Operator, ImportHelper):
	bl_idname = "gbfr.select_mmesh_auto"
	bl_label = "Auto-Select .mmesh Folder"

	filter_glob: StringProperty(
		default="*/",
		options={'HIDDEN'}
	)

	minfo_path: StringProperty()
	import_scale: FloatProperty(name="Model Scale", default=1.0)
	bone_scale: FloatProperty(name="Bone Scale", default=1.0)
	LOD0: BoolProperty(default=True)
	LOD1: BoolProperty(default=False)
	LOD2: BoolProperty(default=False)
	LOD3: BoolProperty(default=False)
	LOD4: BoolProperty(default=False)
	SHADOWLOD0: BoolProperty(default=False)
	SHADOWLOD1: BoolProperty(default=False)
	SHADOWLOD2: BoolProperty(default=False)

	def draw(self, context):
		layout = self.layout
		layout.use_property_split = True
		
		addon_preferences = context.preferences.addons[__package__].preferences

		box = layout.box()
		button = box.row()
		button.enabled = bool(addon_preferences.extracted_game_data_folder_path) # If folder path assigned
		button.operator("gbfr.navigate_to_model_streaming_folder", icon='FILE_FOLDER')

		box = layout.box()
		box.prop(self, "import_scale")
		box.prop(self, "bone_scale")

		box = layout.box()
		box.label(text = "Select Level of Detail Models to import:", icon="MOD_DECIM")
		box.prop(self, "LOD0")
		box.prop(self, "LOD1")
		box.prop(self, "LOD2")
		box.prop(self, "LOD3")
		box.prop(self, "LOD4")
		box.prop(self, "SHADOWLOD0")
		box.prop(self, "SHADOWLOD1")
		box.prop(self, "SHADOWLOD2")

	def execute(self, context): # On import button pressed
		from pathlib import Path
		global MMESH_DIRECTORY

		# Remember for next import
		MMESH_DIRECTORY = self.filepath.rsplit('\\', 1)[0]

		# minfo = self.minfo_path.rsplit('\\', 1)[0] # Path(self.minfo_path)
		mmesh_name = self.minfo_path.rsplit('\\', 1)[1].replace(".minfo", ".mmesh")
		mmesh_dir = Path(MMESH_DIRECTORY)
		mmesh_paths = []

		log_flags = ("LOD0", "LOD1", "LOD2", "LOD3", "LOD4", "SHADOWLOD0", "SHADOWLOD1", "SHADOWLOD2")
		if any([self.LOD0, self.LOD1, self.LOD2, self.LOD3, self.LOD4, self.SHADOWLOD0, self.SHADOWLOD1, self.SHADOWLOD2]):
			for flag in log_flags:
				if getattr(self, flag):
					subdir = mmesh_dir / flag.lower() # f"lod{i}"
					print("subdir", subdir)
					if subdir.is_dir():
						try:
							mmesh_path = next(subdir.glob(mmesh_name))
							print("mmesh_path", mmesh_path)
							mmesh_paths.append(str(mmesh_path.resolve()))
						except StopIteration:
							self.report({'WARNING'}, f"No .mmesh found in {subdir}")
		else:
			mmesh_path = next(mmesh_dir.glob(mmesh_name))
			mmesh_paths.append(str(mmesh_path.resolve()))

		if not mmesh_paths:
			self.report({'WARNING'}, "No .mmesh files found")
			return {'CANCELLED'}

		read_some_data(context, self.minfo_path, mmesh_paths, self.import_scale, self.bone_scale) # Run import process
		self.report({'INFO'}, f"Model Imported!")
		return {'FINISHED'}
	
	def invoke(self, context, event): # On dialog open
		global MMESH_DIRECTORY
		if MMESH_DIRECTORY: # Go to remembered filepath
			self.filepath = MMESH_DIRECTORY + '\\' + self.minfo_path.rsplit('\\', 1)[1].replace(".minfo", ".mmesh")
		else:
			self.filepath = self.minfo_path.replace(".minfo", ".mmesh") # Navigate to same folder as .minfo
		context.window_manager.fileselect_add(self)
		return {'RUNNING_MODAL'}



def menu_func_import(self, context):
	self.layout.operator(SelectMInfo.bl_idname, text="Granblue Fantasy Relink (.minfo)")


# Register and add to the "file selector" menu (required to use F3 search "Text Import Operator" for quick access).
def register():
	bpy.utils.register_class(NavigateToModelFolder)
	bpy.utils.register_class(NavigateToModelStreamingFolder)
	bpy.utils.register_class(SelectMInfo)
	bpy.utils.register_class(SelectMMesh)
	bpy.utils.register_class(SelectMMeshAuto)
	bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
	bpy.utils.unregister_class(NavigateToModelFolder)
	bpy.utils.unregister_class(NavigateToModelStreamingFolder)
	bpy.utils.unregister_class(SelectMInfo)
	bpy.utils.unregister_class(SelectMMesh)
	bpy.utils.unregister_class(SelectMMeshAuto)
	bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
