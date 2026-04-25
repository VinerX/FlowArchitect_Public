from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, QPoint, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

_MODE_LABELS = {0: "Direct", 1: "Adapter", 2: "LLM"}


class HistoryPanel(QWidget):
    """
    Collapsible left panel showing session history and analytics.

    Signals:
        session_selected(int)          — user clicked a session row (session_id)
        new_session_requested()        — user clicked "New Session"
        session_rename_requested(int, str) — user renamed a session
        session_delete_requested(int)  — user deleted a session
        run_ui_task_signal             — used by BaseController._ui() for thread-safe updates
    """

    session_selected = pyqtSignal(int)
    new_session_requested = pyqtSignal()
    session_rename_requested = pyqtSignal(int, str)  # session_id, new_name
    session_delete_requested = pyqtSignal(int)        # session_id
    run_ui_task_signal = pyqtSignal(object)           # BaseController._ui() hook

    EXPANDED_WIDTH  = 230
    COLLAPSED_WIDTH = 38

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self._collapsed = False
        self._sessions: list[dict[str, Any]] = []

        self.run_ui_task_signal.connect(self._run_ui_task)

        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(self.EXPANDED_WIDTH)
        self.setMaximumWidth(self.EXPANDED_WIDTH)

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header bar ──────────────────────────────────────────────
        header = QFrame()
        header.setFixedHeight(40)
        hbox = QHBoxLayout(header)
        hbox.setContentsMargins(12, 0, 6, 0)
        hbox.setSpacing(4)

        lbl = QLabel("SESSIONS")
        lbl.setStyleSheet(
            "font-size: 11px; font-weight: 700; letter-spacing: 0.8px;"
        )
        hbox.addWidget(lbl)
        self._header_label = lbl

        hbox.addStretch()

        self._btn_new = QToolButton()
        self._btn_new.setText("+")
        self._btn_new.setToolTip("New session")
        self._btn_new.setStyleSheet(
            "QToolButton { font-size: 18px; font-weight: 300; "
            "background: transparent; border: none; padding: 2px 4px; border-radius: 4px; }"
            "QToolButton:hover { background: #252D40; }"
        )
        self._btn_new.clicked.connect(self.new_session_requested)
        hbox.addWidget(self._btn_new)

        self._btn_toggle = QToolButton()
        self._btn_toggle.setText("\u00ab")  # «  collapse
        self._btn_toggle.setToolTip("Collapse panel")
        self._btn_toggle.setStyleSheet(
            "QToolButton { font-size: 14px; font-weight: 700; background: transparent; border: none; "
            "padding: 2px 4px; border-radius: 4px; }"
            "QToolButton:hover { background: #252D40; }"
        )
        self._btn_toggle.clicked.connect(self.toggle_collapse)
        hbox.addWidget(self._btn_toggle)

        root.addWidget(header)

        # ── Separator ───────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: #252D40; max-height: 1px;")
        root.addWidget(sep)

        # ── Content (hidden when collapsed) ─────────────────────────
        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        tabs = QTabWidget()

        # Sessions tab
        sessions_tab = QWidget()
        sl = QVBoxLayout(sessions_tab)
        sl.setContentsMargins(4, 6, 4, 4)
        sl.setSpacing(2)

        self._session_list = QListWidget()
        self._session_list.setAlternatingRowColors(False)
        self._session_list.itemClicked.connect(self._on_item_clicked)
        self._session_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._session_list.customContextMenuRequested.connect(self._show_session_context_menu)
        sl.addWidget(self._session_list)

        tabs.addTab(sessions_tab, "Sessions")

        # Stats tab
        stats_tab = QWidget()
        stl = QVBoxLayout(stats_tab)
        stl.setContentsMargins(4, 4, 4, 4)

        self._stats_view = QTextEdit()
        self._stats_view.setReadOnly(True)
        stl.addWidget(self._stats_view)

        tabs.addTab(stats_tab, "Stats")

        content_layout.addWidget(tabs)
        root.addWidget(self._content, 1)

    # ------------------------------------------------------------------
    # Thread-safe UI dispatch
    # ------------------------------------------------------------------

    def _run_ui_task(self, fn) -> None:
        if callable(fn):
            fn()

    # ------------------------------------------------------------------
    # Collapse / expand
    # ------------------------------------------------------------------

    def toggle_collapse(self) -> None:
        if self._collapsed:
            self._expand()
        else:
            self._collapse()

    def _collapse(self) -> None:
        self._collapsed = True
        self._content.hide()
        self._header_label.hide()
        self._btn_new.hide()
        self._btn_toggle.setText("\u00bb")  # »  expand
        self._btn_toggle.setToolTip("Expand panel")
        self.setMinimumWidth(self.COLLAPSED_WIDTH)
        self.setMaximumWidth(self.COLLAPSED_WIDTH)

    def _expand(self) -> None:
        self._collapsed = False
        self._content.show()
        self._header_label.show()
        self._btn_new.show()
        self._btn_toggle.setText("\u00ab")  # «  collapse
        self._btn_toggle.setToolTip("Collapse panel")
        self.setMinimumWidth(self.EXPANDED_WIDTH)
        self.setMaximumWidth(self.EXPANDED_WIDTH)

    # ------------------------------------------------------------------
    # Public update API (called by HistoryController)
    # ------------------------------------------------------------------

    def load_sessions(self, sessions: list[dict[str, Any]]) -> None:
        self._sessions = sessions
        self._session_list.clear()

        for s in sessions:
            mode_label = _MODE_LABELS.get(s.get("mode", 1), "?")
            name = s.get("name") or "New Session"
            updated = (s.get("updated_at") or "")[:10]
            display = f"{name}\n{mode_label}  \u00b7  {updated}"

            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, s["id"])
            item.setToolTip(f"Session #{s['id']} | Mode: {mode_label} | Updated: {updated}")
            self._session_list.addItem(item)

    def update_session_name(self, session_id: int, name: str) -> None:
        for i in range(self._session_list.count()):
            item = self._session_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == session_id:
                lines = item.text().split("\n")
                suffix = lines[1] if len(lines) > 1 else ""
                item.setText(f"{name}\n{suffix}")
                break

    def show_stats(self, stats: dict[str, Any]) -> None:
        lines = [
            f"Sessions:       {stats.get('total_sessions', 0)}",
            f"User messages:  {stats.get('total_user_messages', 0)}",
            f"PIM snapshots:  {stats.get('total_pim_snapshots', 0)}",
            f"NiFi snapshots: {stats.get('total_nifi_snapshots', 0)}",
            f"LLM calls:      {stats.get('total_llm_calls', 0)}",
        ]
        avg = stats.get("avg_duration_ms")
        lines.append(f"Avg gen time:   {avg} ms" if avg else "Avg gen time:   \u2014")

        top_models = stats.get("top_models", [])
        if top_models:
            lines.append("\nTop models:")
            for m in top_models:
                lines.append(f"  {m['model'] or '?':30s} {m['count']}")

        top_providers = stats.get("top_providers", [])
        if top_providers:
            lines.append("\nProviders:")
            for p in top_providers:
                lines.append(f"  {p['provider'] or '?':20s} {p['count']}")

        by_purpose = stats.get("calls_by_purpose", [])
        if by_purpose:
            lines.append("\nCalls by purpose:")
            for p in by_purpose:
                lines.append(f"  {p['purpose']:20s} {p['count']}")

        self._stats_view.setPlainText("\n".join(lines))

    # ------------------------------------------------------------------
    # Internal slots
    # ------------------------------------------------------------------

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        session_id = item.data(Qt.ItemDataRole.UserRole)
        if session_id is not None:
            self.session_selected.emit(int(session_id))

    def _show_session_context_menu(self, pos: QPoint) -> None:
        item = self._session_list.itemAt(pos)
        if item is None:
            return

        session_id: int = int(item.data(Qt.ItemDataRole.UserRole))
        current_name = item.text().split("\n")[0]

        menu = QMenu(self)
        act_rename = menu.addAction("Rename")
        act_delete = menu.addAction("Delete")

        chosen = menu.exec(self._session_list.mapToGlobal(pos))

        if chosen == act_rename:
            new_name, ok = QInputDialog.getText(
                self,
                "Rename Session",
                "New name:",
                text=current_name,
            )
            if ok and new_name.strip():
                self.session_rename_requested.emit(session_id, new_name.strip())

        elif chosen == act_delete:
            reply = QMessageBox.question(
                self,
                "Delete Session",
                f"Delete session \"{current_name}\"?\nThis action cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.session_delete_requested.emit(session_id)
