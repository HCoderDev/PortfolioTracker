from __future__ import annotations

from datetime import datetime
import re
import sys
import unicodedata

from PySide6.QtCore import QDateTime, QEvent, QItemSelectionModel, QPoint, QSize, QTimer, Qt
from PySide6.QtCharts import QChart, QChartView, QDateTimeAxis, QLineSeries, QValueAxis
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
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QStackedWidget,
    QStyle,
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
    update_assets_class,
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


def format_percent(value: float) -> str:
    return f"{value:+.1f}%"


def calculate_change_pct(invested: float, value: float) -> float:
    if invested == 0:
        return 0.0
    return ((value - invested) / invested) * 100


def parse_amount(text: str) -> float:
    cleaned = text.strip().replace(",", "")
    return float(cleaned)


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


class PortfolioWindow(QMainWindow):
    ASSETS_PAGE_INDEX = 0
    LIABILITIES_PAGE_INDEX = 1
    NET_WORTH_PAGE_INDEX = 2
    ADD_ASSET_PAGE_INDEX = 3
    EDIT_ASSET_PAGE_INDEX = 4

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
                button.setProperty("active", item == "Assets")
                button.setCursor(Qt.PointingHandCursor)
                if item in {"Assets", "Liabilities", "Net Worth"}:
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

        user_label = QLabel("Hewitt Vijayan")
        user_label.setObjectName("userLabel")
        layout.addWidget(user_label)

        menu_button = QPushButton("v")
        menu_button.setObjectName("iconButton")
        menu_button.setCursor(Qt.PointingHandCursor)
        layout.addWidget(menu_button)
        return top

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
        add_liability_btn.setCursor(Qt.PointingHandCursor)
        add_liability_btn.clicked.connect(self._open_add_liability_dialog)
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
        layout = QVBoxLayout(panel)
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

        self.snapshot_history_scroll = QScrollArea()
        self.snapshot_history_scroll.setWidgetResizable(True)
        self.snapshot_history_scroll.setFrameShape(QFrame.NoFrame)
        self.snapshot_history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        history_layout.addWidget(self.snapshot_history_scroll)

        snapshot_history_content = QWidget()
        self.snapshot_history_scroll.setWidget(snapshot_history_content)
        self.snapshot_entries_layout = QVBoxLayout(snapshot_history_content)
        self.snapshot_entries_layout.setContentsMargins(0, 0, 0, 0)
        self.snapshot_entries_layout.setSpacing(10)

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
        bounded_height = max(72, min(280, total_height))
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

        axis_y = QValueAxis()
        min_y = min(y_values)
        max_y = max(y_values)
        if min_y == max_y:
            spread = max(abs(max_y), 1.0)
            min_y -= spread * 0.25
            max_y += spread * 0.25
        else:
            pad = (max_y - min_y) * 0.2
            min_y -= pad
            max_y += pad
        if min_y > 0:
            min_y = 0
        axis_y.setRange(min_y, max_y)
        axis_y.setTickCount(5)
        axis_y.setLabelFormat("%.0f")
        axis_y.setLabelsColor(QColor("#5b5953"))
        chart.addAxis(axis_y, Qt.AlignLeft)
        line_series.attachAxis(axis_y)

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

        self._clear_layout(self.snapshot_entries_layout)

        if not snapshots_desc:
            empty_text = QLabel("No snapshots yet. Take your first snapshot to start history.")
            empty_text.setObjectName("subTitle")
            self.snapshot_entries_layout.addWidget(empty_text)
            self.snapshot_entries_layout.addSpacerItem(
                QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding)
            )
            return

        valid_ids = {int(snapshot["id"]) for snapshot in snapshots_desc}
        self.expanded_snapshot_ids = {snapshot_id for snapshot_id in self.expanded_snapshot_ids if snapshot_id in valid_ids}
        if not self.expanded_snapshot_ids:
            self.expanded_snapshot_ids = {int(snapshots_desc[0]["id"])}

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

            card = QFrame()
            card.setObjectName("snapshotEntryCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(0, 0, 0, 0)
            card_layout.setSpacing(0)

            header = QFrame()
            header.setObjectName("snapshotEntryHeader")
            header_layout = QHBoxLayout(header)
            header_layout.setContentsMargins(12, 10, 12, 10)
            header_layout.setSpacing(10)

            toggle_button = QToolButton()
            toggle_button.setObjectName("snapshotToggle")
            toggle_button.setArrowType(Qt.DownArrow if snapshot_id in self.expanded_snapshot_ids else Qt.RightArrow)
            toggle_button.setCursor(Qt.PointingHandCursor)
            toggle_button.clicked.connect(
                lambda _checked=False, selected_snapshot_id=snapshot_id: self._toggle_snapshot_entry(selected_snapshot_id)
            )
            header_layout.addWidget(toggle_button)

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

            if has_previous:
                direction = "up" if delta >= 0 else "down"
                summary_label = QLabel(f"{format_signed_compact_inr(delta)}, {abs(pct):.1f}% {direction}")
                summary_label.setObjectName("snapshotEntryChangePositive" if delta >= 0 else "snapshotEntryChangeNegative")
            else:
                summary_label = QLabel("baseline")
                summary_label.setObjectName("snapshotEntryBaseline")
            header_layout.addWidget(summary_label)
            card_layout.addWidget(header)

            details = QFrame()
            details.setObjectName("snapshotEntryDetails")
            details_layout = QVBoxLayout(details)
            details_layout.setContentsMargins(12, 10, 12, 12)
            details_layout.setSpacing(8)

            if has_previous:
                previous_snapshot = snapshots_desc[row_idx + 1]
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
            self.snapshot_entries_layout.addWidget(card)

        self.snapshot_entries_layout.addSpacerItem(
            QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding)
        )

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


def run() -> None:
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    window = PortfolioWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()
