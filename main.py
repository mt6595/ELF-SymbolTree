"""ELF Variable Explorer 启动入口。

用法:
    python main.py [xxx.elf]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402


def main() -> int:
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("ELF Variable Explorer")

    from gui.main_window import MainWindow

    window = MainWindow()
    window.show()

    if len(sys.argv) > 1:
        window.open_path(sys.argv[1])

    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())