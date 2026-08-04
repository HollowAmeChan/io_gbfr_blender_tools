"""Audit per-corner attributes that the GBFR vertex exporter must preserve.

Run with:
    blender file.blend --background --python this_file.py
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import struct
import sys

import bpy


if "--" in sys.argv:
    arguments = sys.argv[sys.argv.index("--") + 1:]
    if arguments:
        bpy.ops.preferences.addon_enable(module="io_gbfr_blender_tools")
        result = bpy.ops.gbfr.import_mesh(filepath=str(Path(arguments[0]).resolve()), import_scale=1.0)
        assert result == {"FINISHED"}, result


def half3(values):
    return struct.pack("<eee", *(0.0 if value == 0.0 else value for value in values))


def half2(values):
    return struct.pack("<ee", *(0.0 if value == 0.0 else value for value in values))


def audit_mesh(obj):
    mesh = obj.data
    if not mesh.polygons or not mesh.uv_layers:
        return None
    has_tangents = True
    try:
        mesh.calc_tangents()
    except RuntimeError:
        has_tangents = False
    uv_data = mesh.uv_layers.active.data
    by_vertex = defaultdict(lambda: defaultdict(set))
    by_edge_vertex = defaultdict(lambda: defaultdict(list))
    for polygon in mesh.polygons:
        polygon_loops = list(polygon.loop_indices)
        for offset, loop_index in enumerate(polygon_loops):
            loop = mesh.loops[loop_index]
            components = {
                "normal": half3(loop.normal),
                "tangent": half3(loop.tangent) if has_tangents else None,
                "uv": half2(uv_data[loop_index].uv),
                "sign": loop.bitangent_sign < 0.0 if has_tangents else None,
            }
            for key, value in components.items():
                if value is not None:
                    by_vertex[loop.vertex_index][key].add(value)
                    by_edge_vertex[(loop.edge_index, loop.vertex_index)][key].append(value)
            next_loop_index = polygon_loops[(offset + 1) % len(polygon_loops)]
            next_loop = mesh.loops[next_loop_index]
            next_components = {
                "normal": half3(next_loop.normal),
                "tangent": half3(next_loop.tangent) if has_tangents else None,
                "uv": half2(uv_data[next_loop_index].uv),
                "sign": next_loop.bitangent_sign < 0.0 if has_tangents else None,
            }
            for key, value in next_components.items():
                if value is not None:
                    by_edge_vertex[(loop.edge_index, next_loop.vertex_index)][key].append(value)

    split_vertices = {
        key: sum(len(components[key]) > 1 for components in by_vertex.values())
        for key in ("normal", "tangent", "uv", "sign")
    }
    discontinuous_edges = defaultdict(set)
    unprotected_edges = defaultdict(set)
    sharp_edges = set()
    for (edge_index, _vertex_index), components in by_edge_vertex.items():
        edge = mesh.edges[edge_index]
        for key, values in components.items():
            if len(values) < 2 or len(set(values)) == 1:
                continue
            discontinuous_edges[key].add(edge_index)
            if edge.use_edge_sharp:
                sharp_edges.add(edge_index)
            if not edge.use_seam:
                unprotected_edges[key].add(edge_index)
    return {
        "vertices": len(mesh.vertices),
        "loops": len(mesh.loops),
        "split_vertices": split_vertices,
        "discontinuous_edges": {key: len(value) for key, value in discontinuous_edges.items()},
        "sharp_edges": len(sharp_edges),
        "unprotected_edges": {key: len(value) for key, value in unprotected_edges.items()},
    }


rows = []
for obj in bpy.context.scene.objects:
    if obj.type != "MESH":
        continue
    result = audit_mesh(obj)
    if result and any(result["split_vertices"].values()):
        unprotected = sum(result["unprotected_edges"].values())
        rows.append((unprotected, sum(result["split_vertices"].values()), obj.name, result))

rows.sort(reverse=True)
print(f"GBFR corner attribute audit: {len(rows)} affected mesh object(s)")
for _unprotected, _extra, name, result in rows:
    print(
        f"{name}: verts={result['vertices']} loops={result['loops']} "
        f"multi_corner_verts={result['split_vertices']} "
        f"discontinuous_edges={result['discontinuous_edges']} "
        f"sharp_edges={result['sharp_edges']} "
        f"not_uv_seam={result['unprotected_edges']} "
        f"parent={getattr(bpy.data.objects.get(name).parent, 'name', '-')}"
    )
