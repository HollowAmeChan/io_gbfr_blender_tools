bl_info = {
    "name": "Granblue Fantasy Relink Blender Tools",
    "author": "WistfulHopes & AlphaSatanOmega",
    "version": (1, 6, 0),
    "blender": (4, 0, 0),
    "location": "File > Import/Export | View 3D > Tool Shelf > GBFR",
    "description": "Workspace-aware model and CLP/CLH editing tools for Granblue Fantasy Relink",
    "warning": "",
    "category": "Import-Export",
    "doc_url": "https://github.com/WistfulHopes/GBFRBlenderTools?tab=readme-ov-file#gbfr-blender-tools"
}

# Reloads the addons on script reload
# Good for editing script
if "bpy" in locals():
    import importlib
    if "gbfr_import" in locals():
        importlib.reload(gbfr_import)
    if "gbfr_export" in locals():
        importlib.reload(gbfr_export)
    if "gbfr_panel" in locals():
        importlib.reload(gbfr_panel)
    if "utils" in locals():
        importlib.reload(utils)
    if "gbfr_workspace" in locals():
        importlib.reload(gbfr_workspace)
    if "gbfr_cloth_format" in locals():
        importlib.reload(gbfr_cloth_format)
    if "gbfr_cloth_metadata" in locals():
        importlib.reload(gbfr_cloth_metadata)
    if "gbfr_cloth_blender" in locals():
        importlib.reload(gbfr_cloth_blender)
    if "gbfr_sop" in locals():
        importlib.reload(gbfr_sop)
    if "gbfr_sop_blender" in locals():
        importlib.reload(gbfr_sop_blender)
    if "gbfr_animation" in locals():
        importlib.reload(gbfr_animation)
    if "gbfr_animation_blender" in locals():
        importlib.reload(gbfr_animation_blender)
    if "gbfr_material" in locals():
        importlib.reload(gbfr_material)
    if "gbfr_material_blender" in locals():
        importlib.reload(gbfr_material_blender)

import bpy
import bmesh
import mathutils
import struct
import os
from . import (
    gbfr_import, gbfr_export, gbfr_panel, utils,
    gbfr_workspace, gbfr_cloth_format, gbfr_cloth_metadata, gbfr_cloth_blender,
    gbfr_sop, gbfr_sop_blender,
    gbfr_animation, gbfr_animation_blender,
    gbfr_material, gbfr_material_blender,
)
from .Entities.ModelInfo import ModelInfo
# from .Entities.ModelSkeleton import ModelSkeleton

# ImportHelper is a helper class, defines filename and
# invoke() function which calls the file selector.
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty, BoolProperty, EnumProperty
from bpy.types import Operator

# Addon preferences, where users will specify flatc.exe path
class AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__
    
    # Define a custom property for storing the flatc file path
    flatc_file_path: StringProperty(
        name="flatc.exe filepath",
        description="File path to flatc.exe be used for export.",
        subtype='FILE_PATH',
    )

    gbfr_data_tools_path: StringProperty(
        name="GBFRDataTools.exe filepath",
        description="Optional override used to encode edited cloth XML to BXM",
        subtype='FILE_PATH',
    )
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "flatc_file_path")
        layout.prop(self, "gbfr_data_tools_path")


# Register importer & exporter
def register():
    bpy.utils.register_class(AddonPreferences)
    gbfr_import.register()
    gbfr_export.register()
    gbfr_panel.register()
    gbfr_cloth_blender.register()
    gbfr_sop_blender.register()
    gbfr_animation_blender.register()

def unregister():
    gbfr_animation_blender.unregister()
    gbfr_sop_blender.unregister()
    gbfr_cloth_blender.unregister()
    gbfr_import.unregister()
    gbfr_export.unregister()
    gbfr_panel.unregister()
    bpy.utils.unregister_class(AddonPreferences)

#Run the addon
if __name__ == "__main__":
    register()
    # test call
    # bpy.ops.gbfr.mesh('INVOKE_DEFAULT')
