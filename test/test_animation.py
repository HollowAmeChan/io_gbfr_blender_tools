from pathlib import Path
import struct
import tempfile
import unittest

from gbfr_animation import AnimationKey, AnimationTrack, load_mot, read_mot_header


def make_constant_mot(path):
    data = bytearray(56)
    struct.pack_into("<I", data, 0, 0x00746F6D)
    struct.pack_into("<I", data, 4, 0x20200619)
    struct.pack_into("<HhIII", data, 8, 0, 30, 44, 1, 0)
    data[24:35] = b"test_motion"
    struct.pack_into("<hbbhHf", data, 44, 0x00B, 3, 0, 1, 0, 1.25)
    path.write_bytes(data)


class AnimationTests(unittest.TestCase):
    def test_header_constant_track_and_sampling(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "test.mot"
            make_constant_mot(path)
            header = read_mot_header(path)
            self.assertEqual((30, 1, "test_motion"), (header.frame_count, header.track_count, header.name))
            clip = load_mot(path)
            self.assertEqual(1.25, clip.tracks[0].sample(18.0))

    def test_linear_and_hermite_sampling(self):
        linear = AnimationTrack(0, 0, 1, 0, "linear", (AnimationKey(0, 0.0), AnimationKey(10, 2.0)))
        self.assertAlmostEqual(1.0, linear.sample(5.0))
        hermite = AnimationTrack(0, 0, 4, 0, "hermite", (AnimationKey(0, 0.0), AnimationKey(10, 1.0)))
        self.assertAlmostEqual(0.5, hermite.sample(5.0))


if __name__ == "__main__":
    unittest.main()
