"""Run with: blender --background --factory-startup --python this_file.py"""

import math

import bpy
from mathutils import Vector


bpy.ops.preferences.addon_enable(module="io_gbfr_blender_tools")

from io_gbfr_blender_tools.gbfr_model_export_v2 import orthonormalize_tangent


def assert_basis(normal, tangent):
    result = orthonormalize_tangent(normal, tangent)
    unit_normal = Vector(normal).normalized()
    assert all(math.isfinite(value) for value in result)
    assert abs(result.length - 1.0) < 1e-6
    assert abs(result.dot(unit_normal)) < 1e-6


assert_basis((0.0, 0.0, 1.0), (1.0, 0.0, 1.0))
assert_basis((0.2, 2.0, -0.5), (4.0, -1.0, 0.25))
assert_basis((0.0, 1.0, 0.0), (0.0, 0.0, 0.0))
assert_basis((1.0, 0.0, 0.0), (math.nan, 0.0, 0.0))

print("GBFR tangent basis smoke passed")
