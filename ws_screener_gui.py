import sys
import asyncio
import aiohttp
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QLabel, QHBoxLayout, QTabWidget, QHeaderView, QPushButton
)
from PyQt5.QtCore import QTimer, Qt, QUrl
from datetime import datetime
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWidgets import QDialog
import os
import webbrowser

SPOT_WS_URL = "wss://stream.bybit.com/v5/public/spot"
SPOT_SYMBOLS_URL = "https://api.bybit.com/v5/market/instruments-info?category=spot"
FUT_WS_URL = "wss://stream.bybit.com/v5/public/linear"
FUT_SYMBOLS_URL = "https://api.bybit.com/v5/market/instruments-info?category=linear"

# Индексы колонок с числами для сортировки
NUMERIC_COLS_ALL = {2, 3, 4, 5, 6, 7}
NUMERIC_COLS_SPOT = {1, 2, 3, 4}
NUMERIC_COLS_FUT = {1, 2, 3, 4, 5, 6, 7}

COLUMNS_ALL = [
    "Тикер", "Тип", "Последняя цена", "% за 24ч", "Объём 24ч", "Оборот 24ч", "Mark Price", "Index Price", "Открытый интерес"
]
COLUMNS_SPOT = [
    "Тикер", "Последняя цена", "% за 24ч", "Объём 24ч", "Оборот 24ч"
]
COLUMNS_FUT = [
    "Тикер", "Последняя цена", "% за 24ч", "Объём 24ч", "Оборот 24ч", "Mark Price", "Index Price", "Открытый интерес"
]

COLUMN_KEYS_ALL = [
    'symbol', 'type', 'lastPrice', 'price24hPcnt', 'volume24h', 'turnover24h', 'markPrice', 'indexPrice', 'openInterestValue'
]
COLUMN_KEYS_SPOT = [
    'symbol', 'lastPrice', 'price24hPcnt', 'volume24h', 'turnover24h'
]
COLUMN_KEYS_FUT = [
    'symbol', 'lastPrice', 'price24hPcnt', 'volume24h', 'turnover24h', 'markPrice', 'indexPrice', 'openInterestValue'
]

def format_ts(ts):
    return datetime.utcfromtimestamp(ts / 1000).strftime('%H:%M:%S') if ts else ''

def format_percent(val):
    try:
        return f"{float(val) * 100:.2f}%"
    except Exception:
        return val

def format_money(val):
    try:
        return f"{float(val):,.2f}".replace(",", " ")
    except Exception:
        return val

def get_tradingview_symbol(symbol, type_):
    if type_ == 'futures':
        return f"BYBIT:{symbol}.P"
    else:
        return f"BYBIT:{symbol}"

class CustomHeader(QHeaderView):
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.setSectionsClickable(True)
        self.setHighlightSections(False)
    def paintSection(self, painter, rect, logicalIndex):
        from PyQt5.QtGui import QBrush
        from PyQt5.QtCore import QRect
        painter.save()
        painter.fillRect(rect, QBrush(QColor(35, 38, 41)))
        painter.setPen(QColor(224, 224, 224))
        text = self.model().headerData(logicalIndex, self.orientation(), Qt.DisplayRole)
        painter.drawText(rect, Qt.AlignCenter, str(text))
        painter.restore()

class ChartDialog(QDialog):
    def __init__(self, tv_symbol, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"График {tv_symbol}")
        self.resize(400, 150)
        layout = QVBoxLayout(self)
        label = QLabel(f"График будет открыт во внешнем браузере:\n{tv_symbol}")
        layout.addWidget(label)
        btn = QPushButton("Открыть график в браузере")
        btn.setStyleSheet("""
            QPushButton {
                background-color: #444;
                color: #fff;
                font-weight: bold;
                font-size: 16px;
                border-radius: 6px;
                padding: 10px 20px;
                margin-top: 20px;
            }
            QPushButton:hover {
                background-color: #666;
            }
        """)
        layout.addWidget(btn)
        url = f"https://www.tradingview.com/chart/?symbol={tv_symbol}"
        btn.clicked.connect(lambda: webbrowser.open(url))

