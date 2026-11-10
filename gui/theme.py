"""深色主题 QSS(适配 IDE 深色外观)。"""

QSS = """
QMainWindow, QDialog {
    background-color: #16161e;
    color: #c0caf5;
}
QWidget {
    background-color: #16161e;
    color: #c0caf5;
    font-size: 10pt;
}
QToolBar {
    background-color: #1e1f2b;
    border-bottom: 1px solid #2a2b3a;
    spacing: 6px;
    padding: 4px 8px;
}
QToolBar QPushButton {
    background-color: #2e3245;
    color: #c0caf5;
    border: 1px solid #3a3f55;
    border-radius: 5px;
    padding: 5px 14px;
}
QToolBar QPushButton:hover { background-color: #3a3f58; border-color: #565f89; }
QToolBar QPushButton:pressed { background-color: #454b63; }
QToolBar QPushButton:disabled { color: #565f89; background-color: #232430; }

QLineEdit {
    background-color: #1a1b26;
    color: #c0caf5;
    border: 1px solid #3a3f55;
    border-radius: 5px;
    padding: 5px 8px;
    selection-background-color: #2f6feb;
}
QLineEdit:focus { border-color: #2f6feb; }
QLineEdit::placeholder { color: #565f89; }

QTableView, QTreeView, QPlainTextEdit {
    background-color: #1a1b26;
    alternate-background-color: #1c1d29;
    color: #c0caf5;
    border: 1px solid #2a2b3a;
    selection-background-color: #2f3348;
    selection-color: #ffffff;
    outline: none;
}
QTreeView::item { padding: 2px 0; }
QTableView::item { padding: 2px 4px; }
QTreeView::item:hover, QTableView::item:hover { background-color: #25283a; }
QTreeView::item:selected, QTableView::item:selected { background-color: #2f3348; }

QHeaderView::section {
    background-color: #22232f;
    color: #b8c0e0;
    padding: 5px 8px;
    border: none;
    border-bottom: 1px solid #2a2b3a;
    border-right: 1px solid #2a2b3a;
    font-weight: bold;
}
QHeaderView::section:horizontal { border-bottom: 1px solid #3a3f55; }

QSplitter::handle { background-color: #1e1f2b; }
QSplitter::handle:horizontal { width: 3px; }
QSplitter::handle:vertical { height: 3px; }

QStatusBar {
    background-color: #1e1f2b;
    color: #7c82a6;
}
QStatusBar::item { border: none; }

QPlainTextEdit {
    font-size: 10pt;
}
QPlainTextEdit::placeholder { color: #565f89; }

QMenu {
    background-color: #1e1f2b;
    color: #c0caf5;
    border: 1px solid #3a3f55;
}
QMenu::item { padding: 5px 24px; }
QMenu::item:selected { background-color: #2f3348; }

QToolTip {
    background-color: #2e3245;
    color: #e0e6f0;
    border: 1px solid #3a3f55;
    padding: 4px;
}

QMessageBox { background-color: #1a1b26; }
QScrollBar:vertical { background: #1a1b26; width: 10px; }
QScrollBar::handle:vertical { background: #3a3f55; border-radius: 5px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #565f89; }
QScrollBar:horizontal { background: #1a1b26; height: 10px; }
QScrollBar::handle:horizontal { background: #3a3f55; border-radius: 5px; min-width: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
"""