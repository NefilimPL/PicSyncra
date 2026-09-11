"""PySide6 prototype for rendering photo slots without Tkinter Canvas widgets."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import argparse
import os
import sys
from pathlib import Path

from . import config, settings
from .common import B, I, SLOT_DEFS_KEY
from .localization import LANG, SLOT_TITLE_FORMAT, get_slot_label
from .slot_utils import normalize_slot_definitions
from .workflow_utils import parse_slot_filename

try:  # pragma: no cover - import availability depends on local environment
    from PySide6.QtCore import (
        QAbstractListModel,
        QModelIndex,
        QPoint,
        QPointF,
        QPropertyAnimation,
        QRect,
        QRectF,
        QSize,
        Qt,
        QTimer,
        QEasingCurve,
    )
    from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
    from PySide6.QtWidgets import (
        QApplication,
        QAbstractScrollArea,
        QAbstractItemView,
        QFrame,
        QLabel,
        QListView,
        QMainWindow,
        QStyle,
        QStyledItemDelegate,
        QVBoxLayout,
        QWidget,
    )
except Exception as exc:  # pragma: no cover - exercised only without PySide6
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None


SLOT_GRID_COLUMNS = 5
SLOT_PREVIEW_SIZE = QSize(240, 176) if QT_IMPORT_ERROR is None else None
SLOT_TILE_SIZE = QSize(268, 246) if QT_IMPORT_ERROR is None else None
THUMBNAIL_MEMORY_ROWS = 10
THUMBNAIL_PREFETCH_BATCH = 2
THUMBNAIL_PREFETCH_INTERVAL_MS = 18
SLOT_WHEEL_STEP_PX = 30
SMOOTH_SCROLL_FRAME_MS = 16
SMOOTH_SCROLL_EASING = 0.28
GRID_SPACING = 8
IMAGE_EXTENSIONS = {
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}


@dataclass(frozen=True)
class QtSlotItem:
    """Data needed to render one photo slot in the Qt prototype."""

    prefix: str
    label: str
    path: str = B
    source: str = B
    status: str = B


def _image_files(root_dir: str, limit: int) -> list[str]:
    """Return up to ``limit`` image paths from ``root_dir`` without indexing all files."""

    if not root_dir or limit <= 0 or not os.path.isdir(root_dir):
        return []
    paths: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [name for name in dirnames if not name.startswith(".")]
        for filename in filenames:
            if Path(filename).suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            paths.append(os.path.join(dirpath, filename))
            if len(paths) >= limit:
                return paths
    return paths


def assign_sample_paths_to_slots(
    slot_defs: list[dict[str, str]],
    sample_paths: list[str],
) -> list[QtSlotItem]:
    """Map sample image paths to slot definitions for the standalone preview."""

    by_prefix: dict[str, str] = {}
    sequential_paths: list[str] = []
    for path in sample_paths:
        parsed = parse_slot_filename(os.path.basename(path))
        if parsed and parsed.normalized_label not in by_prefix:
            by_prefix[parsed.normalized_label] = path
            continue
        sequential_paths.append(path)

    sequential_iter = iter(sequential_paths)
    items: list[QtSlotItem] = []
    for slot in slot_defs:
        prefix = str(slot.get("prefix") or B).strip()
        label = str(slot.get("label") or B).strip()
        path = by_prefix.get(prefix, B)
        if not path:
            path = next(sequential_iter, B)
        items.append(
            QtSlotItem(
                prefix=prefix,
                label=label,
                path=path,
                source="LOCAL" if path else B,
                status=LANG.get("slot_status_ready", "Gotowe")
                if path
                else LANG.get("no_file_label", "Brak pliku"),
            )
        )
    return items


def load_preview_items(sample_dir: str | None = None) -> list[QtSlotItem]:
    """Load configured slot definitions and optional sample images for preview."""

    slot_defs, _issues = normalize_slot_definitions(
        config.CONFIG.get(SLOT_DEFS_KEY)
    )
    root = sample_dir if sample_dir is not None else settings.l
    sample_paths = _image_files(root, limit=len(slot_defs))
    return assign_sample_paths_to_slots(slot_defs, sample_paths)


if QT_IMPORT_ERROR is None:

    class ThumbnailCache:
        """Small LRU cache of scaled QPixmaps around the visible slot area."""

        def __init__(self, limit: int):
            self.limit = max(1, int(limit))
            self._items: OrderedDict[tuple[str, int | None, int | None], QPixmap] = (
                OrderedDict()
            )
            self._path_keys: dict[str, tuple[str, int | None, int | None]] = {}
            self._missing_paths: set[str] = set()

        def _key(self, path: str):
            abspath = os.path.abspath(path)
            cached = self._path_keys.get(abspath)
            if cached is not None:
                return cached
            try:
                stat = os.stat(path)
                key = (abspath, stat.st_mtime_ns, stat.st_size)
            except OSError:
                key = (abspath, None, None)
            self._path_keys[abspath] = key
            return key

        def peek(self, path: str) -> QPixmap:
            """Return a cached pixmap without doing filesystem or decode work."""

            if not path:
                return QPixmap()
            abspath = os.path.abspath(path)
            key = self._path_keys.get(abspath)
            if key is None:
                return QPixmap()
            pixmap = self._items.get(key)
            if pixmap is None:
                return QPixmap()
            self._items.move_to_end(key)
            return pixmap

        def needs_load(self, path: str) -> bool:
            """Return whether loading ``path`` would add a new pixmap to cache."""

            if not path:
                return False
            abspath = os.path.abspath(path)
            if abspath in self._missing_paths:
                return False
            key = self._path_keys.get(abspath)
            return key is None or key not in self._items

        def get(self, path: str, target_size: QSize) -> QPixmap:
            if not path:
                return QPixmap()
            abspath = os.path.abspath(path)
            if abspath in self._missing_paths:
                return QPixmap()
            key = self._key(path)
            pixmap = self._items.get(key)
            if pixmap is not None:
                self._items.move_to_end(key)
                return pixmap
            pixmap = QPixmap(path)
            if pixmap.isNull():
                self._missing_paths.add(abspath)
                return QPixmap()
            pixmap = pixmap.scaled(
                target_size,
                Qt.KeepAspectRatio,
                Qt.FastTransformation,
            )
            self._items[key] = pixmap
            self._items.move_to_end(key)
            while len(self._items) > self.limit:
                self._items.popitem(last=False)
            return pixmap

        def prefetch(self, paths: list[str], target_size: QSize) -> None:
            for path in paths:
                self.get(path, target_size)


    class SlotListModel(QAbstractListModel):
        """Qt model exposing photo slot records to a QListView."""

        SlotRole = Qt.UserRole + 1

        def __init__(self, items: list[QtSlotItem]):
            super().__init__()
            self._items = list(items)

        def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
            if parent.isValid():
                return 0
            return len(self._items)

        def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
            if not index.isValid():
                return None
            try:
                item = self._items[index.row()]
            except IndexError:
                return None
            if role == self.SlotRole:
                return item
            if role == Qt.DisplayRole:
                return SLOT_TITLE_FORMAT.format(
                    index=item.prefix,
                    label=get_slot_label(item.label),
                )
            return None

        def item_at(self, row: int) -> QtSlotItem | None:
            if 0 <= row < len(self._items):
                return self._items[row]
            return None


    class SlotDelegate(QStyledItemDelegate):
        """Paint one slot tile directly instead of composing nested widgets."""

        def __init__(self, cache: ThumbnailCache, parent=None):
            super().__init__(parent)
            self.cache = cache

        def sizeHint(self, option, index):
            return SLOT_TILE_SIZE

        def paint(self, painter: QPainter, option, index):
            item = index.data(SlotListModel.SlotRole)
            if not isinstance(item, QtSlotItem):
                return

            painter.save()
            rect = option.rect.adjusted(4, 4, -4, -4)
            selected = bool(option.state & QStyle.State_Selected)
            border = QColor("#2f6f7b") if selected else QColor("#c7d2cf")
            painter.setRenderHint(QPainter.Antialiasing, False)
            painter.fillRect(rect, QColor("#ffffff"))
            painter.setPen(QPen(border, 1))
            painter.drawRect(rect)

            title_rect = QRect(rect.left() + 10, rect.top() + 8, rect.width() - 20, 24)
            title_font = QFont("Segoe UI", 9)
            title_font.setBold(True)
            painter.setFont(title_font)
            painter.setPen(QColor("#17323b"))
            title = SLOT_TITLE_FORMAT.format(
                index=item.prefix,
                label=get_slot_label(item.label),
            )
            painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, title)

            preview = QRect(
                rect.left() + 10,
                title_rect.bottom() + 8,
                rect.width() - 20,
                SLOT_PREVIEW_SIZE.height(),
            )
            painter.fillRect(preview, QColor("#edf2ef"))
            painter.setPen(QPen(QColor("#c7d2cf"), 1))
            painter.drawRect(preview)

            pixmap = self.cache.peek(item.path)
            if pixmap.isNull():
                placeholder = LANG.get(
                    "slot_drop_hint",
                    "Przeciagnij plik tutaj\nlub kliknij Wybierz",
                )
                painter.setFont(QFont("Segoe UI", 9))
                painter.setPen(QColor("#36525a"))
                painter.drawText(preview, Qt.AlignCenter | Qt.TextWordWrap, placeholder)
            else:
                x = preview.left() + (preview.width() - pixmap.width()) // 2
                y = preview.top() + (preview.height() - pixmap.height()) // 2
                painter.drawPixmap(x, y, pixmap)

            footer = QRect(
                rect.left() + 10,
                preview.bottom() + 6,
                rect.width() - 20,
                22,
            )
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QColor("#5c6f75"))
            painter.drawText(footer, Qt.AlignLeft | Qt.AlignVCenter, item.status)
            if item.source:
                badge = QRect(footer.right() - 48, footer.top() + 1, 46, 18)
                painter.fillRect(badge, QColor("#17323b"))
                painter.setPen(QColor("#ffffff"))
                painter.drawText(badge, Qt.AlignCenter, item.source)
            painter.restore()


    class SmoothSlotListView(QListView):
        """QListView with small pixel-based wheel steps for slot grids."""

        def __init__(self, parent=None):
            super().__init__(parent)
            self._wheel_remainder = 0.0
            self._scroll_target = 0.0
            self._scroll_animation = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
            self._scroll_animation.setDuration(130)
            self._scroll_animation.setEasingCurve(QEasingCurve.OutCubic)

        def _clamp_scroll_target(self, value: float) -> float:
            bar = self.verticalScrollBar()
            return float(max(bar.minimum(), min(bar.maximum(), int(round(value)))))

        def resizeEvent(self, event):
            super().resizeEvent(event)
            self._scroll_target = self._clamp_scroll_target(self.verticalScrollBar().value())

        def wheelEvent(self, event):
            bar = self.verticalScrollBar()
            pixel_delta = event.pixelDelta().y()
            if pixel_delta:
                delta_px = -float(pixel_delta)
            else:
                angle_delta = event.angleDelta().y()
                if not angle_delta:
                    event.ignore()
                    return
                delta_px = -(float(angle_delta) / 120.0) * SLOT_WHEEL_STEP_PX
            self._wheel_remainder += delta_px
            whole_delta = int(self._wheel_remainder)
            if whole_delta:
                self._wheel_remainder -= whole_delta
                if self._scroll_animation.state() != QPropertyAnimation.Running:
                    self._scroll_target = float(bar.value())
                self._scroll_target = self._clamp_scroll_target(
                    self._scroll_target + whole_delta
                )
                self._scroll_animation.stop()
                self._scroll_animation.setStartValue(bar.value())
                self._scroll_animation.setEndValue(int(round(self._scroll_target)))
                self._scroll_animation.start()
            event.accept()


    class SmoothSlotGridArea(QAbstractScrollArea):
        """Manually painted slot grid with float-offset smooth scrolling."""

        def __init__(self, items: list[QtSlotItem], cache: ThumbnailCache, parent=None):
            super().__init__(parent)
            self.items = list(items)
            self.cache = cache
            self._offset = 0.0
            self._target_offset = 0.0
            self._syncing_scrollbar = False
            self._prefetch_queue: list[str] = []
            self._scroll_timer = QTimer(self)
            self._scroll_timer.setInterval(SMOOTH_SCROLL_FRAME_MS)
            self._scroll_timer.timeout.connect(self._scroll_tick)
            self._prefetch_timer = QTimer(self)
            self._prefetch_timer.setInterval(THUMBNAIL_PREFETCH_INTERVAL_MS)
            self._prefetch_timer.timeout.connect(self._prefetch_tick)
            self._title_font = QFont("Segoe UI", 9)
            self._title_font.setBold(True)
            self._body_font = QFont("Segoe UI", 9)
            self._footer_font = QFont("Segoe UI", 8)
            self._background_color = QColor("#f7faf8")
            self._tile_color = QColor("#ffffff")
            self._border_pen = QPen(QColor("#c7d2cf"), 1)
            self._title_color = QColor("#17323b")
            self._preview_color = QColor("#edf2ef")
            self._placeholder_color = QColor("#36525a")
            self._footer_color = QColor("#5c6f75")
            self._badge_color = QColor("#17323b")
            self._badge_text_color = QColor("#ffffff")
            self.setFrameShape(QFrame.NoFrame)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.verticalScrollBar().setSingleStep(SLOT_WHEEL_STEP_PX)
            self.verticalScrollBar().valueChanged.connect(self._scrollbar_changed)
            self.viewport().setAttribute(Qt.WA_OpaquePaintEvent, True)
            self.viewport().setAttribute(Qt.WA_StaticContents, True)
            QTimer.singleShot(0, self._after_first_layout)

        def slot_count(self) -> int:
            return len(self.items)

        def _after_first_layout(self) -> None:
            self._update_scrollbar()
            self._prefetch_around(self._offset, immediate=True)
            self.viewport().update()

        def _columns(self) -> int:
            pitch = SLOT_TILE_SIZE.width() + GRID_SPACING
            width = max(1, self.viewport().width() - GRID_SPACING)
            return max(1, width // max(1, pitch))

        def _row_pitch(self) -> int:
            return SLOT_TILE_SIZE.height() + GRID_SPACING

        def _row_count(self) -> int:
            columns = self._columns()
            return (len(self.items) + columns - 1) // columns

        def _content_height(self) -> int:
            rows = self._row_count()
            if rows <= 0:
                return 0
            return GRID_SPACING + rows * self._row_pitch()

        def _max_offset(self) -> float:
            return float(max(0, self._content_height() - self.viewport().height()))

        def _clamp_offset(self, value: float) -> float:
            return max(0.0, min(self._max_offset(), float(value)))

        def _update_scrollbar(self) -> None:
            bar = self.verticalScrollBar()
            max_offset = int(round(self._max_offset()))
            self._syncing_scrollbar = True
            try:
                bar.setPageStep(max(1, self.viewport().height()))
                bar.setRange(0, max_offset)
                bar.setValue(int(round(self._offset)))
            finally:
                self._syncing_scrollbar = False

        def resizeEvent(self, event):
            super().resizeEvent(event)
            self._offset = self._clamp_offset(self._offset)
            self._target_offset = self._clamp_offset(self._target_offset)
            self._update_scrollbar()
            self._prefetch_around(self._offset)

        def _scrollbar_changed(self, value: int) -> None:
            if self._syncing_scrollbar:
                return
            self._scroll_timer.stop()
            self._offset = self._clamp_offset(float(value))
            self._target_offset = self._offset
            self._prefetch_around(self._offset, immediate=True)
            self.viewport().update()

        def wheelEvent(self, event):
            pixel_delta = event.pixelDelta().y()
            if pixel_delta:
                delta_px = -float(pixel_delta)
            else:
                angle_delta = event.angleDelta().y()
                if not angle_delta:
                    event.ignore()
                    return
                delta_px = -(float(angle_delta) / 120.0) * SLOT_WHEEL_STEP_PX
            self._target_offset = self._clamp_offset(self._target_offset + delta_px)
            if not self._scroll_timer.isActive():
                self._scroll_timer.start()
            event.accept()

        def _scroll_tick(self) -> None:
            old_display_offset = int(round(self._offset))
            distance = self._target_offset - self._offset
            if abs(distance) < 0.35:
                self._offset = self._target_offset
                self._scroll_timer.stop()
                self._prefetch_around(self._offset)
            else:
                self._offset += distance * SMOOTH_SCROLL_EASING
            self._syncing_scrollbar = True
            try:
                self.verticalScrollBar().setValue(int(round(self._offset)))
            finally:
                self._syncing_scrollbar = False
            if int(round(self._offset)) != old_display_offset:
                self.viewport().update()

        def _visible_row_bounds(self, offset: float) -> tuple[int, int]:
            row_pitch = max(1, self._row_pitch())
            visible_first = max(0, int(offset // row_pitch))
            visible_last = int((offset + self.viewport().height()) // row_pitch)
            visible_rows = max(1, visible_last - visible_first + 1)
            extra_rows = max(0, THUMBNAIL_MEMORY_ROWS - visible_rows)
            first = max(0, visible_first - min(2, extra_rows))
            last = first + THUMBNAIL_MEMORY_ROWS - 1
            return first, min(max(0, self._row_count() - 1), last)

        def _prefetch_around(self, offset: float, immediate: bool = False) -> None:
            if not self.items:
                return
            columns = self._columns()
            first_row, last_row = self._visible_row_bounds(offset)
            paths = []
            for row in range(first_row, last_row + 1):
                for column in range(columns):
                    idx = row * columns + column
                    if idx >= len(self.items):
                        break
                    path = self.items[idx].path
                    if path:
                        paths.append(path)
            if immediate:
                self.cache.prefetch(paths, SLOT_PREVIEW_SIZE)
                return
            self._queue_prefetch(paths)

        def _queue_prefetch(self, paths: list[str]) -> None:
            queued = set(self._prefetch_queue)
            for path in paths:
                if path in queued or not self.cache.needs_load(path):
                    continue
                self._prefetch_queue.append(path)
                queued.add(path)
            if self._prefetch_queue and not self._prefetch_timer.isActive():
                self._prefetch_timer.start()

        def _prefetch_tick(self) -> None:
            loaded = False
            for _ in range(THUMBNAIL_PREFETCH_BATCH):
                if not self._prefetch_queue:
                    break
                path = self._prefetch_queue.pop(0)
                if not self.cache.needs_load(path):
                    continue
                self.cache.get(path, SLOT_PREVIEW_SIZE)
                loaded = True
            if not self._prefetch_queue:
                self._prefetch_timer.stop()
            if loaded and not self._scroll_timer.isActive():
                self.viewport().update()

        def paintEvent(self, event):
            painter = QPainter(self.viewport())
            painter.fillRect(self.viewport().rect(), self._background_color)
            if not self.items:
                return
            columns = self._columns()
            row_pitch = self._row_pitch()
            display_offset = int(round(self._offset))
            first_row = max(0, int(display_offset // row_pitch) - 1)
            last_row = min(
                self._row_count() - 1,
                int((display_offset + self.viewport().height()) // row_pitch) + 1,
            )
            for row in range(first_row, last_row + 1):
                y = GRID_SPACING + row * row_pitch - display_offset
                for column in range(columns):
                    idx = row * columns + column
                    if idx >= len(self.items):
                        break
                    x = GRID_SPACING + column * (SLOT_TILE_SIZE.width() + GRID_SPACING)
                    rect = QRectF(
                        float(x),
                        float(y),
                        float(SLOT_TILE_SIZE.width()),
                        float(SLOT_TILE_SIZE.height()),
                    )
                    if rect.bottom() < 0 or rect.top() > self.viewport().height():
                        continue
                    self._paint_slot(painter, rect, self.items[idx])

        def _paint_slot(self, painter: QPainter, rect: QRectF, item: QtSlotItem) -> None:
            tile = rect.adjusted(4, 4, -4, -4)
            painter.fillRect(tile, self._tile_color)
            painter.setPen(self._border_pen)
            painter.drawRect(tile)

            title_rect = QRectF(tile.left() + 10, tile.top() + 8, tile.width() - 20, 24)
            painter.setFont(self._title_font)
            painter.setPen(self._title_color)
            title = SLOT_TITLE_FORMAT.format(
                index=item.prefix,
                label=get_slot_label(item.label),
            )
            painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, title)

            preview = QRectF(
                tile.left() + 10,
                title_rect.bottom() + 8,
                tile.width() - 20,
                SLOT_PREVIEW_SIZE.height(),
            )
            painter.fillRect(preview, self._preview_color)
            painter.setPen(self._border_pen)
            painter.drawRect(preview)

            pixmap = self.cache.peek(item.path)
            if pixmap.isNull():
                placeholder = LANG.get(
                    "slot_drop_hint",
                    "Przeciagnij plik tutaj\nlub kliknij Wybierz",
                )
                painter.setFont(self._body_font)
                painter.setPen(self._placeholder_color)
                painter.drawText(preview, Qt.AlignCenter | Qt.TextWordWrap, placeholder)
            else:
                x = preview.left() + (preview.width() - pixmap.width()) / 2.0
                y = preview.top() + (preview.height() - pixmap.height()) / 2.0
                painter.drawPixmap(QPointF(x, y), pixmap)

            footer = QRectF(
                tile.left() + 10,
                preview.bottom() + 6,
                tile.width() - 20,
                22,
            )
            painter.setFont(self._footer_font)
            painter.setPen(self._footer_color)
            painter.drawText(footer, Qt.AlignLeft | Qt.AlignVCenter, item.status)
            if item.source:
                badge = QRectF(footer.right() - 48, footer.top() + 1, 46, 18)
                painter.fillRect(badge, self._badge_color)
                painter.setPen(self._badge_text_color)
                painter.drawText(badge, Qt.AlignCenter, item.source)


    class SlotPreviewWindow(QMainWindow):
        """Standalone Qt window used to validate slot scrolling performance."""

        def __init__(self, items: list[QtSlotItem], sample_dir: str | None = None):
            super().__init__()
            self.setWindowTitle("PicSyncra - Qt slot preview")
            self.resize(1380, 860)
            self._cache = ThumbnailCache(SLOT_GRID_COLUMNS * THUMBNAIL_MEMORY_ROWS)
            self._items = list(items)
            initial_paths = [
                item.path
                for item in self._items[: SLOT_GRID_COLUMNS * THUMBNAIL_MEMORY_ROWS]
                if item.path
            ]
            self._cache.prefetch(initial_paths, SLOT_PREVIEW_SIZE)

            root = QWidget(self)
            layout = QVBoxLayout(root)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(8)

            subtitle = sample_dir or settings.l
            header = QLabel(
                f"Sloty zdjec - Qt prototype ({len(items)} slotow)   |   {subtitle}"
            )
            header.setFrameShape(QFrame.NoFrame)
            header.setStyleSheet(
                "font: 600 10pt 'Segoe UI'; color: #17323b; padding: 2px 0;"
            )
            layout.addWidget(header)

            self.view = SmoothSlotGridArea(self._items, self._cache, root)
            self.view.verticalScrollBar().setSingleStep(SLOT_WHEEL_STEP_PX)
            self.view.setStyleSheet(
                "QAbstractScrollArea { background: #f7faf8; border: 0; outline: none; }"
                "QScrollBar:vertical { width: 14px; background: #edf2ef; }"
                "QScrollBar::handle:vertical { background: #a8b2ad; min-height: 40px; }"
            )
            layout.addWidget(self.view, 1)
            self.setCentralWidget(root)


def run_preview(sample_dir: str | None = None) -> int:
    """Run the standalone Qt slot preview window."""

    if QT_IMPORT_ERROR is not None:
        raise ModuleNotFoundError(
            "PySide6 is required for the Qt slot preview. Install it with: pip install PySide6"
        ) from QT_IMPORT_ERROR
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = SlotPreviewWindow(load_preview_items(sample_dir), sample_dir=sample_dir)
    window.show()
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Qt slot scrolling prototype.")
    parser.add_argument(
        "--sample-dir",
        default=None,
        help="Optional directory with images used to fill preview slots.",
    )
    args = parser.parse_args(argv)
    return run_preview(sample_dir=args.sample_dir)


if __name__ == "__main__":  # pragma: no cover - manual launcher
    raise SystemExit(main())
