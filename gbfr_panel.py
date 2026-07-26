import bpy
import bpy.utils.previews # Funny blender at it again acting weird for some by not importing this despite bpy being imported :)))))))))))))))))))))
import os
import webbrowser
import urllib.request
from .utils import *

DIR_PATH = os.path.dirname(os.path.abspath(__file__))
ICONS_PATH = os.path.join(DIR_PATH, "icons")
PCOLL = None
preview_collections = {}
curr_game_magic = None


def _active_armature(context):
	obj = context.active_object
	if obj is None:
		return None
	if obj.type == 'ARMATURE':
		return obj
	armature = obj.find_armature()
	if armature is not None:
		return armature
	parent = obj.parent
	while parent is not None:
		if parent.type == 'ARMATURE':
			return parent
		parent = parent.parent
	return None

# Define the panel class
class GBFRToolPanel_Fixes(bpy.types.Panel):
	"""Creates a custom panel in the Object properties editor"""
	bl_label = "Fixes"
	bl_idname = "VIEW3D_PT_GBFR_Tools_Panel_Fixes"
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'UI'
	bl_category = "GBFR"

	def draw(self, context):
		layout = self.layout
		# Add a boolean property with a tooltip
		# layout.label(text="Fixes")
		box = layout.box()

		row = box.row(align=True) ; row.scale_y = 0.5
		row.label(text="Split Vertices:", icon="MESH_DATA")
		row = box.row(align=True) ; row.scale_y = 1.5
		button = row.operator("mesh.split_mesh_along_uvs", icon='UV')
		# row = box.row() ; row.scale_y = 0.5

		# row = box.row() ; row.scale_y = 0.5
		# row.label(text="Recommended to use this before export", icon='ERROR')
		# row = box.row(align=True) ; row.scale_y = 1.5
		# button = row.operator("mesh.sort_materials", icon='MATERIAL')

		# row = box.row() ; row.scale_y = 0.5
		row = box.row() ; row.scale_y = 0.5
		row.label(text="Mesh Clean Up:", icon='MESH_DATA')
		row = box.row() ; row.scale_y = 1.5
		button = row.operator("mesh.limit_and_normalize_weights", icon='MESH_DATA')
		row = box.row() ; row.scale_y = 1.5
		button = row.operator("mesh.delete_loose_edges_and_verts", icon = "MESH_DATA")

		# ----------------------------

class GBFRToolPanel_Utilities(bpy.types.Panel):
	bl_label = "Utilities"
	bl_idname = "VIEW3D_PT_GBFR_Tools_Panel_Utilities"
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'UI'
	bl_category = "GBFR"

	def draw(self, context):
		layout = self.layout
		# layout.label(text="Utilities", icon='MODIFIER')
		box = layout.box()

		# Armature
		box.label(text="Armature:", icon='ARMATURE_DATA')
		row = box.row() ; row.scale_y = 0.5	
		row.label(text="Translate Bones To:", icon="BONE_DATA")
		
		row = box.row(align=True) ; row.scale_y = 1.5
		button = row.operator("armature.translate_bones_to_unity_blender", icon='NONE')
		button = row.operator("armature.translate_bones_to_gbfr", icon='NONE')

		# Mesh
		box.label(text="Mesh:", icon='MESH_DATA')
		
		col = box.column(align=True)
		row = col.row() ; row.scale_y = 1.4
		button = row.operator("mesh.separate_by_material", icon='MESH_DATA')
		
		row = col.row() ; row.scale_y = 1.4
		button = row.operator("mesh.join_all_meshes", icon='MESH_DATA')
		
		row = box.row()
		button = row.operator("mesh.select_0_weight_vertices", icon='MESH_DATA')
		
		row = box.row()
		button = row.operator("mesh.flip_normals", icon='MESH_DATA')
		
		row = box.row()
		button = row.operator("mesh.remove_doubles", text="Remove Doubles", icon='MESH_DATA')
		button.use_unselected = True
		button.threshold = 0.000001 # Use this threshold or all hell breaks loose