class ScreenerTab(QWidget):
    def __init__(self, columns, column_keys, numeric_cols):
        super().__init__()
        self.table = QTableWidget(0, len(columns))
        # Заменяем стандартный заголовок на кастомный
        self.table.setHorizontalHeader(CustomHeader(Qt.Horizontal, self.table))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.setSortingEnabled(False)  # Отключаем сортировку Qt полностью
        self.table.setSelectionMode(QTableWidget.NoSelection)  # Полностью убираем выделение
        self.table.verticalHeader().setVisible(False)  # Скрываем нумерацию строк
        layout = QVBoxLayout()
        layout.addWidget(self.table)
        self.setLayout(layout)
        self.column_keys = column_keys
        self.numeric_cols = numeric_cols
        self.current_sort_col = None  # None — сортировки нет
        self.current_sort_order = Qt.DescendingOrder
        self.sorted_symbols = []  # Фиксируется только по клику
        self.data_cache = {}  # symbol -> data dict
        self.table.horizontalHeader().sectionClicked.connect(self.handle_sort)
        self._last_symbols = []  # для сохранения порядка без сортировки
        self.table.horizontalHeader().setFocusPolicy(Qt.NoFocus)  # Отключаем фокус у заголовка
        self.table.cellClicked.connect(self.handle_cell_click)

    def handle_cell_click(self, row, col):
        if self.column_keys[col] == 'symbol':
            symbol = self.table.item(row, col).text()
            # Определяем тип тикера (spot/futures) из строки
            type_col = self.column_keys.index('type') if 'type' in self.column_keys else None
            type_ = self.table.item(row, type_col).text() if type_col is not None else 'spot'
            tv_symbol = get_tradingview_symbol(symbol, type_)
            dlg = ChartDialog(tv_symbol, self)
            dlg.exec_()

    def update_data(self, data_cache):
        # Только обновляем значения, не сбрасываем порядок строк
        self.data_cache = data_cache.copy()
        self.refresh_table()

    def refresh_table(self):
        # Если сортировка выбрана — фиксируем порядок только по клику
        if self.current_sort_col is not None and self.sorted_symbols:
            pass
        else:
            # Добавляем новые тикеры в конец
            for k in self.data_cache.keys():
                if k not in self._last_symbols:
                    self._last_symbols.append(k)
            # Удаляем исчезнувшие тикеры
            self._last_symbols = [k for k in self._last_symbols if k in self.data_cache]
            self.sorted_symbols = self._last_symbols.copy()
        self.table.setRowCount(len(self.sorted_symbols))
        for row, symbol in enumerate(self.sorted_symbols):
            d = self.data_cache.get(symbol, {})
            for col, key in enumerate(self.column_keys):
                value = d.get(key, '')
                # Форматируем только для отображения
                if key == 'price24hPcnt' and value not in ('', None):
                    try:
                        percent = float(value) * 100
                        value = f"{percent:.2f}%"
                    except Exception:
                        pass
                elif key == 'turnover24h' and value not in ('', None):
                    try:
                        value = f"{float(value):,.2f}".replace(",", " ")
                    except Exception:
                        pass
                elif key in ('markPrice', 'indexPrice', 'lastPrice') and value not in ('', None):
                    try:
                        value = f"{float(value):.6f}" if float(value) < 100 else f"{float(value):.2f}"
                    except Exception:
                        pass
                elif key == 'openInterestValue' and value not in ('', None):
                    try:
                        value = f"{float(value):,.2f}".replace(",", " ")
                    except Exception:
                        pass
                item = QTableWidgetItem(str(value))
                if col in self.numeric_cols:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                # Цвет процентов
                if key == 'price24hPcnt' and d.get(key, '') not in ('', None):
                    try:
                        percent = float(d.get(key, '')) * 100
                        if percent > 0:
                            item.setForeground(QColor(0, 200, 0))
                        elif percent < 0:
                            item.setForeground(QColor(220, 40, 40))
                    except Exception:
                        pass
                self.table.setItem(row, col, item)

    def handle_sort(self, col):
        if self.current_sort_col == col:
            self.current_sort_order = Qt.AscendingOrder if self.current_sort_order == Qt.DescendingOrder else Qt.DescendingOrder
        else:
            self.current_sort_col = col
            self.current_sort_order = Qt.DescendingOrder
        # Фиксируем порядок строк только по клику
        self.sorted_symbols = self.get_sorted_symbols(self.current_sort_col, self.current_sort_order)
        self.refresh_table()
        self.table.horizontalHeader().clearFocus()  # Сброс фокуса с заголовка
        self.table.clearFocus()  # Сброс фокуса с таблицы

    def get_sorted_symbols(self, col, order):
        key = self.column_keys[col]
        def sort_key(symbol):
            d = self.data_cache.get(symbol, {})
            val = d.get(key, '')
            # Сортируем только по "сырым" числовым значениям (без форматирования)
            if col in self.numeric_cols:
                try:
                    val = str(val).replace('%', '').replace(' ', '')
                    return float(val)
                except Exception:
                    return float('-inf') if order == Qt.DescendingOrder else float('inf')
            return val
        # После сортировки фиксируем порядок до следующего клика
        return sorted(self.data_cache.keys(), key=sort_key, reverse=(order == Qt.DescendingOrder))

