"""离屏渲染主窗口并截图,用于验证界面效果。"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PyQt5.QtCore import QEventLoop, QModelIndex, QTimer  # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

QMessageBox.information = staticmethod(lambda *a, **k: None)  # 避免离线环境弹窗阻塞

app = QApplication([])

from gui.main_window import MainWindow  # noqa: E402

win = MainWindow()
win.resize(1440, 900)
win.show()

elf = os.path.join(ROOT, "samples", "demo.elf")
win.open_path(elf)

loop = QEventLoop()


def poll() -> None:
    if win._result is not None:
        loop.quit()
    else:
        QTimer.singleShot(80, poll)


QTimer.singleShot(80, poll)
QTimer.singleShot(20000, loop.quit)
loop.exec_()

assert win._result is not None, "解析失败"
print("变量数:", win._result.info.variable_count)

# 定位 g_uart1
target = next(v for v in win._result.variables if v.name == "g_uart1")
win._show_variable(target)
win.tree.expandToDepth(3)
app.processEvents()


def find_index(predicate, parent=QModelIndex()) -> QModelIndex:
    model = win.tree_model
    for row in range(model.rowCount(parent)):
        index = model.index(row, 0, parent)
        node = model.node_of(index)
        if node is not None and predicate(node):
            return index
        found = find_index(predicate, index)
        if found.isValid():
            return found
    return QModelIndex()


# 选中位域 baud_prescaler,展示详情面板
bit_index = find_index(lambda n: n.name == "baud_prescaler")
if bit_index.isValid():
    win.tree.setCurrentIndex(bit_index)
    win.tree.scrollTo(bit_index)
app.processEvents()

out1 = os.path.join(ROOT, "docs", "screenshot_overview.png")
os.makedirs(os.path.dirname(out1), exist_ok=True)
win.grab().save(out1)
print("saved:", out1)

# 第二张:展开结构体成员
struct_index = find_index(lambda n: n.name == "CR1_BITS")
if struct_index.isValid():
    win.tree.expand(struct_index)
    win.tree.setCurrentIndex(struct_index)
app.processEvents()
out2 = os.path.join(ROOT, "docs", "screenshot_struct.png")
win.grab().save(out2)
print("saved:", out2)

print("详情面板内容:")
print(win.detail_view.toPlainText())
app.quit()