class GBFRToolPanel_Materials(bpy.types.Panel):
	bl_label = "Materials"
	bl_idname = "VIEW3D_PT_GBFR_Tools_Panel_Materials"
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'UI'
	bl_category = "GBFR"

	def draw(self, context):
		layout = self.layout
		# layout.label(text="Materials", icon='MATERIAL')
		box = layout.box()
		obj = context.object
		if obj and obj.type == 'MESH':
			mesh = obj.data
			materials = mesh.materials
			col = box.column(align=True)
			row = col.row(align=False)
			row.label(text = "", icon = "INFO")
			row = col.row(align=False) ; row.scale_y = 0.5
			row.label(text = "Used to set the index of materials")
			row = col.row(align=False) ; row.scale_y = 0.5
			row.label(text = "to their equivalents in the .mmat.")
			row = box.row(align=False) ; row.scale_y = 0.5
			row.label(text = "Material Name:")
			row.label(text = "Material Index:")
			col = box.column(align=True)
			for slot_index, material in enumerate(materials):
				if material:
					row = col.row(align=True)
					row.prop(material, "name", text="")
					material_id = material.get("MaterialID", None)
					if material_id != None:
						if material_id < 0 and material_id:
							row.alert = True # Highlight red to alert user
						row.prop(material, '["MaterialID"]', text="")						
					else:
						row.alert = True # Highlight red to alert user
						op = row.operator("material.add_material_index")
						op.material_slot = slot_index
		else:
			row = box.row(align=False)
			row.label(text = "Select a mesh to configure materials.", icon = "ERROR")

class GBFRToolPanel_Advanced(bpy.types.Panel):
	bl_label = "Advanced"
	bl_idname = "VIEW3D_PT_GBFR_Tools_Panel_Advanced"
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'UI'
	bl_category = "GBFR"
	bl_options = {"DEFAULT_CLOSED"}

	def draw(self, context):
		layout = self.layout
		box = layout.box()
		col = box.column(align=True)
		obj = context.object
		if obj and obj.type != 'ARMATURE':
			if obj.parent.type == 'ARMATURE':
				obj = obj.parent
		armature = obj
		if armature and armature.type == 'ARMATURE':
			row = col.row(align=False)
			row.label(text = f".minfo Magic Number:", icon="SHADERFX")
			row = col.row(align=False)
			row.label(text = f"Only edit this if game's Magic Number has changed!", icon="ERROR")
			row = col.row(align=False)
			magic = armature.get("Magic", None)
			
			if magic != None:
				if curr_game_magic > magic: row.alert = True # Highlight if model's version is older
				row.prop(armature, '["Magic"]', text="")
			else:
				row.alert = True
				row.operator("armature.add_magic_number")
			row = col.row(align=False) ; row.scale_y = 0.75
			row.label(text = f"Game's current .minfo magic: {curr_game_magic}", icon="INFO")
			


class GBFRToolPanel_Credits(bpy.types.Panel):
	global PCOLL
	bl_label = "Credits"
	bl_idname = "VIEW3D_PT_GBFR_Tools_Panel_Credits"
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'UI'
	bl_category = "GBFR"
	bl_options = {"DEFAULT_CLOSED"}

	def draw(self, context):
		layout = self.layout
		box = layout.box()
		col = box.column(align=True)
		row = col.row(align=False)
		row.label(text = f"GBFR Blender Tools", icon_value=preview_collections["icons"]["GBFR_Modding"].icon_id)
		col.separator()
		row = col.row(align=False) ; row.scale_y = 0.75
		row.label(text = "Created by:")
		row = col.row(align=False) ; row.scale_y = 0.75
		row.label(text = "WistfulHopes & AlphaSatanOmega")
		col.separator()
		row = col.row(align=False) ; row.scale_y = 0.75
		row.label(text = "Special thanks:")
		row = col.row(align=False) ; row.scale_y = 0.75
		row.label(text = "WolfieBeat, bujyu-uo, rurires")
		#TODO: Add discord and github button
		col.separator()
		row = col.row() ; row.scale_y = 1.4
		button = row.operator("gbfr.discord", icon_value=preview_collections["icons"]["discord"].icon_id)
		row = col.row() ; row.scale_y = 1.4
		button = row.operator("gbfr.website", icon_value=preview_collections["icons"]["GBFR_Modding"].icon_id)
		row = col.row() ; row.scale_y = 1.4
		button = row.operator("gbfr.github", icon_value=preview_collections["icons"]["github"].icon_id)

		col.separator()
		row = col.row(align=False) ; row.scale_y = 0.75
		row.label(text = "KEEP IT CLEAN!", icon_value=preview_collections["icons"]["KEEPITCLEAN"].icon_id)


