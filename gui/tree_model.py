"""变量/类型树的 Qt 模型与展示配色。"""
from __future__ import annotations

from PyQt5.QtCore import QAbstractItemModel, QModelIndex, Qt

from elfview import Kind, Node

HEADERS = ["名称", "类型", "偏移", "地址", "大小", "位域"]

# kind -> 前景色(深色主题)
KIND_COLORS = {
    Kind.STRUCT: "#7aa2f7",
    Kind.UNION: "#bb9af7",
    Kind.ARRAY: "#2ac3de",
    Kind.BITFIELD: "#e0af68",
    Kind.POINTER: "#9aa5ce",
    Kind.ENUM: "#9ece6a",
    Kind.ELEMENT: "#a9b1d6",
    Kind.BASE: "#c0caf5",
    Kind.VARIABLE: "#f7768e",
    Kind.TYPEDEF: "#7dcfff",
    Kind.FUNCTION: "#e06c9f",
}


def kind_color(kind: str) -> str:
    return KIND_COLORS.get(kind, "#c0caf5")


def hex8(value, dash="—") -> str:
    return f"0x{value:08X}" if value is not None else dash


class NodeTreeModel(QAbstractItemModel):
    """把 Node 树暴露为 6 列 QTreeView 模型。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._root: Node | None = None
        self._parents: dict[int, Node] = {}

    def set_root(self, root: Node) -> None:
        self.beginResetModel()
        self._root = root
        self._parents = {}
        stack = [(root, None)]
        while stack:
            node, parent = stack.pop()
            self._parents[id(node)] = parent
            for child in node.children:
                stack.append((child, node))
        self.endResetModel()

    def root(self) -> Node | None:
        return self._root

    def node_of(self, index: QModelIndex) -> Node | None:
        if not index.isValid():
            return self._root
        return index.internalPointer()

    # ---------------- QAbstractItemModel 实现 ----------------
    def index(self, row: int, column: int, parent=QModelIndex()) -> QModelIndex:
        if not parent.isValid():
            if self._root is None or row != 0:
                return QModelIndex()
            return self.createIndex(0, column, self._root)
        node = parent.internalPointer()
        if node is None or not (0 <= row < len(node.children)):
            return QModelIndex()
        return self.createIndex(row, column, node.children[row])

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        node = index.internalPointer()
        parent = self._parents.get(id(node))
        if parent is None:
            return QModelIndex()
        grand = self._parents.get(id(parent))
        if grand is None:
            return self.createIndex(0, 0, parent)
        row = grand.children.index(parent)
        return self.createIndex(row, 0, parent)

    def rowCount(self, parent=QModelIndex()) -> int:
        if not parent.isValid():
            return 1 if self._root is not None else 0
        node = parent.internalPointer()
        return len(node.children) if node is not None else 0

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(HEADERS)

    def hasChildren(self, parent=QModelIndex()) -> bool:  # noqa: N802
        if not parent.isValid():
            return self._root is not None
        node = parent.internalPointer()
        return bool(node and node.children)

    def headerData(self, section: int, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        node = index.internalPointer()
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0:
                return node.name
            if col == 1:
                return node.type_str
            if col == 2:
                if node.offset is None:
                    return "—"
                # 相对父节点的字节偏移
                return f"+0x{node.offset:04X}  ({node.offset})"
            if col == 3:
                return hex8(node.address)
            if col == 4:
                if node.is_bitfield:
                    return f"{node.bit_size} bit"
                return f"{node.size}" if node.size is not None else "—"
            if col == 5:
                return node.bit_range_str
            return None

        if role == Qt.ForegroundRole:
            from PyQt5.QtGui import QColor
            return QColor(kind_color(node.kind))

        if role == Qt.FontRole and col in (2, 3, 4, 5):
            from PyQt5.QtGui import QFont
            return QFont("Consolas", 9)

        if role == Qt.ToolTipRole:
            return self._tooltip(node)

        return None

    @staticmethod
    def _tooltip(node: Node) -> str:
        lines = [
            f"名称   : {node.name}",
            f"类型   : {node.type_str}",
            f"Kind   : {node.kind}",
        ]
        if node.offset is not None:
            lines.append(f"偏移   : +0x{node.offset:X}")
        if node.address is not None:
            lines.append(f"地址   : 0x{node.address:X}")
        if node.size is not None:
            lines.append(f"大小   : {node.size} 字节")
        if node.is_bitfield:
            lines.append(f"位域   : {node.bit_range_str} (容器 {node.type_str})")
        typedefs = node.extra.get("typedef_chain")
        if typedefs:
            lines.append(f"typedef: {typedefs}")
        return "\n".join(lines)

    # 允许展开三角标记
    def flags(self, index: QModelIndex):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable