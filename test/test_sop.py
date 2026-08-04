from pathlib import Path
import math
import struct
import tempfile
import unittest

from gbfr_sop import (
    AXIS_X_PROPERTY, AXIS_Y_PROPERTY, AXIS_Z_PROPERTY, OFFSET_X_PROPERTY,
    OFFSET_Y_PROPERTY, OFFSET_Z_PROPERTY, SOP_VERSION, SOURCE_BONE_PROPERTY,
    SWING_RATE_PROPERTY, SWING_TWIST_OPERATION, TARGET_BONE_PROPERTY,
    TWIST_RATE_PROPERTY, SopAsset, SopOperation, SopProperty, dominant_axis,
    evaluate_core_operation, guarded_preview_status, is_editable_swing_twist,
    load_sop, make_swing_twist_operation, quaternion_error,
    save_sop, update_swing_twist_operation,
)


def float_property(property_hash, value):
    raw = struct.unpack("<I", struct.pack("<f", value))[0]
    return struct.pack("<III", property_hash, 1, raw)


def make_sop(path):
    properties = b"".join((
        float_property(AXIS_X_PROPERTY, 1.0), float_property(AXIS_Y_PROPERTY, 0.0),
        float_property(AXIS_Z_PROPERTY, 0.0), float_property(TWIST_RATE_PROPERTY, 0.5),
        float_property(SWING_RATE_PROPERTY, 1.0), float_property(OFFSET_X_PROPERTY, 0.0),
        float_property(OFFSET_Y_PROPERTY, 0.0), float_property(OFFSET_Z_PROPERTY, 0.0),
    ))
    metadata = 8 << 16
    record = struct.pack(
        "<6I", SWING_TWIST_OPERATION, metadata,
        TARGET_BONE_PROPERTY, 0xA0B, SOURCE_BONE_PROPERTY, 0x00B,
    ) + properties
    path.write_bytes(struct.pack("<4sIII", b"sop\0", SOP_VERSION, 1, 16) + record)


class SopTests(unittest.TestCase):
    def test_parse_evaluate_and_rest_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.sop"
            make_sop(path)
            asset = load_sop(path)
            self.assertEqual(1, len(asset.operations))
            source = (math.cos(0.5), math.sin(0.5), 0.0, 0.0)
            expected = (math.cos(0.25), math.sin(0.25), 0.0, 0.0)
            output = evaluate_core_operation(asset.operations[0], source)
            self.assertLess(quaternion_error(output, expected), 1e-6)
            rest = {0x00B: source, 0xA0B: expected}
            self.assertEqual("approximate_constraint", guarded_preview_status(asset.operations[0], rest))
            rest[0xA0B] = (1.0, 0.0, 0.0, 0.0)
            self.assertEqual("rest_guard_failed", guarded_preview_status(asset.operations[0], rest))

    def test_create_edit_save_and_preserve_unknown_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "editable.sop"
            operation = make_swing_twist_operation(0xA50, 0x00E, 1, 0.5, 0.0)
            operation = SopOperation(
                operation.index, operation.type_hash, operation.metadata,
                operation.target_bone, operation.source_bone,
                operation.properties + (SopProperty(0xDEADBEEF, 0, 42),),
            )
            edited = update_swing_twist_operation(
                operation, target_bone=0xA53, source_bone=0x012,
                axis=2, swing_rate=0.6, twist_rate=0.25,
            )
            unknown = SopOperation(
                1, 0x12345678, 0x00010002, 0xA99, 0x001,
                (SopProperty(0xCAFEBABE, 0, 0x11223344),),
            )
            save_sop(path, SopAsset(path, SOP_VERSION, (edited, unknown)))
            loaded = load_sop(path)

            self.assertEqual(2, len(loaded.operations))
            result = loaded.operations[0]
            self.assertTrue(is_editable_swing_twist(result))
            self.assertEqual((0xA53, 0x012, 2), (result.target_bone, result.source_bone, dominant_axis(result)))
            self.assertAlmostEqual(0.6, result.floating(SWING_RATE_PROPERTY), places=6)
            self.assertAlmostEqual(0.25, result.floating(TWIST_RATE_PROPERTY), places=6)
            self.assertEqual((0xDEADBEEF, 0, 42), (
                result.properties[-1].hash,
                result.properties[-1].value_type,
                result.properties[-1].raw_value,
            ))
            self.assertEqual((0x12345678, 0x11223344), (
                loaded.operations[1].type_hash,
                loaded.operations[1].properties[0].raw_value,
            ))
if __name__ == "__main__":
    unittest.main()