class GBFRToolPanel_RestoredUtilities(bpy.types.Panel):
	"""Old editing helpers collected into one top-level, foldable panel."""
	bl_label = "GBFR 实用工具"
	bl_idname = "VIEW3D_PT_GBFR_Restored_Utilities"
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'UI'
	bl_category = "GBFR"
	bl_options = {"DEFAULT_CLOSED"}

	def draw(self, context):
		layout = self.layout
		active = context.active_object
		armature = _active_armature(context)
		mesh = active if active and active.type == 'MESH' else None

		header, panel = layout.panel("gbfr_utility_armature", default_closed=False)
		header.label(text="骨架", icon='ARMATURE_DATA')
		if panel:
			if armature:
				panel.label(text=armature.name, icon='BONE_DATA')
				row = panel.row(align=True)
				row.operator("armature.translate_bones_to_unity_blender", text="Unity / Blender")
				row.operator("armature.translate_bones_to_gbfr", text="GBFR")
			else:
				panel.label(text="选择骨架，或选择其下的模型。", icon='INFO')

		header, panel = layout.panel("gbfr_utility_clp_create", default_closed=False)
		header.label(text="CLP 创建工具", icon='PHYSICS')
		if panel:
			state = getattr(armature, "gbfr_cloth", None) if armature else None
			if not state or not state.enabled:
				panel.label(text="先从工作区中控导入并激活模型会话。", icon='INFO')
			elif not state.clp_groups:
				panel.label(text="当前工作区没有可复用的 CLP 槽位。", icon='INFO')
			else:
				group = state.clp_groups[state.active_clp_index]
				panel.label(text=f"当前 CLP {group.group_id} · {len(group.nodes)} 节点", icon='CONSTRAINT_BONE')
				panel.prop(state, "clp_tool_preset")
				panel.prop(state, "clp_tool_topology", expand=True)
				settings = panel.row(align=True)
				settings.prop(state, "clp_tool_closed", toggle=True, icon='LOOP_FORWARDS')
				settings.prop(state, "clp_tool_apply_header", toggle=True, icon='PRESET')

				create = panel.row(align=True)
				add = create.operator("gbfr.clp_create_from_selection", text="添加所选", icon='ADD')
				add.replace_existing = False
				replace = create.operator("gbfr.clp_create_from_selection", text="替换当前组", icon='FILE_REFRESH')
				replace.replace_existing = True

				remove = panel.row(align=True)
				exact = remove.operator("gbfr.clp_delete_selection", text="删除所选", icon='REMOVE')
				exact.include_descendants = False
				subtree = remove.operator("gbfr.clp_delete_selection", text="删除所选及后代", icon='TRASH')
				subtree.include_descendants = True
				panel.operator("gbfr.clp_rebuild_connections", text="仅重建连接", icon='NODETREE')
				if state.last_status:
					panel.label(text=state.last_status, icon='INFO')

		header, panel = layout.panel("gbfr_utility_mesh", default_closed=False)
		header.label(text="网格", icon='MESH_DATA')
		if panel:
			if mesh:
				row = panel.row(align=True)
				row.operator("mesh.split_mesh_along_uvs", text="按 UV 岛拆分", icon='UV')
				row.operator("mesh.remove_unused_vertex_groups", text="删除无效顶点组")
				row = panel.row(align=True)
				limit4 = row.operator("mesh.limit_and_normalize_weights", text="限制为 4 权重")
				limit4.limit_number = 4
				limit8 = row.operator("mesh.limit_and_normalize_weights", text="限制为 8 权重")
				limit8.limit_number = 8
				row = panel.row(align=True)
				row.operator("mesh.delete_loose_edges_and_verts", text="删除松散几何")
				row.operator("mesh.select_0_weight_vertices", text="选择零权重")
				row = panel.row(align=True)
				row.operator("mesh.separate_by_material", text="按材质拆分")
				row.operator("mesh.join_all_meshes", text="合并模型网格")
				row = panel.row(align=True)
				row.operator("mesh.flip_normals", text="翻转法线")
				row.operator("mesh.remove_doubles", text="合并重复点")
			else:
				panel.label(text="选择要处理的模型网格。", icon='INFO')

		header, panel = layout.panel("gbfr_utility_materials", default_closed=True)
		header.label(text="材质 ID", icon='MATERIAL')
		if panel:
			if mesh:
				panel.label(text="材质槽 ID 对应 .mmat 索引。", icon='INFO')
				for slot_index, material in enumerate(mesh.data.materials):
					if not material:
						continue
					row = panel.row(align=True)
					row.prop(material, "name", text="")
					if "MaterialID" in material:
						row.prop(material, '["MaterialID"]', text="ID")
					else:
						row.alert = True
						op = row.operator("material.add_material_index", text="添加 ID")
						op.material_slot = slot_index
			else:
				panel.label(text="选择模型后编辑材质 ID。", icon='INFO')

		header, panel = layout.panel("gbfr_utility_advanced", default_closed=True)
		header.label(text="高级", icon='PREFERENCES')
		if panel:
			if armature:
				row = panel.row(align=True)
				row.label(text="minfo Magic")
				if "Magic" in armature:
					row.prop(armature, '["Magic"]', text="")
				else:
					row.operator("armature.add_magic_number", text="添加")
				panel.label(text="仅在游戏版本 Magic 变化时手动修改。", icon='INFO')
			else:
				panel.label(text="选择骨架后查看 minfo Magic。", icon='INFO')

		header, panel = layout.panel("gbfr_utility_links", default_closed=True)
		header.label(text="项目链接", icon='URL')
		if panel:
			row = panel.row(align=True)
			row.operator("gbfr.discord", text="Discord")
			row.operator("gbfr.website", text="文档网站")
			row.operator("gbfr.github", text="GitHub")



