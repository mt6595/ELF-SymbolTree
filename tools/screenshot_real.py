"""用真实 ELF 渲染界面并截图。

用法: python tools/screenshot_real.py <elf路径> <输出png> [变量关键字]
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PyQt5.QtCore import QEventLoop, QModelIndex, QTimer  # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)

app = QApplication([])

from gui.main_window import MainWindow  # noqa: E402

elf = sys.argv[1]
out = sys.argv[2]
keyword = sys.argv[3] if len(sys.argv) > 3 else ""

win = MainWindow()
win.resize(1440, 900)
win.show()
win.open_path(elf)

loop = QEventLoop()


def poll() -> None:
    if win._result is not None:
        loop.quit()
    else:
        QTimer.singleShot(100, poll)


QTimer.singleShot(100, poll)
QTimer.singleShot(60000, loop.quit)
loop.exec_()

assert win._result is not None, "解析失败"
print("变量:", win._result.info.variable_count, "| 已分配:",
      sum(1 for v in win._result.variables if v.allocated))

# 选一个有位域、有地址的变量
target = None
for v in win._result.variables:
    if not v.allocated:
        continue
    if keyword and keyword.lower() not in v.name.lower():
        continue
    if any(n.is_bitfield for n in v.node.walk()):
        target = v
        break
if target is None:
    target = next((v for v in win._result.variables if v.allocated), None)

if target is not None:
    win._show_variable(target)
    win.tree.expandToDepth(2)
    app.processEvents()

    def find_index(predicate, parent=QModelIndex()):
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

    bit = find_index(lambda n: n.is_bitfield)
    if bit.isValid():
        win.tree.setCurrentIndex(bit)
        win.tree.scrollTo(bit)
        app.processEvents()
    print("当前变量:", target.name, "|", target.node.type_str,
          "|", hex(target.address) if target.address else "-")

os.makedirs(os.path.dirname(out), exist_ok=True)
win.grab().save(out)
print("saved:", out)
print("--- 详情 ---")
print(win.detail_view.toPlainText())
app.quit()