"""Build-time display-coordinate checks; no automatic visual approval.

Matplotlib is imported only by the rendering entrypoints. Geometry helpers remain
usable without it. Results belong in the existing chart-manifest/selfcheck.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile


def rectangle_segment_intersects(rect, start, end, padding=0):
    """Inclusive Liang-Barsky intersection, including corners and zero-length paths."""
    left, bottom, right, top = rect
    left, bottom, right, top = left-padding, bottom-padding, right+padding, top+padding
    x, y = start
    dx, dy = end[0]-x, end[1]-y
    lo, hi = 0.0, 1.0
    for p, q in ((-dx, x-left), (dx, right-x), (-dy, y-bottom), (dy, top-y)):
        if p == 0:
            if q < 0:
                return False
        else:
            ratio = q/p
            if p < 0:
                lo = max(lo, ratio)
            else:
                hi = min(hi, ratio)
            if lo > hi:
                return False
    return True


def rectangles_intersect(first, second, padding=0):
    return (first[0]-padding <= second[2] and first[2]+padding >= second[0]
            and first[1]-padding <= second[3] and first[3]+padding >= second[1])


def _segments(path):
    """Flatten the actual display path, retaining step corners and path breaks."""
    last = first = None
    for values, code in path.iter_segments(curves=False, simplify=False):
        if code == 1:  # MOVETO
            last = first = tuple(values[-2:])
        elif code == 79:  # CLOSEPOLY
            if last is not None and first is not None:
                yield last, first
            last = first
        elif code == 2:  # LINETO; curves=False already flattened curves
            point = tuple(values[-2:])
            if last is not None and all(math.isfinite(v) for v in (*last, *point)):
                yield last, point
            last = point


def _box(artist, renderer):
    from matplotlib.text import Text
    # Annotation.get_window_extent also includes its arrow. Check TEXT bounds;
    # an intentional arrow leading back to a data point is not text covering it.
    return tuple(float(v) for v in Text.get_window_extent(artist, renderer).extents)


def _digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            result.update(block)
    return result.hexdigest()


def check_figure_layout(figure, annotations=None, padding_px=2):
    """Draw now, then check manual text against visible data edges and other text.

    Default targets are axes/figure manual texts, including Annotation objects;
    ticks/axis names/legend text are obstacles. Filled interiors are not obstacles,
    so counts centered in heatmap cells are allowed. Arbitrary raster content and
    unsupported collections require actual review. Bounding boxes and conservative
    marker circles can produce false positives; known overlaps must be resolved.
    """
    try:
        from matplotlib.collections import LineCollection, PathCollection, QuadMesh
        from matplotlib.text import Text
    except ImportError:
        return {'schema_version': 1, 'geometry_status': 'unavailable',
                'collisions': [], 'unsupported': ['Matplotlib unavailable'],
                'visual_verified': False}
    if not math.isfinite(padding_px) or padding_px < 0:
        raise ValueError('padding_px must be finite and nonnegative')
    figure.canvas.draw()
    try:
        renderer = figure.canvas.get_renderer()
    except AttributeError:
        return {'schema_version': 1, 'geometry_status': 'unavailable',
                'collisions': [], 'unsupported': ['Canvas has no raster renderer'],
                'visual_verified': False}
    targets = list(annotations) if annotations is not None else [
        text for axes in figure.axes for text in axes.texts] + list(figure.texts)
    if any(not isinstance(text, Text) or text.figure is not figure for text in targets):
        raise ValueError('Every annotation must be a Text in this figure')
    targets = [text for text in targets if text.get_visible() and text.get_text()]
    boxes = [(text, _box(text, renderer)) for text in targets]
    all_text = [(text, _box(text, renderer)) for text in figure.findobj(Text)
                if text.get_visible() and text.get_text() and text.figure is figure]
    edges, markers, unsupported = [], [], []
    for ai, axes in enumerate(figure.axes):
        if not axes.get_visible():
            continue
        for li, line in enumerate(axes.lines):
            if not line.get_visible() or line.get_alpha() == 0:
                continue
            if line.get_linestyle() not in ('None', 'none', '', ' ') and line.get_linewidth() > 0:
                path = line.get_transform().transform_path(line.get_path())
                edges.extend(('line', f'{ai}:{li}', start, end,
                              line.get_linewidth()*figure.dpi/144) for start, end in _segments(path))
            if line.get_marker() not in ('None', 'none', '', ' ') and line.get_markersize() > 0:
                # A enclosing circle conservatively includes square/diamond corners.
                radius = line.get_markersize()*figure.dpi/144*math.sqrt(2)
                for x, y in line.get_transform().transform(line.get_xydata()):
                    if math.isfinite(x) and math.isfinite(y):
                        markers.append(('marker', f'{ai}:{li}', float(x), float(y), radius))
        for pi, patch in enumerate(axes.patches):
            if patch.get_visible() and patch.get_alpha() != 0:
                path = patch.get_transform().transform_path(patch.get_path())
                edges.extend(('patch-edge', f'{ai}:{pi}', start, end,
                              patch.get_linewidth()*figure.dpi/144) for start, end in _segments(path))
        for name, spine in axes.spines.items():
            if spine.get_visible() and spine.get_linewidth() > 0:
                path = spine.get_transform().transform_path(spine.get_path())
                edges.extend(('spine', f'{ai}:{name}', start, end,
                              spine.get_linewidth()*figure.dpi/144) for start, end in _segments(path))
        for ci, collection in enumerate(axes.collections):
            if not collection.get_visible() or collection.get_alpha() == 0:
                continue
            if isinstance(collection, PathCollection):
                offsets = collection.get_offset_transform().transform(collection.get_offsets())
                sizes = collection.get_sizes()
                if not len(sizes):
                    unsupported.append(f'axes {ai} collection {ci}: unscaled path collection')
                    continue
                paths = collection.get_paths()
                extent = max((math.hypot(x, y) for path in paths for x, y in path.vertices), default=1)
                for index, (x, y) in enumerate(offsets):
                    radius = extent*math.sqrt(sizes[index % len(sizes)])*figure.dpi/72
                    if math.isfinite(x) and math.isfinite(y):
                        markers.append(('scatter-marker', f'{ai}:{ci}', float(x), float(y), radius))
                if not collection.get_transform().is_affine or not collection.get_transform().get_matrix().tolist() == [[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]]:
                    unsupported.append(f'axes {ai} collection {ci}: custom marker transform')
            elif isinstance(collection, LineCollection):
                if len(collection.get_offsets()) > 1:
                    unsupported.append(f'axes {ai} collection {ci}: offset line collection')
                    continue
                for path in collection.get_paths():
                    display = collection.get_transform().transform_path(path)
                    edges.extend(('collection-edge', f'{ai}:{ci}', start, end, 0)
                                 for start, end in _segments(display))
            elif isinstance(collection, QuadMesh):
                # Intentional matrix counts may sit inside filled cells; only edges count.
                colors = collection.get_edgecolors()
                if len(colors) and any(color[3] > 0 for color in colors):
                    for path in collection.get_paths():
                        display = collection.get_transform().transform_path(path)
                        edges.extend(('matrix-edge', f'{ai}:{ci}', start, end, 0)
                                     for start, end in _segments(display))
            else:
                unsupported.append(f'axes {ai} collection {ci}: {type(collection).__name__}')
        # Raster images may contain plotted lines/text that no vector path exposes.
        if axes.images:
            unsupported.append(f'axes {ai}: raster image content needs actual review')
        if getattr(axes, 'name', '') == '3d':
            unsupported.append(f'axes {ai}: 3D projection needs actual review')
    collisions = []
    for ti, (text, rect) in enumerate(boxes):
        record = {'annotation': ti, 'text': text.get_text(), 'bbox': list(rect)}
        if not all(math.isfinite(v) for v in rect):
            collisions.append(dict(record, kind='invalid-text-bounds'))
            continue
        frame = tuple(figure.bbox.extents)
        if rect[0] < frame[0] or rect[1] < frame[1] or rect[2] > frame[2] or rect[3] > frame[3]:
            collisions.append(dict(record, kind='figure-clipping'))
        if text.axes is not None and text.get_clip_on():
            frame = tuple(text.axes.bbox.extents)
            if rect[0] < frame[0] or rect[1] < frame[1] or rect[2] > frame[2] or rect[3] > frame[3]:
                collisions.append(dict(record, kind='axes-clipping'))
        for kind, identifier, start, end, stroke in edges:
            if rectangle_segment_intersects(rect, start, end, padding_px+stroke):
                collisions.append(dict(record, kind=kind, obstacle=identifier))
                break
        for kind, identifier, x, y, radius in markers:
            nearest_x, nearest_y = min(max(x, rect[0]), rect[2]), min(max(y, rect[1]), rect[3])
            if math.hypot(x-nearest_x, y-nearest_y) <= radius+padding_px:
                collisions.append(dict(record, kind=kind, obstacle=identifier))
                break
        for other, other_rect in all_text:
            if other is not text and rectangles_intersect(rect, other_rect, padding_px):
                collisions.append(dict(record, kind='text', obstacle=other.get_text()))
                break
    layout = {'texts': [(text.get_text(), rect) for text, rect in boxes],
              'edges': edges, 'markers': markers, 'unsupported': unsupported,
              'dpi': float(figure.dpi), 'size': [float(v) for v in figure.get_size_inches()],
              'padding_px': padding_px}
    return {'schema_version': 1,
            'geometry_status': 'fail' if collisions else ('review_required' if unsupported else 'pass'),
            'collisions': collisions, 'unsupported': unsupported,
            'dpi': float(figure.dpi), 'figure_size_inches': layout['size'],
            'layout_sha256': hashlib.sha256(json.dumps(layout, sort_keys=True).encode()).hexdigest(),
            'visual_verified': False}


def save_checked_figure(figure, png, final_width_mm, annotations=None, padding_px=2):
    """Save at planned Word width after fresh checks; return current hash evidence.

    Does not move labels, shrink fonts, cover data, or alter values. Unsupported
    content is reported for high's actual visual selfcheck; known conflicts raise.
    The caller merges this result and the actual PNG review into its manifest.
    """
    if not math.isfinite(final_width_mm) or final_width_mm <= 0:
        raise ValueError('final_width_mm must be finite and positive')
    png = Path(png)
    if png.suffix.lower() != '.png':
        raise ValueError('Checked figure output must be PNG')
    width, height = figure.get_size_inches()
    figure.set_size_inches(final_width_mm/25.4, height/width*final_width_mm/25.4)
    if figure.dpi < 300:
        figure.set_dpi(300)
    before = check_figure_layout(figure, annotations, padding_px)
    if before['geometry_status'] in ('fail', 'unavailable'):
        raise ValueError('Figure cannot be submitted: '+before['geometry_status']+' '+str(before['collisions']))
    temp_dir = os.environ.get('TMPDIR') or os.environ.get('TEMP')
    if not temp_dir:
        raise ValueError('Load Enter-Environment.ps1 before saving checked figures')
    with tempfile.TemporaryDirectory(prefix='figure-preflight-', dir=temp_dir) as directory:
        temporary = Path(directory)/'current.png'
        figure.savefig(temporary, format='png', dpi=figure.dpi, bbox_inches=None)
        after = check_figure_layout(figure, annotations, padding_px)
        if after['geometry_status'] == 'fail' or after.get('layout_sha256') != before['layout_sha256']:
            raise ValueError('Layout changed while saving; redraw and check again')
        png.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(temporary, png)
    after.update(final_width_mm=float(final_width_mm), png_sha256=_digest(png))
    return after
