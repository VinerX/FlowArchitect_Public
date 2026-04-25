"""FlowArchitect UI — Dual Theme System (Dark / Light)

Usage:
    from src.ui.theme import DARK_STYLESHEET, LIGHT_STYLESHEET, DARK, LIGHT

The ThemeManager (src/ui/theme_manager.py) handles applying the correct
stylesheet and notifying widgets to re-render.
"""
from __future__ import annotations

# ── Dark palette ──────────────────────────────────────────────────────────────
DARK: dict[str, str] = {
    "bg_base":        "#0D1117",
    "bg_panel":       "#161B27",
    "bg_sidebar":     "#111622",
    "bg_elevated":    "#1E2436",
    "bg_input":       "#1A2030",
    "bg_hover":       "#252D40",
    "bg_active":      "#1D3461",
    "border":         "#252D40",
    "border_strong":  "#303A50",
    "border_focus":   "#3B82F6",
    "text_primary":   "#F1F5F9",   # crisp white-ish
    "text_secondary": "#94A3B8",   # slate-400
    "text_muted":     "#64748B",   # slate-500
    "accent":         "#3B82F6",
    "accent_hover":   "#2563EB",
    "user_bubble":    "#1A3050",
    "user_text":      "#BAE6FD",   # sky-200
    "bot_bubble":     "#1E2436",
    "bot_text":       "#E2E8F0",   # slate-200
    "service_info":   "#1A2D4A",
    "service_info_text": "#7DD3FC",  # sky-300
    "service_ok":     "#0A2E1E",
    "service_ok_text": "#4ADE80",   # green-400
    "service_err":    "#2A0E0E",
    "service_err_text": "#F87171",  # red-400
    "service_warn":   "#2D1A00",   # amber dark bg
    "service_warn_text": "#FCD34D", # amber-300
    "success_bg":     "#0A2E1E",
    "success_text":   "#4ADE80",
    "nifi_bg":        "#0A2E1E",
    "nifi_border":    "#1A5E30",
    "nifi_text":      "#4ADE80",
    "dialog_bg":      "#0D1117",   # for QGroupBox::title bg fix
}

# ── Light palette ─────────────────────────────────────────────────────────────
LIGHT: dict[str, str] = {
    "bg_base":        "#F8FAFC",
    "bg_panel":       "#FFFFFF",
    "bg_sidebar":     "#F1F5F9",
    "bg_elevated":    "#FFFFFF",
    "bg_input":       "#F8FAFC",
    "bg_hover":       "#E2E8F0",
    "bg_active":      "#DBEAFE",
    "border":         "#E2E8F0",
    "border_strong":  "#CBD5E1",
    "border_focus":   "#3B82F6",
    "text_primary":   "#0F172A",
    "text_secondary": "#475569",
    "text_muted":     "#94A3B8",
    "accent":         "#2563EB",
    "accent_hover":   "#1D4ED8",
    "user_bubble":    "#DBEAFE",
    "user_text":      "#1E3A8A",
    "bot_bubble":     "#F1F5F9",
    "bot_text":       "#1E293B",
    "service_info":   "#EFF6FF",
    "service_info_text": "#1D4ED8",
    "service_ok":     "#F0FDF4",
    "service_ok_text": "#15803D",
    "service_err":    "#FEF2F2",
    "service_err_text": "#DC2626",
    "service_warn":   "#FFFBEB",   # amber light bg
    "service_warn_text": "#D97706", # amber-600
    "success_bg":     "#F0FDF4",
    "success_text":   "#15803D",
    "nifi_bg":        "#F0FDF4",
    "nifi_border":    "#86EFAC",
    "nifi_text":      "#15803D",
    "dialog_bg":      "#F8FAFC",
}