#=======================
# Operator Classes
#=======================

class ButtonAddMaterialIndex(bpy.types.Operator):
	bl_idname = "material.add_material_index"
	bl_label = "Add Material Index"
	bl_description = "Add a Material Index to this Material"
	bl_options = {'REGISTER', 'UNDO'}

	# material = bpy.props.PointerProperty(type=bpy.types.Material)
	material_slot: bpy.props.IntProperty(default=-1)

	@classmethod
	def poll(cls, context):
		return (context.active_object is not None and
				context.active_object.type == 'MESH')

	def execute(self, context):
		try:
			mesh = context.object.data
			materials = mesh.materials
			for slot_index, material in enumerate(materials):
				if slot_index == self.material_slot:
					material["MaterialID"] = -1
					# self.report({'INFO'}, f"{material.name}")
		except Exception as err:
			raise Exception(f"{err}")
		return {'FINISHED'}

class ButtonAddMagicNumber(bpy.types.Operator):
	bl_idname = "armature.add_magic_number"
	bl_label = "Add Magic Number"
	bl_description = "Add GBFR's Magic file number to the model"
	bl_options = {'REGISTER', 'UNDO'}

	@classmethod
	def poll(cls, context):
		return _active_armature(context) is not None

	def execute(self, context):
		try:
			obj = _active_armature(context)
			magic = utils_get_magic()
			obj["Magic"] = magic
			# Set up property
			obj.id_properties_ensure() # ensure manager is updated
			prop_manager = obj.id_properties_ui("Magic")
			prop_manager.update(min=0, max=100000000, default = magic)
		except Exception as err:
			raise Exception(f"{err}")
		return {'FINISHED'}


class ButtonSplitMeshAlongUVs(bpy.types.Operator):
	bl_idname = "mesh.split_mesh_along_uvs"
	bl_label = "Along UV Islands"
	bl_description = "Splits the edges along UV Islands to prevent UVs from joining on export."
	bl_options = {'REGISTER', 'UNDO'}

	@classmethod
	def poll(cls, context):
		return (context.active_object is not None and
				context.active_object.type == 'MESH')

	def execute(self, context):
		try:
			self.report({'INFO'}, f"Mesh(es) successfully split along UVs!")
			split_faces_by_edge_seams(context.active_object)
		except Exception as err:
			print(f"{err}")
			pass
		return {'FINISHED'}

