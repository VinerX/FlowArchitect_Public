from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.ui.theme_manager import ThemeManager

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_COLLAPSE_THRESHOLD = 500
_COLLAPSE_PREVIEW = 300


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _ChildRightClickFilter(QObject):
    """Forwards ContextMenu events from child widgets to the parent bubble/service widget."""

    def __init__(self, target: QWidget, parent: QObject | None = None):
        super().__init__(parent)
        self._target = target

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.ContextMenu:
            self._target.contextMenuEvent(event)
            return True
        return False


def _open_detail_dialog(parent: QWidget, text: str) -> None:
    dlg = QDialog(parent)
    dlg.setWindowTitle("Message Detail")
    dlg.resize(640, 480)
    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(12, 12, 12, 12)
    viewer = QPlainTextEdit(dlg)
    viewer.setPlainText(text)
    viewer.setReadOnly(True)
    viewer.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
    layout.addWidget(viewer)
    close_btn = QPushButton("Close", dlg)
    close_btn.clicked.connect(dlg.accept)
    layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignRight)
    dlg.exec()


# ---------------------------------------------------------------------------
# Input widget
# ---------------------------------------------------------------------------

class ChatInput(QPlainTextEdit):
    send_requested = pyqtSignal()

    def keyPressEvent(self, event):
        # Enter -> send, Shift+Enter -> newline
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                return super().keyPressEvent(event)
            event.accept()
            self.send_requested.emit()
            return
        super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Message bubble widgets
# ---------------------------------------------------------------------------

class _Bubble(QWidget):
    """TG-style chat bubble for user / assistant messages."""

    def __init__(
        self,
        is_user: bool,
        text: str,
        p: dict,
        on_delete=None,
        on_regenerate=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self._is_user = is_user
        self._full_text = text
        self._on_delete = on_delete
        self._on_regenerate = on_regenerate
        self._collapsed = len(text) > _COLLAPSE_THRESHOLD
        self._toggle_btn: QPushButton | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 3, 12, 3)
        outer.setSpacing(4)

        card = QFrame()
        card.setMaximumWidth(480)
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 8, 12, 10)
        card_layout.setSpacing(3)

        # Sender label
        sender = QLabel("You" if is_user else "FlowArchitect")
        sender.setStyleSheet(
            f"font-size: 10px; font-weight: 700; "
            f"color: {p['accent'] if is_user else p['text_muted']}; "
            "background: transparent; padding: 0; border: none;"
        )
        card_layout.addWidget(sender)

        # Message body
        display_text = text[:_COLLAPSE_PREVIEW] + "..." if self._collapsed else text
        self._body_label = QLabel(display_text)
        self._body_label.setWordWrap(True)
        self._body_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self._body_label.setStyleSheet(
            f"font-size: 13px; "
            f"color: {p['user_text'] if is_user else p['bot_text']}; "
            "background: transparent; padding: 0; border: none;"
        )
        card_layout.addWidget(self._body_label)

        # Collapse toggle button
        if len(text) > _COLLAPSE_THRESHOLD:
            self._toggle_btn = QPushButton("▼ Показать полностью")
            self._toggle_btn.setFlat(True)
            self._toggle_btn.setStyleSheet(
                f"font-size: 10px; color: {p['accent']}; "
                "background: transparent; border: none; padding: 0; text-align: left;"
            )
            self._toggle_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self._toggle_btn.clicked.connect(self._toggle_collapse)
            card_layout.addWidget(self._toggle_btn)

        bg = p["user_bubble"] if is_user else p["bot_bubble"]
        corner = (
            "border-bottom-right-radius: 3px;"
            if is_user
            else "border-bottom-left-radius: 3px;"
        )
        card.setStyleSheet(
            f"QFrame {{ background: {bg}; border-radius: 14px; {corner} }}"
        )

        if is_user:
            outer.addStretch(1)
            outer.addWidget(card, 0)
        else:
            outer.addWidget(card, 0)
            outer.addStretch(1)

        # Forward right-clicks from child labels to this widget's contextMenuEvent
        self._rclick_filter = _ChildRightClickFilter(target=self, parent=self)
        self._body_label.installEventFilter(self._rclick_filter)

    def _toggle_collapse(self) -> None:
        if self._collapsed:
            self._body_label.setText(self._full_text)
            self._toggle_btn.setText("▲ Свернуть")
            self._collapsed = False
        else:
            self._body_label.setText(self._full_text[:_COLLAPSE_PREVIEW] + "...")
            self._toggle_btn.setText("▼ Показать полностью")
            self._collapsed = True

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        act_copy = menu.addAction("Копировать")
        act_delete = menu.addAction("Удалить")
        act_regen = (
            menu.addAction("Перегенерировать")
            if (self._is_user and self._on_regenerate)
            else None
        )
        act_detail = (
            menu.addAction("Открыть подробно")
            if len(self._full_text) > _COLLAPSE_THRESHOLD
            else None
        )
        chosen = menu.exec(QCursor.pos())
        if chosen == act_copy:
            QApplication.clipboard().setText(self._full_text)
        elif chosen == act_delete and self._on_delete:
            self._on_delete()
        elif act_regen and chosen == act_regen:
            self._on_regenerate(self._full_text)
        elif act_detail and chosen == act_detail:
            _open_detail_dialog(self, self._full_text)


