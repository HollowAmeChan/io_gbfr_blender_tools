from pathlib import Path
import math
import struct
import tempfile
import unittest

from gbfr_sop import (
    AXIS_X_PROPERTY, AXIS_Y_PROPERTY, AXIS_Z_PROPERTY, OFFSET_X_PROPERTY,
    OFFSET_Y_PROPERTY, OFFSET_Z_PROPERTY, SOP_VERSION, SOURCE_BONE_PROPERTY,
    SWING_RATE_PROPERTY, SWING_TWIST_OPERATION, TARGET_BONE_PROPERTY,
    TWIST_RATE_PROPERTY, evaluate_core_operation, guarded_preview_status,
    load_sop, quaternion_error,
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


if __name__ == "__main__":
    unittest.main()