def _make_stylesheet(p: dict[str, str]) -> str:
    return f"""
/* ── Global ──────────────────────────────────────────────────────────────── */
* {{
    font-family: "Segoe UI", system-ui, sans-serif;
    font-size: 13px;
    color: {p['text_primary']};
}}
QMainWindow {{
    background: {p['bg_base']};
}}
QWidget {{
    background: transparent;
}}

/* ── Header bar ───────────────────────────────────────────────────────────── */
QFrame#header {{
    background: {p['bg_sidebar']};
    border-bottom: 1px solid {p['border_strong']};
    min-height: 44px;
    max-height: 44px;
}}
QLabel#app_title {{
    font-size: 14px;
    font-weight: 700;
    color: {p['text_primary']};
    letter-spacing: 0.3px;
    background: transparent;
}}
QLabel#app_subtitle {{
    font-size: 11px;
    color: {p['text_muted']};
    letter-spacing: 0.5px;
    background: transparent;
}}
QPushButton#stage_provider_btn {{
    background: {p['bg_input']};
    color: {p['text_secondary']};
    border: 1px solid {p['border_strong']};
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 600;
    max-height: 28px;
}}
QPushButton#stage_provider_btn:hover {{
    background: {p['bg_hover']};
    color: {p['text_primary']};
    border-color: {p['accent']};
}}
QToolButton#btn_settings {{
    background: transparent;
    border: none;
    color: {p['text_secondary']};
    padding: 6px 8px;
    border-radius: 6px;
    font-size: 16px;
}}
QToolButton#btn_settings:hover {{
    background: {p['bg_hover']};
    color: {p['text_primary']};
}}

/* ── Status bar ───────────────────────────────────────────────────────────── */
QStatusBar {{
    background: {p['bg_sidebar']};
    color: {p['text_muted']};
    border-top: 1px solid {p['border']};
    font-size: 11px;
    padding: 0 8px;
}}
QStatusBar::item {{
    border: none;
}}

/* ── Splitter ─────────────────────────────────────────────────────────────── */
QSplitter {{
    background: {p['bg_base']};
}}
QSplitter::handle {{
    background: {p['border']};
    width: 1px;
    height: 1px;
}}
QSplitter::handle:hover {{
    background: {p['accent']};
}}

/* ── Sidebar (history panel) ──────────────────────────────────────────────── */
QWidget#sidebar {{
    background: {p['bg_sidebar']};
    border-right: 1px solid {p['border_strong']};
}}
QWidget#sidebar QLabel {{
    color: {p['text_secondary']};
    background: transparent;
}}
QWidget#sidebar QToolButton {{
    color: {p['text_secondary']};
    background: transparent;
    border: none;
    padding: 4px 6px;
    border-radius: 4px;
}}
QWidget#sidebar QToolButton:hover {{
    background: {p['bg_hover']};
    color: {p['text_primary']};
}}
QWidget#sidebar QTabWidget::pane {{
    border: none;
    background: {p['bg_sidebar']};
}}
QWidget#sidebar QTabBar {{
    background: {p['bg_sidebar']};
}}
QWidget#sidebar QTabBar::tab {{
    background: transparent;
    color: {p['text_muted']};
    padding: 6px 10px;
    border: none;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.6px;
}}
QWidget#sidebar QTabBar::tab:selected {{
    color: {p['accent']};
    border-bottom: 2px solid {p['accent']};
}}
QWidget#sidebar QTabBar::tab:hover:!selected {{
    color: {p['text_primary']};
}}
QWidget#sidebar QListWidget {{
    background: transparent;
    border: none;
    color: {p['text_secondary']};
    outline: none;
}}
QWidget#sidebar QListWidget::item {{
    padding: 8px 10px;
    border-radius: 6px;
    margin: 1px 4px;
    font-size: 12px;
    border: 1px solid transparent;
}}
QWidget#sidebar QListWidget::item:hover {{
    background: {p['bg_hover']};
    color: {p['text_primary']};
    border-color: {p['border_strong']};
}}
QWidget#sidebar QListWidget::item:selected {{
    background: {p['bg_active']};
    color: {p['text_primary']};
    border-color: {p['accent']};
}}
QWidget#sidebar QScrollBar:vertical {{
    background: transparent;
    width: 5px;
    margin: 0;
}}
QWidget#sidebar QScrollBar::handle:vertical {{
    background: {p['border_strong']};
    border-radius: 2px;
    min-height: 20px;
}}
QWidget#sidebar QScrollBar::handle:vertical:hover {{
    background: {p['text_muted']};
}}
QWidget#sidebar QScrollBar::add-line:vertical,
QWidget#sidebar QScrollBar::sub-line:vertical {{
    height: 0;
}}
QWidget#sidebar QTextEdit {{
    background: transparent;
    color: {p['text_secondary']};
    border: none;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 11px;
    selection-background-color: {p['bg_active']};
}}

/* ── Chat panel ───────────────────────────────────────────────────────────── */
QWidget#chat_panel {{
    background: {p['bg_panel']};
    border-right: 1px solid {p['border_strong']};
}}
QLabel#chat_header_label {{
    font-size: 11px;
    font-weight: 700;
    color: {p['text_muted']};
    letter-spacing: 0.8px;
    padding: 0 2px;
    background: transparent;
}}
QFrame#chat_header {{
    background: {p['bg_sidebar']};
    border-bottom: 1px solid {p['border_strong']};
    min-height: 44px;
    max-height: 44px;
}}
QTextEdit#chat_history {{
    background: {p['bg_panel']};
    border: none;
    padding: 8px 4px;
    selection-background-color: {p['bg_active']};
    font-size: 13px;
    color: {p['text_primary']};
}}
QScrollArea#chat_scroll {{
    background: {p['bg_panel']};
    border: none;
}}
QWidget#chat_msg_container {{
    background: {p['bg_panel']};
}}
QFrame#chat_input_frame {{
    background: {p['bg_sidebar']};
    border-top: 1px solid {p['border_strong']};
    padding: 8px;
}}
QPlainTextEdit#chat_input {{
    background: {p['bg_input']};
    border: 1.5px solid {p['border_strong']};
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 13px;
    color: {p['text_primary']};
    selection-background-color: {p['bg_active']};
}}
QPlainTextEdit#chat_input:focus {{
    border-color: {p['border_focus']};
}}

/* ── Editor panel ─────────────────────────────────────────────────────────── */
QWidget#editor_panel {{
    background: {p['bg_panel']};
}}
QFrame#editor_toolbar {{
    background: {p['bg_sidebar']};
    border-bottom: 1px solid {p['border_strong']};
    min-height: 44px;
    max-height: 44px;
}}
QPlainTextEdit#code_view {{
    background: {p['bg_panel']};
    border: none;
    font-family: "Cascadia Code", "Consolas", "Courier New", monospace;
    font-size: 12px;
    padding: 12px;
    color: {p['text_primary']};
    selection-background-color: {p['bg_active']};
}}

/* ── Tabs ─────────────────────────────────────────────────────────────────── */
QTabWidget::pane {{
    border: none;
    background: {p['bg_panel']};
}}
QTabWidget QTabBar {{
    background: {p['bg_sidebar']};
    border-bottom: 1px solid {p['border_strong']};
}}
QTabBar::tab {{
    background: transparent;
    color: {p['text_muted']};
    padding: 8px 18px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: 12px;
    font-weight: 600;
    min-width: 80px;
}}
QTabBar::tab:selected {{
    color: {p['accent']};
    border-bottom: 2px solid {p['accent']};
}}
QTabBar::tab:hover:!selected {{
    color: {p['text_primary']};
    background: {p['bg_hover']};
}}

/* ── Buttons ─────────────────────────────────────────────────────────────── */
QPushButton {{
    background: {p['bg_elevated']};
    color: {p['text_secondary']};
    border: 1px solid {p['border_strong']};
    border-radius: 6px;
    padding: 5px 14px;
    font-size: 12px;
    font-weight: 500;
    min-height: 28px;
}}
QPushButton:hover {{
    background: {p['bg_hover']};
    color: {p['text_primary']};
    border-color: {p['text_muted']};
}}
QPushButton:pressed {{
    background: {p['bg_active']};
    border-color: {p['accent']};
}}
QPushButton:disabled {{
    color: {p['text_muted']};
    border-color: {p['border']};
    background: {p['bg_panel']};
}}
QPushButton#btn_primary {{
    background: {p['accent']};
    color: #FFFFFF;
    border: none;
    font-weight: 600;
}}
QPushButton#btn_primary:hover {{
    background: {p['accent_hover']};
}}
QPushButton#btn_primary:disabled {{
    background: {p['bg_active']};
    color: {p['text_muted']};
    border: none;
}}
QPushButton#btn_send {{
    background: {p['accent']};
    color: #FFFFFF;
    border: none;
    border-radius: 7px;
    padding: 6px 18px;
    font-size: 13px;
    font-weight: 600;
    min-height: 36px;
    min-width: 72px;
}}
QPushButton#btn_send:hover {{
    background: {p['accent_hover']};
}}
QPushButton#btn_nifi {{
    background: {p['nifi_bg']};
    color: {p['nifi_text']};
    border: 1px solid {p['nifi_border']};
    font-weight: 600;
}}
QPushButton#btn_nifi:hover {{
    border-color: {p['nifi_text']};
}}
QPushButton#btn_nifi:disabled {{
    background: {p['bg_panel']};
    color: {p['text_muted']};
    border-color: {p['border']};
}}

/* ── ComboBox ─────────────────────────────────────────────────────────────── */
QComboBox {{
    background: {p['bg_input']};
    border: 1px solid {p['border_strong']};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 12px;
    min-height: 28px;
    color: {p['text_secondary']};
    selection-background-color: {p['bg_active']};
}}
QComboBox:hover {{
    border-color: {p['text_muted']};
    color: {p['text_primary']};
}}
QComboBox:focus {{
    border-color: {p['border_focus']};
    color: {p['text_primary']};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background: {p['bg_elevated']};
    border: 1px solid {p['border_strong']};
    border-radius: 6px;
    selection-background-color: {p['bg_active']};
    selection-color: {p['text_primary']};
    color: {p['text_secondary']};
    padding: 4px;
    outline: none;
}}
QComboBox QAbstractItemView::item {{
    padding: 6px 10px;
    border-radius: 4px;
    min-height: 24px;
}}

/* ── Scrollbars ───────────────────────────────────────────────────────────── */
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {p['border_strong']};
    border-radius: 3px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background: {p['text_muted']};
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 6px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {p['border_strong']};
    border-radius: 3px;
    min-width: 20px;
}}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ── Settings dialog ──────────────────────────────────────────────────────── */
QDialog {{
    background: {p['bg_base']};
}}
QGroupBox {{
    background: {p['bg_elevated']};
    border: 1px solid {p['border_strong']};
    border-radius: 8px;
    margin-top: 22px;
    padding: 18px 12px 12px 12px;
    color: {p['text_muted']};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: -2px;
    padding: 2px 8px;
    background: {p['dialog_bg']};
    border-radius: 3px;
}}
QLineEdit {{
    background: {p['bg_input']};
    border: 1px solid {p['border_strong']};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 13px;
    color: {p['text_primary']};
    selection-background-color: {p['bg_active']};
}}
QLineEdit:focus {{
    border-color: {p['border_focus']};
}}
QLineEdit:read-only {{
    background: {p['bg_panel']};
    color: {p['text_muted']};
}}
QPlainTextEdit {{
    background: {p['bg_input']};
    border: 1px solid {p['border_strong']};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 13px;
    color: {p['text_primary']};
    selection-background-color: {p['bg_active']};
}}
QPlainTextEdit:focus {{
    border-color: {p['border_focus']};
}}
QCheckBox {{
    color: {p['text_secondary']};
    spacing: 6px;
    background: transparent;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1.5px solid {p['border_strong']};
    border-radius: 4px;
    background: {p['bg_input']};
}}
QCheckBox::indicator:checked {{
    background: {p['accent']};
    border-color: {p['accent']};
}}
QTabWidget QWidget {{
    background: {p['bg_base']};
}}

/* ── Placeholder panel ────────────────────────────────────────────────────── */
QWidget#placeholder_panel {{
    background: {p['bg_sidebar']};
    border-top: 1px solid {p['border_strong']};
}}
QFrame#placeholder_header {{
    background: {p['bg_sidebar']};
    border-top: 1px solid {p['border_strong']};
    min-height: 30px;
    max-height: 30px;
}}
QPushButton#placeholder_toggle {{
    background: transparent;
    border: none;
    text-align: left;
    color: {p['text_secondary']};
    font-size: 12px;
    font-weight: 600;
    padding: 0 4px;
    min-height: 28px;
}}
QPushButton#placeholder_toggle:hover {{
    color: {p['text_primary']};
}}
QLabel#placeholder_hint {{
    color: {p['text_muted']};
    background: transparent;
}}
QFrame#placeholder_content {{
    background: {p['bg_panel']};
}}
QTableWidget#placeholder_table {{
    background: {p['bg_panel']};
    border: none;
    border-top: 1px solid {p['border']};
    gridline-color: {p['border']};
    color: {p['text_primary']};
    selection-background-color: transparent;
    alternate-background-color: {p['bg_elevated']};
}}
QTableWidget#placeholder_table::item {{
    padding: 2px 6px;
    border: none;
    background: transparent;
}}
QTableWidget#placeholder_table QHeaderView {{
    background: {p['bg_sidebar']};
    border: none;
}}
QTableWidget#placeholder_table QHeaderView::section {{
    background: {p['bg_sidebar']};
    color: {p['text_muted']};
    border: none;
    border-bottom: 1px solid {p['border_strong']};
    border-right: 1px solid {p['border']};
    padding: 4px 6px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.4px;
}}
QTableWidget#placeholder_table QHeaderView::section:last {{
    border-right: none;
}}
QTableWidget#model_picker_table {{
    background: {p['bg_panel']};
    alternate-background-color: {p['bg_elevated']};
    color: {p['text_primary']};
    gridline-color: {p['border']};
    border: 1px solid {p['border_strong']};
    selection-background-color: {p['bg_active']};
    selection-color: {p['text_primary']};
}}
QTableWidget#model_picker_table::item {{
    background: transparent;
    padding: 4px 8px;
}}
QTableWidget#model_picker_table::item:selected {{
    background: {p['bg_active']};
    color: {p['text_primary']};
}}
QTableWidget#model_picker_table QHeaderView::section {{
    background: {p['bg_sidebar']};
    color: {p['text_muted']};
    border: none;
    border-bottom: 1px solid {p['border_strong']};
    border-right: 1px solid {p['border']};
    padding: 6px 8px;
    font-size: 11px;
    font-weight: 700;
}}
QLineEdit#placeholder_value_edit {{
    background: {p['bg_input']};
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 3px 8px;
    color: {p['text_primary']};
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 12px;
}}
QLineEdit#placeholder_value_edit:focus {{
    border-color: {p['border_focus']};
    background: {p['bg_elevated']};
}}
QLineEdit#placeholder_value_edit:hover {{
    border-color: {p['border_strong']};
}}

/* ── Message boxes ────────────────────────────────────────────────────────── */
QMessageBox {{
    background: {p['bg_elevated']};
}}
QMessageBox QLabel {{
    color: {p['text_primary']};
    background: transparent;
}}
QMessageBox QPushButton {{
    min-width: 72px;
}}
QDialogButtonBox QPushButton {{
    min-width: 80px;
}}

/* ── Menu bar ─────────────────────────────────────────────────────────────── */
QMenuBar {{
    background: {p['bg_sidebar']};
    border-bottom: 1px solid {p['border']};
    padding: 2px 0;
}}
QMenuBar::item {{
    padding: 4px 10px;
    border-radius: 4px;
    color: {p['text_secondary']};
    background: transparent;
}}
QMenuBar::item:selected {{
    background: {p['bg_hover']};
    color: {p['text_primary']};
}}
QMenu {{
    background: {p['bg_elevated']};
    border: 1px solid {p['border_strong']};
    border-radius: 8px;
    padding: 4px;
    color: {p['text_primary']};
}}
QMenu::item {{
    padding: 7px 24px 7px 12px;
    border-radius: 5px;
    color: {p['text_secondary']};
}}
QMenu::item:selected {{
    background: {p['bg_active']};
    color: {p['text_primary']};
}}

/* ── Tooltip ──────────────────────────────────────────────────────────────── */
QToolTip {{
    background: {p['bg_elevated']};
    color: {p['text_primary']};
    border: 1px solid {p['border_strong']};
    border-radius: 5px;
    padding: 5px 8px;
    font-size: 12px;
}}
"""


DARK_STYLESHEET: str = _make_stylesheet(DARK)
LIGHT_STYLESHEET: str = _make_stylesheet(LIGHT)

# Backward-compat alias (dark by default)
STYLESHEET = DARK_STYLESHEET
PALETTE = DARK