class _ServiceMsg(QWidget):
    """Centered service/status notification block."""

    _ICONS: dict[str, str] = {
        "system":       "✖",
        "service_err":  "✖",
        "service_ok":   "✔",
        "service_warn": "⚠",
        "service":      "ℹ",
    }

    def __init__(self, role: str, text: str, p: dict, on_delete=None, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self._role = role
        self._full_text = text
        self._on_delete = on_delete
        self._collapsed = len(text) > _COLLAPSE_THRESHOLD
        self._toggle_btn: QPushButton | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 4, 16, 4)
        outer.setSpacing(4)

        card = QFrame()

        if role in ("system", "service_err"):
            bg = p.get("service_err", p["bg_elevated"])
            fg = p.get("service_err_text", p["text_secondary"])
        elif role == "service_ok":
            bg = p.get("service_ok", p["bg_elevated"])
            fg = p.get("service_ok_text", p["text_secondary"])
        elif role == "service_warn":
            bg = p.get("service_warn", p["bg_elevated"])
            fg = p.get("service_warn_text", p["text_secondary"])
        else:  # "service" / info
            bg = p.get("service_info", p["bg_elevated"])
            fg = p.get("service_info_text", p["text_secondary"])

        icon = self._ICONS.get(role, "ℹ")
        card.setStyleSheet(f"QFrame {{ background: {bg}; border-radius: 10px; }}")

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 8, 12, 8)
        card_layout.setSpacing(3)

        display_text = (
            f"{icon}  {text[:_COLLAPSE_PREVIEW]}..."
            if self._collapsed
            else f"{icon}  {text}"
        )
        self._body_label = QLabel(display_text)
        self._body_label.setWordWrap(True)
        self._body_label.setStyleSheet(
            f"font-size: 11px; color: {fg}; background: transparent; border: none;"
        )
        card_layout.addWidget(self._body_label)

        if len(text) > _COLLAPSE_THRESHOLD:
            self._toggle_btn = QPushButton("▼ Показать полностью")
            self._toggle_btn.setFlat(True)
            self._toggle_btn.setStyleSheet(
                f"font-size: 10px; color: {fg}; "
                "background: transparent; border: none; padding: 0; text-align: left;"
            )
            self._toggle_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self._toggle_btn.clicked.connect(self._toggle_collapse)
            card_layout.addWidget(self._toggle_btn)

        outer.addStretch(1)
        outer.addWidget(card, 5)
        outer.addStretch(1)

        self._rclick_filter = _ChildRightClickFilter(target=self, parent=self)
        self._body_label.installEventFilter(self._rclick_filter)

    def _toggle_collapse(self) -> None:
        icon = self._ICONS.get(self._role, "ℹ")
        if self._collapsed:
            self._body_label.setText(f"{icon}  {self._full_text}")
            self._toggle_btn.setText("▲ Свернуть")
            self._collapsed = False
        else:
            self._body_label.setText(f"{icon}  {self._full_text[:_COLLAPSE_PREVIEW]}...")
            self._toggle_btn.setText("▼ Показать полностью")
            self._collapsed = True

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        act_copy = menu.addAction("Копировать")
        act_delete = menu.addAction("Удалить")
        act_detail = (
            menu.addAction("Открыть подробно")
            if len(self._full_text) > _COLLAPSE_THRESHOLD
            else None
        )
        chosen = menu.exec(QCursor.pos())
        if chosen == act_copy:
            QApplication.clipboard().setText(self._full_text)
        elif chosen == act_delete and self._on_delete:
            self._on_delete()
        elif act_detail and chosen == act_detail:
            _open_detail_dialog(self, self._full_text)


