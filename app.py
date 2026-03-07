from __future__ import annotations

from datetime import datetime
import hashlib
import re
import sys
import unicodedata

from PySide6.QtCore import QDateTime, QEvent, QItemSelectionModel, QMargins, QPoint, QPointF, QSize, QTimer, Qt, QObject
from PySide6.QtCharts import QCategoryAxis, QChart, QChartView, QDateTimeAxis, QLineSeries, QValueAxis
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsLineItem,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QStackedWidget,
    QStyle,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from db import (
    add_net_worth_snapshot,
    add_liability,
    add_asset,
    delete_liability,
    delete_assets,
    delete_snapshot,
    fetch_asset_classes,
    fetch_assets,
    fetch_categories,
    fetch_exchange_rates,
    fetch_liabilities,
    fetch_net_worth_snapshots,
    fetch_snapshot_asset_items,
    fetch_snapshot_liability_items,
    init_db,
    update_asset_details,
    update_liability,
    update_asset_tag,
    update_asset_tag,
    update_assets_class,
    fetch_user_settings,
    register_auth_user,
    update_auth_session,
    clear_auth_session,
    reset_auth_password,
    update_financial_profile,
    update_user_profile,
    update_security,
    update_base_currency,
    update_category_targets,
)

CURRENCY_SYMBOLS: dict[str, str] = {
    "INR": "₹",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
}


def normalize_currency(currency: str | None) -> str:
    return (currency or "INR").strip().upper() or "INR"


def format_currency(value: float, currency: str = "INR") -> str:
    code = normalize_currency(currency)
    symbol = CURRENCY_SYMBOLS.get(code)
    if symbol:
        return f"{symbol}{value:,.0f}"
    return f"{code} {value:,.0f}"


def format_indian_number(value: float) -> str:
    integer_value = int(round(value))
    sign = "-" if integer_value < 0 else ""
    digits = str(abs(integer_value))
    if len(digits) <= 3:
        return f"{sign}{digits}"

    last_three = digits[-3:]
    remaining = digits[:-3]
    chunks: list[str] = []
    while len(remaining) > 2:
        chunks.insert(0, remaining[-2:])
        remaining = remaining[:-2]
    if remaining:
        chunks.insert(0, remaining)
    return f"{sign}{','.join(chunks + [last_three])}"


def format_liability_currency(value: float, currency: str = "INR") -> str:
    code = normalize_currency(currency)
    if code == "INR":
        return f"₹{format_indian_number(value)}"
    return format_currency(value, code)


def format_compact_inr(value: float) -> str:
    absolute_value = abs(value)
    if absolute_value >= 10000000:
        return f"₹{value / 10000000:.1f}Cr"
    if absolute_value >= 100000:
        return f"₹{value / 100000:.1f}L"
    if absolute_value >= 1000:
        return f"₹{value / 1000:.1f}K"
    return format_currency(value, "INR")


def format_signed_compact_inr(value: float) -> str:
    sign = "-" if value < 0 else "+"
    return f"{sign}{format_compact_inr(abs(value))}"


def calculate_months_remaining(target_date_str: str) -> int:
    try:
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d")
        now = datetime.now()
        months = (target_date.year - now.year) * 12 + (target_date.month - now.month)
        return max(0, months)
    except Exception:
        return 0


def calculate_required_pmt(fv: float, pv: float, annual_rate_pct: float, months: int) -> float:
    if fv <= pv or months <= 0:
        return 0.0
        
    if annual_rate_pct <= 0:
        return (fv - pv) / months
        
    r = (annual_rate_pct / 100.0) / 12.0
    # PMT = (FV - PV * (1 + r)^n) * r / ((1 + r)^n - 1)
    fv_compounded = pv * ((1 + r) ** months)
    pmt = (fv - fv_compounded) * r / (((1 + r) ** months) - 1)
    return max(0.0, pmt)


def format_percent(value: float) -> str:
    return f"{value:+.1f}%"


def calculate_change_pct(invested: float, value: float) -> float:
    if invested == 0:
        return 0.0
    return ((value - invested) / invested) * 100


def parse_amount(text: str) -> float:
    cleaned = text.strip().replace(",", "")
    return float(cleaned)


def hash_secret(raw_value: str) -> str:
    return hashlib.sha256(raw_value.encode("utf-8")).hexdigest()


def is_auth_registered(settings_row: object | None) -> bool:
    if settings_row is None:
        return False
    return int(settings_row["auth_registered"] or 0) == 1


def auth_password_matches(settings_row: object | None, raw_password: str) -> bool:
    if settings_row is None:
        return False

    stored = (settings_row["password_hash"] or "").strip()
    if not stored:
        return False

    candidate_hash = hash_secret(raw_password)
    return stored == candidate_hash or stored == raw_password


def asset_count_label(count: int) -> str:
    unit = "asset" if count == 1 else "assets"
    return f"{count} {unit}"


def split_asset_tags(tag_text: str | None) -> list[str]:
    if not tag_text:
        return []

    parts = re.split(r"[,\n]+", tag_text)
    tags: list[str] = []
    seen: set[str] = set()
    for raw in parts:
        cleaned = raw.strip()
        if not cleaned:
            continue
        tag_key = cleaned.casefold()
        if tag_key in seen:
            continue
        seen.add(tag_key)
        tags.append(cleaned)
    return tags


def normalize_tag(tag: str) -> str:
    return tag.strip().casefold()


def normalize_search_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    lowered = without_marks.casefold()
    compact = "".join(char if char.isalnum() else " " for char in lowered)
    return " ".join(compact.split())


ADD_CLASS_ICON_MAP: dict[str, str] = {
    "STOCKS_EQUITY": "SP_ArrowUp",
    "MUTUAL_FUNDS": "SP_FileDialogDetailedView",
    "REAL_ESTATE": "SP_DirHomeIcon",
    "GOLD_SILVER": "SP_DialogOpenButton",
    "FD_RD": "SP_DriveHDIcon",
    "BONDS": "SP_FileIcon",
    "DEBT_FUNDS": "SP_ArrowRight",
    "EPF_PPF_NPS": "SP_DialogApplyButton",
    "SSY": "SP_DialogYesButton",
    "CRYPTO": "SP_BrowserReload",
    "INTERNATIONAL": "SP_BrowserStop",
    "EMPLOYER_STOCK": "SP_ComputerIcon",
    "CASH_SAVINGS": "SP_DriveNetIcon",
    "LIQUID_FUNDS": "SP_MediaPlay",
    "ARBITRAGE_FUNDS": "SP_BrowserReload",
    "COMMODITIES": "SP_DirIcon",
    "ULIP": "SP_DialogSaveButton",
    "MONEYBACK_INSURANCE": "SP_DialogResetButton",
    "ENDOWMENT_PLANS": "SP_FileDialogContentsView",
    "OTHER": "SP_FileDialogNewFolder",
}


