"""표본 포즈 미리보기 그림의 골격 계산과 픽셀 출력을 Blender 없이 검사한다."""

from pathlib import Path
import sys
import tempfile
import types
import unittest

root = Path(__file__).resolve().parents[1]
package = types.ModuleType("catani")
package.__path__ = [str(root / "catani")]
sys.modules["catani"] = package
sys.path.insert(0, str(root / "tests"))

from catani import motion_preview
from bvh_fixture import FRAMES, write_bvh


class MotionSketchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="catani-motion-preview-")
        self.path = Path(self.directory.name) / "walk.bvh"
        self.order = write_bvh(self.path)
        self.addCleanup(self.directory.cleanup)

    def test_sketch_reads_meta_and_normalises_poses(self):
        motion = motion_preview.sketch(self.path)
        self.assertEqual(motion.frames, FRAMES)
        self.assertAlmostEqual(motion.fps, 30.0, places=1)
        self.assertAlmostEqual(motion.duration, FRAMES / 30.0, places=1)
        # End Site까지 관절로 세므로 합성 리그의 관절 수보다 많아야 한다.
        self.assertGreater(motion.joints, len(self.order))
        self.assertEqual(len(motion.bones), motion.joints - 1)
        self.assertEqual(len(motion.poses), motion_preview.SAMPLE_COUNT)
        for pose in motion.poses:
            self.assertEqual(len(pose), motion.joints)
            for x, y in pose:
                self.assertTrue(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0, (x, y))
        # 모든 표본이 같은 포즈면 미리보기로 쓸모가 없다.
        self.assertNotEqual(motion.poses[0], motion.poses[-1])

    def test_sample_skips_leading_rest_pose(self):
        self.assertEqual(motion_preview._sample_indices(200, 6)[0], 16)
        self.assertEqual(motion_preview._sample_indices(200, 6)[-1], 199)
        # 프레임이 적으면 처음부터 쓰고, 표본 수를 프레임 수로 줄인다.
        self.assertEqual(motion_preview._sample_indices(3, 6), [0, 1, 2])

    def test_pixels_draw_inside_buffer(self):
        motion = motion_preview.sketch(self.path)
        size = 64
        buffer = motion_preview.pixels(motion, 1, size=size)
        self.assertEqual(len(buffer), size * size * 4)
        self.assertTrue(all(0.0 <= value <= 1.0 for value in buffer))
        alphas = buffer[3::4]
        self.assertGreater(sum(1 for value in alphas if value > 0.5), 20, "뼈대 선이 거의 그려지지 않았습니다")
        self.assertLess(sum(1 for value in alphas if value > 0.0), size * size * 0.5, "선이 화면을 뒤덮었습니다")
        # 첫 표본은 직전 포즈가 없어 잔상 없이 그려진다.
        self.assertLess(sum(motion_preview.pixels(motion, 0, size=size)[3::4]), sum(alphas))

    def test_up_axis_detects_z_up_rig(self):
        z_up = [{"parent": -1, "offset": (0.0, 0.0, 0.0)}, {"parent": 0, "offset": (0.0, 0.5, 9.0)}]
        y_up = [{"parent": -1, "offset": (0.0, 0.0, 0.0)}, {"parent": 0, "offset": (0.0, 9.0, 0.5)}]
        self.assertEqual(motion_preview._up_axis(z_up), 2)
        self.assertEqual(motion_preview._up_axis(y_up), 1)

    def test_broken_file_reports_reason(self):
        broken = Path(self.directory.name) / "broken.bvh"
        broken.write_text("HIERARCHY\nMOTION\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            motion_preview.sketch(broken)


if __name__ == "__main__":
    unittest.main()
