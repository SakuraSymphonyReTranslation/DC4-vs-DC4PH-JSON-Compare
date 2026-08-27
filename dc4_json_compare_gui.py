import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PyQt6.QtGui import QColor, QFont, QKeySequence, QPalette, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

DEFAULT_ALL_AGE_DIR = r"G:\Games\DC4\translated 13-03\translated"
DEFAULT_PLUS_HARMONY_DIR = r"H:\Games\D.C.4 Da Capo 4 Plus Harmony\indo json\json"
JSON_KEY_LINE_RE = re.compile(r'^"[^"\\]*(?:\\.[^"\\]*)*"\s*:')


@dataclass
class CompareRow:
    index: int
    all_age: str
    plus_harmony: str
    status: str
    has_all_age: bool
    has_plus_harmony: bool


@dataclass
class MessageRef:
    owner: Any
    key: Any

    def get_text(self) -> str:
        value = self.owner[self.key]
        return value if isinstance(value, str) else str(value)

    def set_text(self, text: str) -> None:
        self.owner[self.key] = text


@dataclass
class JsonDocument:
    path: Path
    data: Any
    refs: list[MessageRef]
    encoding: str
    newline: str
    mtime_ns: int
    size: int


class CompareTableModel(QAbstractTableModel):
    COL_INDEX = 0
    COL_ALL_AGE = 1
    COL_COPY_TO_PLUS = 2
    COL_COPY_TO_ALL_AGE = 3
    COL_PLUS = 4
    COL_STATUS = 5

    HEADERS = [
        "Index",
        "All-Age (DC4)",
        "All-Age -> 18+",
        "18+ -> All-Age",
        "Plus Harmony (18+)",
        "Status",
    ]

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[CompareRow] = []
        self.rel_path = ""
        self.on_text_edited: Callable[[str, int, str, str], bool] | None = None

    def set_rows(self, rows: list[CompareRow], rel_path: str) -> None:
        self.beginResetModel()
        self.rows = rows
        self.rel_path = rel_path
        self.endResetModel()

    def set_on_text_edited(self, callback: Callable[[str, int, str, str], bool]) -> None:
        self.on_text_edited = callback

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self.HEADERS)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:  # noqa: N802
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        row = self.rows[index.row()]
        column = index.column()

        flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        if column == self.COL_ALL_AGE and row.has_all_age:
            flags |= Qt.ItemFlag.ItemIsEditable
        if column == self.COL_PLUS and row.has_plus_harmony:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self.HEADERS):
                return self.HEADERS[section]
            return None
        return str(section + 1)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # noqa: N802
        if not index.isValid():
            return None

        row = self.rows[index.row()]
        column = index.column()

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if column == self.COL_INDEX:
                return row.index
            if column == self.COL_ALL_AGE:
                return row.all_age
            if column == self.COL_COPY_TO_PLUS:
                return "Copy ->"
            if column == self.COL_COPY_TO_ALL_AGE:
                return "<- Copy"
            if column == self.COL_PLUS:
                return row.plus_harmony
            if column == self.COL_STATUS:
                return row.status

        if role == Qt.ItemDataRole.ToolTipRole:
            if column == self.COL_COPY_TO_PLUS:
                return "Klik kiri untuk copy baris ini dari All-Age ke 18+"
            if column == self.COL_COPY_TO_ALL_AGE:
                return "Klik kiri untuk copy baris ini dari 18+ ke All-Age"

        if role == Qt.ItemDataRole.BackgroundRole:
            if row.status == "Different":
                return QColor("#fff4cc")
            if row.status == "Missing":
                return QColor("#ffd6d6")

        if role == Qt.ItemDataRole.ForegroundRole:
            # Difference and missing rows use pale backgrounds in both themes,
            # so give every cell an explicit dark foreground for readability.
            if row.status == "Different":
                return QColor("#5c3b00")
            if row.status == "Missing":
                return QColor("#6b0000")
            if column == self.COL_STATUS:
                return QColor("#1d5f1d")

        if role == Qt.ItemDataRole.FontRole and column in (self.COL_COPY_TO_PLUS, self.COL_COPY_TO_ALL_AGE):
            font = QFont()
            font.setBold(True)
            return font

        if role == Qt.ItemDataRole.TextAlignmentRole and column in (
            self.COL_INDEX,
            self.COL_COPY_TO_PLUS,
            self.COL_COPY_TO_ALL_AGE,
            self.COL_STATUS,
        ):
            return int(Qt.AlignmentFlag.AlignCenter)

        return None

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False

        row_idx = index.row()
        column = index.column()

        if column not in (self.COL_ALL_AGE, self.COL_PLUS):
            return False

        row = self.rows[row_idx]
        text = "" if value is None else str(value)

        side = "all_age" if column == self.COL_ALL_AGE else "plus_harmony"
        if self.on_text_edited is not None:
            ok = self.on_text_edited(self.rel_path, row.index, side, text)
            if not ok:
                return False

        if column == self.COL_ALL_AGE:
            row.all_age = text
        else:
            row.plus_harmony = text

        row.status = self._calculate_status(row)

        first_idx = self.index(row_idx, 0)
        last_idx = self.index(row_idx, self.columnCount() - 1)
        self.dataChanged.emit(
            first_idx,
            last_idx,
            [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ForegroundRole, Qt.ItemDataRole.BackgroundRole],
        )
        return True

    def _calculate_status(self, row: CompareRow) -> str:
        if not row.has_all_age or not row.has_plus_harmony:
            return "Missing"
        return "Same" if row.all_age == row.plus_harmony else "Different"


