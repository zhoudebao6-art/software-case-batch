from pathlib import Path
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from figure_preflight import (check_figure_layout, rectangle_segment_intersects,
                              rectangles_intersect, save_checked_figure)

try:
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
except ImportError:
    plt = None


class GeometryTests(unittest.TestCase):
    def test_segment_corner_and_zero_length(self):
        self.assertTrue(rectangle_segment_intersects((1, 1, 2, 2), (0, 0), (1, 1)))
        self.assertTrue(rectangle_segment_intersects((1, 1, 2, 2), (1.5, 1.5), (1.5, 1.5)))
        self.assertFalse(rectangle_segment_intersects((1, 1, 2, 2), (0, 0), (0, 3)))
        self.assertTrue(rectangle_segment_intersects((1, 1, 2, 2), (0.9, 0), (0.9, 3), .2))

    def test_rectangles_respect_padding(self):
        self.assertFalse(rectangles_intersect((0, 0, 1, 1), (1.2, 0, 2, 1)))
        self.assertTrue(rectangles_intersect((0, 0, 1, 1), (1.2, 0, 2, 1), .3))


@unittest.skipIf(plt is None, 'Matplotlib raster checks unavailable; geometry tests still run')
class RenderedFigureTests(unittest.TestCase):
    def setUp(self):
        self.fig, self.ax = plt.subplots(figsize=(6.3, 3.8), dpi=100)
        self.ax.set_xlim(0, 3)
        self.ax.set_ylim(0, 3)

    def tearDown(self):
        plt.close(self.fig)

    def kinds(self, result):
        return {entry['kind'] for entry in result['collisions']}

    def test_actual_diagonal_line_collision(self):
        self.ax.plot([0, 3], [0, 3])
        self.ax.text(1.5, 1.5, '450', ha='center', va='center')
        result = check_figure_layout(self.fig)
        self.assertEqual(result['geometry_status'], 'fail')
        self.assertIn('line', self.kinds(result))
        self.assertFalse(result['visual_verified'])

    def test_actual_step_corner_and_vertical_segment(self):
        self.ax.step([0, 1, 2], [2, 1, 1], where='post', linestyle='--')
        label = self.ax.text(1, 1.5, '450', ha='center', va='center')
        result = check_figure_layout(self.fig)
        self.assertIn('line', self.kinds(result))
        label.set_position((1.4, 2.5))
        clean = check_figure_layout(self.fig)
        self.assertEqual(clean['geometry_status'], 'pass')
        self.assertNotEqual(result['layout_sha256'], clean['layout_sha256'])

    def test_actual_bottom_spine_collision(self):
        self.ax.text(1.5, 0, '400', ha='center', va='center')
        self.assertIn('spine', self.kinds(check_figure_layout(self.fig)))

    def test_annotation_arrow_is_not_mistaken_for_text_bounds(self):
        self.ax.plot([0, 3], [1, 1])
        self.ax.annotate('450', xy=(1.5, 1), xytext=(1.5, 2.5),
                         ha='center', arrowprops={'arrowstyle': '->'})
        self.assertEqual(check_figure_layout(self.fig)['geometry_status'], 'pass')

    def test_fully_transparent_artist_is_not_a_visible_data_collision(self):
        self.ax.plot([0, 3], [1, 1], alpha=0)
        self.ax.text(1.5, 1, '450', ha='center', va='center')
        self.assertEqual(check_figure_layout(self.fig)['geometry_status'], 'pass')

    def test_actual_marker_and_bar_edge_collision(self):
        self.ax.plot([1], [1], marker='o', markersize=20, linestyle='None')
        self.ax.text(1, 1, '12', ha='center', va='center')
        self.assertIn('marker', self.kinds(check_figure_layout(self.fig)))
        self.ax.clear()
        self.ax.set_xlim(0, 3)
        self.ax.set_ylim(0, 3)
        self.ax.bar([1], [2], width=.8)
        self.ax.text(1, 2, '12', ha='center', va='center')
        self.assertIn('patch-edge', self.kinds(check_figure_layout(self.fig)))

    def test_actual_scatter_marker_collision(self):
        self.ax.scatter([1], [1], s=300)
        self.ax.text(1, 1, '12', ha='center', va='center')
        self.assertIn('scatter-marker', self.kinds(check_figure_layout(self.fig)))

    def test_current_font_size_is_redrawn(self):
        self.ax.plot([0, 3], [1.8, 1.8])
        label = self.ax.text(1.5, 2.4, '450', fontsize=8, va='center')
        before = check_figure_layout(self.fig)
        self.assertEqual(before['geometry_status'], 'pass')
        label.set_fontsize(120)
        after = check_figure_layout(self.fig)
        self.assertEqual(after['geometry_status'], 'fail')
        self.assertNotEqual(before['layout_sha256'], after['layout_sha256'])

    def test_text_collision_and_figure_clipping(self):
        self.ax.text(1.5, 2, '450', ha='center')
        self.ax.text(1.5, 2, '400', ha='center')
        self.assertIn('text', self.kinds(check_figure_layout(self.fig)))
        self.fig.text(-.02, .5, 'outside', ha='right')
        self.assertIn('figure-clipping', self.kinds(check_figure_layout(self.fig)))

    def test_intentional_matrix_count_not_rejected_for_fill(self):
        self.ax.set_xlim(0, 2)
        self.ax.set_ylim(0, 2)
        self.ax.pcolormesh([[1, 2], [3, 4]], edgecolors='none')
        self.ax.text(.5, .5, '1', ha='center', va='center')
        self.assertEqual(check_figure_layout(self.fig)['geometry_status'], 'pass')

    def test_raster_content_requires_actual_review(self):
        self.ax.imshow([[1, 2], [3, 4]], extent=(0, 3, 0, 3))
        self.assertEqual(check_figure_layout(self.fig)['geometry_status'], 'review_required')

    def test_save_checks_final_width_and_binds_png_hash(self):
        self.ax.plot([0, 3], [1, 1])
        self.ax.text(1.5, 2.5, '450', ha='center')
        with tempfile.TemporaryDirectory(dir=os.environ['TEMP']) as directory:
            png = Path(directory)/'checked.png'
            result = save_checked_figure(self.fig, png, 150)
            self.assertEqual(result['geometry_status'], 'pass')
            self.assertEqual(result['final_width_mm'], 150)
            self.assertEqual(result['dpi'], 300)
            self.assertAlmostEqual(result['figure_size_inches'][0]*25.4, 150)
            self.assertEqual(len(result['png_sha256']), 64)
            self.assertTrue(png.read_bytes().startswith(b'\x89PNG'))
            self.assertFalse(result['visual_verified'])

    def test_save_refuses_known_overlap(self):
        self.ax.step([0, 1, 2], [2, 1, 1], where='post')
        self.ax.text(1, 1.5, '450', ha='center', va='center')
        with tempfile.TemporaryDirectory(dir=os.environ['TEMP']) as directory:
            png = Path(directory)/'bad.png'
            with self.assertRaises(ValueError):
                save_checked_figure(self.fig, png, 150)
            self.assertFalse(png.exists())


if __name__ == '__main__':
    unittest.main()
