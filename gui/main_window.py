"""主窗口:变量列表 + 类型树 + 详情面板。"""
from __future__ import annotations

import json

from PyQt5.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QKeySequence
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableView,
    QToolBar,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from elfview import ElfAnalyzer, ElfParseError, Kind, Node, ParseResult, Variable
from elfview.jsonio import result_to_dict

from .tree_model import HEADERS, NodeTreeModel, hex8


class VariableTableModel(QAbstractTableModel):
    HEADERS = ["名称", "类型", "地址", "大小", "段", "链接属性"]

    def __init__(self, variables: list, parent=None) -> None:
        super().__init__(parent)
        self._vars = variables

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._vars)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        var: Variable = self._vars[index.row()]
        node = var.node
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return node.name
            if col == 1:
                return node.type_str
            if col == 2:
                return hex8(node.address)
            if col == 3:
                return f"{node.size}" if node.size is not None else "—"
            if col == 4:
                return var.section or "—"
            if col == 5:
                return f"{var.linkage}" + (f" (in {var.scope})" if var.scope else "")
            return None
        if role == Qt.ForegroundRole:
            if col == 3:
                from .tree_model import kind_color
                return QColor(kind_color(node.kind))
            return None
        if role == Qt.FontRole and col in (2, 3):
            return QFont("Consolas", 9)
        if role == Qt.ToolTipRole:
            tip = f"{node.name}  {node.type_str}\n地址: {hex8(node.address)}  大小: {node.size}"
            if var.cu_name:
                tip += f"\n编译单元: {var.cu_name}"
            if not var.allocated:
                tip += f"\n⚠ {var.unallocated_reason}"
            return tip
        return None

    def var_at(self, row: int) -> Variable:
        return self._vars[row]


class VariableFilter(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._text = ""
        self.show_unallocated = False

    def set_filter_text(self, text: str) -> None:
        self._text = text.lower()
        self.invalidateFilter()

    def set_show_unallocated(self, show: bool) -> None:
        self.show_unallocated = show
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent) -> bool:
        model: VariableTableModel = self.sourceModel()
        var = model.var_at(source_row)
        if not var.allocated and not self.show_unallocated:
            return False
        if not self._text:
            return True
        node = var.node
        return (
            self._text in node.name.lower()
            or self._text in (node.type_str or "").lower()
            or self._text in (var.scope or "").lower()
            or self._text in (var.section or "").lower()
            or self._text in (var.cu_name or "").lower()
        )


class AnalyzeWorker(QThread):
    ok = pyqtSignal(object)
    fail = pyqtSignal(str)

    def __init__(self, path: str, max_array: int, parent=None) -> None:
        super().__init__(parent)
        self._path = path
        self._max_array = max_array

    def run(self) -> None:
        try:
            result = ElfAnalyzer(self._path, max_array=self._max_array).analyze()
        except ElfParseError as exc:
            self.fail.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.fail.emit(f"发生未预期错误:\n{type(exc).__name__}: {exc}")
        else:
            self.ok.emit(result)