class SpotFuturesScreener(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bybit Скринер (Спот и Фьючерсы, WebSocket, Mainnet)")
        self.setGeometry(100, 100, 1600, 800)
        self.tabs = QTabWidget()
        self.tab_all = ScreenerTab(COLUMNS_ALL, COLUMN_KEYS_ALL, NUMERIC_COLS_ALL)
        self.tab_spot = ScreenerTab(COLUMNS_SPOT, COLUMN_KEYS_SPOT, NUMERIC_COLS_SPOT)
        self.tab_fut = ScreenerTab(COLUMNS_FUT, COLUMN_KEYS_FUT, NUMERIC_COLS_FUT)
        self.tabs.addTab(self.tab_all, "Все")
        self.tabs.addTab(self.tab_spot, "Спот")
        self.tabs.addTab(self.tab_fut, "Фьючерсы")
        self.time_label = QLabel("Время брокера: --:--:--")
        self.time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top_layout = QHBoxLayout()
        top_layout.addStretch(1)
        top_layout.addWidget(self.time_label)
        main_layout = QVBoxLayout()
        main_layout.addLayout(top_layout)
        main_layout.addWidget(self.tabs)
        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)
        self.loop = asyncio.get_event_loop()
        self.ws_timer = QTimer()
        self.ws_timer.timeout.connect(self.process_events)
        self.ws_timer.start(100)
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_tables)
        self.refresh_timer.start(1000)
        self.loop.create_task(self.start_ws())
        self.last_broker_ts = None
        self.data_spot = {}  # symbol -> dict
        self.data_fut = {}   # symbol -> dict
        self.spot_symbols = []
        self.fut_symbols = []

    def process_events(self):
        self.loop.call_soon(self.loop.stop)
        self.loop.run_forever()

    async def get_symbols(self, url):
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                return [x['symbol'] for x in data['result']['list']]

    async def start_ws(self):
        self.spot_symbols = await self.get_symbols(SPOT_SYMBOLS_URL)
        self.fut_symbols = await self.get_symbols(FUT_SYMBOLS_URL)
        # Инициализация data_spot для всех тикеров с пустыми значениями
        for symbol in self.spot_symbols:
            self.data_spot[symbol] = {
                'symbol': symbol,
                'lastPrice': '',
                'price24hPcnt': '',
                'volume24h': '',
                'turnover24h': '',
                'highPrice24h': '',
                'lowPrice24h': '',
            }
        # Инициализация data_fut для всех тикеров с пустыми значениями
        for symbol in self.fut_symbols:
            self.data_fut[symbol] = {
                'symbol': symbol,
                'lastPrice': '',
                'price24hPcnt': '',
                'volume24h': '',
                'turnover24h': '',
                'markPrice': '',
                'indexPrice': '',
                'openInterestValue': '',
            }
        self.loop.create_task(self.ws_spot(self.spot_symbols))
        self.loop.create_task(self.ws_fut(self.fut_symbols))

    async def ws_spot(self, symbols):
        batch_size = 10
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(SPOT_WS_URL) as ws:
                for i in range(0, len(symbols), batch_size):
                    sub_msg = {
                        "op": "subscribe",
                        "args": [f"tickers.{s}" for s in symbols[i:i+batch_size]]
                    }
                    await ws.send_json(sub_msg)
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        self.handle_ws_msg(msg.json(), is_spot=True)
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        break

    async def ws_fut(self, symbols):
        batch_size = 10
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(FUT_WS_URL) as ws:
                for i in range(0, len(symbols), batch_size):
                    sub_msg = {
                        "op": "subscribe",
                        "args": [f"tickers.{s}" for s in symbols[i:i+batch_size]]
                    }
                    await ws.send_json(sub_msg)
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        self.handle_ws_msg(msg.json(), is_spot=False)
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        break

    def handle_ws_msg(self, msg, is_spot):
        if 'data' not in msg or 'topic' not in msg:
            return
        data = msg['data']
        symbol = data.get('symbol')
        if not symbol:
            return
        if is_spot:
            spot = self.data_spot.get(symbol)
            if spot is not None:
                for key in ['lastPrice', 'price24hPcnt', 'volume24h', 'turnover24h', 'highPrice24h', 'lowPrice24h']:
                    new_val = data.get(key)
                    if new_val not in (None, ''):
                        spot[key] = new_val
        else:
            fut = self.data_fut.get(symbol)
            if fut is not None:
                for key in ['lastPrice', 'price24hPcnt', 'volume24h', 'turnover24h', 'markPrice', 'indexPrice', 'openInterestValue']:
                    new_val = data.get(key)
                    if new_val not in (None, ''):
                        fut[key] = new_val
        if 'ts' in msg:
            self.last_broker_ts = msg['ts']
            self.time_label.setText(f"Время брокера: {format_ts(self.last_broker_ts)}")

    def refresh_tables(self):
        # Объединяем оба словаря для вкладки 'Все', добавляем поле 'type', всегда все тикеры
        all_data = {}
        for symbol in self.spot_symbols:
            d = self.data_spot.get(symbol, {})
            all_data[symbol + '_spot'] = {
                'symbol': d.get('symbol', symbol),
                'type': 'spot',
                'lastPrice': d.get('lastPrice', ''),
                'price24hPcnt': d.get('price24hPcnt', ''),
                'volume24h': d.get('volume24h', ''),
                'turnover24h': d.get('turnover24h', ''),
                'highPrice24h': '',
                'lowPrice24h': '',
                'markPrice': '',
                'indexPrice': '',
                'openInterestValue': '',
            }
        for symbol in self.fut_symbols:
            d = self.data_fut.get(symbol, {})
            all_data[symbol + '_fut'] = {
                'symbol': d.get('symbol', symbol),
                'type': 'futures',
                'lastPrice': d.get('lastPrice', ''),
                'price24hPcnt': d.get('price24hPcnt', ''),
                'volume24h': d.get('volume24h', ''),
                'turnover24h': d.get('turnover24h', ''),
                'highPrice24h': '',
                'lowPrice24h': '',
                'markPrice': d.get('markPrice', ''),
                'indexPrice': d.get('indexPrice', ''),
                'openInterestValue': d.get('openInterestValue', ''),
            }
        self.tab_all.update_data(all_data)
        self.tab_spot.update_data(self.data_spot)
        self.tab_fut.update_data(self.data_fut)