class CompareFilterProxyModel(QSortFilterProxyModel):
    def __init__(self) -> None:
        super().__init__()
        self.only_differences = False
        self.search_text = ""

    def set_only_differences(self, enabled: bool) -> None:
        self.only_differences = enabled
        self.invalidateFilter()

    def set_search_text(self, text: str) -> None:
        self.search_text = text.strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        model = self.sourceModel()
        if not isinstance(model, CompareTableModel):
            return True

        row = model.rows[source_row]

        if self.only_differences and row.status == "Same":
            return False

        if not self.search_text:
            return True

        haystack = f"{row.index} {row.all_age} {row.plus_harmony}".lower()
        return self.search_text in haystack


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DC4 vs DC4 Plus Harmony JSON Compare")
        self.resize(1550, 880)

        self.file_pairs: dict[str, tuple[Path | None, Path | None]] = {}
        self.compare_cache: dict[str, list[CompareRow]] = {}
        self.doc_cache: dict[Path, JsonDocument] = {}

        self.model = CompareTableModel()
        self.model.set_on_text_edited(self.handle_text_edited)
        self.proxy_model = CompareFilterProxyModel()
        self.proxy_model.setSourceModel(self.model)

        self._build_ui()
        self._connect_signals()
        self._setup_shortcuts()
        self.reload_file_index()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)

        path_row_1 = QHBoxLayout()
        path_row_1.addWidget(QLabel("Folder All-Age (DC4):"))
        self.all_age_dir_edit = QLineEdit(DEFAULT_ALL_AGE_DIR)
        self.btn_all_age_browse = QPushButton("Browse")
        path_row_1.addWidget(self.all_age_dir_edit, 1)
        path_row_1.addWidget(self.btn_all_age_browse)

        path_row_2 = QHBoxLayout()
        path_row_2.addWidget(QLabel("Folder Plus Harmony (18+):"))
        self.plus_harmony_dir_edit = QLineEdit(DEFAULT_PLUS_HARMONY_DIR)
        self.btn_plus_browse = QPushButton("Browse")
        path_row_2.addWidget(self.plus_harmony_dir_edit, 1)
        path_row_2.addWidget(self.btn_plus_browse)

        action_row = QHBoxLayout()
        self.btn_reload = QPushButton("Reload File List")
        action_row.addWidget(self.btn_reload)
        action_row.addSpacing(18)

        action_row.addWidget(QLabel("Theme:"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Light", "Dark"])
        action_row.addWidget(self.theme_combo)

        action_row.addSpacing(20)
        action_row.addWidget(QLabel("Search Row Text:"))
        self.row_search_edit = QLineEdit()
        self.row_search_edit.setPlaceholderText("Cari teks di kolom kiri/kanan...")
        action_row.addWidget(self.row_search_edit, 1)

        self.only_diff_checkbox = QCheckBox("Only differences")
        action_row.addWidget(self.only_diff_checkbox)

        replace_row = QHBoxLayout()
        replace_row.addWidget(QLabel("Replace per baris terpilih:"))
        self.btn_copy_left_to_right = QPushButton("All-Age -> 18+")
        self.btn_copy_right_to_left = QPushButton("18+ -> All-Age")
        self.btn_copy_left_to_right.setToolTip("Copy teks baris terpilih dari All-Age ke Plus Harmony (Ctrl+Right)")
        self.btn_copy_right_to_left.setToolTip("Copy teks baris terpilih dari Plus Harmony ke All-Age (Ctrl+Left)")
        replace_row.addWidget(self.btn_copy_left_to_right)
        replace_row.addWidget(self.btn_copy_right_to_left)
        replace_row.addStretch(1)

        self.file_summary_label = QLabel("-")
        self.row_summary_label = QLabel("Pilih file untuk mulai compare")

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.addWidget(QLabel("File JSON"))
        self.file_search_edit = QLineEdit()
        self.file_search_edit.setPlaceholderText("Filter nama file...")
        left_layout.addWidget(self.file_search_edit)

        self.file_list = QListWidget()
        self.file_list.setAlternatingRowColors(True)
        left_layout.addWidget(self.file_list, 1)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.addWidget(QLabel("Side-by-side Compare"))

        self.table = QTableView()
        self.table.setModel(self.proxy_model)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(CompareTableModel.COL_INDEX, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(CompareTableModel.COL_ALL_AGE, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(CompareTableModel.COL_COPY_TO_PLUS, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(CompareTableModel.COL_COPY_TO_ALL_AGE, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(CompareTableModel.COL_PLUS, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(CompareTableModel.COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)

        right_layout.addWidget(self.table, 1)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([420, 1130])

        root_layout.addLayout(path_row_1)
        root_layout.addLayout(path_row_2)
        root_layout.addLayout(action_row)
        root_layout.addLayout(replace_row)
        root_layout.addWidget(self.file_summary_label)
        root_layout.addWidget(splitter, 1)
        root_layout.addWidget(self.row_summary_label)

        self.setCentralWidget(root)
        self.statusBar().showMessage("Siap")

    def _connect_signals(self) -> None:
        self.btn_all_age_browse.clicked.connect(lambda: self.select_directory(self.all_age_dir_edit))
        self.btn_plus_browse.clicked.connect(lambda: self.select_directory(self.plus_harmony_dir_edit))
        self.btn_reload.clicked.connect(self.reload_file_index)
        self.file_list.itemSelectionChanged.connect(self.on_file_selected)
        self.only_diff_checkbox.toggled.connect(self.proxy_model.set_only_differences)
        self.row_search_edit.textChanged.connect(self.proxy_model.set_search_text)
        self.file_search_edit.textChanged.connect(self.filter_file_list)
        self.theme_combo.currentTextChanged.connect(self.apply_theme)
        self.btn_copy_left_to_right.clicked.connect(lambda: self.replace_from_selected_row(from_all_age=True))
        self.btn_copy_right_to_left.clicked.connect(lambda: self.replace_from_selected_row(from_all_age=False))
        self.table.clicked.connect(self.on_table_clicked)

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+Right"), self, activated=lambda: self.replace_from_selected_row(from_all_age=True))
        QShortcut(QKeySequence("Ctrl+Left"), self, activated=lambda: self.replace_from_selected_row(from_all_age=False))

    def select_directory(self, target_edit: QLineEdit) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Pilih folder JSON")
        if selected:
            target_edit.setText(selected)

    def reload_file_index(self) -> None:
        all_age_root = Path(self.all_age_dir_edit.text().strip())
        plus_root = Path(self.plus_harmony_dir_edit.text().strip())

        if not all_age_root.exists() or not plus_root.exists():
            QMessageBox.warning(
                self,
                "Folder Tidak Ditemukan",
                "Pastikan kedua folder JSON valid sebelum reload.",
            )
            return

        all_age_files = self.collect_json_files(all_age_root)
        plus_files = self.collect_json_files(plus_root)

        all_rel_paths = sorted(set(all_age_files.keys()) | set(plus_files.keys()))

        self.file_pairs.clear()
        self.compare_cache.clear()
        self.doc_cache.clear()
        self.file_list.clear()

        match_count = 0
        missing_count = 0

        for rel_path in all_rel_paths:
            left = all_age_files.get(rel_path)
            right = plus_files.get(rel_path)
            self.file_pairs[rel_path] = (left, right)

            prefix = ""
            if left and right:
                match_count += 1
            elif left and not right:
                prefix = "[Missing PH] "
                missing_count += 1
            elif right and not left:
                prefix = "[Missing All-Age] "
                missing_count += 1

            item = QListWidgetItem(f"{prefix}{rel_path}")
            item.setData(Qt.ItemDataRole.UserRole, rel_path)
            self.file_list.addItem(item)

        self.file_summary_label.setText(
            f"Total file: {len(all_rel_paths)} | Bisa dibandingkan: {match_count} | Missing salah satu sisi: {missing_count}"
        )

        if self.file_list.count() > 0:
            self.file_list.setCurrentRow(0)

    def collect_json_files(self, root: Path) -> dict[str, Path]:
        files: dict[str, Path] = {}
        for path in root.rglob("*.json"):
            try:
                rel = path.relative_to(root).as_posix()
                files[rel] = path
            except ValueError:
                continue
        return files

    def filter_file_list(self, text: str) -> None:
        query = text.strip().lower()
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            rel_path = str(item.data(Qt.ItemDataRole.UserRole) or "")
            show = query in rel_path.lower()
            item.setHidden(not show)

    def on_file_selected(self) -> None:
        rel_path = self.get_current_rel_path()
        if not rel_path:
            return

        self.compare_cache.pop(rel_path, None)
        for path in self.file_pairs.get(rel_path, (None, None)):
            if path is not None:
                self.doc_cache.pop(path, None)
        self.refresh_current_table(keep_row_index=None)

    def on_table_clicked(self, proxy_index: QModelIndex) -> None:
        if not proxy_index.isValid():
            return

        source_index = self.proxy_model.mapToSource(proxy_index)
        if not source_index.isValid():
            return

        column = source_index.column()
        row_idx = source_index.row()

        if column == CompareTableModel.COL_COPY_TO_PLUS:
            self.replace_row_by_index(row_idx=row_idx, from_all_age=True)
        elif column == CompareTableModel.COL_COPY_TO_ALL_AGE:
            self.replace_row_by_index(row_idx=row_idx, from_all_age=False)

    def refresh_current_table(self, keep_row_index: int | None) -> None:
        rel_path = self.get_current_rel_path()
        if not rel_path:
            return

        rows = self.get_compare_rows(rel_path)
        self.model.set_rows(rows, rel_path)
        self.update_row_summary(rel_path, rows)

        if keep_row_index is None:
            return

        if keep_row_index < 0 or keep_row_index >= self.model.rowCount():
            return

        source_index = self.model.index(keep_row_index, CompareTableModel.COL_INDEX)
        proxy_index = self.proxy_model.mapFromSource(source_index)
        if proxy_index.isValid():
            self.table.selectRow(proxy_index.row())
            self.table.scrollTo(proxy_index)

    def update_row_summary(self, rel_path: str, rows: list[CompareRow]) -> None:
        same_count = sum(1 for r in rows if r.status == "Same")
        diff_count = sum(1 for r in rows if r.status == "Different")
        missing_count = sum(1 for r in rows if r.status == "Missing")
        self.row_summary_label.setText(
            f"File: {rel_path} | Total baris: {len(rows)} | Same: {same_count} | Different: {diff_count} | Missing: {missing_count}"
        )

    def get_current_rel_path(self) -> str | None:
        selected_items = self.file_list.selectedItems()
        if not selected_items:
            return None
        return str(selected_items[0].data(Qt.ItemDataRole.UserRole))

    def get_selected_source_row(self) -> int | None:
        selection_model = self.table.selectionModel()
        if selection_model is None:
            return None

        selected_rows = selection_model.selectedRows()
        if not selected_rows:
            return None

        proxy_index = selected_rows[0]
        source_index = self.proxy_model.mapToSource(proxy_index)
        if not source_index.isValid():
            return None
        return source_index.row()

    def replace_from_selected_row(self, from_all_age: bool) -> None:
        row_idx = self.get_selected_source_row()
        if row_idx is None:
            QMessageBox.warning(self, "Tidak Ada Baris", "Pilih satu baris dulu di tabel compare.")
            return
        self.replace_row_by_index(row_idx=row_idx, from_all_age=from_all_age)

    def replace_row_by_index(self, row_idx: int, from_all_age: bool) -> None:
        rel_path = self.get_current_rel_path()
        if not rel_path:
            QMessageBox.warning(self, "Tidak Ada File", "Pilih file JSON terlebih dahulu.")
            return

        left_path, right_path = self.file_pairs.get(rel_path, (None, None))

        source_path = left_path if from_all_age else right_path
        target_path = right_path if from_all_age else left_path

        if source_path is None or target_path is None:
            QMessageBox.warning(
                self,
                "Sisi Tidak Lengkap",
                "Copy baris butuh file di kedua sisi (All-Age dan Plus Harmony).",
            )
            return

        source_doc = self.get_json_document(source_path)
        target_doc = self.get_json_document(target_path)

        if source_doc is None or target_doc is None:
            QMessageBox.warning(self, "Gagal Baca JSON", "Salah satu file tidak bisa dibaca / parse JSON.")
            return

        if row_idx >= len(source_doc.refs):
            QMessageBox.warning(self, "Baris Tidak Valid", "Baris sumber tidak ditemukan pada JSON sumber.")
            return

        if row_idx >= len(target_doc.refs):
            QMessageBox.warning(
                self,
                "Baris Target Tidak Ada",
                "Baris target tidak tersedia di JSON tujuan (jumlah baris lebih sedikit).",
            )
            return

        replacement = source_doc.refs[row_idx].get_text()
        target_doc.refs[row_idx].set_text(replacement)

        if not self.save_json_document(target_doc):
            QMessageBox.warning(self, "Gagal Simpan", f"Gagal menyimpan perubahan ke file:\n{target_doc.path}")
            return

        self.compare_cache.pop(rel_path, None)
        self.refresh_current_table(keep_row_index=row_idx)

        direction = "All-Age -> 18+" if from_all_age else "18+ -> All-Age"
        self.statusBar().showMessage(f"Baris {row_idx} berhasil di-copy ({direction}) dan disimpan.", 5000)

    def handle_text_edited(self, rel_path: str, row_idx: int, side: str, new_text: str) -> bool:
        if not rel_path:
            return False

        left_path, right_path = self.file_pairs.get(rel_path, (None, None))
        target_path = left_path if side == "all_age" else right_path

        if target_path is None:
            QMessageBox.warning(
                self,
                "Sisi Tidak Tersedia",
                "Kolom ini tidak punya file target untuk disimpan.",
            )
            return False

        target_doc = self.get_json_document(target_path)
        if target_doc is None:
            QMessageBox.warning(self, "Gagal Baca JSON", f"Tidak bisa membaca file:\n{target_path}")
            return False

        if row_idx >= len(target_doc.refs):
            QMessageBox.warning(
                self,
                "Baris Tidak Ditemukan",
                "Baris yang diedit tidak tersedia di file JSON target.",
            )
            return False

        target_doc.refs[row_idx].set_text(new_text)

        if not self.save_json_document(target_doc):
            QMessageBox.warning(self, "Gagal Simpan", f"Gagal menyimpan perubahan ke file:\n{target_doc.path}")
            return False

        self.compare_cache.pop(rel_path, None)
        side_label = "All-Age" if side == "all_age" else "Plus Harmony"
        self.statusBar().showMessage(f"Edit baris {row_idx} di kolom {side_label} tersimpan.", 4000)
        return True

    def get_compare_rows(self, rel_path: str) -> list[CompareRow]:
        cached = self.compare_cache.get(rel_path)
        if cached is not None:
            return cached

        left_path, right_path = self.file_pairs.get(rel_path, (None, None))
        left_doc = self.get_json_document(left_path)
        right_doc = self.get_json_document(right_path)

        left_messages = [ref.get_text() for ref in left_doc.refs] if left_doc else []
        right_messages = [ref.get_text() for ref in right_doc.refs] if right_doc else []

        max_len = max(len(left_messages), len(right_messages))
        rows: list[CompareRow] = []

        for i in range(max_len):
            has_left = i < len(left_messages)
            has_right = i < len(right_messages)
            left = left_messages[i] if has_left else ""
            right = right_messages[i] if has_right else ""

            if not has_left or not has_right:
                status = "Missing"
            elif left == right:
                status = "Same"
            else:
                status = "Different"

            rows.append(
                CompareRow(
                    index=i,
                    all_age=left,
                    plus_harmony=right,
                    status=status,
                    has_all_age=has_left,
                    has_plus_harmony=has_right,
                )
            )

        self.compare_cache[rel_path] = rows
        return rows

    def get_json_document(self, path: Path | None) -> JsonDocument | None:
        if path is None:
            return None

        cached = self.doc_cache.get(path)
        signature = self.get_file_signature(path)
        if cached is not None and signature == (cached.mtime_ns, cached.size):
            return cached

        loaded = self.load_json_document(path)
        if loaded is not None:
            self.doc_cache[path] = loaded
        return loaded

    def load_json_document(self, path: Path) -> JsonDocument | None:
        try:
            raw_bytes = path.read_bytes()
        except OSError:
            return None

        decoded_text: str | None = None
        used_encoding = "utf-8"
        encodings = (
            ("utf-8-sig", "utf-8", "cp932", "shift_jis")
            if raw_bytes.startswith(b"\xef\xbb\xbf")
            else ("utf-8", "cp932", "shift_jis")
        )
        for encoding in encodings:
            try:
                decoded_text = raw_bytes.decode(encoding)
                used_encoding = encoding
                break
            except UnicodeDecodeError:
                continue

        if decoded_text is None:
            return None

        try:
            data = json.loads(decoded_text)
        except json.JSONDecodeError:
            return None

        refs: list[MessageRef] = []
        self.extract_message_refs(data, refs)

        signature = self.get_file_signature(path)
        if signature is None:
            return None

        newline = "\r\n" if "\r\n" in decoded_text else "\n"
        return JsonDocument(
            path=path,
            data=data,
            refs=refs,
            encoding=used_encoding,
            newline=newline,
            mtime_ns=signature[0],
            size=signature[1],
        )

    def get_file_signature(self, path: Path) -> tuple[int, int] | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def extract_message_refs(self, node: Any, output: list[MessageRef]) -> None:
        if isinstance(node, list):
            for idx, item in enumerate(node):
                if isinstance(item, str):
                    output.append(MessageRef(owner=node, key=idx))
                else:
                    self.extract_message_refs(item, output)
            return

        if isinstance(node, dict):
            if "message" in node and isinstance(node["message"], str):
                output.append(MessageRef(owner=node, key="message"))
                return

            if "text" in node and isinstance(node["text"], str):
                output.append(MessageRef(owner=node, key="text"))
                return

            for key, value in node.items():
                if isinstance(value, str):
                    output.append(MessageRef(owner=node, key=key))
                else:
                    self.extract_message_refs(value, output)
            return

    def save_json_document(self, doc: JsonDocument) -> bool:
        try:
            rendered = json.dumps(doc.data, ensure_ascii=False, indent=2)
            rendered = self.normalize_member_indent(rendered, indent=2)
            if doc.newline == "\r\n":
                rendered = rendered.replace("\n", "\r\n")
            rendered += doc.newline
            # Disable platform newline translation to avoid accidental CRCRLF
            # which shows as extra blank lines in editors on Windows.
            with doc.path.open("w", encoding=doc.encoding, newline="") as f:
                f.write(rendered)

            signature = self.get_file_signature(doc.path)
            if signature is not None:
                doc.mtime_ns, doc.size = signature
            return True
        except OSError:
            return False

    def normalize_member_indent(self, text: str, indent: int) -> str:
        """Match project JSON style: object members align with their '{' line."""
        if indent <= 0:
            return text

        lines: list[str] = []
        for line in text.splitlines():
            stripped = line.lstrip(" ")
            lead = len(line) - len(stripped)
            if lead >= indent and JSON_KEY_LINE_RE.match(stripped):
                line = line[indent:]
            lines.append(line)
        return "\n".join(lines)

    def apply_theme(self, theme_name: str) -> None:
        app = QApplication.instance()
        if app is None:
            return

        if theme_name == "Dark":
            dark_palette = QPalette()
            dark_palette.setColor(QPalette.ColorRole.Window, QColor(45, 45, 45))
            dark_palette.setColor(QPalette.ColorRole.WindowText, QColor(230, 230, 230))
            dark_palette.setColor(QPalette.ColorRole.Base, QColor(30, 30, 30))
            dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(43, 43, 43))
            dark_palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(230, 230, 230))
            dark_palette.setColor(QPalette.ColorRole.ToolTipText, QColor(230, 230, 230))
            dark_palette.setColor(QPalette.ColorRole.Text, QColor(230, 230, 230))
            dark_palette.setColor(QPalette.ColorRole.Button, QColor(55, 55, 55))
            dark_palette.setColor(QPalette.ColorRole.ButtonText, QColor(230, 230, 230))
            dark_palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 80, 80))
            dark_palette.setColor(QPalette.ColorRole.Link, QColor(125, 179, 255))
            dark_palette.setColor(QPalette.ColorRole.Highlight, QColor(63, 126, 196))
            dark_palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
            app.setPalette(dark_palette)
            self._apply_table_style(theme_name="Dark")
        else:
            app.setPalette(app.style().standardPalette())
            self._apply_table_style(theme_name="Light")

    def _apply_table_style(self, theme_name: str) -> None:
        if theme_name == "Dark":
            self.table.setStyleSheet(
                """
                QTableView {
                    color: #e6e6e6;
                    background-color: #1e1e1e;
                    alternate-background-color: #2b2b2b;
                    gridline-color: #4a4a4a;
                    selection-background-color: #3f7ec4;
                    selection-color: #ffffff;
                }
                QTableView::item:selected {
                    background-color: #3f7ec4;
                    color: #ffffff;
                }
                QTableView QLineEdit {
                    color: #ffffff;
                    background-color: #252525;
                    border: 1px solid #6a9bd0;
                    selection-background-color: #3f7ec4;
                    selection-color: #ffffff;
                }
                """
            )
            return

        self.table.setStyleSheet(
            """
            QTableView {
                color: #121212;
                background-color: #ffffff;
                alternate-background-color: #f5f7fa;
                gridline-color: #cfd7e3;
                selection-background-color: #cfe3ff;
                selection-color: #101010;
            }
            QTableView::item:selected {
                background-color: #cfe3ff;
                color: #101010;
            }
            QTableView QLineEdit {
                color: #101010;
                background-color: #ffffff;
                border: 1px solid #4a90e2;
                selection-background-color: #9ec5fe;
                selection-color: #101010;
            }
            """
        )


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.apply_theme("Light")
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