# ---------------------------------------------------------------------------
# Waiting indicator
# ---------------------------------------------------------------------------

class _WaitingBar(QWidget):
    """Animated stage indicator shown between chat and input while LLM is processing."""

    _SUFFIXES = ["   ", " .  ", " .. ", " ..."]
    _DEFAULT_STAGE = "Ожидаем ответа"

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._frame_idx = 0
        self._stage = self._DEFAULT_STAGE

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 6, 16, 6)

        self._label = QLabel(self._stage + self._SUFFIXES[0])
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        p = ThemeManager.get().palette
        self._label.setStyleSheet(
            f"font-size: 11px; color: {p.get('text_muted', '#64748B')}; "
            "background: transparent; border: none; font-style: italic;"
        )
        layout.addStretch(1)
        layout.addWidget(self._label)
        layout.addStretch(1)

        self._timer = QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._tick)

    def set_stage(self, stage: str) -> None:
        """Update the stage label and reset the animation."""
        self._stage = stage
        self._frame_idx = 0
        self._label.setText(self._stage + self._SUFFIXES[0])

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._frame_idx = 0
        self._label.setText(self._stage + self._SUFFIXES[0])
        self._timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._timer.stop()
        self._stage = self._DEFAULT_STAGE  # reset for next show

    def _tick(self) -> None:
        self._frame_idx = (self._frame_idx + 1) % len(self._SUFFIXES)
        self._label.setText(self._stage + self._SUFFIXES[self._frame_idx])


# ---------------------------------------------------------------------------
# Main chat widget
# ---------------------------------------------------------------------------