class ButtonDeleteLooseGeometry(bpy.types.Operator):
	bl_idname = "mesh.delete_loose_edges_and_verts"
	bl_label = "Delete Loose Verts & Edges"
	bl_description = "Deletes Loose any loose Vertices & Edges on the mesh so the model doesn't explode."
	bl_options = {'REGISTER', 'UNDO'}

	@classmethod
	def poll(cls, context):
		return (context.active_object is not None and
				context.active_object.type == 'MESH')

	def execute(self, context):
		try:
			mesh = context.active_object.data
			init_verts = len(mesh.vertices) ; init_edges = len(mesh.edges) ; init_faces = len(mesh.polygons)
			utils_set_mode('EDIT')
			bpy.ops.mesh.select_all(action='SELECT')
			bpy.ops.mesh.delete_loose(use_verts=True, use_edges=True, use_faces=False)
			utils_set_mode('OBJECT')
			removed_verts = init_verts - len(mesh.vertices) ; removed_edges = init_edges - len(mesh.edges) ; removed_faces = init_faces - len(mesh.polygons)
			self.report({'INFO'}, f"Removed: {removed_verts} vertices, {removed_edges} edges, {removed_faces} faces")
		except Exception as err:
			print(f"{err}")
			pass
		return {'FINISHED'}


class ButtonTranslateBonesToUnityBlender(bpy.types.Operator):
	bl_idname = "armature.translate_bones_to_unity_blender"
	bl_label = "Unity/Blender"
	bl_options = {'REGISTER', 'UNDO'}
	bl_description = "Translates general humanoid bones in the GBFR naming scheme to a Unity/Blender naming scheme."

	@classmethod
	def poll(cls, context):
		return _active_armature(context) is not None

	def execute(self, context):
		try:
			armature = _active_armature(context)
			armature_data = armature.data
			utils_rename_bones(armature_data, name_to_index = False)
			self.report({'INFO'}, f"Bone names translated to Unity/Blender Format!")
		except Exception as err:
			print(f"{err}")
			pass
		return {'FINISHED'}


class ButtonTranslateBonesToGBFR(bpy.types.Operator):
	bl_idname = "armature.translate_bones_to_gbfr"
	bl_label = "GBFR"
	bl_options = {'REGISTER', 'UNDO'}
	bl_description = "Translates general humanoid bones in the Unity/Blender naming scheme to the GBFR naming scheme."


	@classmethod
	def poll(cls, context):
		return _active_armature(context) is not None

	def execute(self, context):
		try:
			armature = _active_armature(context)
			armature_data = armature.data
			utils_rename_bones(armature_data, name_to_index = True)
			self.report({'INFO'}, f"Bone names translated to GBFR Format!")
		except Exception as err:
			print(f"{err}")
			pass
		return {'FINISHED'}


class ButtonSeparateByMaterial(bpy.types.Operator):
	bl_idname = "mesh.separate_by_material"
	bl_label = "Separate By Materials"
	bl_options = {'REGISTER', 'UNDO'}
	bl_description = "Separates the actively selected mesh by materials and names them accordingly."

	@classmethod
	def poll(cls, context):
		return (context.active_object is not None and
				context.active_object.type == 'MESH')

	def execute(self, context):
		try:
			utils_separate_by_materials(context)
			self.report({'INFO'}, f"Separated by Materials!")
		except Exception as err:
			print(f"{err}")
			pass
		return {'FINISHED'}


class ButtonSortMaterials(bpy.types.Operator):
	bl_idname = "mesh.sort_materials"
	bl_label = "Sort Materials"
	bl_options = {'REGISTER', 'UNDO'}
	bl_description = "Separates the model's meshes by materials, then sorts and joins them in roughly the same order as GBFR's material sorting order."

	@classmethod
	def poll(cls, context):
		return (context.active_object is not None and
				context.active_object.type == 'MESH')

	def execute(self, context):
		try:
			utils_reorder_materials(context)
			self.report({'INFO'}, f"Sorted all Materials!")
		except Exception as err:
			raise #print(f"{err}")
			# raise Exception(f"{err}")
			pass
		return {'FINISHED'}


class ButtonJoinAllMeshes(bpy.types.Operator):
	bl_idname = "mesh.join_all_meshes"
	bl_label = "Join All Meshes"
	bl_options = {'REGISTER', 'UNDO'}
	bl_description = "Joins all the model's meshes"

	@classmethod
	def poll(cls, context):
		return (context.active_object is not None and
				(context.active_object.type == 'MESH' or context.active_object.type == 'ARMATURE'))

	def execute(self, context):
		try:
			utils_join_meshes(context, selected_only = False)
			self.report({'INFO'}, f"Joined all meshes!")
		except Exception as err:
			print(f"{err}")
			raise Exception(f"{err}")
			pass
		return {'FINISHED'}


