from pathlib import Path
import struct
import tempfile
import unittest

from gbfr_animation import (
    AnimationClip, AnimationKey, AnimationTrack, load_mot, read_mot_header,
    guess_mot_annotation, serialize_mot_template, write_mot_template_atomic,
)


def make_constant_mot(path):
    data = bytearray(56)
    struct.pack_into("<I", data, 0, 0x00746F6D)
    struct.pack_into("<I", data, 4, 0x20200619)
    struct.pack_into("<HhIII", data, 8, 0, 30, 44, 1, 0)
    data[24:35] = b"test_motion"
    struct.pack_into("<hbbhHf", data, 44, 0x00B, 3, 0, 1, 0, 1.25)
    path.write_bytes(data)


class AnimationTests(unittest.TestCase):
    def test_filename_annotations_are_explicitly_limited_to_known_suffixes(self):
        expected = {
            "fp1400_030a.mot": "闭左眼",
            "fp1400_031a.mot": "紧张闭眼",
            "fp1400_032a.mot": "闭右眼",
            "fp1400_034a.mot": "闭眼",
            "fp1400_035a.mot": "紧闭眼",
            "fp1400_036a.mot": "舒张闭眼",
            "fp1400_e00a.mot": "闭眼笑",
            "fp1400_c50b.mot": "口型",
            "fp1400_c84b.mot": "口型",
        }
        for name, annotation in expected.items():
            self.assertEqual(annotation, guess_mot_annotation(name))
        self.assertEqual("", guess_mot_annotation("fp1400_c50a.mot"))
        self.assertEqual("", guess_mot_annotation("fp1400_c84c.mot"))
        self.assertEqual("", guess_mot_annotation("fp1400_e001.mot"))
        self.assertEqual("", guess_mot_annotation("fp1400_idle.mot"))

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

    def test_template_writer_preserves_contract_and_roundtrips_samples(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            template = AnimationClip(
                root / "source.mot", 0x20200619, 3, 4, 27, "face_test",
                (
                    AnimationTrack(0x123, 3, 5, 1, "hermite", (AnimationKey(0, 0.0),)),
                    AnimationTrack(0x124, 8, 7, 0, "hermite", (AnimationKey(0, 1.0),)),
                ),
            )
            samples = ((0.25, 0.25, 0.25, 0.25), (1.0, 1.5, 2.0, 2.5))
            payload = serialize_mot_template(template, samples)
            direct = root / "direct.mot"
            direct.write_bytes(payload)
            clip = load_mot(direct)
            self.assertEqual(
                (template.version, template.flags, template.frame_count, template.unknown, template.name),
                (clip.version, clip.flags, clip.frame_count, clip.unknown, clip.name),
            )
            self.assertEqual(
                [(0x123, 3, 0, 1), (0x124, 8, 1, 0)],
                [(track.bone_id, track.property, track.compression, track.unknown) for track in clip.tracks],
            )
            for track, expected in zip(clip.tracks, samples):
                self.assertEqual(expected, tuple(track.sample(frame) for frame in range(4)))

            destination = root / "unpack/data/fp/fp0000/face_test.mot"
            self.assertEqual(destination.resolve(), write_mot_template_atomic(template, samples, destination))
            self.assertEqual(payload, destination.read_bytes())

    def test_template_writer_rejects_bad_sample_shape_and_nonfinite_values(self):
        template = AnimationClip(
            Path("source.mot"), 1, 0, 2, 0, "test",
            (AnimationTrack(1, 0, 0, 0, "constant", (AnimationKey(0, 0.0),)),),
        )
        with self.assertRaisesRegex(ValueError, "轨道数量"):
            serialize_mot_template(template, ())
        with self.assertRaisesRegex(ValueError, "采样帧数"):
            serialize_mot_template(template, ((0.0,),))
        with self.assertRaisesRegex(ValueError, "NaN"):
            serialize_mot_template(template, ((0.0, float("nan")),))


if __name__ == "__main__":
    unittest.main()