def _detail_lines(node: Node, var: Variable | None = None) -> list[str]:
    extra = node.extra or {}
    lines: list[str] = []

    if node.kind == Kind.VARIABLE and var is not None:
        lines.append("── 变量信息 ─────────────────────────")
        lines.append(f"名称      : {node.name}")
        lines.append(f"类型      : {node.type_str}")
        if extra.get("typedef_chain"):
            lines.append(f"typedef链 : {extra['typedef_chain']}")
        if extra.get("qualifiers"):
            lines.append(f"限定符    : {extra['qualifiers']}")
        if node.address is not None:
            end = node.end_address
            lines.append(f"地址      : {hex8(node.address)}" + (f" .. {hex8(end)}" if end else ""))
        lines.append(f"大小      : {node.size} 字节" if node.size is not None else "大小      : —")
        lines.append(f"所在段    : {var.section or '—'}")
        lines.append(f"链接属性  : {var.linkage}" + (f"  (函数 {var.scope})" if var.scope else ""))
        if var.cu_name:
            lines.append(f"编译单元  : {var.cu_name}")
        if not var.allocated:
            lines.append(f"地址状态  : ⚠ {var.unallocated_reason}")

    lines.append("── 节点信息 ─────────────────────────")
    if node.kind != Kind.VARIABLE:
        lines.append(f"名称      : {node.name}")
        lines.append(f"类型      : {node.type_str}")
    lines.append(f"Kind      : {node.kind}")
    if node.offset is not None:
        lines.append(f"偏移      : +0x{node.offset:04X}  (相对父起始 {node.offset} 字节)")
    if node.address is not None:
        end = node.end_address
        lines.append(f"绝对地址  : {hex8(node.address)}" + (f" .. {hex8(end)}" if end else ""))
    if node.is_bitfield:
        lines.append(f"位域      : {node.bit_range_str}")
        lines.append(f"位宽      : {node.bit_size} bit")
        lines.append(f"容器类型  : {extra.get('bit_container', node.type_str)}")
        if extra.get("abs_bit") is not None:
            lines.append(f"绝对位位置: 地址 {hex8(extra['abs_bit'] // 8)} 的 bit {extra['abs_bit'] % 8} 起")
        if extra.get("bit_offset_unknown"):
            lines.append("注: 该位域缺少位偏移信息(旧式编译器),位置可能不准确")
    if node.size is not None and not node.is_bitfield:
        lines.append(f"大小      : {node.size} 字节")

    if node.kind == Kind.ARRAY:
        dims = extra.get("array_dims")
        if dims:
            lines.append(f"维度      : {dims}")
        if extra.get("truncated_array"):
            total, shown = extra["truncated_array"]
            lines.append(f"展示截断  : 共 {total} 个元素,仅显示前 {shown} 个(设置中可调)")

    if node.kind == Kind.POINTER:
        if extra.get("pointer_target"):
            lines.append(f"指向类型  : {extra['pointer_target']}")
        if extra.get("pointer_target_size") is not None:
            lines.append(f"指向类型大小: {extra['pointer_target_size']} 字节")

    enum_values = extra.get("enum_values")
    if enum_values:
        lines.append("枚举值    :")
        for name, value in enum_values:
            lines.append(f"            {name:<20} = {value}")

    if node.tag:
        lines.append(f"DWARF Tag : {node.tag}")
    if node.die_offset is not None:
        lines.append(f"DIE 偏移  : 0x{node.die_offset:X}")
    if extra.get("decl_line"):
        lines.append(f"声明行    : {extra['decl_line']}")

    if extra.get("truncated"):
        lines.append("注: 节点已按深度/规模限制截断")
    return lines


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ELF Variable Explorer — 变量/类型树查看器")
        self.resize(1360, 860)

        self._result: ParseResult | None = None
        self._worker: AnalyzeWorker | None = None
        self._current_var: Variable | None = None
        self._var_filter: VariableFilter | None = None
        self._notes = ""
        self._max_array = 256

        self._build_ui()
        self._apply_style()
        self.statusBar().showMessage("打开 ELF 文件开始分析(Ctrl+O)")

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.act_open = QAction("打开 ELF…", self)
        self.act_open.setShortcut(QKeySequence.Open)
        self.act_open.triggered.connect(self.open_dialog)
        toolbar.addAction(self.act_open)

        self.act_export = QAction("导出 JSON", self)
        self.act_export.setShortcut("Ctrl+E")
        self.act_export.triggered.connect(self.export_json)
        self.act_export.setEnabled(False)
        toolbar.addAction(self.act_export)

        self.act_notes = QAction("解析提示", self)
        self.act_notes.triggered.connect(self._show_notes)
        self.act_notes.setVisible(False)
        toolbar.addAction(self.act_notes)

        toolbar.addSeparator()

        for label, slot in [
            ("展开一层", lambda: self._expand_tree(1)),
            ("展开两层", lambda: self._expand_tree(2)),
            ("展开四层", lambda: self._expand_tree(4)),
            ("折叠", self._collapse_tree),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            toolbar.addWidget(btn)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel("  过滤变量:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("输入名称/类型/段/编译单元关键字(如 uart / uint32_t / bss)…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setFixedWidth(300)
        self.filter_edit.textChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self.filter_edit)

        self.chk_unallocated = QCheckBox("显示未分配变量")
        self.chk_unallocated.setToolTip(
            "显示调试信息中没有有效地址的变量\n(通常是头文件中声明但未被使用的变量,链接时已丢弃)"
        )
        self.chk_unallocated.toggled.connect(self._on_unallocated_toggled)
        toolbar.addWidget(self.chk_unallocated)

        # 主分栏
        splitter = QSplitter(Qt.Horizontal)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(6, 6, 3, 6)
        left_layout.setSpacing(4)
        self.var_table = QTableView()
        self.var_table.setModel(VariableTableModel([], self))
        self.var_table.setWordWrap(False)
        self.var_table.setAlternatingRowColors(True)
        header = self.var_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for col in (2, 3):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.var_table.setSelectionBehavior(QTableView.SelectRows)
        self.var_table.setSelectionMode(QTableView.SingleSelection)
        self.var_table.clicked.connect(self._on_variable_clicked)
        self.var_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.var_table.customContextMenuRequested.connect(self._on_var_menu)
        left_layout.addWidget(self.var_table)
        self.var_count_label = QLabel("")
        self.var_count_label.setStyleSheet("color: #7c82a6; padding-left: 4px;")
        left_layout.addWidget(self.var_count_label)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(3, 6, 6, 6)
        right_layout.setSpacing(4)
        self.tree = QTreeView()
        self.tree_model = NodeTreeModel(self)
        self.tree.setModel(self.tree_model)
        self.tree.setWordWrap(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        tree_header = self.tree.header()
        self.tree.setColumnWidth(0, 300)
        self.tree.setColumnWidth(1, 220)
        tree_header.setSectionResizeMode(0, QHeaderView.Interactive)
        tree_header.setSectionResizeMode(1, QHeaderView.Interactive)
        for col in (2, 3, 4, 5):
            tree_header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.tree.selectionModel().selectionChanged.connect(self._on_tree_selection_changed)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_menu)
        right_layout.addWidget(self.tree, 3)

        self.detail_view = QPlainTextEdit()
        self.detail_view.setReadOnly(True)
        self.detail_view.setPlaceholderText(
            "查看变量/成员详情:类型、地址、偏移、位域、typedef 链、枚举值、DWARF 属性。\n\n"
            "使用方式:\n"
            " 1. 左侧点选变量\n"
            " 2. 右侧树形展开结构体/联合体/数组 — 每一行都有绝对地址与偏移\n"
            " 3. 点选任意节点,下方显示完整类型与 DWARF 信息"
        )
        self.detail_view.setMaximumBlockCount(2000)
        right_layout.addWidget(self.detail_view, 2)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([420, 940])
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        self.setCentralWidget(splitter)

    def _apply_style(self) -> None:
        from .theme import QSS
        self.setStyleSheet(QSS)

    # ------------------------------------------------------------- 打开文件
    def open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 ELF 文件",
            "",
            "ELF 文件 (*.elf *.axf *.out *.o);;所有文件 (*)",
        )
        if path:
            self.open_path(path)

    def open_path(self, path: str) -> None:
        if self._worker and self._worker.isRunning():
            QMessageBox.information(self, "提示", "正在解析其他文件,请稍候…")
            return
        self.act_open.setEnabled(False)
        self.statusBar().showMessage(f"正在解析 {path} …")
        self._worker = AnalyzeWorker(path, self._max_array, self)
        self._worker.ok.connect(self._on_parse_ok)
        self._worker.fail.connect(self._on_parse_fail)
        self._worker.start()

    def _on_parse_ok(self, result: ParseResult) -> None:
        self._result = result
        self.act_open.setEnabled(True)
        self.act_export.setEnabled(True)

        info = result.info
        model = VariableTableModel(result.variables, self)
        self._source_var_model = model
        self._var_filter = VariableFilter(self)
        self._var_filter.setSourceModel(model)
        self._var_filter.set_show_unallocated(self.chk_unallocated.isChecked())
        self.var_table.setModel(self._var_filter)
        self.var_table.setSortingEnabled(False)

        shown = len(result.variables)
        self._update_count_label()

        summary = (
            f"{info.arch_str}  |  {info.elf_type}  |  DWARF v{info.dwarf_version}"
            f"  |  {info.cu_count} 编译单元  |  {shown} 变量"
        )
        self.statusBar().showMessage(summary, 15000)
        self.setWindowTitle(f"ELF Variable Explorer — {info.path}")

        if result.variables:
            self._var_filter.set_filter_text(self.filter_edit.text())
            self.var_table.selectRow(0)
            first = self._var_filter.rowCount() > 0
            if first:
                src = self._var_filter.mapToSource(self._var_filter.index(0, 0))
                self._show_variable(result.variables[src.row()])

        if info.warnings:
            self._notes = "\n\n".join(info.warnings)
            self.act_notes.setText(f"解析提示 ({len(info.warnings)})")
            self.act_notes.setVisible(True)
            self.statusBar().showMessage(f"{summary}  ·  {info.warnings[0]}", 20000)
        else:
            self._notes = ""
            self.act_notes.setVisible(False)

    def _show_notes(self) -> None:
        if self._notes:
            QMessageBox.information(self, "解析提示", self._notes)

    def _on_parse_fail(self, message: str) -> None:
        self.act_open.setEnabled(True)
        self.statusBar().showMessage("解析失败", 5000)
        QMessageBox.warning(self, "无法解析", message)

    # ------------------------------------------------------------- 交互
    def _on_filter_changed(self, text: str) -> None:
        if self._var_filter:
            self._var_filter.set_filter_text(text)
            self._update_count_label()

    def _on_unallocated_toggled(self, checked: bool) -> None:
        if self._var_filter:
            self._var_filter.set_show_unallocated(checked)
            self._update_count_label()

    def _update_count_label(self) -> None:
        if not self._result:
            return
        total = len(self._result.variables)
        unalloc = sum(1 for v in self._result.variables if not v.allocated)
        shown = self._var_filter.rowCount() if self._var_filter else total
        text = f"{shown} / {total} 个变量"
        if unalloc:
            text += f" · 未分配 {unalloc}"
            if not self.chk_unallocated.isChecked():
                text += "(已隐藏)"
        self.var_count_label.setText(text)

    def _on_variable_clicked(self, index: QModelIndex) -> None:
        if not index.isValid() or not self._result or not self._var_filter:
            return
        source_index = self._var_filter.mapToSource(index)
        if not source_index.isValid():
            return
        var = self._result.variables[source_index.row()]
        self._show_variable(var)

    def _show_variable(self, var: Variable) -> None:
        self.tree_model.set_root(var.node)
        self.tree.expandToDepth(2)
        self._current_var = var
        self._render_details(var.node, var)
        # 在变量列表中同步选中
        if self._var_filter and self._result:
            for row in range(self._var_filter.rowCount()):
                src = self._var_filter.mapToSource(self._var_filter.index(row, 0))
                if src.isValid() and self._result.variables[src.row()] is var:
                    self.var_table.selectRow(row)
                    self.var_table.scrollTo(self._var_filter.index(row, 0))
                    break

    def _expand_tree(self, depth: int) -> None:
        if self._result:
            self.tree.expandToDepth(depth)

    def _collapse_tree(self) -> None:
        self.tree.collapseAll()

    def _on_tree_selection_changed(self, *_args) -> None:
        indexes = self.tree.selectionModel().selectedIndexes()
        if not indexes:
            return
        node = self.tree_model.node_of(indexes[0])
        if node is not None:
            self._render_details(node, getattr(self, "_current_var", None))

    def _render_details(self, node: Node, var) -> None:
        lines = _detail_lines(node, var)
        self.detail_view.setPlainText("\n".join(lines))

    # -------------------------------------------------------------- 右键菜单
    def _on_var_menu(self, pos) -> None:
        index = self.var_table.indexAt(pos)
        if not index.isValid() or not self._result or not self._var_filter:
            return
        source_index = self._var_filter.mapToSource(index)
        if not source_index.isValid():
            return
        var = self._result.variables[source_index.row()]
        menu = QMenu(self)
        a_copy_name = menu.addAction("复制变量名")
        a_copy_addr = menu.addAction("复制地址")
        a_show = menu.addAction("在树中查看")
        act = menu.exec_(self.var_table.viewport().mapToGlobal(pos))
        if act == a_copy_name:
            QApplication.clipboard().setText(var.name)
        elif act == a_copy_addr:
            QApplication.clipboard().setText(f"0x{var.address:X}" if var.address is not None else "")
        elif act == a_show:
            self._show_variable(var)

    def _on_tree_menu(self, pos) -> None:
        index = self.tree.indexAt(pos)
        if not index.isValid():
            return
        node = self.tree_model.node_of(index)
        menu = QMenu(self)
        a_copy_name = menu.addAction("复制名称")
        a_copy_type = menu.addAction("复制类型字符串")
        a_copy_addr = menu.addAction("复制地址")
        act = menu.exec_(self.tree.viewport().mapToGlobal(pos))
        if node is None:
            return
        if act == a_copy_name:
            QApplication.clipboard().setText(node.name)
        elif act == a_copy_type:
            QApplication.clipboard().setText(node.type_str)
        elif act == a_copy_addr:
            QApplication.clipboard().setText(f"0x{node.address:X}" if node.address is not None else "")

    # -------------------------------------------------------------- 导出
    def export_json(self) -> None:
        if self._result is None:
            return
        default = self._result.info.path.rsplit(".", 1)[0] + "_vars.json"
        path, _ = QFileDialog.getSaveFileName(self, "导出 JSON", default, "JSON 文件 (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fp:
                json.dump(result_to_dict(self._result), fp, ensure_ascii=False, indent=1)
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        self.statusBar().showMessage(f"已导出: {path}", 5000)