class ButtonSelect0WeightVertices(bpy.types.Operator):
	bl_idname = "mesh.select_0_weight_vertices"
	bl_label = "Select Zero Weight Vertices"
	bl_options = {'REGISTER', 'UNDO'}
	bl_description = "Selects all vertices on the active mesh that have no weights."

	@classmethod
	def poll(cls, context):
		return (context.active_object is not None and
				context.active_object.type == 'MESH')

	def execute(self, context):
		try:
			active_object = context.active_object
			zero_weight_vert_count = utils_select_0_weight_vertices(active_object)
			self.report({'INFO'}, f"{zero_weight_vert_count} Vertices Selected")
		except Exception as err:
			print(f"{err}")
			raise Exception(f"{err}")
			pass
		return {'FINISHED'}


class ButtonLimitAndNormalizeAllWeights(bpy.types.Operator):
	bl_idname = "mesh.limit_and_normalize_weights"
	bl_label = "Limit & Normalize Weights"
	bl_options = {'REGISTER', 'UNDO'}
	bl_description = "Limits the weights of all vertices on the mesh to 4 vertex groups, and normalizes them."
	limit_number: bpy.props.IntProperty(name="权重上限", default=4, min=1, max=8)

	@classmethod
	def poll(cls, context):
		return (context.active_object is not None and
				context.active_object.type == 'MESH')

	def execute(self, context):
		try:
			mesh = context.active_object
			utils_limit_and_normalize_weights(mesh, self.limit_number)
			self.report({'INFO'}, f"Weights normalized and limited to {self.limit_number} groups per vertex.")
		except Exception as err:
			print(f"{err}")
			raise Exception(f"{err}")
			pass
		return {'FINISHED'}


class RemoveUnusedVertexGroups(bpy.types.Operator):
	bl_idname = "mesh.remove_unused_vertex_groups"
	bl_label = "删除无效顶点组"
	bl_description = "删除当前模型中没有同名骨骼的顶点组"
	bl_options = {'REGISTER', 'UNDO'}

	@classmethod
	def poll(cls, context):
		return context.active_object is not None and context.active_object.type == 'MESH' and _active_armature(context) is not None

	def execute(self, context):
		mesh = context.active_object
		armature = _active_armature(context)
		bone_names = {bone.name for bone in armature.data.bones}
		removed = 0
		for group in reversed(mesh.vertex_groups):
			if group.name not in bone_names:
				mesh.vertex_groups.remove(group)
				removed += 1
		self.report({'INFO'}, f"Removed {removed} unused vertex groups.")
		return {'FINISHED'}

class ButtonDiscord(bpy.types.Operator):
	bl_idname = "gbfr.discord"
	bl_label = "Relink Modding Discord"
	bl_options = {'REGISTER', 'UNDO'}

	def execute(self, context):
		webbrowser.open("https://discord.gg/gbsG4CDsru")
		return {'FINISHED'}

class ButtonWebsite(bpy.types.Operator):
	bl_idname = "gbfr.website"
	bl_label = "Relink Modding Website"
	bl_options = {'REGISTER', 'UNDO'}

	def execute(self, context):
		webbrowser.open("https://nenkai.github.io/relink-modding/")
		return {'FINISHED'}

class ButtonGitHub(bpy.types.Operator):
	bl_idname = "gbfr.github"
	bl_label = "GitHub"
	bl_options = {'REGISTER', 'UNDO'}

	def execute(self, context):
		webbrowser.open("https://github.com/WistfulHopes/GBFRBlenderTools")
		return {'FINISHED'}
	


classes = [GBFRToolPanel_RestoredUtilities,
			ButtonSplitMeshAlongUVs, ButtonTranslateBonesToGBFR, ButtonTranslateBonesToUnityBlender,
			ButtonSeparateByMaterial, ButtonSortMaterials, ButtonJoinAllMeshes, ButtonSelect0WeightVertices, 
			ButtonLimitAndNormalizeAllWeights, RemoveUnusedVertexGroups, ButtonDeleteLooseGeometry, ButtonAddMaterialIndex, ButtonAddMagicNumber,
			ButtonDiscord, ButtonWebsite, ButtonGitHub
			]

# Register the panel class
def register():
	for cls in classes:
		bpy.utils.register_class(cls)



# Unregister the panel class
def unregister():
	for cls in reversed(classes):
		bpy.utils.unregister_class(cls)

# Test the panel in Blender
# if __name__ == "__main__":
# 	register()