def set_dark_theme(app):
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.Window, QColor(35, 38, 41))
    dark_palette.setColor(QPalette.WindowText, QColor(224, 224, 224))
    dark_palette.setColor(QPalette.Base, QColor(35, 38, 41))
    dark_palette.setColor(QPalette.AlternateBase, QColor(44, 47, 51))
    dark_palette.setColor(QPalette.ToolTipBase, QColor(224, 224, 224))
    dark_palette.setColor(QPalette.ToolTipText, QColor(224, 224, 224))
    dark_palette.setColor(QPalette.Text, QColor(224, 224, 224))
    dark_palette.setColor(QPalette.Button, QColor(44, 47, 51))
    dark_palette.setColor(QPalette.ButtonText, QColor(224, 224, 224))
    dark_palette.setColor(QPalette.BrightText, QColor(255, 0, 0))
    dark_palette.setColor(QPalette.Highlight, QColor(35, 38, 41))  # тот же цвет, что и фон
    dark_palette.setColor(QPalette.HighlightedText, QColor(224, 224, 224))
    app.setPalette(dark_palette)
    # Глобальный стиль для всех виджетов, вкладок и рамок
    app.setStyleSheet("""
        QWidget, QMainWindow, QTabWidget, QTabBar, QTableWidget, QScrollArea {
            background-color: #232629;
            color: #e0e0e0;
            border: none;
        }
        QHeaderView::section:checked,
        QHeaderView::section:pressed,
        QHeaderView::section:focus,
        QHeaderView::section:!active,
        QHeaderView::section {
            background: #232629;
            color: #e0e0e0;
            border: none;
        }
        QTabBar::tab {
            background: #232629;
            color: #e0e0e0;
            border: 1px solid #444;
            padding: 6px 16px;
        }
        QTabBar::tab:selected {
            background: #444;
            color: #fff;
        }
        QTabBar::tab:!selected {
            background: #232629;
            color: #b0b0b0;
        }
        QTabWidget::pane {
            border: none;
            background: #232629;
        }
        QScrollBar:vertical, QScrollBar:horizontal {
            background: #232629;
            border: none;
        }
        QTableCornerButton::section {
            background: #232629;
            border: none;
        }
        QTableWidget::item:selected, QTableView::item:selected {
            background: transparent;
            color: inherit;
        }
    """)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    set_dark_theme(app)
    window = SpotFuturesScreener()
    window.show()
    sys.exit(app.exec_()) 