class ChatWidget(QWidget):
    send_message_signal = pyqtSignal(str)
    run_ui_task_signal = pyqtSignal(object)  # BaseController._ui() hook
    delete_message_requested = pyqtSignal(int)  # emits db_id when message has one
    regenerate_requested = pyqtSignal(str)      # emits original user query text

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("chat_panel")

        # Message store for re-rendering on theme change
        # Each entry: (role, text, db_id) — db_id may be None
        self._messages: list[tuple[str, str, int | None]] = []

        self.run_ui_task_signal.connect(self._run_ui_task)

        # ── Header ────────────────────────────────────────────────────
        header = QFrame()
        header.setObjectName("chat_header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 0, 14, 0)

        header_lbl = QLabel("CONVERSATION")
        header_lbl.setObjectName("chat_header_label")
        header_layout.addWidget(header_lbl)
        header_layout.addStretch()

        # ── Chat scroll area ───────────────────────────────────────────
        self._chat_scroll = QScrollArea(self)
        self._chat_scroll.setObjectName("chat_scroll")
        self._chat_scroll.setWidgetResizable(True)
        self._chat_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._chat_scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._msg_container = QWidget()
        self._msg_container.setObjectName("chat_msg_container")
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setContentsMargins(0, 8, 0, 8)
        self._msg_layout.setSpacing(4)
        self._msg_layout.addStretch(1)  # trailing stretch keeps messages at top

        self._chat_scroll.setWidget(self._msg_container)

        # Backward-compat alias
        self.history = self._chat_scroll

        # ── Input area ─────────────────────────────────────────────────
        input_frame = QFrame()
        input_frame.setObjectName("chat_input_frame")
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(10, 8, 10, 10)
        input_layout.setSpacing(8)

        self.user_entry = ChatInput(self)
        self.user_entry.setObjectName("chat_input")
        self.user_entry.setPlaceholderText("Type a message...  (Shift+Enter for newline)")
        self.user_entry.setMaximumBlockCount(1000)
        self.user_entry.setMaximumHeight(100)

        self.send_btn = QPushButton("Send", self)
        self.send_btn.setObjectName("btn_send")

        self.user_entry.send_requested.connect(self._emit_send)
        self.send_btn.clicked.connect(self._emit_send)

        input_layout.addWidget(self.user_entry, 1)
        input_layout.addWidget(self.send_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        # ── Waiting bar ────────────────────────────────────────────────
        self._waiting_bar = _WaitingBar(self)
        self._waiting_bar.hide()

        # ── Root layout ────────────────────────────────────────────────
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(self._chat_scroll, 1)
        layout.addWidget(self._waiting_bar)
        layout.addWidget(input_frame)
        self.setLayout(layout)

        ThemeManager.get().register_on_change(self._on_theme_changed)

    # ------------------------------------------------------------------
    # Thread-safe UI dispatch
    # ------------------------------------------------------------------

    def _run_ui_task(self, fn):
        if callable(fn):
            fn()

    # ------------------------------------------------------------------
    # Theme change
    # ------------------------------------------------------------------

    def _on_theme_changed(self, _theme_name: str) -> None:
        self._render_all()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _emit_send(self):
        text = (self.user_entry.toPlainText() or "").strip()
        if not text:
            return
        self.send_message_signal.emit(text)

    # ------------------------------------------------------------------
    # Public API (called by ChatController)
    # ------------------------------------------------------------------

    def clear_input(self):
        self.user_entry.clear()

    def clear_messages(self):
        self._messages.clear()
        self._clear_msg_layout()

    def show_waiting(self, stage: str = "") -> None:
        if stage:
            self._waiting_bar.set_stage(stage)
        self._waiting_bar.show()

    def set_waiting_stage(self, stage: str) -> None:
        self._waiting_bar.set_stage(stage)

    def hide_waiting(self) -> None:
        self._waiting_bar.hide()

    def append_message(self, role: str, text: str, db_id: int | None = None) -> None:
        """Append a message to the chat history.

        Roles:
          user / human         → right-aligned TG-style user bubble
          assistant / bot / "" → left-aligned assistant bubble
          system               → service block at error level (red)
          service_err          → service block at error level (red)
          service_ok           → service block at success level (green)
          service_warn         → service block at warning level (amber)
          service              → service block at info level (blue)
        """
        role = (role or "").strip().lower()
        self._messages.append((role, text, db_id))
        idx = len(self._messages) - 1
        w = self._make_widget(role, text, idx)
        self._add_msg_widget(w)

    def update_last_message_db_id(self, db_id: int) -> None:
        """Update the db_id of the most recently appended message."""
        if self._messages:
            role, text, _ = self._messages[-1]
            self._messages[-1] = (role, text, db_id)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def _delete_message(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._messages):
            return
        _, _, db_id = self._messages[idx]
        del self._messages[idx]
        self._render_all()
        if db_id is not None:
            self.delete_message_requested.emit(db_id)

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    def _render_all(self) -> None:
        """Clear and re-render all stored messages with current palette."""
        self._clear_msg_layout()
        for idx, (role, text, _db_id) in enumerate(self._messages):
            w = self._make_widget(role, text, idx)
            self._add_msg_widget(w, scroll=False)
        self._scroll_to_bottom()

    def _make_widget(self, role: str, text: str, idx: int) -> QWidget:
        p = ThemeManager.get().palette
        on_delete = lambda _i=idx: self._delete_message(_i)
        if role in ("system", "service", "service_ok", "service_err", "service_warn"):
            return _ServiceMsg(role, text, p, on_delete=on_delete)
        is_user = role in ("user", "human")
        on_regenerate = (
            (lambda _t=text: self.regenerate_requested.emit(_t)) if is_user else None
        )
        return _Bubble(is_user, text, p, on_delete=on_delete, on_regenerate=on_regenerate)

    def _clear_msg_layout(self) -> None:
        """Remove all message widgets, leave only the trailing stretch."""
        while self._msg_layout.count():
            item = self._msg_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._msg_layout.addStretch(1)

    def _add_msg_widget(self, w: QWidget, scroll: bool = True) -> None:
        # Insert before the trailing stretch (always last item)
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, w)
        if scroll:
            self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        QTimer.singleShot(
            0,
            lambda: self._chat_scroll.verticalScrollBar().setValue(
                self._chat_scroll.verticalScrollBar().maximum()
            ),
        )