class TooltipFrame(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setStyleSheet(
            """
            QFrame {
                background-color: #ffffff;
                border: 1px solid #d9d8d3;
                border-radius: 6px;
                padding: 6px 10px;
            }
            QLabel {
                border: none;
                background: transparent;
                padding: 0px;
                margin: 0px;
            }
            QLabel#tooltipValue {
                font-family: "Segoe UI";
                font-size: 15px;
                font-weight: 700;
                color: #22211f;
            }
            QLabel#tooltipSub {
                font-family: "Segoe UI";
                font-size: 11px;
                color: #6b6962;
                margin-top: 1px;
            }
            QLabel#tooltipChangePositive {
                font-family: "Segoe UI";
                font-size: 11px;
                font-weight: 600;
                color: #2b7a52;
                margin-top: 1px;
            }
            QLabel#tooltipChangeNegative {
                font-family: "Segoe UI";
                font-size: 11px;
                font-weight: 600;
                color: #c23b31;
                margin-top: 1px;
            }
            QLabel#tooltipChangeNeutral {
                font-family: "Segoe UI";
                font-size: 11px;
                font-weight: 600;
                color: #6b6962;
                margin-top: 1px;
            }
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self.value_label = QLabel()
        self.value_label.setObjectName("tooltipValue")
        layout.addWidget(self.value_label)
        
        self.date_label = QLabel()
        self.date_label.setObjectName("tooltipSub")
        layout.addWidget(self.date_label)
        
        self.change_label = QLabel()
        self.change_label.setObjectName("tooltipChangeNeutral")
        layout.addWidget(self.change_label)


class ChartHoverFilter(QObject):
    def __init__(self, window):
        super().__init__()
        self.window = window

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseMove:
            self.window._handle_chart_mouse_move(event.pos())
        elif event.type() == QEvent.Type.Leave:
            self.window._hide_chart_tooltip()
        return super().eventFilter(obj, event)


class GoalCard(QFrame):
    def __init__(self, goal_data, current_savings, months_remaining, pmt, action_handler=None):
        super().__init__()
        self.goal_data = dict(goal_data)
        self.goal_status = str(self.goal_data.get("status") or "ACTIVE").upper()
        self._action_handler = action_handler

        self.setObjectName("goalCard")
        self.setStyleSheet("QFrame#goalCard { background-color: #ffffff; border: 1px solid #d9d8d3; border-radius: 8px; }")
        self.setFixedWidth(340)
        self.setFixedHeight(220)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        
        # Header
        header = QHBoxLayout()
        name_lbl = QLabel(goal_data["name"])
        name_lbl.setStyleSheet('font-family: "Segoe UI", sans-serif; font-size: 15px; font-weight: bold; color: #22211f; border: none;')
        header.addWidget(name_lbl)

        if self.goal_status != "ACTIVE":
            status_lbl = QLabel("Paused" if self.goal_status == "PAUSED" else "Achieved")
            status_bg = "#f1ece2" if self.goal_status == "PAUSED" else "#e3efe8"
            status_fg = "#6b6962" if self.goal_status == "PAUSED" else "#2b7a52"
            status_lbl.setStyleSheet(
                f"background-color: {status_bg}; color: {status_fg}; border-radius: 4px; "
                "padding: 3px 6px; font-size: 10px; font-weight: 600;"
            )
            header.addWidget(status_lbl)

        header.addStretch()

        if self._action_handler is not None:
            menu_btn = QToolButton()
            menu_btn.setText("⋯")
            menu_btn.setCursor(Qt.PointingHandCursor)
            menu_btn.setStyleSheet(
                "QToolButton { border: none; color: #6b6962; font-size: 18px; padding: 0px 2px; }"
                "QToolButton:hover { color: #22211f; }"
            )
            menu_btn.clicked.connect(lambda: self._show_context_menu_at(menu_btn.mapToGlobal(QPoint(0, menu_btn.height()))))
            header.addWidget(menu_btn)

        layout.addLayout(header)
        
        # Subtitle
        year_str = goal_data["target_date"][:4]
        if goal_data.get("linked_asset_ids"):
            cat_str = "Specific Assets"
        else:
            cat_str = goal_data.get("tracking_label") or goal_data["asset_class_key"] or "All Categories"
        sub_lbl = QLabel(f"by {year_str} • {cat_str}")
        sub_lbl.setStyleSheet("font-size: 12px; color: #6b6962; border: none;")
        layout.addWidget(sub_lbl)
        
        layout.addSpacing(8)
        
        # Progress Bar 1: Savings
        savings_row = QHBoxLayout()
        s_lbl1 = QLabel("Savings")
        s_lbl1.setStyleSheet("font-size: 11px; color: #2b7a52; border: none;")
        
        target = goal_data["target_amount"]
        pct = (current_savings / target) * 100 if target > 0 else 0
        pct = min(100, max(0, pct))
        
        s_lbl2 = QLabel(f"{int(pct)}%")
        s_lbl2.setStyleSheet("font-size: 11px; color: #2b7a52; font-weight: bold; border: none;")
        savings_row.addWidget(s_lbl1)
        savings_row.addStretch()
        savings_row.addWidget(s_lbl2)
        
        layout.addLayout(savings_row)
        
        # Custom Savings Bar
        s_bar = QFrame()
        s_bar.setFixedHeight(6)
        s_bar.setStyleSheet("background-color: #e1e0db; border-radius: 3px; border: none;")
        
        s_fill = QFrame(s_bar)
        s_fill.setStyleSheet("background-color: #2b7a52; border-radius: 3px; border: none;")
        s_fill.setFixedHeight(6)
        s_fill.setFixedWidth(int((pct / 100) * 300)) # Approx 340 minus margins
        layout.addWidget(s_bar)
        
        # Text under savings bar
        from app import format_compact_inr # Local import safe here
        t_lbl = QLabel(f"{format_compact_inr(current_savings)} of {format_compact_inr(target)}")
        t_lbl.setStyleSheet("font-size: 11px; color: #6b6962; border: none;")
        t_lbl.setAlignment(Qt.AlignRight)
        layout.addWidget(t_lbl)
        
        layout.addStretch()
        
        # Action string
        if self.goal_status == "ACHIEVED":
            action_txt = "✓ Goal marked achieved"
            action_color = "#2b7a52"
            action_bg = "#e3efe8"
        elif self.goal_status == "PAUSED":
            action_txt = "Paused. Resume this goal to continue planning."
            action_color = "#6b6962"
            action_bg = "#f1ece2"
        elif pct >= 100:
            action_txt = "Goal Reached! 🎉"
            action_color = "#2b7a52"
            action_bg = "#e3efe8"
        elif months_remaining <= 0:
            action_txt = "Target date passed ⚠"
            action_color = "#cc4b38"
            action_bg = "#fae9e6"
        else:
            action_txt = f"✓ Invest {format_compact_inr(pmt)}/mo at {goal_data['expected_return_pct']}% p.a. to close gap"
            action_color = "#2b7a52"
            action_bg = "#e3efe8"
            
        action_pill = QLabel(action_txt)
        action_pill.setStyleSheet(f"background-color: {action_bg}; color: {action_color}; border-radius: 4px; padding: 6px; font-size: 11px; font-weight: 500;")
        action_pill.setWordWrap(True)
        layout.addWidget(action_pill)

    def contextMenuEvent(self, event) -> None:
        if self._action_handler is None:
            return super().contextMenuEvent(event)
        self._show_context_menu_at(event.globalPos())
        event.accept()

    def _show_context_menu_at(self, global_pos: QPoint) -> None:
        if self._action_handler is None:
            return

        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #ffffff; border: 1px solid #d9d8d3; padding: 4px 0; }"
            "QMenu::item { padding: 8px 16px; color: #22211f; }"
            "QMenu::item:selected { background-color: #f3f2ef; }"
        )

        view_action = menu.addAction("View")
        edit_action = menu.addAction("Edit")
        mark_action = None
        pause_resume_action = None
        if self.goal_status != "ACHIEVED":
            mark_action = menu.addAction("Mark Achieved")
            pause_resume_action = menu.addAction("Resume" if self.goal_status == "PAUSED" else "Pause")
        menu.addSeparator()
        delete_action = menu.addAction("Delete")

        selected = menu.exec(global_pos)
        if selected is None:
            return
        if selected == view_action:
            self._action_handler("view", self.goal_data)
        elif selected == edit_action:
            self._action_handler("edit", self.goal_data)
        elif mark_action is not None and selected == mark_action:
            self._action_handler("mark_achieved", self.goal_data)
        elif pause_resume_action is not None and selected == pause_resume_action:
            action_name = "resume" if self.goal_status == "PAUSED" else "pause"
            self._action_handler(action_name, self.goal_data)
        elif selected == delete_action:
            self._action_handler("delete", self.goal_data)


class AuthDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Portfolio Tracker - Sign In")
        self.setModal(True)
        self.setMinimumSize(460, 560)
        self.resize(460, 600)
        self.setStyleSheet(
            """
            QDialog {
                background: #f7f7f5;
            }
            QFrame#authCard {
                background: #ffffff;
                border: 1px solid #d9d8d3;
                border-radius: 10px;
            }
            QLabel#authTitle {
                font-size: 20px;
                font-weight: 700;
                color: #22211f;
            }
            QLabel#authSub {
                font-size: 12px;
                color: #6b6962;
            }
            QLabel#authLabel {
                font-size: 11px;
                color: #6b6962;
                font-family: "Courier New", monospace;
            }
            QLineEdit {
                border: 1px solid #d9d8d3;
                border-radius: 6px;
                background: #ffffff;
                padding: 9px 10px;
                min-height: 20px;
                font-size: 13px;
                color: #22211f;
            }
            QCheckBox {
                font-size: 12px;
                color: #3b3a36;
            }
            QPushButton#authPrimary {
                background: #2b7a52;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 10px 14px;
                min-height: 18px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton#authPrimary:hover {
                background: #236543;
            }
            QPushButton#authLink {
                background: transparent;
                color: #2b7a52;
                border: none;
                text-align: left;
                padding: 4px 0;
                font-size: 12px;
            }
            QPushButton#authLink:hover {
                color: #1d5c3a;
            }
            QLabel#authError {
                color: #c23b31;
                font-size: 12px;
                font-weight: 600;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(0)

        card = QFrame()
        card.setObjectName("authCard")
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(22, 20, 22, 18)
        card_l.setSpacing(10)
        root.addWidget(card)

        title = QLabel("Portfolio Tracker")
        title.setObjectName("authTitle")
        card_l.addWidget(title)

        sub = QLabel("Sign in to continue")
        sub.setObjectName("authSub")
        card_l.addWidget(sub)
        card_l.addSpacing(6)

        self.auth_error = QLabel("")
        self.auth_error.setObjectName("authError")
        self.auth_error.hide()
        card_l.addWidget(self.auth_error)

        self.auth_stack = QStackedWidget()
        card_l.addWidget(self.auth_stack, 1)

        self._build_login_view()
        self._build_register_view()
        self._build_forgot_view()
        self._normalize_auth_field_heights()

        settings = fetch_user_settings()
        if is_auth_registered(settings):
            self.auth_stack.setCurrentWidget(self.login_page)
            self.login_email_input.setText((settings["email"] or "").strip())
            self.keep_login_cb.setChecked(bool(settings["keep_logged_in"]))
        else:
            self.auth_stack.setCurrentWidget(self.register_page)
            self.register_keep_cb.setChecked(True)

    def _normalize_auth_field_heights(self) -> None:
        line_edits = self.findChildren(QLineEdit)
        for line_edit in line_edits:
            line_edit.setMinimumHeight(34)
        buttons = self.findChildren(QPushButton)
        for button in buttons:
            if button.objectName() == "authPrimary":
                button.setMinimumHeight(36)

    def _set_auth_error(self, message: str) -> None:
        if message:
            self.auth_error.setText(message)
            self.auth_error.show()
        else:
            self.auth_error.hide()
            self.auth_error.setText("")

    def _build_login_view(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        email_lbl = QLabel("Email")
        email_lbl.setObjectName("authLabel")
        layout.addWidget(email_lbl)
        self.login_email_input = QLineEdit()
        self.login_email_input.setPlaceholderText("you@example.com")
        layout.addWidget(self.login_email_input)

        password_lbl = QLabel("Password")
        password_lbl.setObjectName("authLabel")
        layout.addWidget(password_lbl)
        self.login_password_input = QLineEdit()
        self.login_password_input.setEchoMode(QLineEdit.Password)
        self.login_password_input.setPlaceholderText("Enter password")
        layout.addWidget(self.login_password_input)

        self.keep_login_cb = QCheckBox("Keep me logged in")
        layout.addWidget(self.keep_login_cb)
        layout.addSpacing(4)

        login_btn = QPushButton("Log In")
        login_btn.setObjectName("authPrimary")
        login_btn.setCursor(Qt.PointingHandCursor)
        login_btn.clicked.connect(self._on_login_clicked)
        layout.addWidget(login_btn)

        links = QHBoxLayout()
        forgot_btn = QPushButton("Forgot password?")
        forgot_btn.setObjectName("authLink")
        forgot_btn.setCursor(Qt.PointingHandCursor)
        forgot_btn.clicked.connect(lambda: self._switch_auth_page("forgot"))
        links.addWidget(forgot_btn)
        links.addStretch()
        register_btn = QPushButton("Create account")
        register_btn.setObjectName("authLink")
        register_btn.setCursor(Qt.PointingHandCursor)
        register_btn.clicked.connect(lambda: self._switch_auth_page("register"))
        links.addWidget(register_btn)
        layout.addLayout(links)
        layout.addStretch()

        self.login_page = page
        self.auth_stack.addWidget(page)

    def _build_register_view(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        name_lbl = QLabel("Display Name")
        name_lbl.setObjectName("authLabel")
        layout.addWidget(name_lbl)
        self.register_name_input = QLineEdit()
        self.register_name_input.setPlaceholderText("Your name")
        layout.addWidget(self.register_name_input)

        email_lbl = QLabel("Email")
        email_lbl.setObjectName("authLabel")
        layout.addWidget(email_lbl)
        self.register_email_input = QLineEdit()
        self.register_email_input.setPlaceholderText("you@example.com")
        layout.addWidget(self.register_email_input)

        password_lbl = QLabel("Password")
        password_lbl.setObjectName("authLabel")
        layout.addWidget(password_lbl)
        self.register_password_input = QLineEdit()
        self.register_password_input.setEchoMode(QLineEdit.Password)
        self.register_password_input.setPlaceholderText("Min 8 characters")
        layout.addWidget(self.register_password_input)

        confirm_lbl = QLabel("Confirm Password")
        confirm_lbl.setObjectName("authLabel")
        layout.addWidget(confirm_lbl)
        self.register_confirm_input = QLineEdit()
        self.register_confirm_input.setEchoMode(QLineEdit.Password)
        self.register_confirm_input.setPlaceholderText("Re-enter password")
        layout.addWidget(self.register_confirm_input)

        pin_lbl = QLabel("Recovery PIN (4 digits)")
        pin_lbl.setObjectName("authLabel")
        layout.addWidget(pin_lbl)
        self.register_pin_input = QLineEdit()
        self.register_pin_input.setMaxLength(4)
        self.register_pin_input.setPlaceholderText("Used for forgot password")
        layout.addWidget(self.register_pin_input)

        self.register_keep_cb = QCheckBox("Keep me logged in")
        layout.addWidget(self.register_keep_cb)
        layout.addSpacing(4)

        register_btn = QPushButton("Register")
        register_btn.setObjectName("authPrimary")
        register_btn.setCursor(Qt.PointingHandCursor)
        register_btn.clicked.connect(self._on_register_clicked)
        layout.addWidget(register_btn)

        login_link = QPushButton("Already have an account? Log in")
        login_link.setObjectName("authLink")
        login_link.setCursor(Qt.PointingHandCursor)
        login_link.clicked.connect(lambda: self._switch_auth_page("login"))
        layout.addWidget(login_link)
        layout.addStretch()

        self.register_page = page
        self.auth_stack.addWidget(page)

    def _build_forgot_view(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        helper = QLabel("Reset password with your registered email and recovery PIN.")
        helper.setObjectName("authSub")
        helper.setWordWrap(True)
        layout.addWidget(helper)

        email_lbl = QLabel("Email")
        email_lbl.setObjectName("authLabel")
        layout.addWidget(email_lbl)
        self.forgot_email_input = QLineEdit()
        self.forgot_email_input.setPlaceholderText("you@example.com")
        layout.addWidget(self.forgot_email_input)

        pin_lbl = QLabel("Recovery PIN")
        pin_lbl.setObjectName("authLabel")
        layout.addWidget(pin_lbl)
        self.forgot_pin_input = QLineEdit()
        self.forgot_pin_input.setMaxLength(4)
        self.forgot_pin_input.setPlaceholderText("4-digit PIN")
        layout.addWidget(self.forgot_pin_input)

        new_password_lbl = QLabel("New Password")
        new_password_lbl.setObjectName("authLabel")
        layout.addWidget(new_password_lbl)
        self.forgot_password_input = QLineEdit()
        self.forgot_password_input.setEchoMode(QLineEdit.Password)
        self.forgot_password_input.setPlaceholderText("Min 8 characters")
        layout.addWidget(self.forgot_password_input)

        confirm_lbl = QLabel("Confirm New Password")
        confirm_lbl.setObjectName("authLabel")
        layout.addWidget(confirm_lbl)
        self.forgot_confirm_input = QLineEdit()
        self.forgot_confirm_input.setEchoMode(QLineEdit.Password)
        self.forgot_confirm_input.setPlaceholderText("Re-enter new password")
        layout.addWidget(self.forgot_confirm_input)

        reset_btn = QPushButton("Reset Password")
        reset_btn.setObjectName("authPrimary")
        reset_btn.setCursor(Qt.PointingHandCursor)
        reset_btn.clicked.connect(self._on_forgot_clicked)
        layout.addWidget(reset_btn)

        back_btn = QPushButton("Back to login")
        back_btn.setObjectName("authLink")
        back_btn.setCursor(Qt.PointingHandCursor)
        back_btn.clicked.connect(lambda: self._switch_auth_page("login"))
        layout.addWidget(back_btn)
        layout.addStretch()

        self.forgot_page = page
        self.auth_stack.addWidget(page)

    def _switch_auth_page(self, page_name: str) -> None:
        self._set_auth_error("")
        if page_name == "register":
            self.auth_stack.setCurrentWidget(self.register_page)
        elif page_name == "forgot":
            self.auth_stack.setCurrentWidget(self.forgot_page)
            self.forgot_email_input.setText(self.login_email_input.text().strip())
        else:
            self.auth_stack.setCurrentWidget(self.login_page)
            self.login_password_input.clear()

    def _on_login_clicked(self) -> None:
        self._set_auth_error("")
        email = self.login_email_input.text().strip()
        password = self.login_password_input.text()
        if not email or not password:
            self._set_auth_error("Enter both email and password.")
            return

        settings = fetch_user_settings()
        if not is_auth_registered(settings):
            self._set_auth_error("No account found. Please register first.")
            self._switch_auth_page("register")
            return

        stored_email = (settings["email"] or "").strip()
        if stored_email.casefold() != email.casefold():
            self._set_auth_error("Email does not match the registered account.")
            return

        if not auth_password_matches(settings, password):
            self._set_auth_error("Invalid password.")
            return

        # Migrate legacy plain-text password to hash on first successful sign-in.
        if (settings["password_hash"] or "") != hash_secret(password):
            update_security(password_hash=hash_secret(password), app_pin=None)

        update_auth_session(True, keep_logged_in=self.keep_login_cb.isChecked())
        self.accept()

    def _on_register_clicked(self) -> None:
        self._set_auth_error("")
        name = self.register_name_input.text().strip()
        email = self.register_email_input.text().strip()
        password = self.register_password_input.text()
        confirm = self.register_confirm_input.text()
        pin = self.register_pin_input.text().strip()

        if not name:
            self._set_auth_error("Display Name is required.")
            return
        if not email or "@" not in email:
            self._set_auth_error("Enter a valid email address.")
            return
        if len(password) < 8:
            self._set_auth_error("Password must be at least 8 characters.")
            return
        if password != confirm:
            self._set_auth_error("Password confirmation does not match.")
            return
        if len(pin) != 4 or not pin.isdigit():
            self._set_auth_error("Recovery PIN must be exactly 4 digits.")
            return

        settings = fetch_user_settings()
        if is_auth_registered(settings):
            self._set_auth_error("Account already exists. Please log in.")
            self._switch_auth_page("login")
            return

        register_auth_user(
            display_name=name,
            email=email,
            password_hash=hash_secret(password),
            app_pin=pin,
            keep_logged_in=self.register_keep_cb.isChecked(),
        )
        self.accept()

    def _on_forgot_clicked(self) -> None:
        self._set_auth_error("")
        email = self.forgot_email_input.text().strip()
        pin = self.forgot_pin_input.text().strip()
        password = self.forgot_password_input.text()
        confirm = self.forgot_confirm_input.text()

        if not email:
            self._set_auth_error("Email is required.")
            return
        if len(pin) != 4 or not pin.isdigit():
            self._set_auth_error("Recovery PIN must be exactly 4 digits.")
            return
        if len(password) < 8:
            self._set_auth_error("New password must be at least 8 characters.")
            return
        if password != confirm:
            self._set_auth_error("Password confirmation does not match.")
            return

        ok = reset_auth_password(email=email, app_pin=pin, new_password_hash=hash_secret(password))
        if not ok:
            self._set_auth_error("Unable to reset password. Check email and recovery PIN.")
            return

        self._switch_auth_page("login")
        self.login_email_input.setText(email)
        self.login_password_input.clear()
        self._set_auth_error("Password reset successful. Please log in.")

class PortfolioWindow(QMainWindow):
    ASSETS_PAGE_INDEX = 0
    LIABILITIES_PAGE_INDEX = 1
    NET_WORTH_PAGE_INDEX = 2
    ADD_ASSET_PAGE_INDEX = 3
    EDIT_ASSET_PAGE_INDEX = 4
    ESSENTIALS_PAGE_INDEX = 5
    SETTINGS_PAGE_INDEX = 6
    ALLOCATION_PAGE_INDEX = 7
    GOALS_PAGE_INDEX = 8
    DASHBOARD_PAGE_INDEX = 9

    def __init__(self) -> None:
        super().__init__()
        init_db()

        self.categories = fetch_categories()
        self.asset_classes = fetch_asset_classes()
        self.exchange_rates = fetch_exchange_rates()
        self.category_lookup = {row["category_key"]: row["category_name"] for row in self.categories}
        self.class_lookup = {row["class_key"]: row for row in self.asset_classes}

        default_class = "STOCKS_EQUITY" if "STOCKS_EQUITY" in self.class_lookup else self.asset_classes[0]["class_key"]
        self.selected_form_class_key = default_class
        self.editing_asset_id: int | None = None
        self.selected_edit_class_key: str = default_class

        self.selected_category_key: str | None = None
        self.selected_class_filter_key: str | None = None
        self.selected_tag_filters: set[str] = set()
        self.available_tag_counts: list[tuple[str, str, int]] = []

        self.all_assets = []
        self.filtered_assets = []
        self.paged_filtered_assets = []
        self.all_liabilities = []
        self.net_worth_snapshots = []
        self.net_worth_view_mode = "NET_WORTH"
        self.selected_snapshot_history_id: int | None = None
        self.snapshot_assets_cache: dict[int, list[object]] = {}
        self.snapshot_liabilities_cache: dict[int, list[object]] = {}
        self.expanded_snapshot_ids: set[int] = set()
        self.chart_tooltip: TooltipFrame | None = None
        self.chart_v_line: QGraphicsLineItem | None = None
        self.chart_hover_filter = ChartHoverFilter(self)
        self.toast_widget: QFrame | None = None
        self.selected_asset_ids: set[int] = set()
        self.asset_row_by_id: dict[int, int] = {}
        self.asset_checkbox_by_id: dict[int, QCheckBox] = {}
        self.asset_context_menu_by_id: dict[int, QWidget] = {}
        self.asset_row_widgets_by_id: dict[int, list[QWidget]] = {}
        self.asset_row_items_by_id: dict[int, list[QTableWidgetItem]] = {}
        self.hovered_asset_id: int | None = None
        self._syncing_selection = False
        self.row_action_icons: dict[str, QIcon] = {}
        self.nav_buttons: dict[str, QPushButton] = {}
        self.page_size = 10
        self.current_page = 1
        self.total_pages = 1

        self.setWindowTitle("Portfolio Tracker")
        self.setMinimumSize(1380, 900)
        self._apply_style()
        self._build_ui()
        self._populate_add_asset_class_tiles()
        self._populate_edit_asset_class_combo()
        self._set_add_form_visibility(False)
        self._refresh_assets_view()
        self._refresh_liabilities_view()
        self._refresh_net_worth_view()
        self._refresh_dashboard_view()
        self._show_dashboard_page()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background: #f7f7f5;
            }
            QWidget {
                font-family: "Segoe UI";
                color: #2f2e2b;
                font-size: 14px;
            }
            QFrame#sidebar {
                background: #efefee;
                border-right: 1px solid #d9d8d3;
            }
            QLabel#logo {
                font-family: Georgia;
                font-size: 34px;
                font-weight: 700;
                color: #22211f;
            }
            QLabel#menuGroup {
                color: #6b6962;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 0.8px;
                margin-top: 12px;
            }
            QPushButton#navItem {
                background: transparent;
                border: none;
                text-align: left;
                padding: 10px 12px;
                border-radius: 10px;
                font-size: 17px;
                color: #4a4945;
            }
            QPushButton#navItem:hover {
                background: #e6e5e1;
            }
            QPushButton#navItem[active="true"] {
                background: #dce8e2;
                color: #185f3f;
                font-weight: 700;
            }
            QFrame#profileBar {
                min-height: 56px;
                max-height: 56px;
                border-bottom: 1px solid #d9d8d3;
                background: #f7f7f5;
            }
            QPushButton#iconButton {
                border: 1px solid #d8d7d2;
                border-radius: 8px;
                background: #ffffff;
                padding: 8px 12px;
                font-size: 14px;
            }
            QPushButton#iconButton:hover {
                background: #f4f4f2;
            }
            QLabel#userLabel {
                font-size: 14px;
                font-weight: 600;
                color: #343330;
            }
            QLabel#pageTitle,
            QLabel#addAssetTitle {
                font-family: Georgia;
                font-size: 46px;
                font-weight: 700;
                color: #22211f;
            }
            QLabel#editAssetClassSubtitle {
                color: #57554f;
                font-size: 26px;
                font-weight: 500;
            }
            QLabel#subTitle,
            QLabel#addStepLabel {
                color: #57554f;
                font-size: 16px;
            }
            QPushButton#actionButton {
                border: 1px solid #d8d7d2;
                border-radius: 8px;
                background: #ffffff;
                padding: 10px 14px;
                font-size: 14px;
                font-weight: 500;
            }
            QPushButton#actionButton:hover {
                background: #f5f5f3;
            }
            QPushButton#addAssetButton,
            QPushButton#saveButton {
                border: 1px solid #256d46;
                border-radius: 8px;
                background: #256d46;
                color: #ffffff;
                padding: 10px 14px;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton#addAssetButton:hover,
            QPushButton#saveButton:hover {
                background: #1d5c3a;
            }
            QLineEdit#searchInput {
                border: 1px solid #d8d7d2;
                border-radius: 8px;
                background: #ffffff;
                padding: 9px 12px;
                min-width: 220px;
                color: #44433f;
            }
            QPushButton#chip {
                border: 1px solid #dddcd7;
                border-radius: 8px;
                background: #f2f1ed;
                color: #44433f;
                padding: 7px 12px;
                font-size: 13px;
                font-weight: 500;
            }
            QPushButton#chip[active="true"] {
                background: #256d46;
                color: #ffffff;
                border-color: #256d46;
            }
            QLabel#tagsLabel {
                color: #67655f;
                font-size: 13px;
            }
            QListWidget#tagPickerList {
                border: 1px solid #d8d7d2;
                border-radius: 8px;
                background: #ffffff;
                padding: 4px;
            }
            QListWidget#tagPickerList::item {
                padding: 7px 8px;
                border-radius: 6px;
            }
            QListWidget#tagPickerList::item:selected {
                background: #ecebe6;
                color: #2f2e2b;
            }
            QFrame#totalCard {
                border: 1px solid #d9d8d3;
                border-radius: 10px;
                background: #e8e7e3;
                min-height: 68px;
            }
            QLabel#totalTitle {
                color: #5a5853;
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 0.8px;
            }
            QLabel#totalValue {
                color: #22211f;
                font-size: 34px;
                font-weight: 700;
            }
            QLabel#totalSubValue {
                color: #5a5853;
                font-size: 14px;
                font-weight: 500;
            }
            QLabel#netWorthMainValue {
                color: #1d7a4f;
                font-size: 52px;
                font-weight: 700;
            }
            QLabel#netWorthMetricLabel {
                color: #5a5853;
                font-size: 13px;
                font-weight: 700;
                letter-spacing: 0.6px;
            }
            QLabel#netWorthMetricPositive {
                color: #1d7a4f;
                font-size: 34px;
                font-weight: 700;
            }
            QLabel#netWorthMetricNegative {
                color: #c23b31;
                font-size: 34px;
                font-weight: 700;
            }
            QLabel#netWorthDescription {
                color: #4f4d47;
                font-size: 14px;
            }
            QLabel#netWorthSnapshotTime {
                color: #696761;
                font-size: 13px;
            }
            QFrame#chartCard,
            QFrame#metricCard,
            QFrame#snapshotHistoryCard {
                border: 1px solid #d9d8d3;
                border-radius: 10px;
                background: #ffffff;
            }
            QLabel#chartTitle {
                color: #232220;
                font-size: 30px;
                font-weight: 700;
            }
            QLabel#chartSubtitle {
                color: #65635d;
                font-size: 13px;
            }
            QChartView#timelineChart {
                border: none;
                background: #ffffff;
            }
            QLabel#metricCardTitle {
                color: #5a5853;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 0.8px;
            }
            QLabel#metricCardValuePositive {
                color: #1d7a4f;
                font-size: 34px;
                font-weight: 700;
            }
            QLabel#metricCardValueNegative {
                color: #c23b31;
                font-size: 34px;
                font-weight: 700;
            }
            QLabel#metricCardMeta {
                color: #5e5c57;
                font-size: 13px;
            }
            QTableWidget#snapshotHistoryTable,
            QTableWidget#snapshotLineTable {
                border: 1px solid #e5e4df;
                border-radius: 8px;
                background: #ffffff;
                gridline-color: #ecebe7;
                font-size: 13px;
            }
            QLabel#snapshotSectionTitle {
                color: #363530;
                font-size: 14px;
                font-weight: 700;
                letter-spacing: 0.7px;
            }
            QLabel#snapshotChangesText {
                color: #3f3e3a;
                font-size: 14px;
                line-height: 1.5;
            }
            QFrame#snapshotEntryCard {
                border: 1px solid #e1e0db;
                border-radius: 8px;
                background: #ffffff;
            }
            QFrame#snapshotEntryHeader {
                background: #ffffff;
            }
            QToolButton#snapshotToggle {
                border: none;
                background: transparent;
                padding: 0 4px;
            }
            QToolButton#snapshotToggle:hover {
                background: #f1f0ec;
                border-radius: 4px;
            }
            QLabel#snapshotEntryDate {
                color: #2e2d2a;
                font-size: 15px;
                font-weight: 600;
            }
            QLabel#snapshotEntryLabel {
                color: #5f5d57;
                font-size: 13px;
            }
            QLabel#snapshotEntryValue {
                color: #232220;
                font-size: 18px;
                font-weight: 700;
            }
            QLabel#snapshotEntryChangePositive {
                color: #1d7a4f;
                font-size: 13px;
                font-weight: 700;
            }
            QLabel#snapshotEntryChangeNegative {
                color: #c23b31;
                font-size: 13px;
                font-weight: 700;
            }
            QLabel#snapshotEntryBaseline {
                color: #6f6c66;
                font-size: 12px;
                font-weight: 600;
            }
            QFrame#snapshotEntryDetails {
                border-top: 1px solid #ecebe7;
                background: #fbfbf9;
            }
            QFrame#toastMessage {
                background: #1f6d45;
                border: 1px solid #1f6d45;
                border-radius: 10px;
            }
            QLabel#toastLabel {
                color: #ffffff;
                font-size: 13px;
                font-weight: 600;
            }
            QFrame#tableCard {
                border: 1px solid #d9d8d3;
                border-radius: 10px;
                background: #ffffff;
            }
            QTableWidget#assetTable {
                border: none;
                background: #ffffff;
                gridline-color: #ecebe7;
                selection-background-color: #f3f2ee;
                selection-color: #2f2e2b;
                font-size: 14px;
            }
            QTableWidget#liabilityTable {
                border: none;
                background: #ffffff;
                gridline-color: #ecebe7;
                font-size: 14px;
            }
            QTableWidget#assetTable::item:selected,
            QTableWidget#assetTable::item:selected:active,
            QTableWidget#assetTable::item:selected:!active {
                background: #f3f2ee;
                color: #2f2e2b;
            }
            QHeaderView::section {
                background: #ecebe6;
                border: none;
                border-bottom: 1px solid #d9d8d3;
                border-right: 1px solid #ecebe6;
                padding: 12px 10px;
                color: #4d4b46;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel#assetName {
                font-size: 17px;
                font-weight: 600;
                color: #292825;
            }
            QLabel#assetTag {
                font-size: 12px;
                color: #5a7e67;
            }
            QLabel#classBadge {
                background: #ecebe6;
                color: #5d5a52;
                border-radius: 4px;
                font-size: 10px;
                font-weight: 700;
                padding: 2px 8px;
                min-width: 24px;
            }
            QLabel#classBadge[tone="gold"] {
                background: #f4edda;
                color: #9f7a1d;
            }
            QLabel#classBadge[tone="mf"] {
                background: #deefe4;
                color: #2e7a52;
            }
            QLabel#classText {
                font-size: 15px;
                color: #363530;
            }
            QLabel#liabilityTypeBadge {
                background: #dfe8f7;
                color: #2e5082;
                border-radius: 4px;
                font-size: 11px;
                font-weight: 600;
                padding: 2px 8px;
            }
            QLabel#valueMain {
                font-size: 17px;
                font-weight: 700;
                color: #252421;
            }
            QLabel#valueSub {
                font-size: 12px;
                color: #696761;
            }
            QLabel#valuePctPositive {
                font-size: 12px;
                color: #1d7a4f;
            }
            QLabel#valuePctNegative {
                font-size: 12px;
                color: #c23b31;
            }
            QWidget#rowCell {
                background: #ffffff;
            }
            QWidget#rowCell[rowHover="true"] {
                background: #f3f2ee;
            }
            QWidget#rowContextMenu {
                background: transparent;
            }
            QToolButton#rowActionButton {
                border: none;
                border-radius: 5px;
                background: transparent;
                padding: 2px;
            }
            QToolButton#rowActionButton:hover {
                background: #e4e2db;
            }
            QToolButton#rowDeleteActionButton {
                border: none;
                border-radius: 5px;
                background: transparent;
                padding: 2px;
            }
            QToolButton#rowDeleteActionButton:hover {
                background: #f8e2df;
            }
            QLabel#footerText {
                color: #696761;
                font-size: 13px;
            }
            QPushButton#pagerButton {
                border: 1px solid #dddcd7;
                border-radius: 6px;
                background: #f8f8f6;
                color: #55534d;
                padding: 6px 12px;
                font-size: 12px;
            }
            QFrame#selectionBar {
                border: 1px solid #d8d7d2;
                border-radius: 12px;
                background: #f8f8f6;
            }
            QLabel#selectionCount {
                font-size: 13px;
                font-weight: 700;
                color: #2e2d2a;
            }
            QPushButton#selectionActionButton {
                border: 1px solid #d5d4cf;
                border-radius: 8px;
                background: #ffffff;
                color: #2f2e2b;
                padding: 8px 14px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton#selectionActionButton:hover {
                background: #f3f3f1;
            }
            QPushButton#selectionDeleteButton {
                border: 1px solid #e2b1ad;
                border-radius: 8px;
                background: #fff5f4;
                color: #b13c33;
                padding: 8px 14px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton#selectionDeleteButton:hover {
                background: #ffeceb;
            }
            QPushButton#selectionCloseButton {
                border: none;
                background: transparent;
                color: #4f4d47;
                font-size: 16px;
                font-weight: 600;
                padding: 0 6px;
            }
            QPushButton#selectionCloseButton:hover {
                color: #1a1917;
            }
            QPushButton#backLink {
                border: none;
                background: transparent;
                color: #2f2e2b;
                font-size: 16px;
                font-weight: 600;
                text-align: right;
                padding: 0;
            }
            QPushButton#backLink:hover {
                color: #185f3f;
            }
            QFrame#formCard {
                border: 1px solid #d9d8d3;
                border-radius: 8px;
                background: #ffffff;
            }
            QLabel#sectionTitle {
                font-size: 22px;
                font-weight: 700;
                color: #22211f;
            }
            QPushButton#changeClassLink {
                border: none;
                background: transparent;
                color: #2b8055;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton#changeClassLink:hover {
                color: #1d5c3a;
            }
            QToolButton#classTile {
                border: 1px solid #dddcd7;
                border-radius: 6px;
                background: #ffffff;
                color: #2f2e2b;
                min-height: 92px;
                min-width: 160px;
                padding: 12px 8px;
                font-size: 13px;
                font-weight: 500;
            }
            QToolButton#classTile[selected="true"] {
                border-color: #2f7b55;
                background: #eaf3ee;
                color: #175e3e;
                font-weight: 700;
            }
            QToolButton#classTile:hover {
                background: #f4f4f1;
            }
            QLabel#fieldLabel {
                font-size: 13px;
                font-weight: 600;
                color: #32312d;
            }
            QLineEdit#formInput,
            QComboBox#formInput,
            QComboBox#classPicker {
                border: 1px solid #d8d7d2;
                border-radius: 6px;
                background: #ffffff;
                padding: 9px 10px;
                min-height: 20px;
            }
            QLabel#tagPreview {
                background: #dfe8e3;
                color: #1e623f;
                border-radius: 8px;
                font-size: 12px;
                font-weight: 600;
                padding: 4px 8px;
            }
            QLabel#helperLabel {
                color: #6f6c66;
                font-size: 12px;
            }
            QPushButton#disclosure {
                border: none;
                background: transparent;
                color: #3c3b37;
                text-align: left;
                padding: 0;
                font-size: 13px;
                font-weight: 600;
            }
            QLabel#statusSuccess {
                color: #1d7a4f;
                font-size: 13px;
                font-weight: 600;
            }
            QLabel#statusError {
                color: #c23b31;
                font-size: 13px;
                font-weight: 600;
            }
            QFrame#emptyStateCard {
                border: 1px solid #d9d8d3;
                border-radius: 8px;
                background: #ffffff;
                min-height: 240px;
            }
            QLabel#emptyStateIcon {
                font-size: 36px;
            }
            QLabel#emptyStateTitle {
                font-size: 30px;
                font-weight: 600;
                color: #2b2a26;
            }
            QLabel#emptyStateDescription {
                font-size: 15px;
                color: #5f5d57;
            }
            QLabel#liabilityTotalValue {
                color: #cc4b38;
                font-size: 34px;
                font-weight: 700;
            }
            QDialog#liabilityDialog {
                background: #ffffff;
            }
            QDialog#snapshotDialog {
                background: #ffffff;
            }
            QPushButton#dialogCloseButton {
                border: none;
                background: transparent;
                color: #6b6962;
                font-size: 24px;
                min-width: 24px;
                min-height: 24px;
                padding: 0;
            }
            QPushButton#dialogCloseButton:hover {
                color: #2f2e2b;
            }
            QPushButton#secondaryButton {
                border: 1px solid #dddcd7;
                border-radius: 6px;
                background: #f8f8f6;
                color: #2f2e2b;
                padding: 10px 14px;
                font-size: 14px;
                font-weight: 500;
            }
            QPushButton#secondaryButton:hover {
                background: #efefec;
            }
            QDialog#changeClassDialog {
                background: #ffffff;
            }
            """
        )

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_sidebar())
        root_layout.addWidget(self._build_content(), 1)
        self.setCentralWidget(root)

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(240)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(6)

        logo = QLabel("PortTrack")
        logo.setObjectName("logo")
        layout.addWidget(logo)
        layout.addSpacing(8)

        menu_sections = [
            ("OVERVIEW", ["Dashboard"]),
            ("WEALTH", ["Assets", "Liabilities", "Net Worth"]),
            ("PLAN", ["Essentials", "Goals", "Allocation"]),
            ("MONEY", ["Income", "Expenses", "Insights"]),
            ("DATA", ["Install App", "Dark mode", "Feedback"]),
        ]
        for group, items in menu_sections:
            group_label = QLabel(group)
            group_label.setObjectName("menuGroup")
            layout.addWidget(group_label)
            for item in items:
                button = QPushButton(item)
                button.setObjectName("navItem")
                button.setProperty("active", item == "Dashboard")
                button.setCursor(Qt.PointingHandCursor)
                if item in {"Dashboard", "Assets", "Liabilities", "Net Worth", "Essentials", "Allocation", "Goals"}:
                    button.clicked.connect(
                        lambda _checked=False, selected_item=item: self._on_sidebar_navigation(selected_item)
                    )
                layout.addWidget(button)
                self.nav_buttons[item] = button
            layout.addSpacing(6)

        layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding))
        return sidebar

    def _build_content(self) -> QWidget:
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self._build_profile_bar())

        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(self._build_assets_page())
        self.content_stack.addWidget(self._build_liabilities_page())
        self.content_stack.addWidget(self._build_net_worth_page())
        self.content_stack.addWidget(self._build_add_asset_page())
        self.content_stack.addWidget(self._build_edit_asset_page())
        self.content_stack.addWidget(self._build_essentials_page())
        self.content_stack.addWidget(self._build_settings_page())
        self.content_stack.addWidget(self._build_allocation_page())
        self.content_stack.addWidget(self._build_goals_page())
        self.content_stack.addWidget(self._build_dashboard_page())  # index 9
        content_layout.addWidget(self.content_stack, 1)
        return content

    def _build_profile_bar(self) -> QWidget:
        top = QFrame()
        top.setObjectName("profileBar")
        layout = QHBoxLayout(top)
        layout.setContentsMargins(20, 8, 20, 8)
        layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        theme_button = QPushButton("Moon")
        theme_button.setObjectName("iconButton")
        theme_button.setCursor(Qt.PointingHandCursor)
        layout.addWidget(theme_button)

        self.profile_user_label = QLabel("")
        self.profile_user_label.setObjectName("userLabel")
        layout.addWidget(self.profile_user_label)

        self.profile_menu_button = QPushButton("v")
        self.profile_menu_button.setObjectName("iconButton")
        self.profile_menu_button.setCursor(Qt.PointingHandCursor)
        self.profile_menu_button.clicked.connect(self._show_profile_menu)
        layout.addWidget(self.profile_menu_button)
        self._refresh_profile_bar_identity()
        return top

    def _refresh_profile_bar_identity(self) -> None:
        if not hasattr(self, "profile_user_label"):
            return
        settings = fetch_user_settings()
        display_name = (settings["display_name"] or "").strip() if settings else ""
        email = (settings["email"] or "").strip() if settings else ""
        identity = display_name or email or "Guest"
        self.profile_user_label.setText(identity)

    def _show_profile_menu(self) -> None:
        if not hasattr(self, "profile_menu_button"):
            return
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #ffffff; border: 1px solid #d9d8d3; padding: 4px 0; }"
            "QMenu::item { padding: 8px 16px; color: #22211f; }"
            "QMenu::item:selected { background: #f3f2ef; }"
        )
        logout_action = menu.addAction("Log out")
        chosen = menu.exec(self.profile_menu_button.mapToGlobal(QPoint(0, self.profile_menu_button.height())))
        if chosen == logout_action:
            self._logout_user()

    def _logout_user(self) -> None:
        choice = QMessageBox.question(
            self,
            "Log out",
            "Log out from this app?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if choice != QMessageBox.Yes:
            return

        clear_auth_session()
        self.hide()
        auth_dialog = AuthDialog(self)
        if auth_dialog.exec() == QDialog.Accepted:
            self._refresh_profile_bar_identity()
            self.show()
            self._refresh_dashboard_view()
        else:
            app = QApplication.instance()
            if app is not None:
                app.quit()

    def _build_essentials_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(24)

        title = QLabel("Essentials")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        subtitle = QLabel("Financial health check")
        subtitle.setObjectName("subTitle")
        layout.addWidget(subtitle)

        layout.addSpacing(40)

        card_container = QHBoxLayout()
        card_container.addStretch()

        warning_card = QFrame()
        warning_card.setStyleSheet(
            """
            QFrame {
                background-color: #fdf4e4;
                border-radius: 6px;
                border: 1px solid #f6e6cb;
            }
            QLabel {
                border: none;
                background: transparent;
            }
            QLabel#warningTitle {
                font-family: "Georgia";
                font-size: 16px;
                font-weight: bold;
                color: #22211f;
            }
            QLabel#warningDesc {
                font-family: "Segoe UI", sans-serif;
                font-size: 13px;
                color: #22211f;
                line-height: 1.4;
            }
            QPushButton#profileBtn {
                background-color: #2b7a52;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 16px;
                font-family: "Segoe UI", sans-serif;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton#profileBtn:hover {
                background-color: #236543;
            }
            """
        )
        warning_layout = QVBoxLayout(warning_card)
        warning_layout.setContentsMargins(40, 40, 40, 40)
        warning_layout.setSpacing(16)
        warning_layout.setAlignment(Qt.AlignCenter)

        icon_label = QLabel("⚠️")
        icon_label.setAlignment(Qt.AlignCenter)
        font = icon_label.font()
        font.setPointSize(24)
        icon_label.setFont(font)
        warning_layout.addWidget(icon_label)

        warning_title = QLabel("Monthly Expense Data Required")
        warning_title.setObjectName("warningTitle")
        warning_title.setAlignment(Qt.AlignCenter)
        warning_layout.addWidget(warning_title)

        warning_desc = QLabel(
            "To calculate your financial health scores, we need your monthly expense\n"
            "amount. This helps us evaluate your emergency fund, insurance needs, and\n"
            "overall preparedness."
        )
        warning_desc.setObjectName("warningDesc")
        warning_desc.setAlignment(Qt.AlignCenter)
        warning_layout.addWidget(warning_desc)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        setup_btn = QPushButton("Set Up Financial Profile")
        setup_btn.setObjectName("profileBtn")
        setup_btn.setCursor(Qt.PointingHandCursor)
        setup_btn.clicked.connect(self._show_settings_page)
        btn_layout.addWidget(setup_btn)
        btn_layout.addStretch()
        warning_layout.addLayout(btn_layout)

        card_container.addWidget(warning_card)
        card_container.addStretch()
        
        layout.addLayout(card_container)
        layout.addStretch()

        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(24)

        header_layout = QVBoxLayout()
        header_layout.setSpacing(8)
        title = QLabel("Settings")
        title.setObjectName("pageTitle")
        header_layout.addWidget(title)
        subtitle = QLabel("Account, preferences & privacy")
        subtitle.setObjectName("subTitle")
        header_layout.addWidget(subtitle)
        layout.addLayout(header_layout)

        main_split = QHBoxLayout()
        main_split.setSpacing(40)

        # Left Sidebar (Nav Rail)
        sidebar_frame = QFrame()
        sidebar_frame.setStyleSheet(
            """
            QFrame {
                background-color: #ffffff;
                border: 1px solid #d9d8d3;
                border-radius: 6px;
            }
            QPushButton {
                text-align: left;
                padding: 12px 16px;
                background: transparent;
                border: none;
                border-radius: 4px;
                font-family: "Segoe UI", sans-serif;
                font-size: 13px;
                color: #22211f;
                margin: 4px 8px;
            }
            QPushButton:hover {
                background-color: #f7f6f2;
            }
            QPushButton[active="true"] {
                background-color: #e8f3ec;
                color: #2b7a52;
                font-weight: 600;
            }
            """
        )
        sidebar_frame.setFixedWidth(220)
        sidebar_layout = QVBoxLayout(sidebar_frame)
        sidebar_layout.setContentsMargins(0, 8, 0, 8)
        sidebar_layout.setSpacing(0)

        nav_items = [
            "Financial Profile",
            "Profile",
            "Security",
            "Currency & FX"
        ]
        
        self.settings_nav_buttons = {}
        for idx, item in enumerate(nav_items):
            btn = QPushButton(item)
            btn.setCursor(Qt.PointingHandCursor)
            
            btn.clicked.connect(lambda _checked=False, i=idx, name=item: self._on_settings_tab_click(name, i))
                
            sidebar_layout.addWidget(btn)
            self.settings_nav_buttons[item] = btn
            
        sidebar_layout.addStretch()
        main_split.addWidget(sidebar_frame)

        # Right Content Area
        self.settings_stack = QStackedWidget()
        
        # Placeholders for now
        self.settings_stack.addWidget(self._build_settings_financial_profile_tab())
        self.settings_stack.addWidget(self._build_settings_profile_tab())
        self.settings_stack.addWidget(self._build_settings_security_tab())
        self.settings_stack.addWidget(self._build_settings_currency_tab())

        main_split.addWidget(self.settings_stack, 1)
        layout.addLayout(main_split)

        return page

    def _build_settings_financial_profile_tab(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("settingsPanel")
        panel.setStyleSheet(
            """
            QFrame#settingsPanel {
                background-color: #ffffff;
                border: 1px solid #d9d8d3;
                border-radius: 6px;
            }
            QLabel#settingsPanelTitle {
                font-family: "Segoe UI", sans-serif;
                font-size: 14px;
                font-weight: bold;
                color: #22211f;
            }
            QLabel#settingsPanelDesc {
                font-family: "Segoe UI", sans-serif;
                font-size: 12px;
                color: #6b6962;
                margin-bottom: 20px;
            }
            QLabel#fieldLabel {
                font-family: "Courier New", monospace;
                font-size: 11px;
                color: #6b6962;
            }
            QLineEdit {
                border: 1px solid #d9d8d3;
                border-radius: 4px;
                padding: 10px 12px;
                font-family: "Segoe UI", sans-serif;
                font-size: 13px;
                background-color: #ffffff;
                color: #22211f;
            }
            QLineEdit::placeholder {
                color: #a9a8a5;
            }
            QPushButton#saveBtn {
                background-color: #2b7a52;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 24px;
                font-family: "Segoe UI", sans-serif;
                font-size: 13px;
                font-weight: 600;
                margin-top: 16px;
            }
            QPushButton#saveBtn:hover {
                background-color: #236543;
            }
            """
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(32, 28, 32, 32)
        layout.setSpacing(10)
        
        # Load Existing Settings
        settings_row = fetch_user_settings()
        initial_age = str(settings_row["age"] or "") if settings_row else ""
        initial_income = str(int(settings_row["monthly_income"])) if settings_row and settings_row["monthly_income"] else ""
        initial_expense = str(int(settings_row["monthly_expense"])) if settings_row and settings_row["monthly_expense"] else ""
        initial_savings = str(int(settings_row["monthly_savings"])) if settings_row and settings_row["monthly_savings"] else ""

        title = QLabel("Financial Profile")
        title.setObjectName("settingsPanelTitle")
        layout.addWidget(title)
        
        desc = QLabel("Used for health scores, essentials tracking, and personalised guidance. All fields are optional.")
        desc.setObjectName("settingsPanelDesc")
        layout.addWidget(desc)
        
        form_grid = QGridLayout()
        form_grid.setSpacing(16)
        
        # Row 1
        age_label = QLabel("Age")
        age_label.setObjectName("fieldLabel")
        form_grid.addWidget(age_label, 0, 0)
        income_label = QLabel("Monthly Income")
        income_label.setObjectName("fieldLabel")
        form_grid.addWidget(income_label, 0, 1)
        
        age_input = QLineEdit(initial_age)
        age_input.setPlaceholderText("Your age")
        form_grid.addWidget(age_input, 1, 0)
        
        income_input = QLineEdit(initial_income)
        income_input.setPlaceholderText("Monthly income")
        form_grid.addWidget(income_input, 1, 1)

        # Row 2
        expense_label = QLabel("Monthly Expense")
        expense_label.setObjectName("fieldLabel")
        form_grid.addWidget(expense_label, 2, 0)
        savings_label = QLabel("Monthly Savings")
        savings_label.setObjectName("fieldLabel")
        form_grid.addWidget(savings_label, 2, 1)
        
        expense_input = QLineEdit(initial_expense)
        expense_input.setPlaceholderText("Monthly expense")
        form_grid.addWidget(expense_input, 3, 0)
        
        savings_input = QLineEdit(initial_savings)
        savings_input.setPlaceholderText("Monthly savings")
        form_grid.addWidget(savings_input, 3, 1)
        
        layout.addLayout(form_grid)
        
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.setObjectName("saveBtn")
        save_btn.setCursor(Qt.PointingHandCursor)
        
        # Save button states
        save_btn.setStyleSheet("""
            QPushButton#saveBtn {
                background-color: #2b7a52; color: white; border: none; border-radius: 4px; padding: 10px 24px; font-family: "Segoe UI", sans-serif; font-size: 13px; font-weight: 600; margin-top: 16px;
            }
            QPushButton#saveBtn:hover {
                background-color: #236543;
            }
            QPushButton#saveBtn:disabled {
                background-color: #92bca4;
            }
        """)
        save_btn.setEnabled(False)

        saved_lbl = QLabel("Saved!")
        saved_lbl.setStyleSheet("color: #2b7a52; font-family: 'Segoe UI', sans-serif; font-size: 13px; font-weight: 600; margin-top: 16px; margin-left: 12px;")
        saved_lbl.hide()

        def on_input_changed(*args, **kwargs):
            save_btn.setEnabled(True)
            saved_lbl.hide()

        age_input.textChanged.connect(on_input_changed)
        income_input.textChanged.connect(on_input_changed)
        expense_input.textChanged.connect(on_input_changed)
        savings_input.textChanged.connect(on_input_changed)
        
        def save_financial_profile():
            try:
                age_val = int(age_input.text().strip()) if age_input.text().strip() else None
            except: age_val = None
            try:
                inc_val = float(income_input.text().strip().replace(',', '')) if income_input.text().strip() else None
            except: inc_val = None
            try:
                exp_val = float(expense_input.text().strip().replace(',', '')) if expense_input.text().strip() else None
            except: exp_val = None
            try:
                sav_val = float(savings_input.text().strip().replace(',', '')) if savings_input.text().strip() else None
            except: sav_val = None
            
            update_financial_profile(age_val, inc_val, exp_val, sav_val)
            print(f"Saved Financial Profile: Age={age_val}, Income={inc_val}, Expense={exp_val}, Savings={sav_val}")
            
            save_btn.setEnabled(False)
            saved_lbl.show()
            QTimer.singleShot(3000, saved_lbl.hide)
            
        save_btn.clicked.connect(save_financial_profile)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(saved_lbl)
        btn_layout.addStretch()
        
        layout.addLayout(btn_layout)
        layout.addStretch()
        
        outer_container = QWidget()
        outer_layout = QVBoxLayout(outer_container)
        outer_layout.setContentsMargins(0,0,0,0)
        outer_layout.addWidget(panel)
        outer_layout.addStretch()
        
        return outer_container

    def _build_settings_profile_tab(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("settingsPanel")
        panel.setStyleSheet(
            """
            QFrame#settingsPanel {
                background-color: #ffffff;
                border: 1px solid #d9d8d3;
                border-radius: 6px;
            }
            QLabel#settingsPanelTitle {
                font-family: "Segoe UI", sans-serif;
                font-size: 14px;
                font-weight: bold;
                color: #22211f;
            }
            QLabel#fieldLabel {
                font-family: "Courier New", monospace;
                font-size: 11px;
                color: #6b6962;
            }
            QLineEdit {
                border: 1px solid #d9d8d3;
                border-radius: 4px;
                padding: 10px 12px;
                font-family: "Segoe UI", sans-serif;
                font-size: 13px;
                background-color: #ffffff;
                color: #22211f;
            }
            QLineEdit::placeholder {
                color: #a9a8a5;
            }
            """
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(32, 28, 32, 32)
        layout.setSpacing(10)

        settings_row = fetch_user_settings()
        initial_name = settings_row["display_name"] if settings_row and settings_row["display_name"] else ""
        initial_email = settings_row["email"] if settings_row and settings_row["email"] else ""

        title = QLabel("Profile")
        title.setObjectName("settingsPanelTitle")
        layout.addWidget(title)
        layout.addSpacing(16)

        form_grid = QGridLayout()
        form_grid.setSpacing(16)

        name_label = QLabel("Display Name")
        name_label.setObjectName("fieldLabel")
        form_grid.addWidget(name_label, 0, 0)
        
        email_label = QLabel("Email")
        email_label.setObjectName("fieldLabel")
        form_grid.addWidget(email_label, 0, 1)

        name_input = QLineEdit(initial_name)
        form_grid.addWidget(name_input, 1, 0)

        email_input = QLineEdit(initial_email)
        email_input.setPlaceholderText("yourname@example.com")
        form_grid.addWidget(email_input, 1, 1)
        
        email_hint = QLabel("Email cannot be changed")
        email_hint.setStyleSheet("font-size: 10px; color: #6b6962;")
        form_grid.addWidget(email_hint, 2, 1)
        
        layout.addLayout(form_grid)

        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.setObjectName("saveBtn")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setStyleSheet("""
            QPushButton#saveBtn {
                background-color: #2b7a52; color: white; border: none; border-radius: 4px; padding: 10px 24px; font-family: "Segoe UI", sans-serif; font-size: 13px; font-weight: 600; margin-top: 16px;
            }
            QPushButton#saveBtn:hover {
                background-color: #236543;
            }
            QPushButton#saveBtn:disabled {
                background-color: #92bca4;
            }
        """)
        save_btn.setEnabled(False)

        saved_lbl = QLabel("Saved!")
        saved_lbl.setStyleSheet("color: #2b7a52; font-family: 'Segoe UI', sans-serif; font-size: 13px; font-weight: 600; margin-top: 16px; margin-left: 12px;")
        saved_lbl.hide()

        def on_input_changed(*args, **kwargs):
            save_btn.setEnabled(True)
            saved_lbl.hide()
            
        name_input.textChanged.connect(on_input_changed)
        email_input.textChanged.connect(on_input_changed)
        
        def save_profile():
            name_val = name_input.text().strip()
            email_val = email_input.text().strip()
            update_user_profile(name_val, email_val)
            self._refresh_profile_bar_identity()
            print(f"Saved Profile: Name={name_val}, Email={email_val}")
            save_btn.setEnabled(False)
            saved_lbl.show()
            QTimer.singleShot(3000, saved_lbl.hide)
            
        save_btn.clicked.connect(save_profile)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(saved_lbl)
        btn_layout.addStretch()
        
        layout.addLayout(btn_layout)
        layout.addStretch()

        outer_container = QWidget()
        outer_layout = QVBoxLayout(outer_container)
        outer_layout.setContentsMargins(0,0,0,0)
        outer_layout.addWidget(panel)
        outer_layout.addStretch()
        return outer_container

    def _build_settings_security_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        # Set Password Panel
        pwd_panel = QFrame()
        pwd_panel.setObjectName("settingsPanel")
        
        shared_style = """
            QFrame#settingsPanel {
                background-color: #ffffff;
                border: 1px solid #d9d8d3;
                border-radius: 6px;
            }
            QLabel#settingsPanelTitle {
                font-family: "Segoe UI", sans-serif;
                font-size: 14px;
                font-weight: bold;
                color: #22211f;
            }
            QLabel#settingsPanelDesc {
                font-family: "Segoe UI", sans-serif;
                font-size: 12px;
                color: #6b6962;
                margin-bottom: 20px;
            }
            QLabel#fieldLabel {
                font-family: "Courier New", monospace;
                font-size: 11px;
                color: #6b6962;
            }
            QLineEdit {
                border: 1px solid #d9d8d3;
                border-radius: 4px;
                padding: 10px 12px;
                font-family: "Segoe UI", sans-serif;
                font-size: 13px;
                background-color: #ffffff;
                color: #22211f;
            }
            QLineEdit::placeholder {
                color: #a9a8a5;
            }
        """
        pwd_panel.setStyleSheet(shared_style)
        pwd_layout = QVBoxLayout(pwd_panel)
        pwd_layout.setContentsMargins(32, 28, 32, 32)
        pwd_layout.setSpacing(10)

        pwd_title = QLabel("Set Password")
        pwd_title.setObjectName("settingsPanelTitle")
        pwd_layout.addWidget(pwd_title)
        
        pwd_desc = QLabel("Set a password so you can also sign in with email and password, in addition to Google.")
        pwd_desc.setObjectName("settingsPanelDesc")
        pwd_layout.addWidget(pwd_desc)
        
        pwd_form = QVBoxLayout()
        pwd_form.setSpacing(8)
        
        new_pwd_lbl = QLabel("New Password")
        new_pwd_lbl.setObjectName("fieldLabel")
        pwd_form.addWidget(new_pwd_lbl)
        
        new_pwd_input = QLineEdit()
        new_pwd_input.setPlaceholderText("Min 8 characters")
        new_pwd_input.setEchoMode(QLineEdit.Password)
        new_pwd_input.setFixedWidth(300)
        pwd_form.addWidget(new_pwd_input)
        
        pwd_form.addSpacing(8)
        
        conf_pwd_lbl = QLabel("Confirm New Password")
        conf_pwd_lbl.setObjectName("fieldLabel")
        pwd_form.addWidget(conf_pwd_lbl)
        
        conf_pwd_input = QLineEdit()
        conf_pwd_input.setPlaceholderText("Re-enter new password")
        conf_pwd_input.setEchoMode(QLineEdit.Password)
        conf_pwd_input.setFixedWidth(300)
        pwd_form.addWidget(conf_pwd_input)
        
        pwd_layout.addLayout(pwd_form)
        pwd_layout.addSpacing(16)
        
        pwd_btn_layout = QHBoxLayout()
        set_pwd_btn = QPushButton("Set Password")
        set_pwd_btn.setObjectName("saveBtn")
        set_pwd_btn.setStyleSheet("""
            QPushButton#saveBtn {
                background-color: #2b7a52; color: white; border: none; border-radius: 4px; padding: 10px 24px; font-family: "Segoe UI", sans-serif; font-size: 13px; font-weight: 600; margin-top: 16px;
            }
            QPushButton#saveBtn:hover {
                background-color: #236543;
            }
            QPushButton#saveBtn:disabled {
                background-color: #92bca4;
            }
        """)
        set_pwd_btn.setEnabled(False)
        set_pwd_btn.setCursor(Qt.PointingHandCursor)
        
        saved_lbl = QLabel("Saved!")
        saved_lbl.setStyleSheet("color: #2b7a52; font-family: 'Segoe UI', sans-serif; font-size: 13px; font-weight: 600; margin-top: 16px; margin-left: 12px;")
        saved_lbl.hide()

        def on_pwd_changed(*args, **kwargs):
            set_pwd_btn.setEnabled(True)
            saved_lbl.hide()
            
        new_pwd_input.textChanged.connect(on_pwd_changed)
        conf_pwd_input.textChanged.connect(on_pwd_changed)
        
        def save_password():
            if new_pwd_input.text() == conf_pwd_input.text() and len(new_pwd_input.text()) >= 8:
                update_security(password_hash=hash_secret(new_pwd_input.text()), app_pin=None)
                print("Saved new password")
                new_pwd_input.clear()
                conf_pwd_input.clear()
                set_pwd_btn.setEnabled(False)
                saved_lbl.show()
                QTimer.singleShot(3000, saved_lbl.hide)
        
        set_pwd_btn.clicked.connect(save_password)
        pwd_btn_layout.addWidget(set_pwd_btn)
        pwd_btn_layout.addWidget(saved_lbl)
        pwd_btn_layout.addStretch()
        pwd_layout.addLayout(pwd_btn_layout)

        # App Lock Panel
        pin_panel = QFrame()
        pin_panel.setObjectName("settingsPanel")
        pin_panel.setStyleSheet(shared_style)
        pin_layout = QVBoxLayout(pin_panel)
        pin_layout.setContentsMargins(32, 28, 32, 32)
        pin_layout.setSpacing(10)
        
        pin_header = QHBoxLayout()
        pin_icon = QLabel("🔒")
        pin_title = QLabel("App Lock")
        pin_title.setObjectName("settingsPanelTitle")
        pin_header.addWidget(pin_icon)
        pin_header.addWidget(pin_title)
        pin_header.addStretch()
        pin_layout.addLayout(pin_header)
        
        pin_desc = QLabel('Require a 4-digit PIN to open the app. <span style="color:#d97706;">Only available when using the installed PWA.</span>')
        pin_desc.setObjectName("settingsPanelDesc")
        pin_layout.addWidget(pin_desc)
        
        pin_btn_layout = QHBoxLayout()
        set_pin_btn = QPushButton("🔒 Set Up PIN")
        set_pin_btn.setObjectName("saveBtn")
        set_pin_btn.setCursor(Qt.PointingHandCursor)
        pin_btn_layout.addWidget(set_pin_btn)
        pin_btn_layout.addStretch()
        pin_layout.addLayout(pin_btn_layout)
        
        layout.addWidget(pwd_panel)
        layout.addWidget(pin_panel)
        layout.addStretch()
        return container

    def _build_settings_currency_tab(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("settingsPanel")
        panel.setStyleSheet(
            """
            QFrame#settingsPanel {
                background-color: #ffffff;
                border: 1px solid #d9d8d3;
                border-radius: 6px;
            }
            QLabel#settingsPanelTitle {
                font-family: "Segoe UI", sans-serif;
                font-size: 14px;
                font-weight: bold;
                color: #22211f;
            }
            QLabel#fieldLabel {
                font-family: "Courier New", monospace;
                font-size: 11px;
                color: #6b6962;
            }
            """
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(32, 28, 32, 32)
        layout.setSpacing(10)

        title = QLabel("Currency & FX")
        title.setObjectName("settingsPanelTitle")
        layout.addWidget(title)
        layout.addSpacing(16)
        
        settings_row = fetch_user_settings()
        initial_curr = settings_row["base_currency"] if settings_row and settings_row["base_currency"] else "INR"

        curr_label = QLabel("Base Display Currency")
        curr_label.setObjectName("fieldLabel")
        layout.addWidget(curr_label)
        
        curr_combo = QComboBox()
        curr_combo.addItems(["INR (Indian Rupee)", "USD (US Dollar)", "EUR (Euro)", "GBP (British Pound)"])
        curr_combo.setFixedWidth(300)
        curr_combo.setStyleSheet("""
            QComboBox {
                border: 1px solid #d9d8d3;
                border-radius: 4px;
                padding: 10px 12px;
                font-family: "Segoe UI", sans-serif;
                font-size: 13px;
                background-color: #ffffff;
                color: #22211f;
            }
        """)
        for i in range(curr_combo.count()):
            if initial_curr in curr_combo.itemText(i):
                curr_combo.setCurrentIndex(i)
                break
        layout.addWidget(curr_combo)
        
        curr_hint = QLabel('✨ <span style="color:#d97706;">Upgrade to Pro to change currency</span>')
        curr_hint.setStyleSheet("font-size: 11px; margin-bottom: 8px;")
        layout.addWidget(curr_hint)

        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save Currency")
        save_btn.setObjectName("saveBtn")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setStyleSheet("""
            QPushButton#saveBtn {
                background-color: #2b7a52; color: white; border: none; border-radius: 4px; padding: 10px 24px; font-family: "Segoe UI", sans-serif; font-size: 13px; font-weight: 600; margin-top: 16px;
            }
            QPushButton#saveBtn:hover {
                background-color: #236543;
            }
            QPushButton#saveBtn:disabled {
                background-color: #92bca4;
            }
        """)
        save_btn.setEnabled(False)

        saved_lbl = QLabel("Saved!")
        saved_lbl.setStyleSheet("color: #2b7a52; font-family: 'Segoe UI', sans-serif; font-size: 13px; font-weight: 600; margin-top: 16px; margin-left: 12px;")
        saved_lbl.hide()

        def on_curr_changed(*args, **kwargs):
            save_btn.setEnabled(True)
            saved_lbl.hide()
            
        curr_combo.currentIndexChanged.connect(on_curr_changed)
        
        def save_currency():
            curr_code = curr_combo.currentText().split(" ")[0]
            update_base_currency(curr_code)
            print(f"Saved Base Currency: {curr_code}")
            save_btn.setEnabled(False)
            saved_lbl.show()
            QTimer.singleShot(3000, saved_lbl.hide)
            
        save_btn.clicked.connect(save_currency)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(saved_lbl)
        
        refresh_btn = QPushButton("Force Refresh Rates")
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 1px solid #d9d8d3;
                border-radius: 4px;
                padding: 8px 16px;
                font-family: "Segoe UI", sans-serif;
                font-size: 13px;
                font-weight: 600;
                color: #22211f;
                margin-top: 16px;
            }
            QPushButton:hover {
                background-color: #f7f6f2;
            }
        """)
        refresh_btn.setCursor(Qt.PointingHandCursor)
        btn_layout.addWidget(refresh_btn)
        btn_layout.addStretch()
        
        layout.addLayout(btn_layout)
        layout.addSpacing(16)
        
        success_msg = QLabel("✓ FX rates loaded Last updated: Just now")
        success_msg.setStyleSheet("""
            QLabel {
                background-color: #e8f3ec;
                color: #2b7a52;
                padding: 12px;
                border-radius: 4px;
                font-size: 12px;
                border: 1px solid #cce5d6;
            }
        """)
        layout.addWidget(success_msg)

        layout.addStretch()

        outer_container = QWidget()
        outer_layout = QVBoxLayout(outer_container)
        outer_layout.setContentsMargins(0,0,0,0)
        outer_layout.addWidget(panel)
        outer_layout.addStretch()
        return outer_container

    def _on_settings_tab_click(self, item_name: str, index: int) -> None:
        for name, btn in self.settings_nav_buttons.items():
            is_active = name == item_name
            btn.setProperty("active", is_active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self.settings_stack.setCurrentIndex(index)

    def _show_settings_page(self) -> None:
        self._set_active_nav_item("Essentials") # Keep Essentials active in main sidebar
        self.content_stack.setCurrentIndex(self.SETTINGS_PAGE_INDEX)
        
        # Default to first tab
        self._on_settings_tab_click("Financial Profile", 0)

    def _build_assets_page(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(32, 26, 32, 24)
        layout.setSpacing(14)

        header_row = QHBoxLayout()
        title_stack = QVBoxLayout()
        title_stack.setSpacing(0)

        title = QLabel("Assets")
        title.setObjectName("pageTitle")
        title_stack.addWidget(title)

        self.asset_count_label = QLabel("0 assets")
        self.asset_count_label.setObjectName("subTitle")
        title_stack.addWidget(self.asset_count_label)

        header_row.addLayout(title_stack)
        header_row.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        controls = QHBoxLayout()
        controls.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("searchInput")
        self.search_input.setPlaceholderText("Search...")
        self.search_input.textChanged.connect(self._on_search_text_changed)
        controls.addWidget(self.search_input)

        add_btn = QPushButton("+ Add Asset")
        add_btn.setObjectName("addAssetButton")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self._show_add_asset_page)
        controls.addWidget(add_btn)

        header_row.addLayout(controls)
        layout.addLayout(header_row)

        self.category_chip_layout = QHBoxLayout()
        self.category_chip_layout.setSpacing(10)
        layout.addLayout(self.category_chip_layout)

        self.class_chip_container = QWidget()
        self.class_chip_layout = QHBoxLayout(self.class_chip_container)
        self.class_chip_layout.setContentsMargins(0, 0, 0, 0)
        self.class_chip_layout.setSpacing(10)
        layout.addWidget(self.class_chip_container)

        tag_row = QHBoxLayout()
        tags = QLabel("Tags")
        tags.setObjectName("tagsLabel")
        tag_row.addWidget(tags)
        self.tag_chip_layout = QHBoxLayout()
        self.tag_chip_layout.setContentsMargins(0, 0, 0, 0)
        self.tag_chip_layout.setSpacing(10)
        tag_row.addLayout(self.tag_chip_layout)
        tag_row.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        layout.addLayout(tag_row)

        total_card = QFrame()
        total_card.setObjectName("totalCard")
        total_layout = QHBoxLayout(total_card)
        total_layout.setContentsMargins(18, 14, 18, 14)
        self.total_title_label = QLabel("TOTAL ASSETS")
        self.total_title_label.setObjectName("totalTitle")
        self.total_value_label = QLabel(format_currency(0))
        self.total_value_label.setObjectName("totalValue")
        self.total_sub_value_label = QLabel(f"of {format_currency(0)}")
        self.total_sub_value_label.setObjectName("totalSubValue")
        total_layout.addWidget(self.total_title_label)
        total_layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        value_wrap = QWidget()
        value_layout = QHBoxLayout(value_wrap)
        value_layout.setContentsMargins(0, 0, 0, 0)
        value_layout.setSpacing(8)
        value_layout.addWidget(self.total_value_label)
        value_layout.addWidget(self.total_sub_value_label, alignment=Qt.AlignBottom)
        total_layout.addWidget(value_wrap)
        layout.addWidget(total_card)

        table_card = QFrame()
        table_card.setObjectName("tableCard")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)

        self.asset_table = QTableWidget(0, 6)
        self.asset_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.asset_table.setObjectName("assetTable")
        self.asset_table.setHorizontalHeaderLabels(["", "NAME", "CLASS", "SUB-TYPE", "INVESTED", "VALUE"])
        self.asset_table.verticalHeader().setVisible(False)
        self.asset_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.asset_table.setSelectionMode(QAbstractItemView.MultiSelection)
        self.asset_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.asset_table.setShowGrid(True)
        self.asset_table.setAlternatingRowColors(False)
        self.asset_table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.asset_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.asset_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.asset_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.asset_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.asset_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.asset_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.asset_table.setColumnWidth(0, 44)
        self.asset_table.horizontalHeader().setMinimumSectionSize(44)
        self.asset_table.setMouseTracking(True)
        self.asset_table.viewport().setMouseTracking(True)
        self.asset_table.viewport().installEventFilter(self)
        self.asset_table.itemSelectionChanged.connect(self._on_table_selection_changed)
        table_layout.addWidget(self.asset_table)

        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 12, 16, 12)
        footer_layout.setSpacing(8)

        self.footer_text = QLabel("Showing 0 of 0 assets")
        self.footer_text.setObjectName("footerText")
        footer_layout.addWidget(self.footer_text)
        footer_layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        self.prev_page_button = QPushButton("Prev")
        self.prev_page_button.setObjectName("pagerButton")
        self.prev_page_button.setCursor(Qt.PointingHandCursor)
        self.prev_page_button.clicked.connect(self._go_to_prev_page)
        footer_layout.addWidget(self.prev_page_button)

        self.page_indicator_button = QPushButton("1 / 1")
        self.page_indicator_button.setObjectName("pagerButton")
        self.page_indicator_button.setEnabled(False)
        footer_layout.addWidget(self.page_indicator_button)

        self.next_page_button = QPushButton("Next")
        self.next_page_button.setObjectName("pagerButton")
        self.next_page_button.setCursor(Qt.PointingHandCursor)
        self.next_page_button.clicked.connect(self._go_to_next_page)
        footer_layout.addWidget(self.next_page_button)

        table_layout.addWidget(footer)
        layout.addWidget(table_card, 1)

        self.selection_bar = QFrame()
        self.selection_bar.setObjectName("selectionBar")
        self.selection_bar_layout = QHBoxLayout(self.selection_bar)
        self.selection_bar_layout.setContentsMargins(14, 10, 14, 10)
        self.selection_bar_layout.setSpacing(10)

        self.selection_count_label = QLabel("0 selected")
        self.selection_count_label.setObjectName("selectionCount")
        self.selection_bar_layout.addWidget(self.selection_count_label)

        self.selection_bar_layout.addWidget(self._build_selection_divider())

        self.change_class_button = QPushButton("Change Class")
        self.change_class_button.setObjectName("selectionActionButton")
        self.change_class_button.setCursor(Qt.PointingHandCursor)
        self.change_class_button.clicked.connect(self._open_change_class_dialog)
        self.selection_bar_layout.addWidget(self.change_class_button)

        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("selectionDeleteButton")
        self.delete_button.setCursor(Qt.PointingHandCursor)
        self.delete_button.clicked.connect(self._delete_selected_assets)
        self.selection_bar_layout.addWidget(self.delete_button)

        self.clear_selection_button = QPushButton("x")
        self.clear_selection_button.setObjectName("selectionCloseButton")
        self.clear_selection_button.setCursor(Qt.PointingHandCursor)
        self.clear_selection_button.clicked.connect(self._clear_selected_assets)
        self.selection_bar_layout.addWidget(self.clear_selection_button)

        self.selection_bar.hide()
        layout.addWidget(self.selection_bar, alignment=Qt.AlignHCenter)
        return panel

    def _build_liabilities_page(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(32, 26, 32, 24)
        layout.setSpacing(14)

        header_row = QHBoxLayout()
        title_stack = QVBoxLayout()
        title_stack.setSpacing(2)

        title = QLabel("Liabilities")
        title.setObjectName("pageTitle")
        title_stack.addWidget(title)

        subtitle = QLabel("Track your debts")
        subtitle.setObjectName("subTitle")
        title_stack.addWidget(subtitle)

        header_row.addLayout(title_stack)
        header_row.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        add_liability_btn = QPushButton("+ Add Liability")
        add_liability_btn.setObjectName("addAssetButton")
        add_liability_btn.clicked.connect(lambda: self._open_add_liability_dialog())
        header_row.addWidget(add_liability_btn)
        layout.addLayout(header_row)

        self.liabilities_empty_card = QFrame()
        self.liabilities_empty_card.setObjectName("emptyStateCard")
        empty_layout = QVBoxLayout(self.liabilities_empty_card)
        empty_layout.setContentsMargins(20, 24, 20, 24)
        empty_layout.setSpacing(10)
        empty_layout.setAlignment(Qt.AlignCenter)

        icon = QLabel("✅")
        icon.setObjectName("emptyStateIcon")
        icon.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(icon)

        empty_title = QLabel("No liabilities")
        empty_title.setObjectName("emptyStateTitle")
        empty_title.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(empty_title)

        empty_description = QLabel(
            "Debt-free is a great place to be! Add loans or credit card balances here\nif you have any."
        )
        empty_description.setObjectName("emptyStateDescription")
        empty_description.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(empty_description)

        layout.addWidget(self.liabilities_empty_card)

        self.liabilities_table_card = QFrame()
        self.liabilities_table_card.setObjectName("tableCard")
        table_layout = QVBoxLayout(self.liabilities_table_card)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)

        total_card = QFrame()
        total_card.setObjectName("totalCard")
        total_layout = QHBoxLayout(total_card)
        total_layout.setContentsMargins(18, 14, 18, 14)
        total_title = QLabel("TOTAL LIABILITIES")
        total_title.setObjectName("totalTitle")
        self.liabilities_total_value_label = QLabel(format_liability_currency(0, "INR"))
        self.liabilities_total_value_label.setObjectName("liabilityTotalValue")
        total_layout.addWidget(total_title)
        total_layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        total_layout.addWidget(self.liabilities_total_value_label)
        table_layout.addWidget(total_card)

        self.liabilities_table = QTableWidget(0, 6)
        self.liabilities_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.liabilities_table.setObjectName("liabilityTable")
        self.liabilities_table.setHorizontalHeaderLabels(
            ["NAME", "TYPE", "OUTSTANDING ↓", "RATE", "MONTHLY EMI", ""]
        )
        self.liabilities_table.verticalHeader().setVisible(False)
        self.liabilities_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.liabilities_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.liabilities_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.liabilities_table.setShowGrid(True)
        self.liabilities_table.setAlternatingRowColors(False)
        self.liabilities_table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.liabilities_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.liabilities_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.liabilities_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.liabilities_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.liabilities_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.liabilities_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Fixed)
        self.liabilities_table.setColumnWidth(5, 88)
        table_layout.addWidget(self.liabilities_table, 1)

        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 12, 16, 12)
        footer_layout.setSpacing(8)
        self.liabilities_footer_text = QLabel("0/0 liabilities")
        self.liabilities_footer_text.setObjectName("footerText")
        footer_layout.addWidget(self.liabilities_footer_text)
        footer_layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        table_layout.addWidget(footer)

        layout.addWidget(self.liabilities_table_card, 1)
        layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding))
        return panel

    def _build_net_worth_page(self) -> QWidget:
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel_layout.addWidget(scroll_area)

        scroll_content = QWidget()
        scroll_area.setWidget(scroll_content)

        layout = QVBoxLayout(scroll_content)
        layout.setContentsMargins(32, 26, 32, 24)
        layout.setSpacing(14)

        header_row = QHBoxLayout()
        title_stack = QVBoxLayout()
        title_stack.setSpacing(2)

        title = QLabel("Net Worth")
        title.setObjectName("pageTitle")
        title_stack.addWidget(title)

        self.net_worth_snapshot_count_label = QLabel("0 snapshots")
        self.net_worth_snapshot_count_label.setObjectName("subTitle")
        title_stack.addWidget(self.net_worth_snapshot_count_label)

        header_row.addLayout(title_stack)
        header_row.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        take_snapshot_btn = QPushButton("Take New Snapshot")
        take_snapshot_btn.setObjectName("addAssetButton")
        take_snapshot_btn.setCursor(Qt.PointingHandCursor)
        take_snapshot_btn.clicked.connect(self._open_take_snapshot_dialog)
        header_row.addWidget(take_snapshot_btn)
        layout.addLayout(header_row)

        tabs_row = QHBoxLayout()
        tabs_row.setSpacing(10)

        self.net_worth_tab_button = self._make_chip("Net Worth", active=True)
        self.net_worth_tab_button.clicked.connect(lambda: self._set_net_worth_mode("NET_WORTH"))
        tabs_row.addWidget(self.net_worth_tab_button)

        self.net_worth_assets_tab_button = self._make_chip("Assets", active=False)
        self.net_worth_assets_tab_button.clicked.connect(lambda: self._set_net_worth_mode("ASSETS"))
        tabs_row.addWidget(self.net_worth_assets_tab_button)

        self.net_worth_liabilities_tab_button = self._make_chip("Liabilities", active=False)
        self.net_worth_liabilities_tab_button.clicked.connect(lambda: self._set_net_worth_mode("LIABILITIES"))
        tabs_row.addWidget(self.net_worth_liabilities_tab_button)
        tabs_row.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        layout.addLayout(tabs_row)

        top_content = QHBoxLayout()
        top_content.setSpacing(16)

        chart_card = QFrame()
        chart_card.setObjectName("chartCard")
        chart_layout = QVBoxLayout(chart_card)
        chart_layout.setContentsMargins(20, 16, 20, 16)
        chart_layout.setSpacing(6)

        self.timeline_chart_title = QLabel("Net Worth History")
        self.timeline_chart_title.setObjectName("sectionTitle")
        chart_layout.addWidget(self.timeline_chart_title)

        timeline_subtitle = QLabel("Values in ₹ INR")
        timeline_subtitle.setObjectName("chartSubtitle")
        chart_layout.addWidget(timeline_subtitle)

        self.timeline_chart_view = QChartView()
        self.timeline_chart_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.timeline_chart_view.setObjectName("timelineChart")
        self.timeline_chart_view.setMinimumHeight(320)
        self.timeline_chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        chart_layout.addWidget(self.timeline_chart_view, 1)
        top_content.addWidget(chart_card, 1)

        metrics_col = QVBoxLayout()
        metrics_col.setSpacing(12)

        def create_metric_card(title_text: str) -> tuple[QFrame, QLabel, QLabel]:
            card = QFrame()
            card.setObjectName("metricCard")
            card.setFixedWidth(300)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 14, 16, 14)
            card_layout.setSpacing(6)
            title = QLabel(title_text)
            title.setObjectName("metricCardTitle")
            value = QLabel("₹0")
            value.setObjectName("metricCardValuePositive")
            meta = QLabel("-")
            meta.setObjectName("metricCardMeta")
            card_layout.addWidget(title)
            card_layout.addWidget(value)
            card_layout.addWidget(meta)
            return card, value, meta

        growth_card, self.net_worth_growth_value_label, self.net_worth_growth_meta_label = create_metric_card("GROWTH")
        metrics_col.addWidget(growth_card)

        best_card, self.net_worth_best_month_value_label, self.net_worth_best_month_meta_label = create_metric_card("BEST MONTH")
        metrics_col.addWidget(best_card)

        avg_card, self.net_worth_avg_value_label, self.net_worth_avg_meta_label = create_metric_card("AVG / SNAPSHOT")
        metrics_col.addWidget(avg_card)
        metrics_col.addStretch(1)
        top_content.addLayout(metrics_col)
        layout.addLayout(top_content)

        snapshot_history_card = QFrame()
        snapshot_history_card.setObjectName("snapshotHistoryCard")
        history_layout = QVBoxLayout(snapshot_history_card)
        history_layout.setContentsMargins(16, 14, 16, 14)
        history_layout.setSpacing(10)

        history_title = QLabel("Snapshot History")
        history_title.setObjectName("sectionTitle")
        history_layout.addWidget(history_title)

        history_hint = QLabel("Expand a snapshot to view recorded line items")
        history_hint.setObjectName("subTitle")
        history_layout.addWidget(history_hint)

        self.snapshot_entries_layout = QVBoxLayout()
        self.snapshot_entries_layout.setContentsMargins(0, 0, 0, 0)
        self.snapshot_entries_layout.setSpacing(10)
        history_layout.addLayout(self.snapshot_entries_layout)

        self.take_first_snapshot_button = QPushButton("Take Your First Snapshot")
        self.take_first_snapshot_button.setObjectName("addAssetButton")
        self.take_first_snapshot_button.setCursor(Qt.PointingHandCursor)
        self.take_first_snapshot_button.clicked.connect(self._open_take_snapshot_dialog)
        history_layout.addWidget(self.take_first_snapshot_button, alignment=Qt.AlignLeft)

        layout.addWidget(snapshot_history_card)
        layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding))
        return panel

    def _create_snapshot_line_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setObjectName("snapshotLineTable")
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        return table

    def _fit_snapshot_table_height(self, table: QTableWidget) -> None:
        row_count = table.rowCount()
        header_height = table.horizontalHeader().height() or 32
        total_height = header_height + (row_count * 28) + 4
        bounded_height = max(72, total_height)
        table.setMinimumHeight(bounded_height)
        table.setMaximumHeight(bounded_height)

    def _build_add_asset_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page_layout.addWidget(scroll_area)

        scroll_content = QWidget()
        scroll_area.setWidget(scroll_content)

        layout = QVBoxLayout(scroll_content)
        layout.setContentsMargins(32, 26, 32, 24)
        layout.setSpacing(18)

        header_row = QHBoxLayout()
        title_stack = QVBoxLayout()
        title_stack.setSpacing(3)

        title = QLabel("Add Asset")
        title.setObjectName("addAssetTitle")
        title_stack.addWidget(title)

        self.add_step_label = QLabel("Step 2 of 2: Stocks & Equity")
        self.add_step_label.setObjectName("addStepLabel")
        title_stack.addWidget(self.add_step_label)

        header_row.addLayout(title_stack)
        header_row.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        back_to_assets_btn = QPushButton("< Back to Assets")
        back_to_assets_btn.setObjectName("backLink")
        back_to_assets_btn.setCursor(Qt.PointingHandCursor)
        back_to_assets_btn.clicked.connect(self._show_assets_page)
        header_row.addWidget(back_to_assets_btn)

        layout.addLayout(header_row)

        class_card = QFrame()
        class_card.setObjectName("formCard")
        class_layout = QVBoxLayout(class_card)
        class_layout.setContentsMargins(20, 16, 20, 18)
        class_layout.setSpacing(14)

        class_header = QHBoxLayout()
        class_title = QLabel("Select Asset Class")
        class_title.setObjectName("sectionTitle")
        class_header.addWidget(class_title)
        class_header.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        change_class_btn = QPushButton("Change class")
        change_class_btn.setObjectName("changeClassLink")
        change_class_btn.setCursor(Qt.PointingHandCursor)
        change_class_btn.clicked.connect(self._show_add_class_picker_only)
        class_header.addWidget(change_class_btn)
        class_layout.addLayout(class_header)

        self.add_class_tiles_grid = QGridLayout()
        self.add_class_tiles_grid.setHorizontalSpacing(10)
        self.add_class_tiles_grid.setVerticalSpacing(10)
        for column in range(4):
            self.add_class_tiles_grid.setColumnStretch(column, 1)
        class_layout.addLayout(self.add_class_tiles_grid)
        layout.addWidget(class_card)

        self.add_details_card = QFrame()
        self.add_details_card.setObjectName("formCard")
        details_layout = QVBoxLayout(self.add_details_card)
        details_layout.setContentsMargins(20, 16, 20, 12)
        details_layout.setSpacing(12)

        self.details_title = QLabel("Asset Details: Stocks & Equity")
        self.details_title.setObjectName("sectionTitle")
        details_layout.addWidget(self.details_title)

        fields_grid = QGridLayout()
        fields_grid.setHorizontalSpacing(12)
        fields_grid.setVerticalSpacing(8)

        name_label = QLabel("Name *")
        name_label.setObjectName("fieldLabel")
        fields_grid.addWidget(name_label, 0, 0)

        current_label = QLabel("Current Value *")
        current_label.setObjectName("fieldLabel")
        fields_grid.addWidget(current_label, 0, 1)

        currency_label = QLabel("Currency")
        currency_label.setObjectName("fieldLabel")
        fields_grid.addWidget(currency_label, 0, 2)

        self.name_input = QLineEdit()
        self.name_input.setObjectName("formInput")
        self.name_input.setPlaceholderText("e.g. Groww Portfolio or HDFC Bank")
        fields_grid.addWidget(self.name_input, 1, 0)

        self.current_value_input = QLineEdit()
        self.current_value_input.setObjectName("formInput")
        self.current_value_input.setPlaceholderText("Total value")
        fields_grid.addWidget(self.current_value_input, 1, 1)

        self.currency_combo = QComboBox()
        self.currency_combo.setObjectName("formInput")
        self.currency_combo.addItems(["INR", "USD", "EUR", "GBP"])
        fields_grid.addWidget(self.currency_combo, 1, 2)

        invested_label = QLabel("Invested Amount")
        invested_label.setObjectName("fieldLabel")
        fields_grid.addWidget(invested_label, 2, 0)

        self.invested_input = QLineEdit()
        self.invested_input.setObjectName("formInput")
        self.invested_input.setPlaceholderText("Total invested")
        fields_grid.addWidget(self.invested_input, 3, 0)

        invested_hint = QLabel("Optional - if empty, it uses current value")
        invested_hint.setObjectName("helperLabel")
        fields_grid.addWidget(invested_hint, 4, 0)

        fields_grid.setColumnStretch(0, 2)
        fields_grid.setColumnStretch(1, 2)
        fields_grid.setColumnStretch(2, 1)
        details_layout.addLayout(fields_grid)

        self.disclosure_button = QPushButton("v Add details (sub-type, tags, notes)")
        self.disclosure_button.setObjectName("disclosure")
        self.disclosure_button.setCursor(Qt.PointingHandCursor)
        self.disclosure_button.clicked.connect(self._toggle_extra_details)
        details_layout.addWidget(self.disclosure_button)

        self.extra_details_box = QWidget()
        extra_layout = QGridLayout(self.extra_details_box)
        extra_layout.setHorizontalSpacing(12)
        extra_layout.setVerticalSpacing(8)

        subtype_label = QLabel("Sub-type")
        subtype_label.setObjectName("fieldLabel")
        extra_layout.addWidget(subtype_label, 0, 0)

        tag_label = QLabel("Tag")
        tag_label.setObjectName("fieldLabel")
        extra_layout.addWidget(tag_label, 0, 1)

        notes_label = QLabel("Notes")
        notes_label.setObjectName("fieldLabel")
        extra_layout.addWidget(notes_label, 0, 2)

        self.subtype_input = QLineEdit()
        self.subtype_input.setObjectName("formInput")
        self.subtype_input.setPlaceholderText("e.g. Flexi Cap")
        extra_layout.addWidget(self.subtype_input, 1, 0)

        self.tag_input = QLineEdit()
        self.tag_input.setObjectName("formInput")
        self.tag_input.setPlaceholderText("e.g. #long-term")
        extra_layout.addWidget(self.tag_input, 1, 1)

        self.notes_input = QLineEdit()
        self.notes_input.setObjectName("formInput")
        self.notes_input.setPlaceholderText("Notes")
        extra_layout.addWidget(self.notes_input, 1, 2)

        self.extra_details_box.hide()
        details_layout.addWidget(self.extra_details_box)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #e1e0db;")
        details_layout.addWidget(line)

        self.add_form_status = QLabel("")
        self.add_form_status.hide()
        details_layout.addWidget(self.add_form_status)

        actions = QHBoxLayout()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondaryButton")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.clicked.connect(self._show_assets_page)
        actions.addWidget(cancel_btn)

        actions.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        save_another_btn = QPushButton("Save & Add Another")
        save_another_btn.setObjectName("secondaryButton")
        save_another_btn.setCursor(Qt.PointingHandCursor)
        save_another_btn.clicked.connect(lambda: self._save_asset(stay_on_page=True))
        actions.addWidget(save_another_btn)

        save_btn = QPushButton("Save Asset")
        save_btn.setObjectName("saveButton")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.clicked.connect(lambda: self._save_asset(stay_on_page=False))
        actions.addWidget(save_btn)

        details_layout.addLayout(actions)
        layout.addWidget(self.add_details_card)
        layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding))
        return page

    def _build_allocation_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        content = QWidget()
        content.setStyleSheet("QWidget { background: transparent; }")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(24)

        header_layout = QVBoxLayout()
        header_layout.setSpacing(8)
        
        title = QLabel("Allocation")
        title.setObjectName("pageTitle")
        header_layout.addWidget(title)
        
        subtitle = QLabel("Asset allocation & rebalancing")
        subtitle.setObjectName("subTitle")
        header_layout.addWidget(subtitle)
        
        layout.addLayout(header_layout)
        
        tabs_layout = QHBoxLayout()
        tabs_layout.setSpacing(16)
        
        asset_alloc_btn = QPushButton("Asset Allocation")
        asset_alloc_btn.setCursor(Qt.PointingHandCursor)
        asset_alloc_btn.setStyleSheet("""
            QPushButton {
                background-color: #2b7a52; color: white; border: none; border-radius: 4px; padding: 10px 16px; font-family: "Segoe UI", sans-serif; font-size: 13px; font-weight: 600;
            }
        """)
        
        monthly_sip_btn = QPushButton("Monthly SIP Plan")
        monthly_sip_btn.setCursor(Qt.PointingHandCursor)
        monthly_sip_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent; color: #22211f; border: none; border-radius: 4px; padding: 10px 16px; font-family: "Segoe UI", sans-serif; font-size: 13px; font-weight: 600;
            }
            QPushButton:hover {
                background-color: #f7f6f2;
            }
        """)
        
        tabs_layout.addWidget(asset_alloc_btn)
        tabs_layout.addWidget(monthly_sip_btn)
        tabs_layout.addStretch()
        layout.addLayout(tabs_layout)
        
        # Target Allocation Box Placeholder
        target_panel = QFrame()
        target_panel.setObjectName("targetPanel")
        target_panel.setStyleSheet("QFrame#targetPanel { background-color: #ffffff; border: 1px solid #d9d8d3; border-radius: 6px; }")
        target_layout = QVBoxLayout(target_panel)
        target_layout.setContentsMargins(24, 24, 24, 24)
        
        target_header_layout = QHBoxLayout()
        target_title = QLabel("Target Allocation")
        target_title.setStyleSheet('font-family: "Segoe UI", sans-serif; font-size: 14px; font-weight: bold; color: #22211f; border: none;')
        target_header_layout.addWidget(target_title)
        target_header_layout.addStretch()
        
        self.allocation_edit_btn = QPushButton("✎ Edit")
        self.allocation_edit_btn.setCursor(Qt.PointingHandCursor)
        self.allocation_edit_btn.setStyleSheet("color: #2b7a52; font-weight: bold; border: none;")
        self.allocation_edit_btn.clicked.connect(self._toggle_allocation_edit_mode)
        target_header_layout.addWidget(self.allocation_edit_btn)
        target_layout.addLayout(target_header_layout)
        
        self.allocation_target_content = QVBoxLayout()
        target_layout.addLayout(self.allocation_target_content)
        
        layout.addWidget(target_panel)
        
        # Actuals Box Placeholder
        actuals_panel = QFrame()
        actuals_panel.setObjectName("actualsPanel")
        actuals_panel.setStyleSheet("QFrame#actualsPanel { background-color: #ffffff; border: 1px solid #d9d8d3; border-radius: 6px; }")
        actuals_layout = QVBoxLayout(actuals_panel)
        actuals_layout.setContentsMargins(24, 24, 24, 24)
        actuals_title = QLabel("Target vs Actual")
        actuals_title.setStyleSheet('font-family: "Segoe UI", sans-serif; font-size: 14px; font-weight: bold; color: #22211f; border: none;')
        actuals_layout.addWidget(actuals_title)
        
        self.allocation_actuals_content = QVBoxLayout()
        actuals_layout.addLayout(self.allocation_actuals_content)
        
        layout.addWidget(actuals_panel)
        
        layout.addStretch()
        scroll.setWidget(content)
        
        self.allocation_edit_mode = False
        self._refresh_allocation_view()
        
        return scroll

    def _toggle_allocation_edit_mode(self):
        self.allocation_edit_mode = not getattr(self, "allocation_edit_mode", False)
        self.allocation_edit_btn.setText("Close" if self.allocation_edit_mode else "✎ Edit")
        self._refresh_allocation_view()

    def _refresh_allocation_view(self):
        self._clear_layout(self.allocation_target_content)
        categories = fetch_categories()
        
        # Color scale based on screenshots
        colors = {
            "EQUITY": "#24508f", # Blue
            "DEBT": "#45815a", # Green
            "GOLD_SILVER": "#ce9027", # Gold
            "CASH": "#837d74", # Grey
            "INSURANCE": "#b9707e", # Pinkish
            "OTHER_COMMODITIES": "#a68257", # Brown
            "REAL_ESTATE": "#a18a56", # Dark Gold
            "CRYPTO": "#606af9", # Bright Blue
            "ALTERNATIVES": "#712f6f" # Purple
        }
        
        from PySide6.QtGui import QPainter, QColor, QFont
        from PySide6.QtWidgets import QToolTip
        
        class TargetStackedBar(QWidget):
            def __init__(self, data):
                super().__init__()
                self.data = data
                self.setFixedHeight(30)
                self.setMouseTracking(True)
                self._hovered_idx = -1
                
            def update_data(self, data):
                self.data = data
                self.update()
                
            def mouseMoveEvent(self, event):
                total_width = self.rect().width()
                current_x = 0
                for i, (key, name, pct, color) in enumerate(self.data):
                    w = (pct / 100.0) * total_width
                    if current_x <= event.position().x() <= current_x + w:
                        if self._hovered_idx != i:
                            self._hovered_idx = i
                            QToolTip.showText(event.globalPosition().toPoint(), f"{name}: {pct:.1f}%", self)
                            self.update()
                        return
                    current_x += w
                if self._hovered_idx != -1:
                    self._hovered_idx = -1
                    QToolTip.hideText()
                    self.update()

            def leaveEvent(self, event):
                self._hovered_idx = -1
                QToolTip.hideText()
                self.update()

            def paintEvent(self, event):
                painter = QPainter(self)
                painter.setRenderHint(QPainter.Antialiasing)
                rect = self.rect()
                
                total_width = rect.width()
                current_x = 0
                
                for i, (key, name, pct, color) in enumerate(self.data):
                    if pct <= 0: continue
                    w = (pct / 100.0) * total_width
                    painter.fillRect(int(current_x), 0, int(w), 20, QColor(color))
                    
                    # Highlight on hover
                    if i == self._hovered_idx:
                        painter.setBrush(QColor(255, 255, 255, 60))
                        painter.drawRect(int(current_x), 0, int(w), 20)
                    
                    # Smart label rendering based on segment width
                    if w > 60:
                        painter.setPen(QColor("white"))
                        painter.setFont(QFont("Segoe UI", 9))
                        painter.drawText(int(current_x), 0, int(w), 20, Qt.AlignCenter, f"{name} {int(pct)}%")
                    elif w > 30:
                        painter.setPen(QColor("white"))
                        painter.setFont(QFont("Segoe UI", 9))
                        short_name = name[:3] + "." if len(name) > 3 else name
                        painter.drawText(int(current_x), 0, int(w), 20, Qt.AlignCenter, short_name)
                        
                    current_x += w

        if getattr(self, "allocation_edit_mode", False):
            # Edit Mode
            edit_container = QWidget()
            edit_layout = QVBoxLayout(edit_container)
            edit_layout.setContentsMargins(0, 0, 0, 0)
            
            top_bar_layout = QHBoxLayout()
            self.edit_stacked_bar = TargetStackedBar([])
            top_bar_layout.addWidget(self.edit_stacked_bar)
            
            self.alloc_sliders = {}
            self.alloc_inputs = {}
            total_lbl = QLabel()
            total_lbl.setFixedWidth(50)
            total_lbl.setAlignment(Qt.AlignCenter)
            total_lbl.setStyleSheet("font-family: 'Segoe UI'; font-size: 14px; font-weight: bold; border: none;")
            top_bar_layout.addWidget(total_lbl)
            
            edit_layout.addLayout(top_bar_layout)
            edit_layout.addSpacing(16)
            
            def update_total():
                total = sum(s.value() for s in self.alloc_sliders.values())
                total_lbl.setText(f"{total}% ✓" if total == 100 else f"{total}% ⚠")
                total_lbl.setStyleSheet(f"font-family: 'Segoe UI'; font-size: 14px; font-weight: bold; border: none; color: {'#2b7a52' if total == 100 else '#cc4b38'};")
                save_btn.setEnabled(total == 100)
                
                bar_data = []
                for cat in categories:
                    k = cat["category_key"]
                    if k in self.alloc_sliders:
                        pct = self.alloc_sliders[k].value()
                        if pct > 0:
                            bar_data.append((k, cat["category_name"], pct, colors.get(k, "#CCC")))
                self.edit_stacked_bar.update_data(bar_data)

            for cat in categories:
                key = cat["category_key"]
                name = cat["category_name"]
                target = int(cat["target_percentage"]) if "target_percentage" in cat.keys() and cat["target_percentage"] is not None else 0
                
                row = QHBoxLayout()
                
                # Color Box
                color_box = QLabel()
                color_box.setFixedSize(12, 12)
                color_box.setStyleSheet(f"background-color: {colors.get(key, '#CCCCCC')}; border-radius: 2px;")
                row.addWidget(color_box)
                
                # Label
                lbl = QLabel(name)
                lbl.setFixedWidth(120)
                lbl.setStyleSheet("font-family: 'Segoe UI'; font-size: 13px; color: #22211f; border: none;")
                row.addWidget(lbl)
                
                # Slider
                slider = QSlider(Qt.Horizontal)
                slider.setRange(0, 100)
                slider.setValue(target)
                slider.setStyleSheet(f"""
                    QSlider::groove:horizontal {{ height: 4px; background: #e1e0db; border-radius: 2px; }}
                    QSlider::handle:horizontal {{ background: {colors.get(key, '#CCCCCC')}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
                    QSlider::sub-page:horizontal {{ background: {colors.get(key, '#CCCCCC')}; border-radius: 2px; }}
                """)
                row.addWidget(slider)
                
                # Value Input
                val_input = QLineEdit(str(target))
                val_input.setFixedWidth(40)
                val_input.setStyleSheet("border: 1px solid #d9d8d3; border-radius: 4px; padding: 4px; text-align: right;")
                row.addWidget(val_input)
                
                pct_lbl = QLabel("%")
                pct_lbl.setStyleSheet("border: none;")
                row.addWidget(pct_lbl)
                
                # Bindings
                self.alloc_sliders[key] = slider
                self.alloc_inputs[key] = val_input
                
                def on_slider_change(val, k=key, i=val_input):
                    i.setText(str(val))
                    update_total()
                    
                def on_input_change(txt, k=key, s=slider):
                    try:
                        v = int(txt)
                        if 0 <= v <= 100:
                            s.setValue(v)
                    except:
                        pass
                        
                slider.valueChanged.connect(on_slider_change)
                val_input.textChanged.connect(on_input_change)
                
                edit_layout.addLayout(row)
                
            # Footer row for total & actions
            footer_row = QHBoxLayout()
            save_btn = QPushButton("Save")
            save_btn.setObjectName("saveButton")
            save_btn.setStyleSheet("""
                QPushButton { background-color: #92bca4; color: white; border: none; border-radius: 4px; padding: 8px 16px; font-weight: 600; }
                QPushButton:enabled { background-color: #2b7a52; }
            """)
            save_btn.setCursor(Qt.PointingHandCursor)
            
            def save_targets():
                targets = {k: float(s.value()) for k, s in self.alloc_sliders.items()}
                update_category_targets(targets)
                self._toggle_allocation_edit_mode()
                
            save_btn.clicked.connect(save_targets)
            footer_row.addWidget(save_btn)
            
            reset_btn = QPushButton("Reset to Default")
            reset_btn.setObjectName("secondaryButton")
            reset_btn.setCursor(Qt.PointingHandCursor)
            
            def reset_targets():
                for s in self.alloc_sliders.values(): s.setValue(0)
            reset_btn.clicked.connect(reset_targets)
            footer_row.addWidget(reset_btn)
            
            footer_row.addStretch()
            
            edit_layout.addSpacing(16)
            edit_layout.addLayout(footer_row)
            
            self.allocation_target_content.addWidget(edit_container)
            update_total()

        else:
            # View Mode: Custom Canvas Draw for Stacked Bar
            bar_data = []
            desc_text = "Target allocation"
            for cat in categories:
                pct = float(cat["target_percentage"]) if "target_percentage" in cat.keys() and cat["target_percentage"] is not None else 0.0
                if pct > 0:
                    bar_data.append((cat["category_key"], cat["category_name"], pct, colors.get(cat["category_key"], "#CCC")))
            
            view_container = QWidget()
            vl = QVBoxLayout(view_container)
            vl.setContentsMargins(0,0,0,0)
            
            if not bar_data:
                desc_text = "No target allocation set. Click Edit to set one."
            else:
                stacked_bar = TargetStackedBar(bar_data)
                vl.addWidget(stacked_bar)
                
            desc_lbl = QLabel(desc_text)
            desc_lbl.setStyleSheet("font-size: 11px; color: #6b6962;")
            vl.addWidget(desc_lbl)
            
            self.allocation_target_content.addWidget(view_container)
            
        # Target vs Actual Logic
        self._clear_layout(self.allocation_actuals_content)
        
        assets = fetch_assets()
        cat_actuals = {}
        total_actual = 0.0
        
        for a in assets:
            cat = a["category_key"]
            val = float(a["value"])
            if cat not in cat_actuals:
                cat_actuals[cat] = 0.0
            cat_actuals[cat] += val
            total_actual += val
            
        actuals_data = []
        for cat in categories:
            key = cat["category_key"]
            target_pct = float(cat["target_percentage"]) if "target_percentage" in cat.keys() and cat["target_percentage"] is not None else 0.0
            actual_val = cat_actuals.get(key, 0.0)
            actual_pct = (actual_val / total_actual * 100) if total_actual > 0 else 0.0
            
            target_val = (target_pct / 100.0) * total_actual
            diff_val = actual_val - target_val
            diff_pct = actual_pct - target_pct
            
            actuals_data.append({
                "key": key,
                "name": cat["category_name"],
                "color": colors.get(key, "#CCC"),
                "actual_val": actual_val,
                "actual_pct": actual_pct,
                "target_val": target_val,
                "target_pct": target_pct,
                "diff_val": diff_val,
                "diff_pct": diff_pct
            })
            
        # 1. Big Actual Stacked Bar
        actuals_view = QWidget()
        actuals_vl = QVBoxLayout(actuals_view)
        actuals_vl.setContentsMargins(0,0,0,0)
        actuals_vl.setSpacing(16)
        
        bar_data = [(d["key"], d["name"], d["actual_pct"], d["color"]) for d in actuals_data if d["actual_pct"] > 0]
        
        if total_actual > 0 and bar_data:
            from PySide6.QtGui import QPainter, QColor, QFont
            from PySide6.QtWidgets import QToolTip
            # Recycle or redefine TargetStackedBar for actuals
            class ActualStackedBar(QWidget):
                def __init__(self, data, on_hover_callback=None):
                    super().__init__()
                    self.data = data
                    self.on_hover_callback = on_hover_callback
                    self.setFixedHeight(30)
                    self.setMouseTracking(True)
                    self._hovered_idx = -1
                    
                def mouseMoveEvent(self, event):
                    total_width = self.rect().width()
                    current_x = 0
                    for i, (key, name, pct, color) in enumerate(self.data):
                        w = (pct / 100.0) * total_width
                        if current_x <= event.position().x() <= current_x + w:
                            if self._hovered_idx != i:
                                self._hovered_idx = i
                                QToolTip.showText(event.globalPosition().toPoint(), f"{name}: {pct:.1f}%", self)
                                if self.on_hover_callback:
                                    self.on_hover_callback(key)
                                self.update()
                            return
                        current_x += w
                    if self._hovered_idx != -1:
                        self._hovered_idx = -1
                        QToolTip.hideText()
                        if self.on_hover_callback:
                            self.on_hover_callback(None)
                        self.update()

                def leaveEvent(self, event):
                    self._hovered_idx = -1
                    QToolTip.hideText()
                    if self.on_hover_callback:
                        self.on_hover_callback(None)
                    self.update()

                def paintEvent(self, event):
                    painter = QPainter(self)
                    painter.setRenderHint(QPainter.Antialiasing)
                    rect = self.rect()
                    total_width = rect.width()
                    current_x = 0
                    
                    for i, (key, name, pct, color) in enumerate(self.data):
                        w = (pct / 100.0) * total_width
                        
                        painter.fillRect(int(current_x), 0, int(w), 20, QColor(color))
                        
                        # Draw hover highlights
                        if i == self._hovered_idx:
                            painter.setBrush(QColor(255, 255, 255, 60))
                            painter.drawRect(int(current_x), 0, int(w), 20)
                            
                        if w > 60:
                            painter.setPen(QColor("white"))
                            painter.setFont(QFont("Segoe UI", 9))
                            painter.drawText(int(current_x), 0, int(w), 20, Qt.AlignCenter, f"{name} {pct:.1f}%")
                        elif w > 30:
                            painter.setPen(QColor("white"))
                            painter.setFont(QFont("Segoe UI", 9))
                            short_name = name[:3] + "." if len(name) > 3 else name
                            painter.drawText(int(current_x), 0, int(w), 20, Qt.AlignCenter, short_name)
                            
                        current_x += w
            
            self._category_rows = {}
            def handle_bar_hover(key):
                for k, row_widget in self._category_rows.items():
                    if k == key:
                        row_widget.setStyleSheet("QFrame#catRow { background-color: #f7f7f5; border-bottom: 1px solid #f0f0f0; border-radius: 6px; }")
                    else:
                        row_widget.setStyleSheet("QFrame#catRow { background-color: transparent; border-bottom: 1px solid #f0f0f0; border-radius: 0px; }")
                        
            actuals_vl.addWidget(ActualStackedBar(bar_data, handle_bar_hover))
        else:
            empty_lbl = QLabel("No assets to show for actual allocation.")
            empty_lbl.setStyleSheet("color: #6b6962; font-size: 13px;")
            actuals_vl.addWidget(empty_lbl)
            
        # 2. Category Breakdown Rows
        
        class CategoryDiffRow(QFrame):
            def __init__(self, data):
                super().__init__()
                self.setObjectName("catRow")
                self.setStyleSheet("QFrame#catRow { background-color: transparent; border-bottom: 1px solid #f0f0f0; border-radius: 0px; }")
                layout = QVBoxLayout(self)
                layout.setContentsMargins(0, 16, 0, 16)
                layout.setSpacing(8)
                
                header_row = QHBoxLayout()
                
                color_box = QLabel()
                color_box.setFixedSize(10, 10)
                color_box.setStyleSheet(f"background-color: {data['color']}; border-radius: 2px; border: none;")
                header_row.addWidget(color_box)
                
                name_lbl = QLabel(data['name'])
                name_lbl.setStyleSheet("font-family: 'Segoe UI'; font-size: 13px; font-weight: bold; border: none;")
                header_row.addWidget(name_lbl)
                
                diff_pct_str = f"+{data['diff_pct']:.1f}%" if data['diff_pct'] >= 0 else f"{data['diff_pct']:.1f}%"
                diff_lbl = QLabel(diff_pct_str)
                bg_color = "#e8f3ec" if data['diff_pct'] >= 0 else "#f9eaea"
                tx_color = "#2b7a52" if data['diff_pct'] >= 0 else "#c23b31"
                diff_lbl.setStyleSheet(f"background-color: {bg_color}; color: {tx_color}; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; border: none;")
                header_row.addWidget(diff_lbl)
                
                header_row.addStretch()
                layout.addLayout(header_row)
                
                # Visual Bar with Target Marker
                class ProgressBarWithTarget(QWidget):
                    def paintEvent(self, event):
                        from PySide6.QtGui import QPainter, QColor, QPen
                        painter = QPainter(self)
                        painter.setRenderHint(QPainter.Antialiasing)
                        rect = self.rect()
                        
                        # Background
                        painter.fillRect(0, 0, rect.width(), 12, QColor("#f4f3ef"))
                        
                        # Fill
                        fill_w = (data['actual_pct'] / 100.0) * rect.width()
                        painter.fillRect(0, 0, int(fill_w), 12, QColor(data['color']))
                        
                        # Target Marker
                        target_x = (data['target_pct'] / 100.0) * rect.width()
                        pen = QPen(QColor("#a9a8a5"))
                        pen.setWidth(2)
                        painter.setPen(pen)
                        painter.drawLine(int(target_x), -2, int(target_x), 14)

                bar = ProgressBarWithTarget()
                bar.setFixedHeight(16)
                layout.addWidget(bar)
                
                # Details text
                details_row = QHBoxLayout()
                curr_txt = f"Current <b>{data['actual_pct']:.1f}%</b> ({format_signed_compact_inr(data['actual_val']).replace('+','')})"
                tgt_txt = f"Target <b>{data['target_pct']:.0f}%</b> ({format_signed_compact_inr(data['target_val']).replace('+','')})"
                
                details_lbl = QLabel(f"{curr_txt}   {tgt_txt}")
                details_lbl.setStyleSheet("font-size: 12px; color: #6b6962; border: none;")
                details_row.addWidget(details_lbl)
                
                if abs(data['diff_pct']) > 0.1: # Only suggest action if diff is meaningful
                    action_txt = "Reduce" if data['diff_val'] > 0 else "Add"
                    action_val = format_signed_compact_inr(abs(data['diff_val'])).replace('+','')
                    action_lbl = QLabel(f"→ <span style='color: {'#c23b31' if action_txt == 'Reduce' else '#2b7a52'}; font-weight: bold;'>{action_txt} {action_val}</span>")
                    action_lbl.setStyleSheet("font-size: 12px; border: none;")
                    details_row.addWidget(action_lbl)
                
                details_row.addStretch()
                layout.addLayout(details_row)
        
        if not hasattr(self, "_category_rows"):
            self._category_rows = {}
        self._category_rows.clear()
            
        for d in actuals_data:
            if d["actual_val"] > 0 or d["target_pct"] > 0:
                row = CategoryDiffRow(d)
                self._category_rows[d["key"]] = row
                actuals_vl.addWidget(row)
                
        self.allocation_actuals_content.addWidget(actuals_view)

    def _build_edit_asset_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 26, 32, 24)
        layout.setSpacing(16)

        header_title = QLabel("Edit Asset")
        header_title.setObjectName("addAssetTitle")
        layout.addWidget(header_title)

        self.edit_class_subtitle = QLabel("Asset Class")
        self.edit_class_subtitle.setObjectName("editAssetClassSubtitle")
        layout.addWidget(self.edit_class_subtitle)

        card = QFrame()
        card.setObjectName("formCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 16, 20, 14)
        card_layout.setSpacing(12)

        section_title = QLabel("Edit Asset")
        section_title.setObjectName("sectionTitle")
        card_layout.addWidget(section_title)

        class_label = QLabel("Asset Class")
        class_label.setObjectName("fieldLabel")
        card_layout.addWidget(class_label)

        self.edit_asset_class_combo = QComboBox()
        self.edit_asset_class_combo.setObjectName("classPicker")
        self.edit_asset_class_combo.currentIndexChanged.connect(self._on_edit_class_combo_changed)
        card_layout.addWidget(self.edit_asset_class_combo)

        fields_grid = QGridLayout()
        fields_grid.setHorizontalSpacing(12)
        fields_grid.setVerticalSpacing(8)

        name_label = QLabel("Name *")
        name_label.setObjectName("fieldLabel")
        fields_grid.addWidget(name_label, 0, 0)

        value_label = QLabel("Current Value *")
        value_label.setObjectName("fieldLabel")
        fields_grid.addWidget(value_label, 0, 1)

        currency_label = QLabel("Currency")
        currency_label.setObjectName("fieldLabel")
        fields_grid.addWidget(currency_label, 0, 2)

        self.edit_name_input = QLineEdit()
        self.edit_name_input.setObjectName("formInput")
        fields_grid.addWidget(self.edit_name_input, 1, 0)

        self.edit_current_value_input = QLineEdit()
        self.edit_current_value_input.setObjectName("formInput")
        fields_grid.addWidget(self.edit_current_value_input, 1, 1)

        self.edit_currency_combo = QComboBox()
        self.edit_currency_combo.setObjectName("formInput")
        self.edit_currency_combo.addItems(["INR", "USD", "EUR", "GBP"])
        fields_grid.addWidget(self.edit_currency_combo, 1, 2)

        invested_label = QLabel("Invested Amount")
        invested_label.setObjectName("fieldLabel")
        fields_grid.addWidget(invested_label, 2, 0)

        self.edit_invested_input = QLineEdit()
        self.edit_invested_input.setObjectName("formInput")
        fields_grid.addWidget(self.edit_invested_input, 3, 0)

        invested_hint = QLabel("Optional - enables gain/loss tracking")
        invested_hint.setObjectName("helperLabel")
        fields_grid.addWidget(invested_hint, 4, 0)

        fields_grid.setColumnStretch(0, 2)
        fields_grid.setColumnStretch(1, 2)
        fields_grid.setColumnStretch(2, 1)
        card_layout.addLayout(fields_grid)

        self.edit_details_toggle = QPushButton("^ Hide details")
        self.edit_details_toggle.setObjectName("disclosure")
        self.edit_details_toggle.setCursor(Qt.PointingHandCursor)
        self.edit_details_toggle.clicked.connect(self._toggle_edit_details)
        card_layout.addWidget(self.edit_details_toggle)

        details_divider = QFrame()
        details_divider.setFrameShape(QFrame.HLine)
        details_divider.setStyleSheet("color: #e1e0db;")
        card_layout.addWidget(details_divider)

        self.edit_details_box = QWidget()
        edit_details_layout = QGridLayout(self.edit_details_box)
        edit_details_layout.setHorizontalSpacing(12)
        edit_details_layout.setVerticalSpacing(8)

        geography_label = QLabel("Geography")
        geography_label.setObjectName("fieldLabel")
        edit_details_layout.addWidget(geography_label, 0, 0)

        subclass_label = QLabel("Sub-class")
        subclass_label.setObjectName("fieldLabel")
        edit_details_layout.addWidget(subclass_label, 0, 1)

        self.edit_geography_combo = QComboBox()
        self.edit_geography_combo.setObjectName("formInput")
        self.edit_geography_combo.addItems(
            ["India", "United States", "Europe", "Global", "Asia Pacific", "Other"]
        )
        edit_details_layout.addWidget(self.edit_geography_combo, 1, 0)

        self.edit_subclass_input = QLineEdit()
        self.edit_subclass_input.setObjectName("formInput")
        edit_details_layout.addWidget(self.edit_subclass_input, 1, 1)

        tags_label = QLabel("Tags")
        tags_label.setObjectName("fieldLabel")
        edit_details_layout.addWidget(tags_label, 2, 0, 1, 2)

        self.edit_tag_input = QLineEdit()
        self.edit_tag_input.setObjectName("formInput")
        self.edit_tag_input.textChanged.connect(self._update_edit_tag_preview)
        edit_details_layout.addWidget(self.edit_tag_input, 3, 0, 1, 2)

        self.edit_tag_preview = QLabel("")
        self.edit_tag_preview.setObjectName("tagPreview")
        self.edit_tag_preview.hide()
        edit_details_layout.addWidget(self.edit_tag_preview, 4, 0, 1, 2, alignment=Qt.AlignLeft)

        notes_label = QLabel("Notes")
        notes_label.setObjectName("fieldLabel")
        edit_details_layout.addWidget(notes_label, 5, 0, 1, 2)

        self.edit_notes_input = QLineEdit()
        self.edit_notes_input.setObjectName("formInput")
        self.edit_notes_input.setPlaceholderText("Optional notes...")
        edit_details_layout.addWidget(self.edit_notes_input, 6, 0, 1, 2)

        edit_details_layout.setColumnStretch(0, 1)
        edit_details_layout.setColumnStretch(1, 2)
        card_layout.addWidget(self.edit_details_box)

        save_divider = QFrame()
        save_divider.setFrameShape(QFrame.HLine)
        save_divider.setStyleSheet("color: #e1e0db;")
        card_layout.addWidget(save_divider)

        self.edit_form_status = QLabel("")
        self.edit_form_status.setObjectName("statusError")
        self.edit_form_status.hide()
        card_layout.addWidget(self.edit_form_status)

        actions = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondaryButton")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.clicked.connect(self._cancel_edit_asset)
        actions.addWidget(cancel_btn)

        actions.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        save_btn = QPushButton("Save Asset")
        save_btn.setObjectName("saveButton")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.clicked.connect(self._save_edited_asset)
        actions.addWidget(save_btn)

        card_layout.addLayout(actions)
        layout.addWidget(card)
        layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding))
        return page

    def _clear_layout(self, layout: QHBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _make_chip(self, text: str, active: bool = False) -> QPushButton:
        chip = QPushButton(text)
        chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        chip.setObjectName("chip")
        chip.setProperty("active", active)
        chip.setCursor(Qt.PointingHandCursor)
        return chip

    def _build_selection_divider(self) -> QWidget:
        divider = QFrame()
        divider.setFrameShape(QFrame.VLine)
        divider.setStyleSheet("color: #dfddd7;")
        divider.setFixedHeight(20)
        return divider

    def _get_row_action_icon(self, action: str) -> QIcon:
        cached_icon = self.row_action_icons.get(action)
        if cached_icon is not None:
            return cached_icon

        icon = self._draw_row_action_icon(action)
        self.row_action_icons[action] = icon
        return icon

    def _draw_row_action_icon(self, action: str) -> QIcon:
        size = 16
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(QColor("#363530"))
        pen.setWidthF(1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        if action == "add_tag":
            painter.save()
            painter.translate(8, 8)
            painter.rotate(-45)
            painter.drawRoundedRect(-5.0, -2.8, 9.0, 5.6, 1.1, 1.1)
            painter.restore()
            painter.drawEllipse(10.2, 3.6, 1.8, 1.8)
        elif action == "edit":
            painter.drawLine(3.1, 12.9, 4.9, 11.1)
            painter.drawLine(4.6, 12.6, 12.0, 5.2)
            tip = QPainterPath()
            tip.moveTo(11.2, 4.4)
            tip.lineTo(12.8, 2.8)
            tip.lineTo(14.0, 4.0)
            tip.lineTo(12.4, 5.6)
            tip.closeSubpath()
            painter.drawPath(tip)
            painter.drawLine(3.1, 12.9, 4.8, 13.7)
        elif action == "delete":
            painter.drawLine(4.0, 4.6, 12.0, 4.6)
            painter.drawLine(6.7, 3.2, 9.3, 3.2)
            painter.drawRect(4.8, 5.4, 6.4, 7.0)
            painter.drawLine(6.8, 6.6, 6.8, 11.3)
            painter.drawLine(8.0, 6.6, 8.0, 11.3)
            painter.drawLine(9.2, 6.6, 9.2, 11.3)
        else:
            painter.drawEllipse(4.5, 4.5, 7.0, 7.0)

        painter.end()
        return QIcon(pixmap)

    def _build_row_context_menu(self, asset_id: int) -> QWidget:
        menu_widget = QWidget()
        menu_widget.setObjectName("rowContextMenu")
        layout = QHBoxLayout(menu_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        add_tag_button = QToolButton()
        add_tag_button.setObjectName("rowActionButton")
        add_tag_button.setCursor(Qt.PointingHandCursor)
        add_tag_button.setIcon(self._get_row_action_icon("add_tag"))
        add_tag_button.setIconSize(QSize(14, 14))
        add_tag_button.setToolTip("Add Tag")
        add_tag_button.clicked.connect(
            lambda _checked=False, selected_asset_id=asset_id: self._add_tag_from_context(selected_asset_id)
        )
        layout.addWidget(add_tag_button)

        edit_button = QToolButton()
        edit_button.setObjectName("rowActionButton")
        edit_button.setCursor(Qt.PointingHandCursor)
        edit_button.setIcon(self._get_row_action_icon("edit"))
        edit_button.setIconSize(QSize(14, 14))
        edit_button.setToolTip("Edit")
        edit_button.clicked.connect(
            lambda _checked=False, selected_asset_id=asset_id: self._edit_asset_from_context(selected_asset_id)
        )
        layout.addWidget(edit_button)

        delete_button = QToolButton()
        delete_button.setObjectName("rowDeleteActionButton")
        delete_button.setCursor(Qt.PointingHandCursor)
        delete_button.setIcon(self._get_row_action_icon("delete"))
        delete_button.setIconSize(QSize(14, 14))
        delete_button.setToolTip("Delete")
        delete_button.clicked.connect(
            lambda _checked=False, selected_asset_id=asset_id: self._delete_asset_from_context(selected_asset_id)
        )
        layout.addWidget(delete_button)
        return menu_widget

    def _find_asset_by_id(self, asset_id: int) -> object | None:
        for asset in self.all_assets:
            if int(asset["id"]) == asset_id:
                return asset
        return None

    def _add_tag_from_context(self, asset_id: int) -> None:
        asset = self._find_asset_by_id(asset_id)
        if asset is None:
            return

        current_tag = (asset["tag"] or "").strip()
        tag, accepted = QInputDialog.getText(self, "Add Tag", "Tag:", text=current_tag)
        if not accepted:
            return

        try:
            update_asset_tag(asset_id, tag.strip())
        except Exception:
            QMessageBox.critical(self, "Tag update failed", "Unable to update tag for this asset.")
            return
        self._refresh_assets_view()

    def _edit_asset_from_context(self, asset_id: int) -> None:
        self._show_edit_asset_page(asset_id)

    def _delete_asset_from_context(self, asset_id: int) -> None:
        asset = self._find_asset_by_id(asset_id)
        if asset is None:
            return

        choice = QMessageBox.question(
            self,
            "Delete asset",
            f"Delete '{asset['name']}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if choice != QMessageBox.Yes:
            return

        try:
            delete_assets([asset_id])
        except Exception:
            QMessageBox.critical(self, "Delete failed", "Unable to delete this asset.")
            return

        self.selected_asset_ids.discard(asset_id)
        self._refresh_assets_view()

    def _set_combo_text(self, combo: QComboBox, value: str, default: str | None = None) -> None:
        target_value = value.strip() if value else ""
        if not target_value and default is not None:
            target_value = default
        if not target_value:
            combo.setCurrentIndex(0)
            return

        index = combo.findText(target_value)
        if index < 0:
            combo.addItem(target_value)
            index = combo.findText(target_value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _show_edit_asset_page(self, asset_id: int) -> None:
        asset = self._find_asset_by_id(asset_id)
        if asset is None:
            self._refresh_assets_view()
            return

        class_key = asset["class_key"] or self.selected_form_class_key
        if class_key not in self.class_lookup:
            class_key = self.selected_form_class_key

        self.editing_asset_id = asset_id
        self.selected_edit_class_key = class_key
        self._populate_edit_asset_class_combo(class_key)
        self._on_edit_class_combo_changed(self.edit_asset_class_combo.currentIndex())

        self.edit_name_input.setText(asset["name"] or "")
        self.edit_current_value_input.setText(f"{float(asset['value']):.2f}".rstrip("0").rstrip("."))
        self.edit_invested_input.setText(f"{float(asset['invested']):.2f}".rstrip("0").rstrip("."))
        self.edit_subclass_input.setText(asset["sub_type"] or "")
        self.edit_tag_input.setText(asset["tag"] or "")
        self.edit_notes_input.setText(asset["notes"] or "")
        self._set_combo_text(self.edit_currency_combo, (asset["currency"] or "INR").upper(), default="INR")
        self._set_combo_text(self.edit_geography_combo, asset["geography"] or "India", default="India")

        self.edit_details_box.show()
        self.edit_details_toggle.setText("^ Hide details")
        self._update_edit_tag_preview()
        self._clear_edit_form_status()
        self._set_active_nav_item("Assets")
        self.content_stack.setCurrentIndex(self.EDIT_ASSET_PAGE_INDEX)
        self.edit_name_input.setFocus()

    def _toggle_edit_details(self) -> None:
        if self.edit_details_box.isVisible():
            self.edit_details_box.hide()
            self.edit_details_toggle.setText("v Show details")
        else:
            self.edit_details_box.show()
            self.edit_details_toggle.setText("^ Hide details")

    def _update_edit_tag_preview(self) -> None:
        tag_text = self.edit_tag_input.text().strip()
        if tag_text:
            self.edit_tag_preview.setText(tag_text)
            self.edit_tag_preview.show()
        else:
            self.edit_tag_preview.hide()

    def _clear_edit_form_status(self) -> None:
        self.edit_form_status.hide()
        self.edit_form_status.setText("")
        self.edit_form_status.setObjectName("statusError")

    def _set_edit_form_error(self, message: str) -> None:
        self.edit_form_status.setObjectName("statusError")
        self.edit_form_status.setText(message)
        self.edit_form_status.show()
        self.edit_form_status.style().unpolish(self.edit_form_status)
        self.edit_form_status.style().polish(self.edit_form_status)

    def _cancel_edit_asset(self) -> None:
        self.editing_asset_id = None
        self._clear_edit_form_status()
        self._show_assets_page()

    def _save_edited_asset(self) -> None:
        if self.editing_asset_id is None:
            self._set_edit_form_error("No asset selected for editing.")
            return

        class_key = self.edit_asset_class_combo.currentData(Qt.UserRole)
        if not class_key:
            self._set_edit_form_error("Please select an asset class.")
            return

        name = self.edit_name_input.text().strip()
        if not name:
            self._set_edit_form_error("Name is required.")
            return

        current_value_text = self.edit_current_value_input.text().strip()
        if not current_value_text:
            self._set_edit_form_error("Current value is required.")
            return

        try:
            current_value = parse_amount(current_value_text)
        except ValueError:
            self._set_edit_form_error("Current value must be a valid number.")
            return
        if current_value <= 0:
            self._set_edit_form_error("Current value must be greater than 0.")
            return

        invested_text = self.edit_invested_input.text().strip()
        if invested_text:
            try:
                invested_value = parse_amount(invested_text)
            except ValueError:
                self._set_edit_form_error("Invested amount must be a valid number.")
                return
            if invested_value < 0:
                self._set_edit_form_error("Invested amount cannot be negative.")
                return
        else:
            invested_value = current_value

        try:
            update_asset_details(
                asset_id=self.editing_asset_id,
                class_key=class_key,
                name=name,
                sub_type=self.edit_subclass_input.text().strip() or "-",
                geography=self.edit_geography_combo.currentText().strip() or "India",
                invested=invested_value,
                value=current_value,
                tag=self.edit_tag_input.text().strip(),
                currency=self.edit_currency_combo.currentText().strip() or "INR",
                notes=self.edit_notes_input.text().strip(),
            )
        except Exception:
            self._set_edit_form_error("Unable to save asset changes.")
            return

        self.editing_asset_id = None
        self.selected_asset_ids.clear()
        self._clear_edit_form_status()
        self._show_assets_page()

    def _set_hovered_row(self, row_idx: int) -> None:
        hovered_asset_id: int | None = None
        if 0 <= row_idx < len(self.paged_filtered_assets):
            hovered_asset_id = int(self.paged_filtered_assets[row_idx]["id"])

        if hovered_asset_id == self.hovered_asset_id:
            return

        previous_hovered_asset_id = self.hovered_asset_id
        self.hovered_asset_id = hovered_asset_id
        for asset_id, menu_widget in self.asset_context_menu_by_id.items():
            menu_widget.setVisible(asset_id == hovered_asset_id)
        self._apply_row_state_visual(previous_hovered_asset_id)
        self._apply_row_state_visual(hovered_asset_id)

    def _is_row_highlighted(self, asset_id: int) -> bool:
        return asset_id in self.selected_asset_ids or asset_id == self.hovered_asset_id

    def _apply_row_state_visual(self, asset_id: int | None) -> None:
        if asset_id is None:
            return

        is_highlighted = self._is_row_highlighted(asset_id)
        for widget in self.asset_row_widgets_by_id.get(asset_id, []):
            widget.setProperty("rowHover", is_highlighted)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

        row_color = QColor("#f3f2ee") if is_highlighted else QColor("#ffffff")
        for item in self.asset_row_items_by_id.get(asset_id, []):
            item.setBackground(row_color)

    def _refresh_visible_row_highlights(self) -> None:
        for asset_id in self.asset_row_by_id:
            self._apply_row_state_visual(asset_id)

    def eventFilter(self, watched: object, event: object) -> bool:
        if watched is self.asset_table.viewport():
            event_type = event.type()
            if event_type == QEvent.Type.MouseMove:
                y_pos = int(event.position().y()) if hasattr(event, "position") else event.pos().y()
                self._set_hovered_row(self.asset_table.rowAt(y_pos))
            elif event_type == QEvent.Type.Leave:
                self._set_hovered_row(-1)

        return super().eventFilter(watched, event)

    def _build_grouped_class_model(
        self,
        selected_class_key: str | None = None,
        placeholder_text: str | None = None,
    ) -> tuple[QStandardItemModel, int]:
        model = QStandardItemModel()
        selected_index = 0
        index = 0
        first_selectable_index: int | None = None

        if placeholder_text:
            placeholder_item = QStandardItem(placeholder_text)
            placeholder_item.setData(None, Qt.UserRole)
            model.appendRow(placeholder_item)
            selected_index = 0
            index += 1

        for category in self.categories:
            category_key = category["category_key"]
            classes = [row for row in self.asset_classes if row["category_key"] == category_key]
            if not classes:
                continue

            header_item = QStandardItem(category["category_name"])
            header_item.setFlags(Qt.NoItemFlags)
            model.appendRow(header_item)
            index += 1

            for class_row in classes:
                item = QStandardItem(f"   {class_row['class_name']}")
                item.setData(class_row["class_key"], Qt.UserRole)
                model.appendRow(item)
                if first_selectable_index is None:
                    first_selectable_index = index
                if selected_class_key and class_row["class_key"] == selected_class_key:
                    selected_index = index
                index += 1

        if selected_class_key is None and placeholder_text is None and first_selectable_index is not None:
            selected_index = first_selectable_index

        return model, selected_index

    def _class_icon_for(self, class_key: str):
        icon_name = ADD_CLASS_ICON_MAP.get(class_key, "SP_FileIcon")
        icon_type = getattr(QStyle.StandardPixmap, icon_name, QStyle.StandardPixmap.SP_FileIcon)
        return self.style().standardIcon(icon_type)

    def _populate_add_asset_class_tiles(self) -> None:
        self.add_class_tile_buttons: dict[str, QToolButton] = {}

        while self.add_class_tiles_grid.count():
            item = self.add_class_tiles_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for idx, class_row in enumerate(self.asset_classes):
            class_key = class_row["class_key"]
            button = QToolButton()
            button.setObjectName("classTile")
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setCursor(Qt.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setMinimumHeight(92)
            button.setText(class_row["class_name"])
            button.setIcon(self._class_icon_for(class_key))
            button.setIconSize(QSize(24, 24))
            button.setProperty("selected", class_key == self.selected_form_class_key)
            button.clicked.connect(
                lambda _checked=False, selected_class_key=class_key: self._on_add_class_tile_clicked(selected_class_key)
            )
            self.add_class_tile_buttons[class_key] = button

            row = idx // 4
            column = idx % 4
            self.add_class_tiles_grid.addWidget(button, row, column)

    def _refresh_add_class_tile_styles(self) -> None:
        for class_key, button in self.add_class_tile_buttons.items():
            button.setProperty("selected", class_key == self.selected_form_class_key)
            button.style().unpolish(button)
            button.style().polish(button)

    def _on_add_class_tile_clicked(self, class_key: str) -> None:
        self.selected_form_class_key = class_key
        self._refresh_add_class_tile_styles()
        self._apply_form_class(class_key)
        self._set_add_form_visibility(True)
        self.name_input.setFocus()

    def _populate_edit_asset_class_combo(self, selected_class_key: str | None = None) -> None:
        if selected_class_key is None:
            selected_class_key = self.selected_edit_class_key
        model, selected_index = self._build_grouped_class_model(selected_class_key=selected_class_key)
        self.edit_asset_class_combo.blockSignals(True)
        self.edit_asset_class_combo.setModel(model)
        self.edit_asset_class_combo.setCurrentIndex(selected_index)
        self.edit_asset_class_combo.blockSignals(False)

    def _on_edit_class_combo_changed(self, _index: int) -> None:
        class_key = self.edit_asset_class_combo.currentData(Qt.UserRole)
        if not class_key:
            return
        self.selected_edit_class_key = class_key
        class_meta = self.class_lookup.get(class_key)
        if class_meta:
            self.edit_class_subtitle.setText(class_meta["class_name"])

    def _apply_form_class(self, class_key: str) -> None:
        class_meta = self.class_lookup.get(class_key)
        if class_meta is None:
            return
        self.add_step_label.setText(f"Step 2 of 2: {class_meta['class_name']}")
        self.details_title.setText(f"Asset Details: {class_meta['class_name']}")

    def _set_add_form_visibility(self, is_visible: bool) -> None:
        self.add_details_card.setVisible(is_visible)
        if not is_visible:
            self.add_step_label.setText("Step 1 of 2: Select Asset Class")

    def _get_inr_rate(self, currency: str | None) -> float:
        code = normalize_currency(currency)
        if code == "INR":
            return 1.0
        return float(self.exchange_rates.get(code, 1.0))

    def _convert_to_inr(self, amount: float, currency: str | None) -> float:
        return float(amount) * self._get_inr_rate(currency)

    def _show_add_class_picker_only(self) -> None:
        self._set_add_form_visibility(False)

    def _on_search_text_changed(self, _text: str) -> None:
        self.current_page = 1
        self._refresh_assets_view()

    def _recalculate_pagination(self) -> None:
        filtered_count = len(self.filtered_assets)
        if filtered_count == 0:
            self.total_pages = 1
            self.current_page = 1
            self.paged_filtered_assets = []
        else:
            self.total_pages = max(1, (filtered_count + self.page_size - 1) // self.page_size)
            if self.current_page < 1:
                self.current_page = 1
            if self.current_page > self.total_pages:
                self.current_page = self.total_pages

            start_idx = (self.current_page - 1) * self.page_size
            end_idx = start_idx + self.page_size
            self.paged_filtered_assets = self.filtered_assets[start_idx:end_idx]

        self.prev_page_button.setEnabled(self.current_page > 1)
        self.next_page_button.setEnabled(self.current_page < self.total_pages)
        self.page_indicator_button.setText(f"{self.current_page} / {self.total_pages}")

    def _go_to_prev_page(self) -> None:
        if self.current_page <= 1:
            return
        self.current_page -= 1
        self._recalculate_pagination()
        self._populate_assets_table()
        self._update_selection_bar()

    def _go_to_next_page(self) -> None:
        if self.current_page >= self.total_pages:
            return
        self.current_page += 1
        self._recalculate_pagination()
        self._populate_assets_table()
        self._update_selection_bar()

    def _asset_matches_search(self, asset: object, search_tokens: list[str]) -> bool:
        if not search_tokens:
            return True

        searchable_parts = [
            asset["name"] or "",
            asset["asset_class"] or "",
            asset["class_code"] or "",
            asset["sub_type"] or "",
            asset["tag"] or "",
            asset["notes"] or "",
            asset["geography"] or "",
            asset["currency"] or "",
            asset["category_name"] or "",
        ]
        searchable_text = normalize_search_text(" ".join(str(part) for part in searchable_parts if part))
        searchable_words = searchable_text.split()
        searchable_compact = searchable_text.replace(" ", "")

        def token_matches(token: str) -> bool:
            if len(token) <= 2:
                return any(word.startswith(token) for word in searchable_words)
            return any(word.startswith(token) or token in word for word in searchable_words) or token in searchable_compact

        return all(token_matches(token) for token in search_tokens)

    def _build_category_counts_from_assets(self, assets: list[object]) -> list[dict[str, object]]:
        counts: dict[str, int] = {}
        for asset in assets:
            category_key = asset["category_key"]
            if not category_key:
                continue
            counts[category_key] = counts.get(category_key, 0) + 1

        rows: list[dict[str, object]] = []
        for category in self.categories:
            category_key = category["category_key"]
            asset_count = counts.get(category_key, 0)
            if asset_count <= 0:
                continue
            rows.append(
                {
                    "category_key": category_key,
                    "category_name": category["category_name"],
                    "asset_count": asset_count,
                }
            )
        return rows

    def _build_class_counts_from_assets(
        self,
        assets: list[object],
        category_key: str | None,
    ) -> list[dict[str, object]]:
        if category_key is None:
            return []

        counts: dict[str, int] = {}
        for asset in assets:
            class_key = asset["class_key"]
            if not class_key:
                continue
            counts[class_key] = counts.get(class_key, 0) + 1

        rows: list[dict[str, object]] = []
        for class_row in self.asset_classes:
            if class_row["category_key"] != category_key:
                continue
            class_key = class_row["class_key"]
            asset_count = counts.get(class_key, 0)
            if asset_count <= 0:
                continue
            rows.append(
                {
                    "class_key": class_key,
                    "class_name": class_row["class_name"],
                    "category_key": category_key,
                    "asset_count": asset_count,
                }
            )
        return rows

    def _sum_assets_value_inr(self, assets: list[object]) -> float:
        return sum(self._convert_to_inr(float(asset["value"]), asset["currency"]) for asset in assets)

    def _refresh_assets_view(self) -> None:
        self.all_assets = fetch_assets()
        search_text = normalize_search_text(self.search_input.text().strip())
        if search_text:
            search_tokens = search_text.split()
            search_assets = [asset for asset in self.all_assets if self._asset_matches_search(asset, search_tokens)]
        else:
            search_assets = list(self.all_assets)

        category_counts = self._build_category_counts_from_assets(search_assets)
        valid_category_keys = {row["category_key"] for row in category_counts}
        if self.selected_category_key and self.selected_category_key not in valid_category_keys:
            self.selected_category_key = None

        category_assets = [
            asset
            for asset in search_assets
            if self.selected_category_key is None or asset["category_key"] == self.selected_category_key
        ]

        class_counts = self._build_class_counts_from_assets(category_assets, self.selected_category_key)
        valid_class_keys = {row["class_key"] for row in class_counts}
        if self.selected_class_filter_key and self.selected_class_filter_key not in valid_class_keys:
            self.selected_class_filter_key = None

        scoped_assets = [
            asset
            for asset in category_assets
            if self.selected_class_filter_key is None or asset["class_key"] == self.selected_class_filter_key
        ]

        tag_counts = self._collect_tag_counts(scoped_assets)
        valid_tag_keys = {tag_key for tag_key, _label, _count in tag_counts}
        self.selected_tag_filters = {
            tag_key for tag_key in self.selected_tag_filters if tag_key in valid_tag_keys
        }

        self.filtered_assets = [asset for asset in scoped_assets if self._asset_matches_selected_tags(asset)]

        visible_asset_ids = {int(asset["id"]) for asset in self.filtered_assets}
        self.selected_asset_ids = {asset_id for asset_id in self.selected_asset_ids if asset_id in visible_asset_ids}

        self._rebuild_category_chips(category_counts, len(search_assets))
        self._rebuild_class_chips(class_counts)
        self._rebuild_tag_chips(tag_counts)
        self._recalculate_pagination()

        filtered_count = len(self.filtered_assets)
        current_page_count = len(self.paged_filtered_assets)
        filtered_total_value = self._sum_assets_value_inr(self.filtered_assets)
        comparison_assets = search_assets if search_text else self.all_assets
        comparison_total_value = self._sum_assets_value_inr(comparison_assets)

        if search_text:
            self.total_title_label.setText("SEARCH RESULTS")
        elif self.selected_class_filter_key:
            class_name = self.class_lookup[self.selected_class_filter_key]["class_name"]
            self.total_title_label.setText(class_name.upper())
        elif self.selected_category_key:
            category_name = self.category_lookup.get(self.selected_category_key, "Category")
            self.total_title_label.setText(category_name.upper())
        else:
            self.total_title_label.setText("TOTAL ASSETS")

        self.asset_count_label.setText(asset_count_label(filtered_count))
        self.total_value_label.setText(format_currency(filtered_total_value, "INR"))
        self.total_sub_value_label.setText(f"of {format_currency(comparison_total_value, 'INR')}")
        self.footer_text.setText(f"Showing {current_page_count} of {filtered_count} assets")

        self._populate_assets_table()
        self._update_selection_bar()

    def _rebuild_category_chips(self, category_counts, total_assets_count: int) -> None:
        self._clear_layout(self.category_chip_layout)

        all_chip = self._make_chip(
            f"All ({total_assets_count})",
            active=self.selected_category_key is None,
        )
        all_chip.clicked.connect(lambda: self._set_category_filter(None))
        self.category_chip_layout.addWidget(all_chip)

        for row in category_counts:
            category_key = row["category_key"]
            chip = self._make_chip(
                f"{row['category_name']} ({row['asset_count']})",
                active=self.selected_category_key == category_key,
            )
            chip.clicked.connect(lambda _checked=False, key=category_key: self._set_category_filter(key))
            self.category_chip_layout.addWidget(chip)

        self.category_chip_layout.addSpacerItem(
            QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
        )

    def _rebuild_class_chips(self, class_counts) -> None:
        self._clear_layout(self.class_chip_layout)

        if self.selected_category_key is None:
            self.class_chip_container.hide()
            return

        self.class_chip_container.show()

        total_class_assets = sum(row["asset_count"] for row in class_counts)
        category_name = self.category_lookup.get(self.selected_category_key, "Category")

        all_class_chip = self._make_chip(
            f"All {category_name} ({total_class_assets})",
            active=self.selected_class_filter_key is None,
        )
        all_class_chip.clicked.connect(lambda: self._set_class_filter(None))
        self.class_chip_layout.addWidget(all_class_chip)

        for row in class_counts:
            class_key = row["class_key"]
            chip = self._make_chip(
                f"{row['class_name']} ({row['asset_count']})",
                active=self.selected_class_filter_key == class_key,
            )
            chip.clicked.connect(lambda _checked=False, key=class_key: self._set_class_filter(key))
            self.class_chip_layout.addWidget(chip)

        self.class_chip_layout.addSpacerItem(
            QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
        )

    def _collect_tag_counts(self, assets: list[object]) -> list[tuple[str, str, int]]:
        tag_counts: dict[str, int] = {}
        tag_labels: dict[str, str] = {}
        for asset in assets:
            for tag in split_asset_tags(asset["tag"]):
                tag_key = normalize_tag(tag)
                if not tag_key:
                    continue
                tag_counts[tag_key] = tag_counts.get(tag_key, 0) + 1
                if tag_key not in tag_labels:
                    tag_labels[tag_key] = tag

        rows = [(tag_key, tag_labels[tag_key], count) for tag_key, count in tag_counts.items()]
        rows.sort(key=lambda row: (-row[2], row[1].lower()))
        return rows

    def _asset_matches_selected_tags(self, asset: object) -> bool:
        if not self.selected_tag_filters:
            return True
        asset_tags = {normalize_tag(tag) for tag in split_asset_tags(asset["tag"])}
        return bool(asset_tags.intersection(self.selected_tag_filters))

    def _rebuild_tag_chips(self, tag_counts: list[tuple[str, str, int]]) -> None:
        self.available_tag_counts = tag_counts
        self._clear_layout(self.tag_chip_layout)

        all_tags_chip = self._make_chip("All tags", active=not self.selected_tag_filters)
        all_tags_chip.clicked.connect(self._clear_tag_filters)
        self.tag_chip_layout.addWidget(all_tags_chip)

        if not tag_counts:
            self.tag_chip_layout.addSpacerItem(
                QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
            )
            return

        visible_limit = 7
        visible_tags = tag_counts[:visible_limit]
        hidden_tags = tag_counts[visible_limit:]

        for tag_key, tag_label, count in visible_tags:
            chip = self._make_chip(
                f"{tag_label} ({count})",
                active=tag_key in self.selected_tag_filters,
            )
            chip.clicked.connect(lambda _checked=False, key=tag_key: self._toggle_tag_filter(key))
            self.tag_chip_layout.addWidget(chip)

        if hidden_tags:
            hidden_count = len(hidden_tags)
            has_hidden_selection = any(tag_key in self.selected_tag_filters for tag_key, _, _ in hidden_tags)
            more_chip = self._make_chip(f"More ({hidden_count})", active=has_hidden_selection)
            more_chip.clicked.connect(self._open_more_tags_dialog)
            self.tag_chip_layout.addWidget(more_chip)

        self.tag_chip_layout.addSpacerItem(
            QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
        )

    def _toggle_tag_filter(self, tag_key: str) -> None:
        if tag_key in self.selected_tag_filters:
            self.selected_tag_filters.remove(tag_key)
        else:
            self.selected_tag_filters.add(tag_key)
        self.current_page = 1
        self._refresh_assets_view()

    def _clear_tag_filters(self) -> None:
        if not self.selected_tag_filters:
            return
        self.selected_tag_filters.clear()
        self.current_page = 1
        self._refresh_assets_view()

    def _open_more_tags_dialog(self) -> None:
        if not self.available_tag_counts:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("More Tags")
        dialog.setModal(True)
        dialog.resize(360, 460)

        layout = QVBoxLayout(dialog)
        description = QLabel("Select one or more tags to filter assets.")
        description.setObjectName("subTitle")
        layout.addWidget(description)

        tag_list = QListWidget()
        tag_list.setObjectName("tagPickerList")
        for tag_key, tag_label, count in self.available_tag_counts:
            item = QListWidgetItem(f"{tag_label} ({count})")
            item.setData(Qt.UserRole, tag_key)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if tag_key in self.selected_tag_filters else Qt.CheckState.Unchecked)
            tag_list.addItem(item)
        layout.addWidget(tag_list)

        actions = QHBoxLayout()

        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("secondaryButton")
        def clear_checks() -> None:
            for index in range(tag_list.count()):
                tag_list.item(index).setCheckState(Qt.CheckState.Unchecked)

        clear_btn.clicked.connect(clear_checks)
        actions.addWidget(clear_btn)

        actions.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondaryButton")
        cancel_btn.clicked.connect(dialog.reject)
        actions.addWidget(cancel_btn)

        apply_btn = QPushButton("Apply")
        apply_btn.setObjectName("saveButton")
        actions.addWidget(apply_btn)
        layout.addLayout(actions)

        def apply_tags() -> None:
            selected: set[str] = set()
            for index in range(tag_list.count()):
                item = tag_list.item(index)
                if item.checkState() == Qt.CheckState.Checked:
                    tag_key = item.data(Qt.UserRole)
                    if tag_key:
                        selected.add(str(tag_key))
            self.selected_tag_filters = selected
            dialog.accept()

        apply_btn.clicked.connect(apply_tags)

        if dialog.exec():
            self.current_page = 1
            self._refresh_assets_view()

    def _set_category_filter(self, category_key: str | None) -> None:
        self.selected_category_key = category_key
        self.selected_class_filter_key = None
        self.current_page = 1
        self._refresh_assets_view()

    def _set_class_filter(self, class_key: str | None) -> None:
        self.selected_class_filter_key = class_key
        self.current_page = 1
        self._refresh_assets_view()

    def _populate_assets_table(self) -> None:
        self.asset_row_by_id = {}
        self.asset_checkbox_by_id = {}
        self.asset_context_menu_by_id = {}
        self.asset_row_widgets_by_id = {}
        self.asset_row_items_by_id = {}
        self.asset_table.setRowCount(len(self.paged_filtered_assets))
        for row_idx, asset in enumerate(self.paged_filtered_assets):
            self.asset_table.setRowHeight(row_idx, 68)
            asset_id = int(asset["id"])
            self.asset_row_by_id[asset_id] = row_idx

            check_widget = QWidget()
            check_layout = QHBoxLayout(check_widget)
            check_layout.setContentsMargins(12, 0, 0, 0)
            check_layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            check_box = QCheckBox()
            check_box.setChecked(asset_id in self.selected_asset_ids)
            check_box.stateChanged.connect(
                lambda state, selected_asset_id=asset_id: self._on_asset_checkbox_toggled(selected_asset_id, state)
            )
            self.asset_checkbox_by_id[asset_id] = check_box
            check_layout.addWidget(check_box)
            check_widget.setObjectName("rowCell")
            check_widget.setProperty("rowHover", False)
            self.asset_table.setCellWidget(row_idx, 0, check_widget)

            name_widget = QWidget()
            name_layout = QVBoxLayout(name_widget)
            name_layout.setContentsMargins(0, 4, 0, 4)
            name_layout.setSpacing(2)

            name_header = QHBoxLayout()
            name_header.setContentsMargins(0, 0, 0, 0)
            name_header.setSpacing(8)
            name = QLabel(asset["name"])
            name.setObjectName("assetName")
            name_header.addWidget(name)
            name_header.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

            context_menu = self._build_row_context_menu(asset_id)
            context_menu.setVisible(asset_id == self.hovered_asset_id)
            self.asset_context_menu_by_id[asset_id] = context_menu
            name_header.addWidget(context_menu, alignment=Qt.AlignRight | Qt.AlignVCenter)
            name_layout.addLayout(name_header)

            if asset["tag"]:
                tag = QLabel(asset["tag"])
                tag.setObjectName("assetTag")
                name_layout.addWidget(tag)
            name_widget.setObjectName("rowCell")
            name_widget.setProperty("rowHover", False)
            self.asset_table.setCellWidget(row_idx, 1, name_widget)

            class_widget = QWidget()
            class_layout = QHBoxLayout(class_widget)
            class_layout.setContentsMargins(0, 0, 0, 0)
            class_layout.setSpacing(10)
            badge = QLabel(asset["class_code"])
            badge.setObjectName("classBadge")
            badge.setAlignment(Qt.AlignCenter)
            class_key = (asset["class_key"] or "").upper()
            if class_key == "GOLD_SILVER":
                badge.setProperty("tone", "gold")
            elif class_key == "MUTUAL_FUNDS":
                badge.setProperty("tone", "mf")
            else:
                badge.setProperty("tone", "default")
            class_layout.addWidget(badge)
            class_name = QLabel(asset["asset_class"])
            class_name.setObjectName("classText")
            class_layout.addWidget(class_name)
            class_layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
            class_widget.setObjectName("rowCell")
            class_widget.setProperty("rowHover", False)
            self.asset_table.setCellWidget(row_idx, 2, class_widget)

            subtype_item = QTableWidgetItem(asset["sub_type"] or "-")
            subtype_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.asset_table.setItem(row_idx, 3, subtype_item)

            asset_currency = normalize_currency(asset["currency"])
            invested_value = float(asset["invested"])
            current_value = float(asset["value"])
            invested_inr = self._convert_to_inr(invested_value, asset_currency)
            value_inr = self._convert_to_inr(current_value, asset_currency)

            invested_item = QTableWidgetItem(format_currency(invested_inr, "INR"))
            invested_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if asset_currency != "INR":
                invested_item.setToolTip(f"Original: {format_currency(invested_value, asset_currency)}")
            self.asset_table.setItem(row_idx, 4, invested_item)

            value_widget = QWidget()
            value_layout = QVBoxLayout(value_widget)
            value_layout.setContentsMargins(0, 4, 6, 4)
            value_layout.setSpacing(2)
            value_layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            value_main = QLabel(format_currency(value_inr, "INR"))
            value_main.setObjectName("valueMain")
            value_layout.addWidget(value_main, alignment=Qt.AlignRight)

            if asset_currency != "INR":
                value_sub = QLabel(format_currency(current_value, asset_currency))
                value_sub.setObjectName("valueSub")
                value_layout.addWidget(value_sub, alignment=Qt.AlignRight)

            change_pct = calculate_change_pct(invested_inr, value_inr)
            change_label = QLabel(f"{change_pct:+.1f}%")
            change_label.setObjectName("valuePctPositive" if change_pct >= 0 else "valuePctNegative")
            value_layout.addWidget(change_label, alignment=Qt.AlignRight)
            value_widget.setObjectName("rowCell")
            value_widget.setProperty("rowHover", False)
            self.asset_table.setCellWidget(row_idx, 5, value_widget)

            self.asset_row_widgets_by_id[asset_id] = [check_widget, name_widget, class_widget, value_widget]
            self.asset_row_items_by_id[asset_id] = [subtype_item, invested_item]

        self._sync_selection_to_table()
        self._set_hovered_row(-1)
        self._refresh_visible_row_highlights()

    def _sync_selection_to_table(self) -> None:
        self._syncing_selection = True
        self.asset_table.clearSelection()
        selection_model = self.asset_table.selectionModel()
        if selection_model is not None:
            for asset_id in self.selected_asset_ids:
                row_idx = self.asset_row_by_id.get(asset_id)
                if row_idx is None:
                    continue
                index = self.asset_table.model().index(row_idx, 0)
                selection_model.select(index, QItemSelectionModel.Select | QItemSelectionModel.Rows)
                checkbox = self.asset_checkbox_by_id.get(asset_id)
                if checkbox is not None and not checkbox.isChecked():
                    checkbox.setChecked(True)
        self._syncing_selection = False
        self._refresh_visible_row_highlights()

    def _on_asset_checkbox_toggled(self, asset_id: int, state: int) -> None:
        if self._syncing_selection:
            return
        if state == int(Qt.CheckState.Checked):
            self.selected_asset_ids.add(asset_id)
        else:
            self.selected_asset_ids.discard(asset_id)

        row_idx = self.asset_row_by_id.get(asset_id)
        selection_model = self.asset_table.selectionModel()
        if row_idx is not None and selection_model is not None:
            self._syncing_selection = True
            index = self.asset_table.model().index(row_idx, 0)
            if state == int(Qt.CheckState.Checked):
                selection_model.select(index, QItemSelectionModel.Select | QItemSelectionModel.Rows)
            else:
                selection_model.select(index, QItemSelectionModel.Deselect | QItemSelectionModel.Rows)
            self._syncing_selection = False

        self._apply_row_state_visual(asset_id)
        self._update_selection_bar()

    def _on_table_selection_changed(self) -> None:
        if self._syncing_selection:
            return

        selected_rows = {item.row() for item in self.asset_table.selectionModel().selectedRows()}
        page_asset_ids = {int(asset["id"]) for asset in self.paged_filtered_assets}
        new_selected_ids: set[int] = {asset_id for asset_id in self.selected_asset_ids if asset_id not in page_asset_ids}
        for row_idx in selected_rows:
            if 0 <= row_idx < len(self.paged_filtered_assets):
                new_selected_ids.add(int(self.paged_filtered_assets[row_idx]["id"]))
        self.selected_asset_ids = new_selected_ids

        self._syncing_selection = True
        for asset_id, checkbox in self.asset_checkbox_by_id.items():
            checkbox.setChecked(asset_id in self.selected_asset_ids)
        self._syncing_selection = False

        self._refresh_visible_row_highlights()
        self._update_selection_bar()

    def _update_selection_bar(self) -> None:
        selected_count = len(self.selected_asset_ids)
        if selected_count == 0:
            self.selection_bar.hide()
            return

        self.selection_bar.show()
        self.selection_count_label.setText(f"{selected_count} selected")
        self.change_class_button.setEnabled(True)
        self.delete_button.setEnabled(True)
        self.clear_selection_button.setVisible(True)

    def _clear_selected_assets(self) -> None:
        if not self.selected_asset_ids:
            return
        self.selected_asset_ids.clear()
        self._syncing_selection = True
        self.asset_table.clearSelection()
        for checkbox in self.asset_checkbox_by_id.values():
            checkbox.setChecked(False)
        self._syncing_selection = False
        self._refresh_visible_row_highlights()
        self._update_selection_bar()

    def _open_change_class_dialog(self) -> None:
        selected_ids = sorted(self.selected_asset_ids)
        if not selected_ids:
            return

        selected_class_keys = {
            asset["class_key"] for asset in self.all_assets if int(asset["id"]) in self.selected_asset_ids
        }
        initial_class_key = next(iter(selected_class_keys)) if len(selected_class_keys) == 1 else None

        dialog = QDialog(self)
        dialog.setObjectName("changeClassDialog")
        dialog.setWindowTitle("Change Asset Class")
        dialog.setModal(True)
        dialog.setMinimumWidth(520)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        title = QLabel("Change asset class")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        helper = QLabel(f"Move {len(selected_ids)} selected asset(s) to a new class.")
        helper.setObjectName("subTitle")
        layout.addWidget(helper)

        class_combo = QComboBox()
        class_combo.setObjectName("classPicker")
        model, selected_index = self._build_grouped_class_model(
            selected_class_key=initial_class_key,
            placeholder_text="Select asset class...",
        )
        class_combo.setModel(model)
        class_combo.setCurrentIndex(selected_index)
        layout.addWidget(class_combo)

        action_row = QHBoxLayout()
        action_row.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondaryButton")
        cancel_btn.clicked.connect(dialog.reject)
        action_row.addWidget(cancel_btn)

        apply_btn = QPushButton("Change Class")
        apply_btn.setObjectName("saveButton")
        action_row.addWidget(apply_btn)
        layout.addLayout(action_row)

        def apply_change() -> None:
            class_key = class_combo.currentData(Qt.UserRole)
            if not class_key:
                QMessageBox.warning(dialog, "Class required", "Please select an asset class.")
                return
            try:
                update_assets_class(selected_ids, class_key)
            except Exception:
                QMessageBox.critical(dialog, "Update failed", "Unable to update asset class.")
                return
            dialog.accept()

        apply_btn.clicked.connect(apply_change)

        if dialog.exec():
            self.selected_asset_ids.clear()
            self._refresh_assets_view()

    def _delete_selected_assets(self) -> None:
        selected_ids = sorted(self.selected_asset_ids)
        if not selected_ids:
            return

        noun = "asset" if len(selected_ids) == 1 else "assets"
        choice = QMessageBox.question(
            self,
            "Delete assets",
            f"Delete {len(selected_ids)} selected {noun}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if choice != QMessageBox.Yes:
            return

        try:
            delete_assets(selected_ids)
        except Exception:
            QMessageBox.critical(self, "Delete failed", "Unable to delete selected assets.")
            return

        self.selected_asset_ids.clear()
        self._refresh_assets_view()

    def _toggle_extra_details(self) -> None:
        if self.extra_details_box.isVisible():
            self.extra_details_box.hide()
            self.disclosure_button.setText("v Add details (sub-type, tags, notes)")
        else:
            self.extra_details_box.show()
            self.disclosure_button.setText("^ Add details (sub-type, tags, notes)")

    def _set_active_nav_item(self, item_name: str) -> None:
        for name, button in self.nav_buttons.items():
            is_active = name == item_name
            button.setProperty("active", is_active)
            button.style().unpolish(button)
            button.style().polish(button)

    def _on_sidebar_navigation(self, item_name: str) -> None:
        if item_name == "Assets":
            self._show_assets_page()
        elif item_name == "Liabilities":
            self._show_liabilities_page()
        elif item_name == "Net Worth":
            self._show_net_worth_page()
        elif item_name == "Essentials":
            settings = fetch_user_settings()
            has_data = False
            if settings:
                if (settings["age"] or settings["monthly_income"] or 
                    settings["monthly_expense"] or settings["monthly_savings"] or 
                    settings["display_name"] or settings["email"]):
                    has_data = True

            if has_data:
                self._show_settings_page()
            else:
                self._show_essentials_page()
        elif item_name == "Allocation":
            self._show_allocation_page()
        elif item_name == "Goals":
            self._show_goals_page()
        elif item_name == "Dashboard":
            self._show_dashboard_page()

    def _set_net_worth_mode(self, mode: str) -> None:
        if self.net_worth_view_mode == mode:
            return
        self.net_worth_view_mode = mode
        self._refresh_net_worth_mode_chips()
        self._refresh_net_worth_view()

    def _refresh_net_worth_mode_chips(self) -> None:
        if not hasattr(self, "net_worth_tab_button"):
            return

        mode_map = {
            "NET_WORTH": self.net_worth_tab_button,
            "ASSETS": self.net_worth_assets_tab_button,
            "LIABILITIES": self.net_worth_liabilities_tab_button,
        }
        for key, button in mode_map.items():
            button.setProperty("active", key == self.net_worth_view_mode)
            button.style().unpolish(button)
            button.style().polish(button)

    def _show_essentials_page(self) -> None:
        self._set_active_nav_item("Essentials")
        self.content_stack.setCurrentIndex(self.ESSENTIALS_PAGE_INDEX)

    def _show_settings_page(self) -> None:
        self._set_active_nav_item("Essentials")
        self.content_stack.setCurrentIndex(self.SETTINGS_PAGE_INDEX)
        
    def _show_allocation_page(self) -> None:
        self._set_active_nav_item("Allocation")
        self.content_stack.setCurrentIndex(self.ALLOCATION_PAGE_INDEX)

    def _show_goals_page(self) -> None:
        self._set_active_nav_item("Goals")
        self.content_stack.setCurrentIndex(self.GOALS_PAGE_INDEX)
        self._refresh_goals_view()

    def _snapshot_mode_title(self, mode: str) -> str:
        if mode == "ASSETS":
            return "Assets History"
        if mode == "LIABILITIES":
            return "Liabilities History"
        return "Net Worth History"

    def _snapshot_metric_value(self, snapshot: object, mode: str) -> float:
        if mode == "ASSETS":
            return float(snapshot["assets_total_inr"] or 0)
        if mode == "LIABILITIES":
            return float(snapshot["liabilities_total_inr"] or 0)
        return float(snapshot["net_worth_inr"] or 0)

    def _parse_snapshot_datetime(self, snapshot: object) -> datetime:
        created_at_text = str(snapshot["created_at"] or "").strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
            try:
                return datetime.strptime(created_at_text, fmt)
            except ValueError:
                continue
        return datetime.now()

    def _calculate_net_worth_totals(
        self,
        assets: list[object] | None = None,
        liabilities: list[object] | None = None,
    ) -> tuple[float, float, float]:
        if assets is None:
            assets = fetch_assets()
        if liabilities is None:
            liabilities = fetch_liabilities()
        assets_total_inr = self._sum_assets_value_inr(assets)
        liabilities_total_inr = sum(
            self._convert_to_inr(float(liability["outstanding_amount"] or 0), liability["currency"])
            for liability in liabilities
        )
        net_worth_inr = assets_total_inr - liabilities_total_inr
        return assets_total_inr, liabilities_total_inr, net_worth_inr

    def _refresh_timeline_chart(self, snapshots_desc: list[object]) -> None:
        chart = self.timeline_chart_view.chart()
        if chart is None:
            chart = QChart()
            chart.legend().hide()
            chart.setBackgroundVisible(False)
            chart.setPlotAreaBackgroundVisible(False)
            self.timeline_chart_view.setChart(chart)

        for series in list(chart.series()):
            chart.removeSeries(series)

        for axis in list(chart.axes()):
            chart.removeAxis(axis)

        chart.setTitle("")

        snapshots_asc = list(reversed(snapshots_desc))
        if not snapshots_asc:
            chart.setTitle("No snapshots yet")
            return

        line_series = QLineSeries()
        line_series.setUseOpenGL(False)

        x_values: list[float] = []
        y_values: list[float] = []
        for snapshot in snapshots_asc:
            dt = self._parse_snapshot_datetime(snapshot)
            x_val = float(QDateTime.fromSecsSinceEpoch(int(dt.timestamp())).toMSecsSinceEpoch())
            y_val = self._snapshot_metric_value(snapshot, self.net_worth_view_mode)
            x_values.append(x_val)
            y_values.append(y_val)
            line_series.append(x_val, y_val)
        line_pen = QPen(QColor("#2b7a52"))
        line_pen.setWidth(3)
        line_series.setPen(line_pen)
        line_series.setPointsVisible(True)
        line_series.setPointLabelsVisible(False)
        line_series.setColor(QColor("#2b7a52"))

        chart.addSeries(line_series)

        axis_x = QDateTimeAxis()
        axis_x.setFormat("dd MMM")
        axis_x.setTickCount(min(6, max(2, len(x_values))))

        min_x = min(x_values)
        max_x = max(x_values)
        if len(x_values) == 1 or min_x == max_x:
            axis_x.setRange(
                QDateTime.fromMSecsSinceEpoch(int(min_x - 86400000)),
                QDateTime.fromMSecsSinceEpoch(int(max_x + 86400000)),
            )
        else:
            axis_x.setRange(
                QDateTime.fromMSecsSinceEpoch(int(min_x)),
                QDateTime.fromMSecsSinceEpoch(int(max_x)),
            )
        axis_x.setLabelsColor(QColor("#5b5953"))
        chart.addAxis(axis_x, Qt.AlignBottom)
        line_series.attachAxis(axis_x)

        axis_y = QCategoryAxis()
        axis_y.setLabelsPosition(QCategoryAxis.AxisLabelsPositionOnValue)
        min_y = min(y_values)
        max_y_actual = max(y_values)
        
        if max_y_actual > 0:
            max_y = max_y_actual * 1.2
        elif max_y_actual < 0:
            max_y = max_y_actual * 0.8
        else:
            max_y = 1.0

        if min_y == max_y_actual:
            spread = max(abs(max_y_actual), 1.0)
            min_y -= spread * 0.25
            max_y = max_y_actual + spread * 0.25
        else:
            pad = (max_y - min_y) * 0.05
            min_y -= pad
            
        if min_y > 0:
            min_y = 0

        axis_y.setMin(min_y)
        axis_y.setMax(max_y)

        # Generate 5 evenly spaced ticks
        tick_count = 5
        seen_labels = {}
        for i in range(tick_count):
            val = min_y + (max_y - min_y) * (i / (tick_count - 1))
            label = format_compact_inr(val)
            # Ensure unique labels since QCategoryAxis behaves like a dictionary keys
            if label in seen_labels:
                seen_labels[label] += 1
                label = label + ("\u200b" * seen_labels[label])
            else:
                seen_labels[label] = 0
            axis_y.append(label, val)

        axis_y.setLabelsColor(QColor("#5b5953"))
        chart.addAxis(axis_y, Qt.AlignLeft)
        line_series.attachAxis(axis_y)

        # Setup mouse tracking overlay
        self.timeline_chart_view.viewport().setMouseTracking(True)
        self.timeline_chart_view.viewport().removeEventFilter(self.chart_hover_filter)
        self.timeline_chart_view.viewport().installEventFilter(self.chart_hover_filter)

        # Setup custom tooltip as overlay widget
        if self.chart_tooltip is None:
            self.chart_tooltip = TooltipFrame(self.timeline_chart_view)
            self.chart_tooltip.hide()

        # Add vertical line
        if self.chart_v_line is None:
            self.chart_v_line = QGraphicsLineItem(chart.plotArea().topLeft().x(), chart.plotArea().top(), chart.plotArea().topLeft().x(), chart.plotArea().bottom())
            line_pen = QPen(QColor("#a9a8a5"))
            line_pen.setWidth(1)
            line_pen.setStyle(Qt.DashLine)
            self.chart_v_line.setPen(line_pen)
            self.chart_v_line.setZValue(999)
            scene = self.timeline_chart_view.scene()
            if scene:
                scene.addItem(self.chart_v_line)
        self.chart_v_line.hide()

        # Add single scatter point for highlighting on hover
        from PySide6.QtCharts import QScatterSeries
        self.hover_point_series = QScatterSeries()
        self.hover_point_series.setMarkerShape(QScatterSeries.MarkerShapeCircle)
        self.hover_point_series.setMarkerSize(12)
        hover_pen = QPen(QColor("#2b7a52"))
        hover_pen.setWidth(3)
        self.hover_point_series.setPen(hover_pen)
        self.hover_point_series.setBrush(QColor("white"))
        self.hover_point_series.setUseOpenGL(False)
        chart.addSeries(self.hover_point_series)
        self.hover_point_series.attachAxis(axis_x)
        self.hover_point_series.attachAxis(axis_y)


    def _handle_chart_mouse_move(self, pos: QPoint) -> None:
        if not hasattr(self, "chart_tooltip") or self.chart_tooltip is None: return
        chart = self.timeline_chart_view.chart()
        if not chart: return
            
        scene_pos = self.timeline_chart_view.mapToScene(pos)
        chart_val = chart.mapToValue(scene_pos)
        x_target = chart_val.x()
        
        snapshots_asc = list(reversed(self.net_worth_snapshots))
        if not snapshots_asc: return

        # Find closest snapshot
        closest_idx = 0
        min_dist = float('inf')
        for i, snapshot in enumerate(snapshots_asc):
            dt = self._parse_snapshot_datetime(snapshot)
            x_val = float(QDateTime.fromSecsSinceEpoch(int(dt.timestamp())).toMSecsSinceEpoch())
            dist = abs(x_val - x_target)
            if dist < min_dist:
                min_dist = dist
                closest_idx = i

        snapshot = snapshots_asc[closest_idx]
        dt = self._parse_snapshot_datetime(snapshot)
        x_val = float(QDateTime.fromSecsSinceEpoch(int(dt.timestamp())).toMSecsSinceEpoch())
        y_val = self._snapshot_metric_value(snapshot, self.net_worth_view_mode)
        
        closest_point = chart.mapToPosition(QPointF(x_val, y_val))
        
        # Only snap if the mouse is close in screen X
        dist_screen = abs(scene_pos.x() - closest_point.x())
        if dist_screen > 80:
            self._hide_chart_tooltip()
            return
            
        # Update hover dot
        self.hover_point_series.clear()
        self.hover_point_series.append(x_val, y_val)
        
        # Update vertical line
        plot_area = chart.plotArea()
        self.chart_v_line.setLine(closest_point.x(), plot_area.top(), closest_point.x(), plot_area.bottom())
        if self.chart_v_line.scene() != self.timeline_chart_view.scene():
             if self.chart_v_line.scene():
                 self.chart_v_line.scene().removeItem(self.chart_v_line)
             self.timeline_chart_view.scene().addItem(self.chart_v_line)
        self.chart_v_line.show()
        
        # Update tooltip content
        self.chart_tooltip.value_label.setText(format_currency(y_val, "INR"))
        self.chart_tooltip.date_label.setText(dt.strftime("%d %b %Y"))
        
        if closest_idx > 0:
            prev_snapshot = snapshots_asc[closest_idx - 1]
            prev_value = self._snapshot_metric_value(prev_snapshot, self.net_worth_view_mode)
            delta = y_val - prev_value
            pct = (delta / prev_value * 100) if abs(prev_value) > 0.0001 else 0.0
            
            if delta > 0:
                self.chart_tooltip.change_label.setText(f"▲ {format_signed_compact_inr(delta)} (+{abs(pct):.1f}%)")
                self.chart_tooltip.change_label.setObjectName("tooltipChangePositive")
            elif delta < 0:
                self.chart_tooltip.change_label.setText(f"▼ {format_signed_compact_inr(delta)} (-{abs(pct):.1f}%)")
                self.chart_tooltip.change_label.setObjectName("tooltipChangeNegative")
            else:
                self.chart_tooltip.change_label.setText(f"▲ ₹0 (+0.0%)")
                self.chart_tooltip.change_label.setObjectName("tooltipChangePositive")
        else:
            self.chart_tooltip.change_label.setText("baseline")
            self.chart_tooltip.change_label.setObjectName("tooltipChangeNeutral")
            
        self.chart_tooltip.change_label.style().unpolish(self.chart_tooltip.change_label)
        self.chart_tooltip.change_label.style().polish(self.chart_tooltip.change_label)

        # Position tooltip
        self.chart_tooltip.adjustSize()
        rect = self.chart_tooltip.geometry()
        
        # Map scene coordinates of closest point back to viewport coordinates
        view_pos = self.timeline_chart_view.mapFromScene(closest_point)
        
        # safely handle different Point types
        vx = view_pos.x()
        vy = view_pos.y()
        tooltip_x = vx + 15
        tooltip_y = vy - rect.height() - 15
        
        if tooltip_x + rect.width() > self.timeline_chart_view.viewport().width():
            tooltip_x = view_pos.x() - rect.width() - 15
            
        if tooltip_y < 0:
            tooltip_y = 10
            
        self.chart_tooltip.move(tooltip_x, tooltip_y)
        self.chart_tooltip.show()

    def _hide_chart_tooltip(self):
        if hasattr(self, "chart_tooltip") and self.chart_tooltip:
            self.chart_tooltip.hide()
        if hasattr(self, "chart_v_line") and self.chart_v_line:
            self.chart_v_line.hide()
        if hasattr(self, "hover_point_series") and self.hover_point_series:
            self.hover_point_series.clear()


    def _set_metric_card_value(self, value_label: QLabel, meta_label: QLabel, value: float, meta_text: str) -> None:
        value_label.setText(format_signed_compact_inr(value))
        value_label.setObjectName("metricCardValueNegative" if value < 0 else "metricCardValuePositive")
        value_label.style().unpolish(value_label)
        value_label.style().polish(value_label)
        meta_label.setText(meta_text)

    def _refresh_top_metrics(self, snapshots_desc: list[object]) -> None:
        if not snapshots_desc:
            self._set_metric_card_value(
                self.net_worth_growth_value_label, self.net_worth_growth_meta_label, 0.0, "No snapshots yet"
            )
            self._set_metric_card_value(
                self.net_worth_avg_value_label, self.net_worth_avg_meta_label, 0.0, "No snapshots yet"
            )
            self._set_metric_card_value(
                self.net_worth_best_month_value_label, self.net_worth_best_month_meta_label, 0.0, "No snapshots yet"
            )
            return

        latest_value = self._snapshot_metric_value(snapshots_desc[0], self.net_worth_view_mode)
        if len(snapshots_desc) >= 2:
            previous_value = self._snapshot_metric_value(snapshots_desc[1], self.net_worth_view_mode)
            growth_value = latest_value - previous_value
            growth_pct = (growth_value / previous_value * 100) if abs(previous_value) > 0.0001 else 0.0
            growth_meta = f"{format_percent(growth_pct)} vs previous snapshot"
        else:
            growth_value = 0.0
            growth_meta = "Need at least 2 snapshots"
        self._set_metric_card_value(
            self.net_worth_growth_value_label,
            self.net_worth_growth_meta_label,
            growth_value,
            growth_meta,
        )

        oldest_value = self._snapshot_metric_value(snapshots_desc[-1], self.net_worth_view_mode)
        snapshot_count = len(snapshots_desc)
        avg_per_snapshot = (latest_value - oldest_value) / (snapshot_count - 1) if snapshot_count > 1 else 0.0
        self._set_metric_card_value(
            self.net_worth_avg_value_label,
            self.net_worth_avg_meta_label,
            avg_per_snapshot,
            f"{snapshot_count} snapshots total",
        )

        snapshots_asc = list(reversed(snapshots_desc))
        if len(snapshots_asc) <= 1:
            self._set_metric_card_value(
                self.net_worth_best_month_value_label,
                self.net_worth_best_month_meta_label,
                0.0,
                self._parse_snapshot_datetime(snapshots_asc[0]).strftime("%b %Y"),
            )
            return

        deltas: list[tuple[float, object]] = []
        for idx in range(1, len(snapshots_asc)):
            previous = snapshots_asc[idx - 1]
            current = snapshots_asc[idx]
            delta = self._snapshot_metric_value(current, self.net_worth_view_mode) - self._snapshot_metric_value(
                previous, self.net_worth_view_mode
            )
            deltas.append((delta, current))

        if self.net_worth_view_mode == "LIABILITIES":
            best_delta, best_snapshot = min(deltas, key=lambda row: row[0])
        else:
            best_delta, best_snapshot = max(deltas, key=lambda row: row[0])

        self._set_metric_card_value(
            self.net_worth_best_month_value_label,
            self.net_worth_best_month_meta_label,
            best_delta,
            self._parse_snapshot_datetime(best_snapshot).strftime("%b %Y"),
        )

    def _populate_snapshot_history_table(self, snapshots_desc: list[object]) -> None:
        if not hasattr(self, "snapshot_entries_layout"):
            return

        # Instead of deleting all widgets, we will hide excess ones and reuse existing ones.
        # This prevents macOS from losing window focus when switching tabs in full screen.
        layout = self.snapshot_entries_layout
        
        # Remove the stretching spacer at the end before we add/update widgets
        for i in range(layout.count() - 1, -1, -1):
            item = layout.itemAt(i)
            if item.spacerItem():
                layout.removeItem(item)

        if not snapshots_desc:
            # Hide all existing cards
            for i in range(layout.count()):
                widget = layout.itemAt(i).widget()
                if widget:
                    widget.hide()
            
            # Show or add empty text
            empty_text_found = False
            for i in range(layout.count()):
                widget = layout.itemAt(i).widget()
                if isinstance(widget, QLabel) and widget.objectName() == "subTitle":
                    widget.show()
                    empty_text_found = True
                    break
            
            if not empty_text_found:
                empty_text = QLabel("No snapshots yet. Take your first snapshot to start history.")
                empty_text.setObjectName("subTitle")
                layout.addWidget(empty_text)
                
            layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding))
            return

        valid_ids = {int(snapshot["id"]) for snapshot in snapshots_desc}
        self.expanded_snapshot_ids = {snapshot_id for snapshot_id in self.expanded_snapshot_ids if snapshot_id in valid_ids}

        # Find all existing cards
        existing_cards = []
        for i in range(layout.count()):
            widget = layout.itemAt(i).widget()
            if isinstance(widget, QFrame) and widget.objectName() == "snapshotEntryCard":
                existing_cards.append(widget)
            elif isinstance(widget, QLabel) and widget.objectName() == "subTitle":
                widget.hide()

        for row_idx, snapshot in enumerate(snapshots_desc):
            snapshot_id = int(snapshot["id"])
            value = self._snapshot_metric_value(snapshot, self.net_worth_view_mode)
            snapshot_dt = self._parse_snapshot_datetime(snapshot)
            label_text = str(snapshot["label"] or "").strip() or "Snapshot"

            has_previous = row_idx < len(snapshots_desc) - 1
            delta = 0.0
            pct = 0.0
            if has_previous:
                previous_snapshot = snapshots_desc[row_idx + 1]
                previous_value = self._snapshot_metric_value(previous_snapshot, self.net_worth_view_mode)
                delta = value - previous_value
                pct = (delta / previous_value * 100) if abs(previous_value) > 0.0001 else 0.0

            if row_idx < len(existing_cards):
                card = existing_cards[row_idx]
                card.show()
                # Clear the card's old contents and recreate to ensure correct data
                # Recreating inner contents is lighter and less likely to drop top-level window focus
                # than deleting the main cards themselves.
                QTimer.singleShot(0, lambda c=card, s_id=snapshot_id, val=value, dt=snapshot_dt, lbl=label_text, hp=has_previous, d=delta, p=pct, r=row_idx, sd=snapshots_desc: self._rebuild_card_contents(c, s_id, val, dt, lbl, hp, d, p, r, sd))
            else:
                card = QFrame()
                card.setObjectName("snapshotEntryCard")
                card_layout = QVBoxLayout(card)
                card_layout.setContentsMargins(0, 0, 0, 0)
                card_layout.setSpacing(0)
                layout.addWidget(card)
                self._rebuild_card_contents(card, snapshot_id, value, snapshot_dt, label_text, has_previous, delta, pct, row_idx, snapshots_desc)

        # Hide excess cards
        for i in range(len(snapshots_desc), len(existing_cards)):
            existing_cards[i].hide()

        layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding))

    def _rebuild_card_contents(self, card: QFrame, snapshot_id: int, value: float, snapshot_dt: datetime, label_text: str, has_previous: bool, delta: float, pct: float, row_idx: int, snapshots_desc: list[object]) -> None:
        if getattr(card, "snapshot_id", None) == snapshot_id:
            card.value_label.setText(format_currency(value, "INR"))
            is_expanded = snapshot_id in self.expanded_snapshot_ids
            card.toggle_button.setArrowType(Qt.DownArrow if is_expanded else Qt.RightArrow)
            card.details.setVisible(is_expanded)
            
            if has_previous:
                direction = "up" if delta >= 0 else "down"
                card.summary_label.setText(f"{format_signed_compact_inr(delta)}, {abs(pct):.1f}% {direction}")
                card.summary_label.setObjectName("snapshotEntryChangePositive" if delta >= 0 else "snapshotEntryChangeNegative")
            else:
                card.summary_label.setText("baseline")
                card.summary_label.setObjectName("snapshotEntryBaseline")
            card.summary_label.style().unpolish(card.summary_label)
            card.summary_label.style().polish(card.summary_label)

            if has_previous:
                previous_snapshot = snapshots_desc[row_idx + 1]
                snapshot = snapshots_desc[row_idx]
                current_assets = float(snapshot["assets_total_inr"] or 0)
                previous_assets = float(previous_snapshot["assets_total_inr"] or 0)
                current_liabilities = float(snapshot["liabilities_total_inr"] or 0)
                previous_liabilities = float(previous_snapshot["liabilities_total_inr"] or 0)
                card.details_summary.setText(
                    "What changed: Net worth "
                    f"{format_signed_compact_inr(delta)} "
                    f"(Assets {format_signed_compact_inr(current_assets - previous_assets)}, "
                    f"Liabilities {format_signed_compact_inr(current_liabilities - previous_liabilities)})"
                )
            else:
                card.details_summary.setText("What changed: baseline snapshot")
            return

        card.snapshot_id = snapshot_id
        
        card_layout = card.layout()
        if card_layout is None:
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(0, 0, 0, 0)
            card_layout.setSpacing(0)
            
        # Clear out old card contents (only happens when shifting actual snapshot data)
        while card_layout.count():
            item = card_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        header = QFrame()
        header.setObjectName("snapshotEntryHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 10, 12, 10)
        header_layout.setSpacing(10)

        toggle_button = QToolButton()
        toggle_button.setObjectName("snapshotToggle")
        toggle_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        toggle_button.setArrowType(Qt.DownArrow if snapshot_id in self.expanded_snapshot_ids else Qt.RightArrow)
        toggle_button.setCursor(Qt.PointingHandCursor)
        toggle_button.clicked.connect(
            lambda _checked=False, selected_snapshot_id=snapshot_id: self._toggle_snapshot_entry(selected_snapshot_id)
        )
        header_layout.addWidget(toggle_button)
        card.toggle_button = toggle_button

        date_label = QLabel(snapshot_dt.strftime("%d %b %Y"))
        date_label.setObjectName("snapshotEntryDate")
        header_layout.addWidget(date_label)

        label_label = QLabel(label_text)
        label_label.setObjectName("snapshotEntryLabel")
        header_layout.addWidget(label_label)

        header_layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        value_label = QLabel(format_currency(value, "INR"))
        value_label.setObjectName("snapshotEntryValue")
        header_layout.addWidget(value_label)
        card.value_label = value_label

        if has_previous:
            direction = "up" if delta >= 0 else "down"
            summary_label = QLabel(f"{format_signed_compact_inr(delta)}, {abs(pct):.1f}% {direction}")
            summary_label.setObjectName("snapshotEntryChangePositive" if delta >= 0 else "snapshotEntryChangeNegative")
        else:
            summary_label = QLabel("baseline")
            summary_label.setObjectName("snapshotEntryBaseline")
        header_layout.addWidget(summary_label)
        card.summary_label = summary_label

        delete_button = QToolButton()
        delete_button.setIcon(self.row_action_icons.get("delete", QIcon()))
        delete_button.setToolTip(f"Delete '{label_text}'")
        delete_button.setCursor(Qt.PointingHandCursor)
        delete_button.setObjectName("rowActionBtn")
        delete_button.clicked.connect(lambda _checked=False, s_id=snapshot_id, name=label_text: self._delete_snapshot(s_id, name))
        header_layout.addWidget(delete_button)
        card.delete_button = delete_button

        card_layout.addWidget(header)

        details = QFrame()
        details.setObjectName("snapshotEntryDetails")
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(12, 10, 12, 12)
        details_layout.setSpacing(8)

        if has_previous:
            previous_snapshot = snapshots_desc[row_idx + 1]
            snapshot = snapshots_desc[row_idx]
            current_assets = float(snapshot["assets_total_inr"] or 0)
            previous_assets = float(previous_snapshot["assets_total_inr"] or 0)
            current_liabilities = float(snapshot["liabilities_total_inr"] or 0)
            previous_liabilities = float(previous_snapshot["liabilities_total_inr"] or 0)
            summary = QLabel(
                "What changed: Net worth "
                f"{format_signed_compact_inr(delta)} "
                f"(Assets {format_signed_compact_inr(current_assets - previous_assets)}, "
                f"Liabilities {format_signed_compact_inr(current_liabilities - previous_liabilities)})"
            )
        else:
            summary = QLabel("What changed: baseline snapshot")
        summary.setObjectName("snapshotChangesText")
        summary.setWordWrap(True)
        details_layout.addWidget(summary)
        card.details_summary = summary


        asset_items = self._get_snapshot_asset_items(snapshot_id)
        assets_title = QLabel(f"ASSETS ({len(asset_items)})")
        assets_title.setObjectName("snapshotSectionTitle")
        details_layout.addWidget(assets_title)

        assets_table = self._create_snapshot_line_table(["Name", "Class", "Original", "In ₹ INR"])
        assets_table.setRowCount(len(asset_items))
        for asset_row, item in enumerate(asset_items):
            assets_table.setItem(asset_row, 0, QTableWidgetItem(item["asset_name"]))
            assets_table.setItem(asset_row, 1, QTableWidgetItem(item["asset_class"]))
            original_item = QTableWidgetItem(
                format_currency(float(item["original_value"] or 0), normalize_currency(item["currency"]))
            )
            original_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            assets_table.setItem(asset_row, 2, original_item)
            inr_item = QTableWidgetItem(format_currency(float(item["value_inr"] or 0), "INR"))
            inr_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            assets_table.setItem(asset_row, 3, inr_item)
            assets_table.setRowHeight(asset_row, 28)
        self._fit_snapshot_table_height(assets_table)
        details_layout.addWidget(assets_table)

        liability_items = self._get_snapshot_liability_items(snapshot_id)
        liabilities_title = QLabel(f"LIABILITIES ({len(liability_items)})")
        liabilities_title.setObjectName("snapshotSectionTitle")
        details_layout.addWidget(liabilities_title)

        liabilities_table = self._create_snapshot_line_table(["Name", "Type", "Original", "In ₹ INR"])
        liabilities_table.setRowCount(len(liability_items))
        for liability_row, item in enumerate(liability_items):
            liabilities_table.setItem(liability_row, 0, QTableWidgetItem(item["liability_name"]))
            liabilities_table.setItem(liability_row, 1, QTableWidgetItem(item["liability_type"]))
            original_item = QTableWidgetItem(
                format_currency(
                    float(item["original_outstanding"] or 0),
                    normalize_currency(item["currency"]),
                )
            )
            original_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            liabilities_table.setItem(liability_row, 2, original_item)
            inr_item = QTableWidgetItem(format_currency(float(item["outstanding_inr"] or 0), "INR"))
            inr_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            inr_item.setForeground(QColor("#c23b31"))
            liabilities_table.setItem(liability_row, 3, inr_item)
            liabilities_table.setRowHeight(liability_row, 28)
        self._fit_snapshot_table_height(liabilities_table)
        details_layout.addWidget(liabilities_table)

        details.setVisible(snapshot_id in self.expanded_snapshot_ids)
        card_layout.addWidget(details)
        card.details = details

    def _get_snapshot_asset_items(self, snapshot_id: int) -> list[object]:
        if snapshot_id not in self.snapshot_assets_cache:
            self.snapshot_assets_cache[snapshot_id] = fetch_snapshot_asset_items(snapshot_id)
        return self.snapshot_assets_cache[snapshot_id]

    def _get_snapshot_liability_items(self, snapshot_id: int) -> list[object]:
        if snapshot_id not in self.snapshot_liabilities_cache:
            self.snapshot_liabilities_cache[snapshot_id] = fetch_snapshot_liability_items(snapshot_id)
        return self.snapshot_liabilities_cache[snapshot_id]

    def _summarize_snapshot_item_changes(
        self,
        current_items: list[object],
        previous_items: list[object],
        name_key: str,
        value_key: str,
    ) -> tuple[list[str], list[str], list[tuple[str, float]]]:
        current_map = {str(item[name_key]): float(item[value_key] or 0) for item in current_items}
        previous_map = {str(item[name_key]): float(item[value_key] or 0) for item in previous_items}

        added = sorted([name for name in current_map if name not in previous_map])
        removed = sorted([name for name in previous_map if name not in current_map])
        changed: list[tuple[str, float]] = []
        for name in sorted(current_map):
            if name not in previous_map:
                continue
            delta = current_map[name] - previous_map[name]
            if abs(delta) > 0.5:
                changed.append((name, delta))
        return added, removed, changed

    def _build_change_line(self, title: str, added: list[str], removed: list[str], changed: list[tuple[str, float]]) -> str:
        parts: list[str] = [f"{title}:"]
        if added:
            preview = ", ".join(added[:4])
            parts.append(f"added {len(added)} ({preview}{'...' if len(added) > 4 else ''})")
        if removed:
            preview = ", ".join(removed[:4])
            parts.append(f"removed {len(removed)} ({preview}{'...' if len(removed) > 4 else ''})")
        if changed:
            preview = ", ".join(
                f"{name} {format_signed_compact_inr(delta)}" for name, delta in changed[:4]
            )
            parts.append(f"changed {len(changed)} ({preview}{'...' if len(changed) > 4 else ''})")
        if len(parts) == 1:
            parts.append("no line item changes")
        return " ".join(parts)

    def _toggle_snapshot_entry(self, snapshot_id: int) -> None:
        if snapshot_id in self.expanded_snapshot_ids:
            self.expanded_snapshot_ids.remove(snapshot_id)
        else:
            self.expanded_snapshot_ids = {snapshot_id}
        self._populate_snapshot_history_table(self.net_worth_snapshots)

    def _delete_snapshot(self, snapshot_id: int, snapshot_name: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        choice = QMessageBox.question(
            self,
            "Delete snapshot",
            f"Are you sure you want to delete '{snapshot_name}'? This action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if choice != QMessageBox.Yes:
            return

        try:
            delete_snapshot(snapshot_id)
        except Exception as e:
            QMessageBox.critical(self, "Delete failed", f"Unable to delete this snapshot:\n{e}")
            return

        if snapshot_id in self.expanded_snapshot_ids:
            self.expanded_snapshot_ids.remove(snapshot_id)
            
        self._refresh_net_worth_view()

    def _refresh_net_worth_view(self) -> None:
        if not hasattr(self, "net_worth_snapshot_count_label"):
            return

        self.net_worth_snapshots = fetch_net_worth_snapshots()
        self.timeline_chart_title.setText(self._snapshot_mode_title(self.net_worth_view_mode))
        self._refresh_timeline_chart(self.net_worth_snapshots)
        self._refresh_top_metrics(self.net_worth_snapshots)
        self._populate_snapshot_history_table(self.net_worth_snapshots)

        snapshot_count = len(self.net_worth_snapshots)
        if snapshot_count <= 0:
            self.net_worth_snapshot_count_label.setText("0 snapshots")
            self.take_first_snapshot_button.show()
            return

        oldest_snapshot = self.net_worth_snapshots[-1]
        oldest_dt = self._parse_snapshot_datetime(oldest_snapshot)
        self.net_worth_snapshot_count_label.setText(
            f"{snapshot_count} snapshots · Tracking since {oldest_dt.strftime('%b %Y')}"
        )
        self.take_first_snapshot_button.hide()

    def _show_toast(self, message: str, duration_ms: int = 2200) -> None:
        if self.toast_widget is not None:
            self.toast_widget.deleteLater()
            self.toast_widget = None

        toast = QFrame(self)
        toast.setObjectName("toastMessage")
        toast_layout = QHBoxLayout(toast)
        toast_layout.setContentsMargins(12, 8, 12, 8)
        toast_label = QLabel(message)
        toast_label.setObjectName("toastLabel")
        toast_layout.addWidget(toast_label)
        toast.adjustSize()

        margin = 24
        toast_x = max(margin, self.width() - toast.width() - margin)
        toast_y = max(margin, self.height() - toast.height() - margin)
        toast.move(QPoint(toast_x, toast_y))
        toast.show()
        toast.raise_()
        self.toast_widget = toast

        def clear_toast() -> None:
            if self.toast_widget is toast:
                self.toast_widget = None
            toast.deleteLater()

        QTimer.singleShot(duration_ms, clear_toast)

    def _open_take_snapshot_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setObjectName("snapshotDialog")
        dialog.setWindowTitle("Take Snapshot")
        dialog.setModal(True)
        dialog.setMinimumWidth(500)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        title = QLabel("Take Snapshot")
        title.setObjectName("sectionTitle")
        header_row.addWidget(title)
        header_row.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        close_button = QPushButton("×")
        close_button.setObjectName("dialogCloseButton")
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.clicked.connect(dialog.reject)
        header_row.addWidget(close_button)
        layout.addLayout(header_row)

        label_field = QLabel("Label (optional)")
        label_field.setObjectName("fieldLabel")
        layout.addWidget(label_field)

        label_input = QLineEdit()
        label_input.setObjectName("formInput")
        label_input.setPlaceholderText("e.g. Regular March audit, Job change, Big bonus")
        layout.addWidget(label_input)

        helper_text = QLabel("A label helps you remember what was happening at this point in time.")
        helper_text.setObjectName("helperLabel")
        helper_text.setWordWrap(True)
        layout.addWidget(helper_text)

        status_label = QLabel("")
        status_label.setObjectName("statusError")
        status_label.hide()
        layout.addWidget(status_label)

        actions = QHBoxLayout()
        actions.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondaryButton")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.clicked.connect(dialog.reject)
        actions.addWidget(cancel_btn)

        save_btn = QPushButton("Take Snapshot")
        save_btn.setObjectName("saveButton")
        save_btn.setCursor(Qt.PointingHandCursor)
        actions.addWidget(save_btn)
        layout.addLayout(actions)

        def on_save_clicked() -> None:
            status_label.hide()
            label = label_input.text().strip()
            if len(label) > 120:
                status_label.setText("Label must be 120 characters or fewer.")
                status_label.show()
                status_label.style().unpolish(status_label)
                status_label.style().polish(status_label)
                return

            if not self._take_net_worth_snapshot(label):
                status_label.setText("Unable to capture net worth snapshot. Please try again.")
                status_label.show()
                status_label.style().unpolish(status_label)
                status_label.style().polish(status_label)
                return
            self._show_toast("Snapshot saved")
            dialog.accept()

        save_btn.clicked.connect(on_save_clicked)
        label_input.setFocus()
        dialog.exec()

    def _take_net_worth_snapshot(self, label: str = "") -> bool:
        assets = fetch_assets()
        liabilities = fetch_liabilities()
        assets_total_inr, liabilities_total_inr, net_worth_inr = self._calculate_net_worth_totals(assets, liabilities)

        snapshot_asset_items = [
            (
                str(asset["name"] or ""),
                str(asset["asset_class"] or ""),
                normalize_currency(asset["currency"]),
                float(asset["value"] or 0),
                self._convert_to_inr(float(asset["value"] or 0), asset["currency"]),
            )
            for asset in assets
        ]
        snapshot_liability_items = [
            (
                str(liability["name"] or ""),
                str(liability["liability_type"] or ""),
                normalize_currency(liability["currency"]),
                float(liability["outstanding_amount"] or 0),
                self._convert_to_inr(float(liability["outstanding_amount"] or 0), liability["currency"]),
            )
            for liability in liabilities
        ]

        try:
            add_net_worth_snapshot(
                label=label,
                net_worth_inr=net_worth_inr,
                assets_total_inr=assets_total_inr,
                liabilities_total_inr=liabilities_total_inr,
                snapshot_asset_items=snapshot_asset_items,
                snapshot_liability_items=snapshot_liability_items,
            )
        except Exception:
            return False

        self.snapshot_assets_cache.clear()
        self.snapshot_liabilities_cache.clear()
        self._refresh_net_worth_view()
        return True

    def _refresh_liabilities_view(self) -> None:
        self.all_liabilities = fetch_liabilities()
        if not hasattr(self, "liabilities_empty_card"):
            return

        if not self.all_liabilities:
            self.liabilities_empty_card.show()
            self.liabilities_table_card.hide()
            return

        self.liabilities_empty_card.hide()
        self.liabilities_table_card.show()
        self._populate_liabilities_table()

    def _populate_liabilities_table(self) -> None:
        liabilities = self.all_liabilities
        self.liabilities_table.setRowCount(len(liabilities))

        total_outstanding_inr = 0.0
        for row_idx, liability in enumerate(liabilities):
            self.liabilities_table.setRowHeight(row_idx, 58)

            currency = normalize_currency(liability["currency"])
            outstanding = float(liability["outstanding_amount"] or 0)
            emi = float(liability["monthly_emi"] or 0)
            interest = float(liability["interest_rate"] or 0)
            total_outstanding_inr += self._convert_to_inr(outstanding, currency)

            name_item = QTableWidgetItem(liability["name"] or "-")
            name_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.liabilities_table.setItem(row_idx, 0, name_item)

            type_widget = QWidget()
            type_layout = QHBoxLayout(type_widget)
            type_layout.setContentsMargins(0, 0, 0, 0)
            type_layout.setSpacing(0)
            type_badge = QLabel(liability["liability_type"] or "-")
            type_badge.setObjectName("liabilityTypeBadge")
            type_layout.addWidget(type_badge, alignment=Qt.AlignLeft | Qt.AlignVCenter)
            type_layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
            self.liabilities_table.setCellWidget(row_idx, 1, type_widget)

            outstanding_item = QTableWidgetItem(format_liability_currency(outstanding, currency))
            outstanding_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            outstanding_item.setForeground(QColor("#cc4b38"))
            outstanding_font = outstanding_item.font()
            outstanding_font.setBold(True)
            outstanding_item.setFont(outstanding_font)
            self.liabilities_table.setItem(row_idx, 2, outstanding_item)

            interest_item = QTableWidgetItem(f"{interest:.1f}%" if interest > 0 else "-")
            interest_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.liabilities_table.setItem(row_idx, 3, interest_item)

            emi_item = QTableWidgetItem(format_liability_currency(emi, currency) if emi > 0 else "-")
            emi_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.liabilities_table.setItem(row_idx, 4, emi_item)

            liability_id = int(liability["id"])
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(4, 0, 4, 0)
            action_layout.setSpacing(6)

            edit_button = QToolButton()
            edit_button.setObjectName("rowActionButton")
            edit_button.setCursor(Qt.PointingHandCursor)
            edit_button.setIcon(self._get_row_action_icon("edit"))
            edit_button.setIconSize(QSize(14, 14))
            edit_button.setToolTip("Edit Liability")
            edit_button.clicked.connect(
                lambda _checked=False, selected_liability_id=liability_id: self._edit_liability(selected_liability_id)
            )
            action_layout.addWidget(edit_button)

            delete_button = QToolButton()
            delete_button.setObjectName("rowDeleteActionButton")
            delete_button.setCursor(Qt.PointingHandCursor)
            delete_button.setIcon(self._get_row_action_icon("delete"))
            delete_button.setIconSize(QSize(14, 14))
            delete_button.setToolTip("Delete Liability")
            delete_button.clicked.connect(
                lambda _checked=False, selected_liability_id=liability_id: self._delete_liability(selected_liability_id)
            )
            action_layout.addWidget(delete_button)
            action_layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
            self.liabilities_table.setCellWidget(row_idx, 5, action_widget)

        self.liabilities_total_value_label.setText(format_liability_currency(total_outstanding_inr, "INR"))
        total_count = len(liabilities)
        self.liabilities_footer_text.setText(f"{total_count}/{total_count} liabilities")

    def _find_liability_by_id(self, liability_id: int) -> object | None:
        for liability in self.all_liabilities:
            if int(liability["id"]) == liability_id:
                return liability
        return None

    def _edit_liability(self, liability_id: int) -> None:
        liability = self._find_liability_by_id(liability_id)
        if liability is None:
            self._refresh_liabilities_view()
            return
        self._open_add_liability_dialog(liability)

    def _delete_liability(self, liability_id: int) -> None:
        liability = self._find_liability_by_id(liability_id)
        if liability is None:
            self._refresh_liabilities_view()
            return

        choice = QMessageBox.question(
            self,
            "Delete liability",
            f"Delete '{liability['name']}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if choice != QMessageBox.Yes:
            return

        try:
            delete_liability(liability_id)
        except Exception:
            QMessageBox.critical(self, "Delete failed", "Unable to delete this liability.")
            return

        self._refresh_liabilities_view()

    def _open_add_liability_dialog(self, liability: object | None = None) -> None:
        is_edit_mode = liability is not None
        liability_id = int(liability["id"]) if is_edit_mode else None

        dialog = QDialog(self)
        dialog.setObjectName("liabilityDialog")
        dialog.setWindowTitle("Edit Liability" if is_edit_mode else "Add Liability")
        dialog.setModal(True)
        dialog.setMinimumWidth(620)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        header_row = QHBoxLayout()
        header_title = QLabel("Edit Liability" if is_edit_mode else "Add Liability")
        header_title.setObjectName("sectionTitle")
        header_row.addWidget(header_title)
        header_row.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        close_button = QPushButton("×")
        close_button.setObjectName("dialogCloseButton")
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.clicked.connect(dialog.reject)
        header_row.addWidget(close_button)
        layout.addLayout(header_row)

        form_grid = QGridLayout()
        form_grid.setHorizontalSpacing(14)
        form_grid.setVerticalSpacing(8)

        name_label = QLabel("Name *")
        name_label.setObjectName("fieldLabel")
        form_grid.addWidget(name_label, 0, 0, 1, 2)

        name_input = QLineEdit()
        name_input.setObjectName("formInput")
        name_input.setPlaceholderText("Home Loan - SBI")
        form_grid.addWidget(name_input, 1, 0, 1, 2)

        type_label = QLabel("Type *")
        type_label.setObjectName("fieldLabel")
        form_grid.addWidget(type_label, 2, 0)

        currency_label = QLabel("Currency")
        currency_label.setObjectName("fieldLabel")
        form_grid.addWidget(currency_label, 2, 1)

        type_combo = QComboBox()
        type_combo.setObjectName("formInput")
        type_combo.addItem("Select type", None)
        for liability_type in [
            "Home Loan",
            "Car Loan",
            "Personal Loan",
            "Education Loan",
            "Credit Card",
            "Other",
        ]:
            type_combo.addItem(liability_type, liability_type)
        form_grid.addWidget(type_combo, 3, 0)

        currency_combo = QComboBox()
        currency_combo.setObjectName("formInput")
        currency_combo.addItem("INR ₹", "INR")
        currency_combo.addItem("USD $", "USD")
        currency_combo.addItem("EUR €", "EUR")
        currency_combo.addItem("GBP £", "GBP")
        form_grid.addWidget(currency_combo, 3, 1)

        amount_label = QLabel("Outstanding Amount *")
        amount_label.setObjectName("fieldLabel")
        form_grid.addWidget(amount_label, 4, 0)

        interest_label = QLabel("Interest Rate (%)")
        interest_label.setObjectName("fieldLabel")
        form_grid.addWidget(interest_label, 4, 1)

        amount_input = QLineEdit()
        amount_input.setObjectName("formInput")
        amount_input.setPlaceholderText("Amount")
        form_grid.addWidget(amount_input, 5, 0)

        interest_input = QLineEdit()
        interest_input.setObjectName("formInput")
        interest_input.setPlaceholderText("e.g. 8.5")
        form_grid.addWidget(interest_input, 5, 1)

        emi_label = QLabel("Monthly EMI")
        emi_label.setObjectName("fieldLabel")
        form_grid.addWidget(emi_label, 6, 0)

        start_date_label = QLabel("Start Date")
        start_date_label.setObjectName("fieldLabel")
        form_grid.addWidget(start_date_label, 6, 1)

        emi_input = QLineEdit()
        emi_input.setObjectName("formInput")
        emi_input.setPlaceholderText("Monthly payment")
        form_grid.addWidget(emi_input, 7, 0)

        start_date_input = QLineEdit()
        start_date_input.setObjectName("formInput")
        start_date_input.setPlaceholderText("dd/mm/yyyy")
        form_grid.addWidget(start_date_input, 7, 1)
        layout.addLayout(form_grid)

        status_label = QLabel("")
        status_label.setObjectName("statusError")
        status_label.hide()
        layout.addWidget(status_label)

        actions = QHBoxLayout()
        actions.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondaryButton")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.clicked.connect(dialog.reject)
        actions.addWidget(cancel_btn)

        add_btn = QPushButton("Save Liability" if is_edit_mode else "Add Liability")
        add_btn.setObjectName("saveButton")
        add_btn.setCursor(Qt.PointingHandCursor)
        actions.addWidget(add_btn)
        layout.addLayout(actions)

        def set_dialog_error(message: str) -> None:
            status_label.setText(message)
            status_label.show()
            status_label.style().unpolish(status_label)
            status_label.style().polish(status_label)

        def submit_liability() -> None:
            status_label.hide()
            name = name_input.text().strip()
            if not name:
                set_dialog_error("Name is required.")
                return

            liability_type = type_combo.currentData(Qt.UserRole)
            if not liability_type:
                set_dialog_error("Please select a liability type.")
                return

            amount_text = amount_input.text().strip()
            if not amount_text:
                set_dialog_error("Outstanding amount is required.")
                return
            try:
                outstanding_amount = parse_amount(amount_text)
            except ValueError:
                set_dialog_error("Outstanding amount must be a valid number.")
                return
            if outstanding_amount <= 0:
                set_dialog_error("Outstanding amount must be greater than 0.")
                return

            interest_text = interest_input.text().strip()
            if interest_text:
                try:
                    interest_rate = float(interest_text.replace(",", ""))
                except ValueError:
                    set_dialog_error("Interest rate must be a valid number.")
                    return
                if interest_rate < 0:
                    set_dialog_error("Interest rate cannot be negative.")
                    return
            else:
                interest_rate = 0.0

            emi_text = emi_input.text().strip()
            if emi_text:
                try:
                    monthly_emi = parse_amount(emi_text)
                except ValueError:
                    set_dialog_error("Monthly EMI must be a valid number.")
                    return
                if monthly_emi < 0:
                    set_dialog_error("Monthly EMI cannot be negative.")
                    return
            else:
                monthly_emi = 0.0

            start_date_text = start_date_input.text().strip()
            start_date = ""
            if start_date_text:
                try:
                    start_date = datetime.strptime(start_date_text, "%d/%m/%Y").strftime("%Y-%m-%d")
                except ValueError:
                    set_dialog_error("Start date must be in dd/mm/yyyy format.")
                    return

            currency = currency_combo.currentData(Qt.UserRole) or "INR"

            try:
                if is_edit_mode and liability_id is not None:
                    updated_rows = update_liability(
                        liability_id=liability_id,
                        name=name,
                        liability_type=str(liability_type),
                        currency=str(currency),
                        outstanding_amount=outstanding_amount,
                        interest_rate=interest_rate,
                        monthly_emi=monthly_emi,
                        start_date=start_date,
                    )
                    if updated_rows <= 0:
                        set_dialog_error("Unable to update liability.")
                        return
                else:
                    add_liability(
                        name=name,
                        liability_type=str(liability_type),
                        currency=str(currency),
                        outstanding_amount=outstanding_amount,
                        interest_rate=interest_rate,
                        monthly_emi=monthly_emi,
                        start_date=start_date,
                    )
            except Exception:
                error_text = "Unable to update liability. Please try again." if is_edit_mode else "Unable to save liability. Please try again."
                set_dialog_error(error_text)
                return

            dialog.accept()

        add_btn.clicked.connect(submit_liability)

        if is_edit_mode and liability is not None:
            name_input.setText(liability["name"] or "")

            current_type = (liability["liability_type"] or "").strip()
            type_index = type_combo.findData(current_type, role=Qt.UserRole)
            if type_index >= 0:
                type_combo.setCurrentIndex(type_index)

            current_currency = normalize_currency(liability["currency"])
            currency_index = currency_combo.findData(current_currency, role=Qt.UserRole)
            if currency_index >= 0:
                currency_combo.setCurrentIndex(currency_index)

            outstanding_amount = float(liability["outstanding_amount"] or 0)
            interest_rate = float(liability["interest_rate"] or 0)
            monthly_emi = float(liability["monthly_emi"] or 0)
            amount_input.setText(f"{outstanding_amount:.2f}".rstrip("0").rstrip("."))
            if interest_rate > 0:
                interest_input.setText(f"{interest_rate:.2f}".rstrip("0").rstrip("."))
            if monthly_emi > 0:
                emi_input.setText(f"{monthly_emi:.2f}".rstrip("0").rstrip("."))

            start_date_raw = (liability["start_date"] or "").strip()
            if start_date_raw:
                try:
                    start_date_input.setText(datetime.strptime(start_date_raw, "%Y-%m-%d").strftime("%d/%m/%Y"))
                except ValueError:
                    start_date_input.setText(start_date_raw)

        name_input.setFocus()

        if dialog.exec():
            self._refresh_liabilities_view()

    def _show_add_asset_page(self) -> None:
        self._clear_add_form()
        self._clear_status()
        self.selected_form_class_key = ""
        self._refresh_add_class_tile_styles()
        self._set_add_form_visibility(False)
        self._set_active_nav_item("Assets")
        self.content_stack.setCurrentIndex(self.ADD_ASSET_PAGE_INDEX)

    def _show_assets_page(self) -> None:
        self._clear_status()
        self._clear_edit_form_status()
        self._refresh_assets_view()
        self._set_active_nav_item("Assets")
        self.content_stack.setCurrentIndex(self.ASSETS_PAGE_INDEX)

    def _show_liabilities_page(self) -> None:
        self._clear_status()
        self._clear_edit_form_status()
        self._refresh_liabilities_view()
        self._set_active_nav_item("Liabilities")
        self.content_stack.setCurrentIndex(self.LIABILITIES_PAGE_INDEX)

    def _show_net_worth_page(self) -> None:
        self._clear_status()
        self._clear_edit_form_status()
        self._refresh_net_worth_view()
        self._set_active_nav_item("Net Worth")
        self._refresh_net_worth_mode_chips()
        self.content_stack.setCurrentIndex(self.NET_WORTH_PAGE_INDEX)

    def _clear_status(self) -> None:
        self.add_form_status.hide()
        self.add_form_status.setText("")
        self.add_form_status.setObjectName("statusSuccess")

    def _clear_add_form(self) -> None:
        self.name_input.clear()
        self.current_value_input.clear()
        self.invested_input.clear()
        self.subtype_input.clear()
        self.tag_input.clear()
        self.notes_input.clear()
        self.currency_combo.setCurrentText("INR")
        if self.extra_details_box.isVisible():
            self.extra_details_box.hide()
            self.disclosure_button.setText("v Add details (sub-type, tags, notes)")
        self._clear_status()

    def _show_error(self, message: str) -> None:
        self.add_form_status.setObjectName("statusError")
        self.add_form_status.setText(message)
        self.add_form_status.show()
        self.add_form_status.style().unpolish(self.add_form_status)
        self.add_form_status.style().polish(self.add_form_status)

    def _show_success(self, message: str) -> None:
        self.add_form_status.setObjectName("statusSuccess")
        self.add_form_status.setText(message)
        self.add_form_status.show()
        self.add_form_status.style().unpolish(self.add_form_status)
        self.add_form_status.style().polish(self.add_form_status)

    def _save_asset(self, stay_on_page: bool) -> None:
        if not self.selected_form_class_key or self.selected_form_class_key not in self.class_lookup:
            self._show_error("Select an asset class to continue.")
            return

        name = self.name_input.text().strip()
        if not name:
            self._show_error("Name is required.")
            return

        current_value_text = self.current_value_input.text().strip()
        if not current_value_text:
            self._show_error("Current value is required.")
            return

        try:
            current_value = parse_amount(current_value_text)
        except ValueError:
            self._show_error("Current value must be a valid number.")
            return

        if current_value <= 0:
            self._show_error("Current value must be greater than 0.")
            return

        invested_text = self.invested_input.text().strip()
        if invested_text:
            try:
                invested_value = parse_amount(invested_text)
            except ValueError:
                self._show_error("Invested amount must be a valid number.")
                return
            if invested_value < 0:
                self._show_error("Invested amount cannot be negative.")
                return
        else:
            invested_value = current_value

        subtype = self.subtype_input.text().strip() or "-"
        tag = self.tag_input.text().strip()
        notes = self.notes_input.text().strip()
        currency = self.currency_combo.currentText().strip() or "INR"

        try:
            add_asset(
                name=name,
                class_key=self.selected_form_class_key,
                sub_type=subtype,
                geography="India",
                invested=invested_value,
                value=current_value,
                tag=tag,
                currency=currency,
                notes=notes,
            )
        except Exception:
            self._show_error("Unable to save asset. Please try again.")
            return

        self._refresh_assets_view()

        if stay_on_page:
            self._clear_add_form()
            self._show_success("Asset saved. You can add another one.")
        else:
            self._clear_add_form()
            self.selected_category_key = None
            self.selected_class_filter_key = None
            self._show_assets_page()

    def _build_goals_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        container = QWidget()
        container.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(32)
        
        # Section 1: Active Goals Gallery (wrapped rows)
        self.goals_container = QWidget()
        self.goals_container.setStyleSheet("background-color: transparent;")
        self.active_goals_layout = QGridLayout(self.goals_container)
        self.active_goals_layout.setSpacing(16)
        self.active_goals_layout.setContentsMargins(0, 0, 0, 0)
        self.active_goals_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        layout.addWidget(self.goals_container)
        
        # Section 2: Create Goal Form
        create_panel = QFrame()
        create_panel.setObjectName("targetPanel")
        create_panel.setStyleSheet("QFrame#targetPanel { background-color: #ffffff; border: 1px solid #d9d8d3; border-radius: 6px; }")
        create_layout = QVBoxLayout(create_panel)
        create_layout.setContentsMargins(24, 24, 24, 24)
        create_layout.setSpacing(16)
        
        create_title = QLabel("Create New Goal")
        create_title.setStyleSheet('font-family: "Segoe UI", sans-serif; font-size: 14px; font-weight: bold; color: #22211f; border: none;')
        create_layout.addWidget(create_title)
        
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)
        
        # Row 0
        grid.addWidget(QLabel("Goal Name *"), 0, 0)
        self.goal_name_input = QLineEdit()
        self.goal_name_input.setPlaceholderText("e.g. Dream House")
        self.goal_name_input.setMinimumHeight(35)
        self.goal_name_input.setStyleSheet("border: 1px solid #d9d8d3; border-radius: 4px; padding: 0 8px;")
        grid.addWidget(self.goal_name_input, 1, 0)
        
        grid.addWidget(QLabel("Target Date *"), 0, 1)
        self.goal_date_input = QLineEdit()
        self.goal_date_input.setPlaceholderText("YYYY-MM-DD")
        self.goal_date_input.setMinimumHeight(35)
        self.goal_date_input.setStyleSheet("border: 1px solid #d9d8d3; border-radius: 4px; padding: 0 8px;")
        grid.addWidget(self.goal_date_input, 1, 1)
        
        # Row 1
        grid.addWidget(QLabel("Target Amount *"), 2, 0)
        self.goal_amount_input = QLineEdit()
        self.goal_amount_input.setPlaceholderText("e.g. 5000000")
        self.goal_amount_input.setMinimumHeight(35)
        self.goal_amount_input.setStyleSheet("border: 1px solid #d9d8d3; border-radius: 4px; padding: 0 8px;")
        grid.addWidget(self.goal_amount_input, 3, 0)
        
        grid.addWidget(QLabel("Expected Return (% p.a.)"), 2, 1)
        self.goal_return_input = QLineEdit("7.0")
        self.goal_return_input.setMinimumHeight(35)
        self.goal_return_input.setStyleSheet("border: 1px solid #d9d8d3; border-radius: 4px; padding: 0 8px;")
        grid.addWidget(self.goal_return_input, 3, 1)
        
        create_layout.addLayout(grid)
        
        # Row 2: Tracking options
        create_layout.addWidget(QLabel("Track Progress By"))
        self.goal_class_combo = QComboBox()
        self.goal_class_combo.setMinimumHeight(35)
        self.goal_class_combo.setStyleSheet("border: 1px solid #d9d8d3; border-radius: 4px; padding: 0 8px;")
        create_layout.addWidget(self.goal_class_combo)

        create_layout.addWidget(QLabel("Link Specific Assets (optional)"))
        self.goal_assets_hint = QLabel("Selecting specific assets overrides Track Progress By.")
        self.goal_assets_hint.setStyleSheet("font-size: 11px; color: #6b6962; border: none;")
        create_layout.addWidget(self.goal_assets_hint)

        self.goal_assets_scroll = QScrollArea()
        self.goal_assets_scroll.setWidgetResizable(True)
        self.goal_assets_scroll.setFixedHeight(160)
        self.goal_assets_scroll.setStyleSheet(
            "QScrollArea { border: 1px solid #d9d8d3; border-radius: 4px; background-color: #ffffff; }"
        )
        self.goal_assets_container = QWidget()
        self.goal_assets_layout = QVBoxLayout(self.goal_assets_container)
        self.goal_assets_layout.setContentsMargins(10, 8, 10, 8)
        self.goal_assets_layout.setSpacing(6)
        self.goal_assets_scroll.setWidget(self.goal_assets_container)
        create_layout.addWidget(self.goal_assets_scroll)
        self.goal_asset_checkboxes: dict[int, QCheckBox] = {}
        
        create_btn_row = QHBoxLayout()
        self.create_goal_btn = QPushButton("Create Goal")
        self.create_goal_btn.setObjectName("primaryButton")
        self.create_goal_btn.setMinimumHeight(35)
        self.create_goal_btn.setCursor(Qt.PointingHandCursor)
        self.create_goal_btn.clicked.connect(self._on_create_goal)
        create_btn_row.addStretch()
        create_btn_row.addWidget(self.create_goal_btn)
        
        create_layout.addLayout(create_btn_row)
        
        layout.addWidget(create_panel)
        layout.addStretch()
        
        scroll.setWidget(container)
        return scroll

    def _selected_goal_asset_ids(self) -> list[int]:
        if not hasattr(self, "goal_asset_checkboxes"):
            return []
        return sorted(aid for aid, cb in self.goal_asset_checkboxes.items() if cb.isChecked())

    def _refresh_goal_asset_selector(
        self,
        assets: list[object],
        target_layout: QVBoxLayout | None = None,
        checkbox_store: dict[int, QCheckBox] | None = None,
        selected_ids: set[int] | None = None,
    ) -> dict[int, QCheckBox]:
        layout = target_layout if target_layout is not None else getattr(self, "goal_assets_layout", None)
        if layout is None:
            return {} if checkbox_store is None else checkbox_store

        store = checkbox_store if checkbox_store is not None else getattr(self, "goal_asset_checkboxes", {})
        preserved_selected = selected_ids
        if preserved_selected is None:
            preserved_selected = {aid for aid, cb in store.items() if cb.isChecked()}

        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        store.clear()

        if not assets:
            empty_lbl = QLabel("No investments found. Add assets to link them to a goal.")
            empty_lbl.setStyleSheet("font-size: 11px; color: #6b6962; border: none;")
            empty_lbl.setWordWrap(True)
            layout.addWidget(empty_lbl)
            return store

        for asset in sorted(assets, key=lambda row: str(row["name"] or "").lower()):
            aid = int(asset["id"])
            asset_name = asset["name"] or f"Asset {aid}"
            class_row = self.class_lookup.get(asset["class_key"])
            class_name = class_row["class_name"] if class_row else (asset["class_key"] or "Unclassified")
            value_text = format_compact_inr(float(asset["value"] or 0))
            cb = QCheckBox(f"{asset_name} • {class_name} • {value_text}")
            cb.setStyleSheet("font-size: 12px; color: #22211f;")
            cb.setChecked(aid in preserved_selected)
            store[aid] = cb
            layout.addWidget(cb)

        layout.addStretch()
        return store

    def _goal_tracking_label(self, goal_data: dict) -> str:
        if goal_data.get("linked_asset_ids"):
            return "Specific Assets"
        category_key = goal_data.get("asset_class_key")
        if not category_key:
            return "All Categories"
        return self.category_lookup.get(category_key, str(category_key).replace("_", " ").title())

    def _goal_created_at(self, goal_data: dict) -> datetime:
        raw = str(goal_data.get("created_at") or "").strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
        return datetime.now()

    def _asset_matches_goal_tracking(self, asset: object, goal_data: dict) -> bool:
        linked_ids = {int(aid) for aid in goal_data.get("linked_asset_ids") or []}
        if linked_ids:
            return int(asset["id"]) in linked_ids

        tracked_category = goal_data.get("asset_class_key")
        if not tracked_category:
            return True

        class_row = self.class_lookup.get(asset["class_key"])
        asset_category = class_row["category_key"] if class_row else None
        return asset_category == tracked_category

    def _calculate_goal_current_savings(self, goal_data: dict, assets: list[object]) -> float:
        total = 0.0
        for asset in assets:
            if self._asset_matches_goal_tracking(asset, goal_data):
                total += self._convert_to_inr(float(asset["value"] or 0), asset["currency"])
        return total

    def _calculate_goal_metrics(self, goal_data: dict, assets: list[object]) -> dict[str, float]:
        target_amt = float(goal_data["target_amount"] or 0)
        ret_pct = float(goal_data["expected_return_pct"] or 0)
        current_savings = self._calculate_goal_current_savings(goal_data, assets)
        progress_pct = min(100.0, max(0.0, (current_savings / target_amt) * 100)) if target_amt > 0 else 0.0

        months_remaining = calculate_months_remaining(goal_data["target_date"])
        monthly_needed = calculate_required_pmt(target_amt, current_savings, ret_pct, months_remaining)
        remaining_amt = max(0.0, target_amt - current_savings)

        now = datetime.now()
        created_at = self._goal_created_at(goal_data)
        try:
            target_date = datetime.strptime(goal_data["target_date"], "%Y-%m-%d")
        except ValueError:
            target_date = now

        total_days = (target_date - created_at).days
        elapsed_days = max(0, (now - created_at).days)
        if total_days <= 0:
            time_elapsed_pct = 100.0 if now >= target_date else 0.0
        else:
            time_elapsed_pct = min(100.0, max(0.0, (elapsed_days / total_days) * 100.0))
        days_remaining = max(0, (target_date.date() - now.date()).days)

        return {
            "current_savings": current_savings,
            "target_amount": target_amt,
            "progress_pct": progress_pct,
            "months_remaining": float(months_remaining),
            "monthly_needed": monthly_needed,
            "remaining_amount": remaining_amt,
            "time_elapsed_pct": time_elapsed_pct,
            "days_remaining": float(days_remaining),
            "expected_return_pct": ret_pct,
        }

    def _refresh_goals_view(self):
        from db import fetch_categories, fetch_assets, fetch_goals

        current_idx = self.goal_class_combo.currentIndex()
        self.goal_class_combo.blockSignals(True)
        self.goal_class_combo.clear()
        self.goal_class_combo.addItem("All Categories", "")
        for cat in fetch_categories():
            self.goal_class_combo.addItem(cat["category_name"], cat["category_key"])
        if 0 <= current_idx < self.goal_class_combo.count():
            self.goal_class_combo.setCurrentIndex(current_idx)
        self.goal_class_combo.blockSignals(False)

        while self.active_goals_layout.count():
            item = self.active_goals_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        assets = fetch_assets()
        self._refresh_goal_asset_selector(assets)
        goals = fetch_goals()

        card_width = 340
        spacing = self.active_goals_layout.horizontalSpacing()
        if spacing < 0:
            spacing = 16
        available_width = self.goals_container.width()
        if available_width <= 0:
            available_width = max(360, self.content_stack.width() - 120)
        columns = max(1, int((available_width + spacing) / (card_width + spacing)))

        for idx, goal in enumerate(goals):
            goal["tracking_label"] = self._goal_tracking_label(goal)
            metrics = self._calculate_goal_metrics(goal, assets)
            card = GoalCard(
                goal,
                metrics["current_savings"],
                int(metrics["months_remaining"]),
                metrics["monthly_needed"],
                self._on_goal_card_action,
            )
            row = idx // columns
            col = idx % columns
            self.active_goals_layout.addWidget(card, row, col)

        for col in range(0, 10):
            self.active_goals_layout.setColumnStretch(col, 0)
        self.active_goals_layout.setColumnStretch(columns, 1)

    def _on_create_goal(self):
        from db import create_goal

        name = self.goal_name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Create goal", "Goal Name is required.")
            return

        amt_str = self.goal_amount_input.text().strip()
        try:
            target_amount = parse_amount(amt_str)
            if target_amount <= 0:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Create goal", "Target Amount must be a positive number.")
            return

        date_str = self.goal_date_input.text().strip()
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            QMessageBox.warning(self, "Create goal", "Date must be in YYYY-MM-DD format.")
            return

        ret_str = self.goal_return_input.text().strip()
        try:
            ret_pct = float(ret_str)
        except ValueError:
            QMessageBox.warning(self, "Create goal", "Expected Return must be a number.")
            return

        linked_asset_ids = self._selected_goal_asset_ids()
        cat_key = self.goal_class_combo.currentData()
        if cat_key == "" or linked_asset_ids:
            cat_key = None

        try:
            create_goal(name, target_amount, date_str, ret_pct, cat_key, linked_asset_ids)
        except Exception:
            QMessageBox.critical(self, "Create goal", "Failed to create goal.")
            return

        self.goal_name_input.clear()
        self.goal_amount_input.clear()
        self.goal_date_input.clear()
        for cb in self.goal_asset_checkboxes.values():
            cb.setChecked(False)
        self._refresh_goals_view()
        self._refresh_dashboard_view()
        self._show_toast("Goal created")

    def _on_goal_card_action(self, action_name: str, goal_data: dict) -> None:
        from db import fetch_goal_by_id

        goal_id = int(goal_data["id"])
        latest_goal = fetch_goal_by_id(goal_id)
        if latest_goal is None:
            self._refresh_goals_view()
            return

        if action_name == "view":
            self._open_goal_summary_dialog(goal_id)
        elif action_name == "edit":
            self._open_goal_edit_dialog(goal_id)
        elif action_name == "pause":
            self._set_goal_status(goal_id, "PAUSED", "Goal paused")
        elif action_name == "resume":
            self._set_goal_status(goal_id, "ACTIVE", "Goal resumed")
        elif action_name == "mark_achieved":
            self._set_goal_status(goal_id, "ACHIEVED", "Goal marked achieved")
        elif action_name == "delete":
            self._confirm_goal_delete(latest_goal)

    def _set_goal_status(self, goal_id: int, status: str, success_message: str) -> None:
        from db import update_goal_status

        try:
            update_goal_status(goal_id, status)
        except Exception:
            QMessageBox.critical(self, "Goal update", "Unable to update goal status.")
            return

        self._refresh_goals_view()
        self._refresh_dashboard_view()
        self._show_toast(success_message)

    def _confirm_goal_delete(self, goal_data: dict) -> bool:
        from db import delete_goal

        choice = QMessageBox.question(
            self,
            "Delete goal",
            f"Delete '{goal_data['name']}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if choice != QMessageBox.Yes:
            return False

        try:
            delete_goal(int(goal_data["id"]))
        except Exception:
            QMessageBox.critical(self, "Delete goal", "Unable to delete this goal.")
            return False

        self._refresh_goals_view()
        self._refresh_dashboard_view()
        self._show_toast("Goal deleted")
        return True

    def _open_goal_edit_dialog(self, goal_id: int) -> None:
        from db import fetch_assets, fetch_categories, fetch_goal_by_id, update_goal

        goal_data = fetch_goal_by_id(goal_id)
        if goal_data is None:
            QMessageBox.warning(self, "Edit goal", "Goal was not found.")
            self._refresh_goals_view()
            return

        assets = fetch_assets()
        categories = fetch_categories()
        selected_asset_ids = {int(aid) for aid in goal_data.get("linked_asset_ids") or []}

        dialog = QDialog(self)
        dialog.setWindowTitle("Edit Goal")
        dialog.setModal(True)
        dialog.resize(760, 540)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel(f"Edit Goal • {goal_data['name']}")
        title.setStyleSheet('font-family: "Segoe UI"; font-size: 16px; font-weight: 700; color: #22211f;')
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)

        grid.addWidget(QLabel("Goal Name *"), 0, 0)
        name_input = QLineEdit(goal_data["name"])
        name_input.setMinimumHeight(35)
        name_input.setStyleSheet("border: 1px solid #d9d8d3; border-radius: 4px; padding: 0 8px;")
        grid.addWidget(name_input, 1, 0)

        grid.addWidget(QLabel("Target Date *"), 0, 1)
        date_input = QLineEdit(goal_data["target_date"])
        date_input.setMinimumHeight(35)
        date_input.setStyleSheet("border: 1px solid #d9d8d3; border-radius: 4px; padding: 0 8px;")
        grid.addWidget(date_input, 1, 1)

        grid.addWidget(QLabel("Target Amount *"), 2, 0)
        raw_target_amount = float(goal_data["target_amount"] or 0)
        amount_text = f"{raw_target_amount:.2f}".rstrip("0").rstrip(".")
        amount_input = QLineEdit(amount_text)
        amount_input.setMinimumHeight(35)
        amount_input.setStyleSheet("border: 1px solid #d9d8d3; border-radius: 4px; padding: 0 8px;")
        grid.addWidget(amount_input, 3, 0)

        grid.addWidget(QLabel("Expected Return (% p.a.)"), 2, 1)
        return_input = QLineEdit(str(goal_data["expected_return_pct"]))
        return_input.setMinimumHeight(35)
        return_input.setStyleSheet("border: 1px solid #d9d8d3; border-radius: 4px; padding: 0 8px;")
        grid.addWidget(return_input, 3, 1)

        layout.addLayout(grid)

        layout.addWidget(QLabel("Track Progress By"))
        class_combo = QComboBox()
        class_combo.setMinimumHeight(35)
        class_combo.setStyleSheet("border: 1px solid #d9d8d3; border-radius: 4px; padding: 0 8px;")
        class_combo.addItem("All Categories", "")
        for cat in categories:
            class_combo.addItem(cat["category_name"], cat["category_key"])
        active_cat = goal_data.get("asset_class_key") or ""
        class_index = class_combo.findData(active_cat)
        class_combo.setCurrentIndex(class_index if class_index >= 0 else 0)
        layout.addWidget(class_combo)

        layout.addWidget(QLabel("Link Specific Assets (optional)"))
        hint_lbl = QLabel("Selecting specific assets overrides Track Progress By.")
        hint_lbl.setStyleSheet("font-size: 11px; color: #6b6962; border: none;")
        layout.addWidget(hint_lbl)

        assets_scroll = QScrollArea()
        assets_scroll.setWidgetResizable(True)
        assets_scroll.setFixedHeight(170)
        assets_scroll.setStyleSheet("QScrollArea { border: 1px solid #d9d8d3; border-radius: 4px; background: #fff; }")
        assets_container = QWidget()
        assets_layout = QVBoxLayout(assets_container)
        assets_layout.setContentsMargins(10, 8, 10, 8)
        assets_layout.setSpacing(6)
        assets_scroll.setWidget(assets_container)
        layout.addWidget(assets_scroll)

        edit_checkboxes: dict[int, QCheckBox] = {}
        self._refresh_goal_asset_selector(
            assets,
            target_layout=assets_layout,
            checkbox_store=edit_checkboxes,
            selected_ids=selected_asset_ids,
        )

        actions = QHBoxLayout()
        actions.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondaryButton")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.clicked.connect(dialog.reject)
        actions.addWidget(cancel_btn)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("primaryButton")
        save_btn.setCursor(Qt.PointingHandCursor)
        actions.addWidget(save_btn)
        layout.addLayout(actions)

        def save_goal() -> None:
            name = name_input.text().strip()
            if not name:
                QMessageBox.warning(dialog, "Edit goal", "Goal Name is required.")
                return

            amount_text = amount_input.text().strip()
            try:
                target_amount = parse_amount(amount_text)
                if target_amount <= 0:
                    raise ValueError
            except ValueError:
                QMessageBox.warning(dialog, "Edit goal", "Target Amount must be a positive number.")
                return

            target_date = date_input.text().strip()
            try:
                datetime.strptime(target_date, "%Y-%m-%d")
            except ValueError:
                QMessageBox.warning(dialog, "Edit goal", "Date must be in YYYY-MM-DD format.")
                return

            try:
                expected_return = float(return_input.text().strip())
            except ValueError:
                QMessageBox.warning(dialog, "Edit goal", "Expected Return must be a number.")
                return

            linked_assets = sorted(aid for aid, cb in edit_checkboxes.items() if cb.isChecked())
            category_key = class_combo.currentData()
            if category_key == "" or linked_assets:
                category_key = None

            try:
                update_goal(
                    goal_id,
                    name,
                    target_amount,
                    target_date,
                    expected_return,
                    category_key,
                    linked_assets,
                )
            except Exception:
                QMessageBox.critical(dialog, "Edit goal", "Failed to update goal.")
                return

            dialog.accept()
            self._refresh_goals_view()
            self._refresh_dashboard_view()
            self._show_toast("Goal updated")

        save_btn.clicked.connect(save_goal)
        dialog.exec()

    def _open_goal_summary_dialog(self, goal_id: int) -> None:
        from db import fetch_assets, fetch_goal_by_id

        goal_data = fetch_goal_by_id(goal_id)
        if goal_data is None:
            QMessageBox.warning(self, "View goal", "Goal was not found.")
            self._refresh_goals_view()
            return

        assets = fetch_assets()
        metrics = self._calculate_goal_metrics(goal_data, assets)
        status = str(goal_data.get("status") or "ACTIVE").upper()
        tracking_label = self._goal_tracking_label(goal_data)

        dialog = QDialog(self)
        dialog.setModal(True)
        dialog.setWindowTitle(goal_data["name"])
        dialog.resize(600, 640)
        dialog.setStyleSheet(
            """
            QDialog {
                background: #f7f7f4;
            }
            QLabel {
                border: none;
                background: transparent;
            }
            QFrame#goalSummaryCallout {
                border: none;
                border-radius: 10px;
            }
            QFrame#goalSummaryInfoCard {
                background: #f0efe9;
                border: none;
                border-radius: 10px;
            }
            QFrame#goalSummaryActionBar {
                background: #ecebe5;
                border: none;
                border-radius: 10px;
            }
            QPushButton#goalActionButton {
                border: none;
                background: transparent;
                color: #252421;
                padding: 10px 14px;
                font-size: 14px;
                font-weight: 500;
            }
            QPushButton#goalActionButton:hover {
                background: #e2e0d8;
            }
            QPushButton#goalActionButtonPrimary {
                border: none;
                background: transparent;
                color: #2b7a52;
                padding: 10px 14px;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton#goalActionButtonPrimary:hover {
                background: #deebe3;
            }
            QPushButton#goalDeleteAction {
                border: none;
                background: transparent;
                color: #c23b31;
                padding: 10px 14px;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton#goalDeleteAction:hover {
                background: #f3dfdc;
            }
            QFrame#goalActionDivider {
                background: #d7d5cc;
                min-width: 1px;
                max-width: 1px;
            }
            """
        )

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        head = QHBoxLayout()
        title_lbl = QLabel(goal_data["name"])
        title_lbl.setStyleSheet('font-family: "Segoe UI"; font-size: 30px; font-weight: 700; color: #22211f;')
        head.addWidget(title_lbl)
        head.addStretch()
        close_btn = QToolButton()
        close_btn.setText("✕")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet("QToolButton { border: none; font-size: 16px; color: #6b6962; }")
        close_btn.clicked.connect(dialog.reject)
        head.addWidget(close_btn)
        layout.addLayout(head)

        amount_row = QHBoxLayout()
        current_col = QVBoxLayout()
        current_caption = QLabel("CURRENT")
        current_caption.setStyleSheet("font-size: 12px; color: #6b6962; font-weight: 700; letter-spacing: 0.8px;")
        current_val = QLabel(format_compact_inr(metrics["current_savings"]))
        current_val.setStyleSheet('font-family: "Segoe UI"; font-size: 42px; font-weight: 700; color: #22211f;')
        current_col.addWidget(current_caption)
        current_col.addWidget(current_val)
        amount_row.addLayout(current_col, 1)

        target_col = QVBoxLayout()
        target_caption = QLabel("TARGET")
        target_caption.setStyleSheet("font-size: 12px; color: #6b6962; font-weight: 700; letter-spacing: 0.8px;")
        target_caption.setAlignment(Qt.AlignRight)
        target_val = QLabel(format_compact_inr(metrics["target_amount"]))
        target_val.setStyleSheet('font-family: "Segoe UI"; font-size: 42px; font-weight: 700; color: #22211f;')
        target_val.setAlignment(Qt.AlignRight)
        target_col.addWidget(target_caption)
        target_col.addWidget(target_val)
        amount_row.addLayout(target_col, 1)
        layout.addLayout(amount_row)

        def add_progress(label: str, pct: float, color: str) -> None:
            row = QHBoxLayout()
            label_widget = QLabel(label)
            label_widget.setStyleSheet("font-size: 12px; color: #6b6962;")
            row.addWidget(label_widget)
            row.addStretch()
            pct_widget = QLabel(f"{pct:.1f}%")
            pct_widget.setStyleSheet(f"font-size: 12px; color: {color}; font-weight: 700;")
            row.addWidget(pct_widget)
            layout.addLayout(row)

            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(int(max(0, min(1000, round(pct * 10)))))
            bar.setTextVisible(False)
            bar.setFixedHeight(10)
            bar.setStyleSheet(
                "QProgressBar { border: none; border-radius: 5px; background: #e6e4dd; }"
                f"QProgressBar::chunk {{ border-radius: 5px; background: {color}; }}"
            )
            layout.addWidget(bar)

        add_progress("Savings progress", metrics["progress_pct"], "#2b7a52")
        add_progress("Time elapsed", metrics["time_elapsed_pct"], "#8f8b80")

        callout = QFrame()
        callout.setObjectName("goalSummaryCallout")
        if status == "ACHIEVED":
            callout_bg = "#e3efe8"
            callout_fg = "#2b7a52"
            title_text = "✓ Achieved"
            subtitle_text = "This goal has been marked as achieved."
        elif status == "PAUSED":
            callout_bg = "#f1ece2"
            callout_fg = "#6b6962"
            title_text = "⏸ Paused"
            subtitle_text = "This goal is paused. Resume it to continue progress planning."
        elif metrics["months_remaining"] <= 0 and metrics["progress_pct"] < 100:
            callout_bg = "#fae9e6"
            callout_fg = "#cc4b38"
            title_text = "⚠ Behind schedule"
            subtitle_text = "Target date passed before completion."
        elif metrics["progress_pct"] + 5 >= metrics["time_elapsed_pct"]:
            callout_bg = "#e3efe8"
            callout_fg = "#2b7a52"
            title_text = "✓ On track"
            subtitle_text = (
                f"Invest {format_compact_inr(metrics['monthly_needed'])}/mo at "
                f"{metrics['expected_return_pct']:.1f}% p.a. to close remaining gap."
            )
        else:
            callout_bg = "#fff1d6"
            callout_fg = "#8a6100"
            title_text = "△ At risk"
            subtitle_text = (
                f"Current pace is below timeline. Needed: {format_compact_inr(metrics['monthly_needed'])}/mo."
            )
        callout.setStyleSheet(
            f"QFrame#goalSummaryCallout {{ background: {callout_bg}; }}"
        )
        callout_layout = QVBoxLayout(callout)
        callout_layout.setContentsMargins(14, 12, 14, 12)
        callout_layout.setSpacing(6)
        callout_title = QLabel(title_text)
        callout_title.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {callout_fg};")
        callout_layout.addWidget(callout_title)
        callout_sub = QLabel(subtitle_text)
        callout_sub.setWordWrap(True)
        callout_sub.setStyleSheet("font-size: 16px; color: #3b3a36;")
        callout_layout.addWidget(callout_sub)
        layout.addWidget(callout)

        info_grid = QGridLayout()
        info_grid.setHorizontalSpacing(10)
        info_grid.setVerticalSpacing(10)

        def make_info_card(title: str, value: str, subtext: str) -> QFrame:
            card = QFrame()
            card.setObjectName("goalSummaryInfoCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(4)
            title_lbl = QLabel(title)
            title_lbl.setStyleSheet("font-size: 11px; color: #6b6962; font-weight: 700; letter-spacing: 0.6px;")
            value_lbl = QLabel(value)
            value_lbl.setStyleSheet('font-family: "Segoe UI"; font-size: 30px; font-weight: 700; color: #22211f;')
            sub_lbl = QLabel(subtext)
            sub_lbl.setStyleSheet("font-size: 12px; color: #6b6962;")
            sub_lbl.setWordWrap(True)
            card_layout.addWidget(title_lbl)
            card_layout.addWidget(value_lbl)
            card_layout.addWidget(sub_lbl)
            return card

        days_left = int(metrics["days_remaining"])
        months_left = int(metrics["months_remaining"])
        try:
            target_date_display = datetime.strptime(goal_data["target_date"], "%Y-%m-%d").strftime("%d %b %Y")
        except ValueError:
            target_date_display = goal_data["target_date"]
        info_grid.addWidget(
            make_info_card(
                "TARGET DATE",
                target_date_display,
                f"{days_left} day{'s' if days_left != 1 else ''} left",
            ),
            0,
            0,
        )
        info_grid.addWidget(
            make_info_card(
                "REMAINING",
                format_compact_inr(metrics["remaining_amount"]),
                f"over {months_left} month{'s' if months_left != 1 else ''}",
            ),
            0,
            1,
        )
        info_grid.addWidget(
            make_info_card(
                "MONTHLY NEEDED",
                format_compact_inr(metrics["monthly_needed"]),
                f"at {metrics['expected_return_pct']:.1f}% p.a. assumed",
            ),
            1,
            0,
        )
        info_grid.addWidget(
            make_info_card(
                "LINKED TO",
                tracking_label,
                "specific assets" if goal_data.get("linked_asset_ids") else "asset class",
            ),
            1,
            1,
        )
        layout.addLayout(info_grid)

        action_bar = QFrame()
        action_bar.setObjectName("goalSummaryActionBar")
        actions = QHBoxLayout(action_bar)
        actions.setContentsMargins(8, 6, 8, 6)
        actions.setSpacing(0)

        def add_action_divider() -> None:
            divider = QFrame()
            divider.setObjectName("goalActionDivider")
            divider.setFixedHeight(24)
            actions.addWidget(divider)

        edit_btn = QPushButton("Edit Goal")
        edit_btn.setObjectName("goalActionButton")
        edit_btn.setCursor(Qt.PointingHandCursor)
        actions.addWidget(edit_btn)

        if status != "ACHIEVED":
            add_action_divider()
            mark_btn = QPushButton("Mark Achieved")
            mark_btn.setObjectName("goalActionButtonPrimary")
            mark_btn.setCursor(Qt.PointingHandCursor)
            actions.addWidget(mark_btn)

            add_action_divider()
            pause_resume_btn = QPushButton("Resume" if status == "PAUSED" else "Pause")
            pause_resume_btn.setObjectName("goalActionButton")
            pause_resume_btn.setCursor(Qt.PointingHandCursor)
            actions.addWidget(pause_resume_btn)
        else:
            mark_btn = None
            pause_resume_btn = None

        add_action_divider()
        delete_btn = QPushButton("Delete")
        delete_btn.setObjectName("goalDeleteAction")
        delete_btn.setCursor(Qt.PointingHandCursor)
        actions.addWidget(delete_btn)
        layout.addWidget(action_bar)

        def open_edit() -> None:
            dialog.accept()
            self._open_goal_edit_dialog(goal_id)

        def mark_achieved() -> None:
            dialog.accept()
            self._set_goal_status(goal_id, "ACHIEVED", "Goal marked achieved")

        def toggle_pause_resume() -> None:
            dialog.accept()
            if status == "PAUSED":
                self._set_goal_status(goal_id, "ACTIVE", "Goal resumed")
            else:
                self._set_goal_status(goal_id, "PAUSED", "Goal paused")

        def delete_goal_action() -> None:
            if self._confirm_goal_delete(goal_data):
                dialog.accept()

        edit_btn.clicked.connect(open_edit)
        delete_btn.clicked.connect(delete_goal_action)
        if mark_btn is not None:
            mark_btn.clicked.connect(mark_achieved)
        if pause_resume_btn is not None:
            pause_resume_btn.clicked.connect(toggle_pause_resume)

        dialog.exec()



    # ─────────────────────────────────────────────
    # DASHBOARD PAGE
    # ─────────────────────────────────────────────

    def _show_dashboard_page(self) -> None:
        self._refresh_dashboard_view()
        self._set_active_nav_item("Dashboard")
        self.content_stack.setCurrentIndex(self.DASHBOARD_PAGE_INDEX)

    def _build_dashboard_page(self) -> QWidget:
        """Build the static skeleton for the Dashboard overview page."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: #f7f7f5; }")

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        root = QVBoxLayout(container)
        root.setContentsMargins(28, 22, 28, 24)
        root.setSpacing(16)

        # ── Row 1: Net Worth hero card ────────────────────────────────────
        hero_card = QFrame()
        hero_card.setObjectName("dashHeroCard")
        hero_card.setStyleSheet(
            """
            QFrame#dashHeroCard {
                background: #ffffff;
                border: 1px solid #d9d8d3;
                border-radius: 12px;
            }
            """
        )
        hero_card.setFixedHeight(240)
        hero_hl = QHBoxLayout(hero_card)
        hero_hl.setContentsMargins(28, 18, 28, 18)
        hero_hl.setSpacing(24)

        # Left: net-worth value block — centered
        nw_col = QVBoxLayout()
        nw_col.setSpacing(4)
        nw_col.setAlignment(Qt.AlignHCenter)

        self.dash_nw_label = QLabel("NET WORTH · ₹ INR")
        self.dash_nw_label.setAlignment(Qt.AlignCenter)
        self.dash_nw_label.setStyleSheet(
            "font-size: 11px; font-weight: 700; color: #6b6962;"
            " letter-spacing: 0.8px;"
        )
        nw_col.addWidget(self.dash_nw_label)

        self.dash_nw_value = QLabel("₹0")
        self.dash_nw_value.setAlignment(Qt.AlignCenter)
        self.dash_nw_value.setStyleSheet(
            "font-size: 84px; font-weight: 800; color: #1d7a4f;"
        )
        nw_col.addWidget(self.dash_nw_value)

        self.dash_nw_delta = QLabel("+₹0 (+0.0%) vs last snapshot")
        self.dash_nw_delta.setAlignment(Qt.AlignCenter)
        self.dash_nw_delta.setStyleSheet("font-size: 13px; color: #2b7a52;")
        nw_col.addWidget(self.dash_nw_delta)

        # Sparkline chart (compact, inline below delta)
        self.dash_sparkline_view = QChartView()
        self.dash_sparkline_view.setObjectName("timelineChart")
        self.dash_sparkline_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.dash_sparkline_view.setFixedSize(260, 60)
        self.dash_sparkline_view.setStyleSheet("background: transparent; border: none;")

        spark_chart = QChart()
        spark_chart.setBackgroundBrush(Qt.transparent)
        spark_chart.setBackgroundVisible(False)
        spark_chart.setPlotAreaBackgroundVisible(False)
        spark_chart.legend().setVisible(False)
        spark_chart.setMargins(QMargins(0, 0, 0, 0))
        self.dash_spark_series = QLineSeries()
        pen = QPen(QColor("#2b7a52"))
        pen.setWidth(2)
        self.dash_spark_series.setPen(pen)
        spark_chart.addSeries(self.dash_spark_series)
        spark_chart.createDefaultAxes()
        for axis in spark_chart.axes():
            axis.setVisible(False)
        self.dash_sparkline_view.setChart(spark_chart)
        self.dash_spark_chart = spark_chart

        nw_col.addWidget(self.dash_sparkline_view, 0, Qt.AlignHCenter)

        nw_outer = QVBoxLayout()
        nw_outer.setContentsMargins(0, 0, 0, 0)
        nw_outer.setSpacing(0)
        nw_outer.addStretch()
        nw_outer.addLayout(nw_col)
        nw_outer.addStretch()

        hero_hl.addLayout(nw_outer, 3)

        # Divider
        divider = QFrame()
        divider.setFrameShape(QFrame.VLine)
        divider.setStyleSheet("color: #e5e4df;")
        hero_hl.addWidget(divider)

        # Right: 2×2 grid of colorful mini metric tiles (no inner boxes)
        mini_grid = QGridLayout()
        mini_grid.setSpacing(10)

        def make_mini_tile(bg: str, label_text: str, accent: str) -> tuple[QFrame, QLabel, QLabel, QLabel]:
            tile = QFrame()
            tile.setStyleSheet(
                f"QFrame {{ background: {bg}; border: none; border-radius: 10px; }}"
            )
            tile.setFixedSize(210, 74)
            tl = QVBoxLayout(tile)
            tl.setContentsMargins(14, 10, 14, 10)
            tl.setSpacing(2)
            lbl = QLabel(label_text)
            lbl.setStyleSheet(
                f"font-size: 10px; font-weight: 700; color: {accent};"
                f" letter-spacing: 0.7px; background: transparent;"
            )
            val = QLabel("₹0")
            val.setStyleSheet(
                f"font-size: 19px; font-weight: 800; color: {accent}; background: transparent;"
            )
            sub = QLabel("–")
            sub.setStyleSheet(f"font-size: 11px; color: {accent}; opacity: 0.75; background: transparent;")
            tl.addWidget(lbl)
            tl.addWidget(val)
            tl.addWidget(sub)
            return tile, lbl, val, sub

        assets_tile, _, self.dash_assets_value, self.dash_assets_sub = make_mini_tile(
            "#dbeafe", "ASSETS", "#1e40af"
        )
        liab_tile, _, self.dash_liab_value, self.dash_liab_sub = make_mini_tile(
            "#fee2e2", "LIABILITIES", "#991b1b"
        )
        inv_tile, _, self.dash_inv_value, self.dash_inv_sub = make_mini_tile(
            "#dcfce7", "INVESTED", "#166534"
        )

        # Health Score tile — with hover tooltip
        health_tile = QFrame()
        health_tile.setStyleSheet(
            "QFrame { background: #ede9fe; border: none; border-radius: 10px; }"
        )
        health_tile.setFixedSize(210, 74)
        htl = QVBoxLayout(health_tile)
        htl.setContentsMargins(14, 10, 14, 10)
        htl.setSpacing(2)
        h_lbl = QLabel("HEALTH SCORE")
        h_lbl.setStyleSheet(
            "font-size: 10px; font-weight: 700; color: #5b21b6;"
            " letter-spacing: 0.7px; background: transparent;"
        )
        self.dash_health_value = QLabel("–")
        self.dash_health_value.setStyleSheet(
            "font-size: 19px; font-weight: 800; color: #5b21b6; background: transparent;"
        )
        self.dash_health_sub = QLabel("–")
        self.dash_health_sub.setStyleSheet(
            "font-size: 11px; color: #5b21b6; background: transparent;"
        )
        htl.addWidget(h_lbl)
        htl.addWidget(self.dash_health_value)
        htl.addWidget(self.dash_health_sub)

        # Tooltip popup for health score
        self._health_tooltip = QFrame(None, Qt.ToolTip)
        self._health_tooltip.setWindowFlags(Qt.ToolTip)
        self._health_tooltip.setStyleSheet(
            "QFrame { background: #1e1b2e; border-radius: 8px; padding: 4px; }"
            " QLabel { color: #e9d5ff; font-size: 12px; background: transparent; }"
        )
        tt_layout = QVBoxLayout(self._health_tooltip)
        tt_layout.setContentsMargins(12, 10, 12, 10)
        tt_layout.setSpacing(4)
        self._health_tooltip_title = QLabel("Health Score Breakdown")
        self._health_tooltip_title.setStyleSheet(
            "font-weight: 700; font-size: 13px; color: #f3e8ff; background: transparent;"
        )
        tt_layout.addWidget(self._health_tooltip_title)
        self._health_tooltip_body = QLabel("")
        self._health_tooltip_body.setWordWrap(True)
        self._health_tooltip_body.setStyleSheet(
            "color: #c4b5fd; font-size: 12px; line-height: 1.5; background: transparent;"
        )
        tt_layout.addWidget(self._health_tooltip_body)
        self._health_tooltip.hide()

        def health_enter(event):
            pos = health_tile.mapToGlobal(health_tile.rect().bottomLeft())
            self._health_tooltip.move(pos)
            self._health_tooltip.adjustSize()
            self._health_tooltip.show()
            self._health_tooltip.raise_()

        def health_leave(event):
            self._health_tooltip.hide()

        health_tile.enterEvent = health_enter
        health_tile.leaveEvent = health_leave

        mini_grid.addWidget(assets_tile, 0, 0)
        mini_grid.addWidget(liab_tile, 0, 1)
        mini_grid.addWidget(inv_tile, 1, 0)
        mini_grid.addWidget(health_tile, 1, 1)

        hero_hl.addLayout(mini_grid, 1)
        root.addWidget(hero_card)


        # ── Bottom row: Asset Allocation | Top Holdings | Goals ──────────
        bottom_hl = QHBoxLayout()
        bottom_hl.setSpacing(16)

        # --- Asset Allocation card ---
        alloc_card = QFrame()
        alloc_card.setObjectName("dashAllocCard")
        alloc_card.setStyleSheet(
            "QFrame#dashAllocCard { background: #ffffff; border: 1px solid #d9d8d3; border-radius: 12px; }"
        )
        alloc_vl = QVBoxLayout(alloc_card)
        alloc_vl.setContentsMargins(18, 14, 18, 14)
        alloc_vl.setSpacing(8)

        alloc_title_lbl = QLabel("Asset Allocation")
        alloc_title_lbl.setStyleSheet("font-size: 15px; font-weight: 700; color: #22211f;")
        alloc_sub_lbl = QLabel("By category")
        alloc_sub_lbl.setStyleSheet("font-size: 11px; color: #6b6962;")
        alloc_vl.addWidget(alloc_title_lbl)
        alloc_vl.addWidget(alloc_sub_lbl)

        alloc_inner_hl = QHBoxLayout()
        alloc_inner_hl.setSpacing(12)

        class DonutWidget(QWidget):
            def __init__(self, parent=None):
                super().__init__(parent)
                # data: list of (label, pct, color, value_inr)
                self._data: list[tuple[str, float, str, float]] = []
                self._total_label: str = ""
                self._hovered: int = -1  # index of hovered segment
                self.setFixedSize(168, 168)
                self.setMouseTracking(True)

            def set_data(self, data: list[tuple[str, float, str, float]], total_label: str):
                self._data = data
                self._total_label = total_label
                self._hovered = -1
                self.update()

            def _center(self) -> tuple[float, float]:
                return self.width() / 2.0, self.height() / 2.0

            def _ring_geometry(self) -> tuple[float, float, float, float]:
                # Keep enough inner/outer margin so hover strokes don't clip.
                base_radius = min(self.width(), self.height()) * 0.315
                hover_radius = base_radius + 2.0
                base_pen = 16.0
                hover_pen = 20.0
                return base_radius, hover_radius, base_pen, hover_pen

            def _angle_from_center(self, x: float, y: float) -> float:
                """Return angle in degrees 0-360 measured clockwise from 12 o'clock."""
                import math
                cx, cy = self._center()
                dx, dy = x - cx, y - cy
                # atan2 gives angle from +x axis; convert to clockwise from +y (12 o'clock)
                angle = math.degrees(math.atan2(dx, -dy)) % 360
                return angle

            def _segment_at(self, x: float, y: float) -> int:
                """Return segment index under (x,y), or -1 if not over the ring."""
                import math
                cx, cy = self._center()
                base_radius, hover_radius, base_pen, hover_pen = self._ring_geometry()
                dist = math.hypot(x - cx, y - cy)
                inner_radius = max(0.0, base_radius - (base_pen / 2.0) - 6.0)
                outer_radius = hover_radius + (hover_pen / 2.0) + 2.0
                if dist < inner_radius or dist > outer_radius:
                    return -1
                angle = self._angle_from_center(x, y)
                cum = 0.0
                for i, (label, pct, color, val) in enumerate(self._data):
                    cum += pct * 360 / 100
                    if angle < cum:
                        return i
                return -1

            def mouseMoveEvent(self, event):
                idx = self._segment_at(event.position().x(), event.position().y())
                if idx != self._hovered:
                    self._hovered = idx
                    self.update()

            def leaveEvent(self, event):
                self._hovered = -1
                self.update()

            def paintEvent(self, event):
                from PySide6.QtGui import QPainter, QColor, QPen, QFont
                from PySide6.QtCore import QRectF
                painter = QPainter(self)
                painter.setRenderHint(QPainter.Antialiasing)
                cx, cy = self._center()
                base_radius, hover_radius, base_pen, hover_pen = self._ring_geometry()
                rect = QRectF(cx - base_radius, cy - base_radius, base_radius * 2.0, base_radius * 2.0)
                rect_highlight = QRectF(
                    cx - hover_radius,
                    cy - hover_radius,
                    hover_radius * 2.0,
                    hover_radius * 2.0,
                )
                start_angle = 90 * 16
                total_pct = sum(d[1] for d in self._data)

                if total_pct <= 0:
                    painter.setPen(QPen(QColor("#e5e4df"), base_pen))
                    painter.drawArc(rect, 0, 360 * 16)
                else:
                    for i, (label, pct, color, val) in enumerate(self._data):
                        span = int((pct / 100.0) * 360 * 16)
                        is_hovered = (i == self._hovered)
                        c = QColor(color)
                        if is_hovered:
                            # Use larger rect + slightly brighter color + thicker stroke
                            c = c.lighter(115)
                            painter.setPen(QPen(c, hover_pen))
                            painter.drawArc(rect_highlight, start_angle, -span)
                        else:
                            alpha = 180 if self._hovered != -1 else 255  # dim non-hovered
                            c.setAlpha(alpha)
                            painter.setPen(QPen(c, base_pen))
                            painter.drawArc(rect, start_angle, -span)
                        start_angle -= span

                # Center text
                text_width = min(self.width() * 0.76, 130.0)
                text_x = cx - (text_width / 2.0)
                if self._hovered >= 0 and self._hovered < len(self._data):
                    label, pct, color, val = self._data[self._hovered]
                    from app import format_compact_inr as _fmt
                    painter.setPen(QColor(color))
                    f = QFont("Segoe UI", 7, QFont.Bold)
                    painter.setFont(f)
                    # Wrap long category names
                    painter.drawText(
                        QRectF(text_x, cy - 38.0, text_width, 20.0),
                        Qt.AlignCenter | Qt.TextWordWrap,
                        label,
                    )
                    painter.setPen(QColor("#22211f"))
                    f2 = QFont("Segoe UI", 8, QFont.Bold)
                    painter.setFont(f2)
                    painter.drawText(QRectF(text_x, cy - 16.0, text_width, 20.0), Qt.AlignCenter, _fmt(val))
                    painter.setPen(QColor("#6b6962"))
                    f3 = QFont("Segoe UI", 7)
                    painter.setFont(f3)
                    painter.drawText(QRectF(text_x, cy + 2.0, text_width, 18.0), Qt.AlignCenter, f"{pct:.0f}% of portfolio")
                else:
                    painter.setPen(QColor("#22211f"))
                    f = QFont("Segoe UI", 8, QFont.Bold)
                    painter.setFont(f)
                    painter.drawText(QRectF(text_x, cy - 20.0, text_width, 22.0), Qt.AlignCenter, self._total_label)
                    f2 = QFont("Segoe UI", 7)
                    painter.setFont(f2)
                    painter.setPen(QColor("#6b6962"))
                    painter.drawText(QRectF(text_x, cy - 2.0, text_width, 16.0), Qt.AlignCenter, "TOTAL (INR)")
                painter.end()

        self.dash_donut = DonutWidget()
        alloc_inner_hl.addWidget(self.dash_donut)

        self.dash_alloc_legend_layout = QVBoxLayout()
        self.dash_alloc_legend_layout.setSpacing(4)
        self.dash_alloc_legend_layout.addStretch()
        alloc_inner_hl.addLayout(self.dash_alloc_legend_layout, 1)

        # Don't add to bottom_hl here — added later in mid_hl

        alloc_vl.addLayout(alloc_inner_hl)
        alloc_vl.addStretch()

        # --- Top Holdings card ---
        holdings_card = QFrame()
        holdings_card.setObjectName("dashHoldCard")
        holdings_card.setStyleSheet(
            "QFrame#dashHoldCard { background: #ffffff; border: 1px solid #d9d8d3; border-radius: 12px; }"
        )
        holdings_vl = QVBoxLayout(holdings_card)
        holdings_vl.setContentsMargins(20, 16, 20, 16)
        holdings_vl.setSpacing(12)

        hold_header = QHBoxLayout()
        hold_title = QLabel("Top Holdings")
        hold_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #22211f;")
        hold_header.addWidget(hold_title)
        hold_header.addStretch()
        hold_view_all = QLabel("View all →")
        hold_view_all.setStyleSheet("font-size: 12px; color: #2b7a52;")
        hold_header.addWidget(hold_view_all)
        holdings_vl.addLayout(hold_header)

        self.dash_holdings_grid = QGridLayout()
        self.dash_holdings_grid.setSpacing(10)
        holdings_vl.addLayout(self.dash_holdings_grid)
        # holdings_card added to mid_hl below

        # --- Goals Tracking card ---
        goals_track_card = QFrame()
        goals_track_card.setObjectName("dashGoalsCard")
        goals_track_card.setStyleSheet(
            "QFrame#dashGoalsCard { background: #ffffff; border: 1px solid #d9d8d3; border-radius: 12px; }"
        )
        goals_vl = QVBoxLayout(goals_track_card)
        goals_vl.setContentsMargins(20, 16, 20, 16)
        goals_vl.setSpacing(10)

        goals_header = QHBoxLayout()
        goals_title = QLabel("Goals")
        goals_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #22211f;")
        goals_header.addWidget(goals_title)
        goals_header.addStretch()
        goals_manage = QLabel("Manage →")
        goals_manage.setStyleSheet("font-size: 12px; color: #2b7a52;")
        goals_header.addWidget(goals_manage)
        goals_vl.addLayout(goals_header)

        self.dash_goals_vl = QVBoxLayout()
        self.dash_goals_vl.setSpacing(8)
        goals_vl.addLayout(self.dash_goals_vl)
        goals_vl.addStretch()

        root.addWidget(hero_card)

        # ── Row 2: Asset Allocation | Top Holdings (equal columns) ─────────
        mid_hl = QHBoxLayout()
        mid_hl.setSpacing(16)
        mid_hl.addWidget(alloc_card, 1)
        mid_hl.addWidget(holdings_card, 1)
        root.addLayout(mid_hl)

        # ── Row 3: Goals (same width as Asset Allocation = left half) ──────
        goals_hl = QHBoxLayout()
        goals_hl.setSpacing(16)
        goals_hl.addWidget(goals_track_card, 1)
        goals_hl.addStretch(1)  # mirror the right column gap
        root.addLayout(goals_hl)

        root.addStretch()



        scroll.setWidget(container)
        return scroll

    def _refresh_dashboard_view(self) -> None:
        """Populate all dynamic labels in the Dashboard page from live DB data."""
        # Guard: dashboard widgets may not exist yet during first call
        if not hasattr(self, "dash_nw_value"):
            return

        from db import fetch_goals  # local import (may not exist if goals not seeded)

        assets = fetch_assets()
        liabilities = fetch_liabilities()
        snapshots = fetch_net_worth_snapshots(limit=10)
        exchange_rates: dict[str, float] = fetch_exchange_rates()  # already dict[str, float]

        # ── Compute totals ──────────────────────────────────────────────
        def to_inr(value: float, currency: str) -> float:
            rate = exchange_rates.get(normalize_currency(currency), 1.0)
            return value * rate

        total_assets_inr = sum(to_inr(float(a["value"]), a["currency"]) for a in assets)
        total_invested_inr = sum(to_inr(float(a["invested"]), a["currency"]) for a in assets)
        total_liab_inr = sum(to_inr(float(lb["outstanding_amount"]), lb["currency"]) for lb in liabilities)
        net_worth_inr = total_assets_inr - total_liab_inr
        pnl_pct = calculate_change_pct(total_invested_inr, total_assets_inr)

        asset_count = len(assets)
        liab_count = len(liabilities)

        # ── Net Worth card ──────────────────────────────────────────────
        self.dash_nw_value.setText(format_compact_inr(net_worth_inr))

        # Delta vs last snapshot
        if len(snapshots) >= 2:
            latest = float(snapshots[0]["net_worth_inr"])
            prev = float(snapshots[1]["net_worth_inr"])
            delta = latest - prev
            delta_pct = (delta / prev * 100) if prev != 0 else 0
            sign = "+" if delta >= 0 else ""
            color = "#2b7a52" if delta >= 0 else "#c23b31"
            self.dash_nw_delta.setText(
                f"{sign}{format_compact_inr(delta)} ({sign}{delta_pct:.1f}%) vs last snapshot"
            )
            self.dash_nw_delta.setStyleSheet(f"font-size: 12px; color: {color};")
        elif len(snapshots) == 1:
            self.dash_nw_delta.setText("No previous snapshot to compare")
            self.dash_nw_delta.setStyleSheet("font-size: 12px; color: #6b6962;")
        else:
            self.dash_nw_delta.setText("No snapshots recorded yet")
            self.dash_nw_delta.setStyleSheet("font-size: 12px; color: #6b6962;")

        # ── Sparkline ───────────────────────────────────────────────────
        self.dash_spark_series.clear()
        snap_list = list(reversed(snapshots))  # oldest → newest
        if len(snap_list) >= 2:
            for i, s in enumerate(snap_list):
                self.dash_spark_series.append(float(i), float(s["net_worth_inr"]))
            self.dash_spark_chart.createDefaultAxes()
            for axis in self.dash_spark_chart.axes():
                axis.setVisible(False)
        elif len(snap_list) == 1:
            # Single point – flat line
            v = float(snap_list[0]["net_worth_inr"])
            self.dash_spark_series.append(0, v)
            self.dash_spark_series.append(1, v)

        # ── Mini tiles ─────────────────────────────────────────────────
        self.dash_assets_value.setText(format_compact_inr(total_assets_inr))
        self.dash_assets_sub.setText(f"{asset_count_label(asset_count)}")

        self.dash_liab_value.setText(format_compact_inr(total_liab_inr))
        active_loans = sum(1 for lb in liabilities if float(lb["outstanding_amount"] or 0) > 0)
        self.dash_liab_sub.setText(f"{active_loans} active loan{'s' if active_loans != 1 else ''}")

        self.dash_inv_value.setText(format_compact_inr(total_invested_inr))
        pnl_sign = "+" if pnl_pct >= 0 else ""
        self.dash_inv_sub.setText(f"{pnl_sign}{pnl_pct:.1f}% ({pnl_sign}{format_compact_inr(total_assets_inr - total_invested_inr)})")

        # ── Health Score: multi-factor model (0–10) ────────────────────
        # Factor 1: Net Worth Ratio  (net worth / assets)  → max 2 pts
        if total_assets_inr > 0:
            nw_ratio = net_worth_inr / total_assets_inr  # 1.0 = no debt
            f1 = min(2.0, max(0.0, nw_ratio * 2.0))
            f1_note = f"Net worth / assets = {nw_ratio*100:.0f}%"
        else:
            f1 = 0.0
            f1_note = "No assets recorded"

        # Factor 2: Diversification  (number of distinct categories)  → max 2 pts
        cat_keys_present: set[str] = set()
        for a in assets:
            ck = a["class_key"]
            cl2 = self.class_lookup.get(ck)
            try:
                cat_keys_present.add(cl2["category_key"] if cl2 else "OTHER")
            except (KeyError, IndexError):
                cat_keys_present.add("OTHER")
        num_cats = len(cat_keys_present)
        f2 = min(2.0, num_cats * 0.5)
        f2_note = f"{num_cats} asset categor{'y' if num_cats == 1 else 'ies'} held"

        # Factor 3: Debt-to-Assets (lower is better)  → max 2 pts
        if total_assets_inr > 0:
            dta = total_liab_inr / total_assets_inr
            f3 = min(2.0, max(0.0, (1.0 - dta) * 2.0))
            f3_note = f"Debt-to-assets = {dta*100:.0f}%"
        else:
            f3 = 2.0 if total_liab_inr == 0 else 0.0
            f3_note = "No assets to compare debt against"

        # Factor 4: Returns (P&L %)  → max 2 pts
        if pnl_pct >= 15:
            f4 = 2.0
        elif pnl_pct >= 5:
            f4 = 1.0 + (pnl_pct - 5) / 10.0
        elif pnl_pct >= 0:
            f4 = pnl_pct / 5.0
        else:
            f4 = max(0.0, 1.0 + pnl_pct / 10.0)
        f4 = round(min(2.0, max(0.0, f4)), 2)
        f4_note = f"Portfolio P&L = {pnl_pct:+.1f}%"

        # Factor 5: Asset base (at least ≥ 3 assets = good habit)  → max 2 pts
        f5 = min(2.0, asset_count * 0.4)
        f5_note = f"{asset_count} asset{'s' if asset_count != 1 else ''} tracked"

        hs = round(f1 + f2 + f3 + f4 + f5, 1)

        if hs >= 8:
            hs_label = "Excellent 🏆"
        elif hs >= 6:
            hs_label = "Good shape"
        elif hs >= 4:
            hs_label = "Fair"
        else:
            hs_label = "Needs attention"

        self.dash_health_value.setText(f"{hs:.1f}/10")
        self.dash_health_sub.setText(hs_label)

        # Update tooltip breakdown
        if hasattr(self, "_health_tooltip_body"):
            breakdown = (
                f"① Net worth ratio:   {f1:.1f}/2  — {f1_note}\n"
                f"② Diversification:    {f2:.1f}/2  — {f2_note}\n"
                f"③ Debt-to-assets:    {f3:.1f}/2  — {f3_note}\n"
                f"④ Portfolio returns: {f4:.1f}/2  — {f4_note}\n"
                f"⑤ Asset breadth:     {f5:.1f}/2  — {f5_note}"
            )
            self._health_tooltip_body.setText(breakdown)
            self._health_tooltip_body.setMinimumWidth(340)



        # ── Asset Allocation donut ──────────────────────────────────────
        CATEGORY_COLORS: dict[str, str] = {
            "REAL_ESTATE": "#b5860a",
            "DEBT": "#2b7a52",
            "EQUITY": "#256d46",
            "GOLD_SILVER": "#c49a0a",
            "CRYPTO": "#5b6dcd",
            "CASH": "#4a90d9",
            "INSURANCE": "#8e8680",
            "ALTERNATIVES": "#9c6b9e",
            "OTHER_COMMODITIES": "#c2784f",
        }

        cat_totals: dict[str, float] = {}
        for a in assets:
            class_key = a["class_key"]
            # find category for this class via class_lookup (sqlite3.Row)
            cl = self.class_lookup.get(class_key)  # dict key lookup is fine
            try:
                cat_key = cl["category_key"] if cl is not None else "OTHER"
            except (IndexError, KeyError):
                cat_key = "OTHER"
            val_inr = to_inr(float(a["value"]), a["currency"])
            cat_totals[cat_key] = cat_totals.get(cat_key, 0.0) + val_inr

        sorted_cats = sorted(cat_totals.items(), key=lambda x: x[1], reverse=True)
        donut_data: list[tuple[str, float, str]] = []
        for cat_key, val in sorted_cats:
            pct = (val / total_assets_inr * 100) if total_assets_inr > 0 else 0
            cat_name = self.category_lookup.get(cat_key, cat_key.replace("_", " ").title())
            color = CATEGORY_COLORS.get(cat_key, "#aaa")
            donut_data.append((cat_name, pct, color, val))  # include raw value for hover

        self.dash_donut.set_data(donut_data, format_compact_inr(total_assets_inr))

        # Rebuild legend
        for i in reversed(range(self.dash_alloc_legend_layout.count())):
            item = self.dash_alloc_legend_layout.itemAt(i)
            if item and item.widget():
                item.widget().setParent(None)

        for cat_name, pct, color, _val in donut_data:
            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(6)

            dot = QLabel("●")
            dot.setStyleSheet(f"color: {color}; font-size: 14px;")
            row_l.addWidget(dot)

            name_lbl = QLabel(cat_name)
            name_lbl.setStyleSheet("font-size: 12px; color: #3a3936;")
            row_l.addWidget(name_lbl)
            row_l.addStretch()

            pct_lbl = QLabel(f"{pct:.0f}%")
            pct_lbl.setStyleSheet("font-size: 12px; font-weight: 700; color: #22211f;")
            row_l.addWidget(pct_lbl)

            self.dash_alloc_legend_layout.addWidget(row_w)

        self.dash_alloc_legend_layout.addStretch()

        # ── Top Holdings ────────────────────────────────────────────────
        # Clear previous
        for i in reversed(range(self.dash_holdings_grid.count())):
            item = self.dash_holdings_grid.itemAt(i)
            if item and item.widget():
                item.widget().setParent(None)

        sorted_assets = sorted(assets, key=lambda a: to_inr(float(a["value"]), a["currency"]), reverse=True)
        top4 = sorted_assets[:4]

        ASSET_CLASS_COLORS: dict[str, str] = {
            "REAL_ESTATE": "#f0e6c8",
            "STOCKS_EQUITY": "#d6ede2",
            "MUTUAL_FUNDS": "#d6ede2",
            "FD_RD": "#c8dff0",
            "BONDS": "#c8dff0",
            "DEBT_FUNDS": "#c8dff0",
            "GOLD_SILVER": "#f5ebc0",
            "CRYPTO": "#ddd4f5",
            "INTERNATIONAL": "#d6ede2",
        }
        ASSET_CLASS_TEXT_COLORS: dict[str, str] = {
            "REAL_ESTATE": "#7a5c0a",
            "STOCKS_EQUITY": "#1d5c3a",
            "MUTUAL_FUNDS": "#1d5c3a",
            "FD_RD": "#0a3d6b",
            "BONDS": "#0a3d6b",
            "DEBT_FUNDS": "#0a3d6b",
            "GOLD_SILVER": "#7a5c0a",
            "CRYPTO": "#3d1d7a",
            "INTERNATIONAL": "#1d5c3a",
        }

        for idx, asset in enumerate(top4):
            row = idx // 2
            col = idx % 2
            tile = QFrame()
            tile.setStyleSheet(
                "QFrame { background: #f9f9f7; border: 1px solid #e5e4df; border-radius: 10px; }"
            )
            tile.setFixedHeight(80)
            tl = QVBoxLayout(tile)
            tl.setContentsMargins(12, 10, 12, 10)
            tl.setSpacing(4)

            name_lbl = QLabel(asset["name"] or "–")
            name_lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #22211f; border: none;")
            name_lbl.setWordWrap(False)
            tl.addWidget(name_lbl)

            val_inr = to_inr(float(asset["value"]), asset["currency"])
            val_lbl = QLabel(format_compact_inr(val_inr))
            val_lbl.setStyleSheet("font-size: 16px; font-weight: 700; color: #22211f; border: none;")
            tl.addWidget(val_lbl)

            class_key = asset["class_key"] if "class_key" in asset.keys() else ""
            class_info = self.class_lookup.get(class_key)  # sqlite3.Row or None
            if class_info is not None:
                try:
                    class_label = class_info["class_name"]
                except (IndexError, KeyError):
                    class_label = class_key.replace("_", " ").title()
            else:
                class_label = class_key.replace("_", " ").title() if class_key else "–"
            badge_bg = ASSET_CLASS_COLORS.get(class_key, "#e8e7e3")
            badge_fg = ASSET_CLASS_TEXT_COLORS.get(class_key, "#5a5853")
            badge_lbl = QLabel(class_label)
            badge_lbl.setStyleSheet(
                f"font-size: 10px; font-weight: 600; color: {badge_fg};"
                f" background: {badge_bg}; border-radius: 4px; padding: 2px 6px; border: none;"
            )
            badge_lbl.setFixedHeight(18)
            tl.addWidget(badge_lbl)

            self.dash_holdings_grid.addWidget(tile, row, col)

        # ── Goals Tracking ─────────────────────────────────────────────
        for i in reversed(range(self.dash_goals_vl.count())):
            item = self.dash_goals_vl.itemAt(i)
            if item and item.widget():
                item.widget().setParent(None)

        try:
            from db import fetch_goals
            goals = fetch_goals()
        except Exception:
            goals = []

        if not goals:
            no_goals = QLabel("No goals yet. Create one in Goals →")
            no_goals.setStyleSheet("font-size: 12px; color: #6b6962;")
            self.dash_goals_vl.addWidget(no_goals)
        else:
            for goal in goals[:3]:  # show up to 3 goals
                g_frame = QFrame()
                g_frame.setStyleSheet(
                    "QFrame { background: transparent; border: none; }"
                )
                g_vl = QVBoxLayout(g_frame)
                g_vl.setContentsMargins(0, 0, 0, 0)
                g_vl.setSpacing(4)
                goal["tracking_label"] = self._goal_tracking_label(goal)
                metrics = self._calculate_goal_metrics(goal, assets)
                target_amt = metrics["target_amount"]
                current_savings = metrics["current_savings"]
                pct = metrics["progress_pct"]
                year_str = (goal["target_date"] or "")[:4]

                header_row = QHBoxLayout()
                g_name_lbl = QLabel(goal["name"])
                g_name_lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #22211f; border: none;")
                header_row.addWidget(g_name_lbl)
                header_row.addStretch()
                status = str(goal.get("status") or "ACTIVE").upper()
                suffix = " (Paused)" if status == "PAUSED" else (" (Achieved)" if status == "ACHIEVED" else "")
                target_lbl = QLabel(f"{format_compact_inr(target_amt)} by {year_str}{suffix}")
                target_lbl.setStyleSheet("font-size: 11px; color: #6b6962; border: none;")
                header_row.addWidget(target_lbl)
                g_vl.addLayout(header_row)

                # Progress bar
                bar_bg = QFrame()
                bar_bg.setFixedHeight(6)
                bar_bg.setStyleSheet("background: #e5e4df; border-radius: 3px; border: none;")
                bar_fill = QFrame(bar_bg)
                bar_fill.setFixedHeight(6)
                bar_fill.setStyleSheet("background: #2b7a52; border-radius: 3px; border: none;")
                bar_fill.setFixedWidth(max(0, int(pct / 100 * 340)))
                g_vl.addWidget(bar_bg)

                pct_lbl = QLabel(f"{int(pct)}% complete   {format_compact_inr(current_savings)} of {format_compact_inr(target_amt)}")
                pct_lbl.setStyleSheet("font-size: 11px; color: #6b6962; border: none;")
                pct_lbl.setWordWrap(True)
                g_vl.addWidget(pct_lbl)

                self.dash_goals_vl.addWidget(g_frame)

                # Thin divider between goals
                if goal != goals[min(2, len(goals) - 1)]:
                    div = QFrame()
                    div.setFrameShape(QFrame.HLine)
                    div.setStyleSheet("color: #e5e4df;")
                    self.dash_goals_vl.addWidget(div)


def run() -> None:
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))

    init_db()
    settings = fetch_user_settings()
    auto_login = bool(
        is_auth_registered(settings)
        and settings
        and int(settings["keep_logged_in"] or 0) == 1
        and int(settings["logged_in"] or 0) == 1
    )

    if not auto_login:
        auth_dialog = AuthDialog()
        if auth_dialog.exec() != QDialog.Accepted:
            return

    window = PortfolioWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()
