from binance.client import Client
from time import time, sleep
from binance.websockets import BinanceSocketManager
from datetime import datetime
from strategy import Strategy
from utils import Order, configure_logging, to_string
from uuid import uuid1
from threading import Thread
from sys import exit
from Interface import Interface
from Models import Orders
try:
    from credentials import API_KEY, API_SECRET
except ImportError:
    API_KEY = API_SECRET = None
    exit("CAN'T RUN BOT WITHOUT API_KEY, API_SECRET FROM CREDENTIALS.PY")

log_warns = configure_logging()


class BinanceTrader(Thread):

    ORDER_STATUS_NEW = 'NEW'
    ORDER_STATUS_PARTIALLY_FILLED = 'PARTIALLY_FILLED'
    ORDER_STATUS_FILLED = 'FILLED'
    ORDER_STATUS_REJECTED = 'REJECTED'
    ORDER_STATUS_CANCELED = 'CANCELED'
    ORDER_STATUS_EXPIRED = 'EXPIRED'

    KLINE_INTERVALS = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w', '1M']

    def __init__(self, symbol: str, interval: str, leverage: int, api_key: str, api_secret: str, ui, test: bool,
                 tracker: float, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.symbol = symbol
        self.interval = interval
        self.leverage = leverage
        self.tracker = tracker
        self.balance = {}
        self.ohlc = []
        self.long, self.short = False, False
        self.time_offset = 500
        self.precision = None
        self.ui = ui
        self.test = test

        self.orders = Orders
        self.api_key = api_key
        self.api_secret = api_secret
        self.client = Client(self.api_key, self.api_secret)
        self.socket_manager, self.kline_socket_key = None, None

    def run(self):
        self.get_exchange_info()
        klines = self.get_klines(interval=self.interval)
        self.get_account_balance()
        strategy = Strategy(klines=klines, symbol=self.symbol, leverage=self.leverage, quantity=self.get_quantity)
        self.start_kline_stream()
        sleep(5)
        while True:
            sleep(0.25)
            time_check = strategy.timer()
            if time_check:
                self.ui.main_window.write_event_value(
                    key="Klines",
                    value=f"Time: {datetime.utcnow()} - Close: {self.ohlc[4]} - High: {self.ohlc[2]} - "
                          f"Low: {self.ohlc[3]}"
                )
                sleep(2)
                signals = strategy.check(on_long=self.long, on_short=self.short, ohlc=self.ohlc)
                if signals:
                    for signal in signals:
                        self.place_order(order=signal, test=self.test)
            sl = strategy.stoploss(ohlc=self.ohlc, on_long=self.long, on_short=self.short, tracker=self.tracker)
            if sl:
                self.place_order(order=sl, test=self.test)

    def start_kline_stream(self):
        try:
            self.socket_manager = BinanceSocketManager(client=self.client, user_timeout=60)
            self.kline_socket_key = self.socket_manager.start_kline_socket(symbol=self.symbol, interval=self.interval,
                                                                           callback=self.callback)
            if self.kline_socket_key:
                self.socket_manager.start()
            else:
                raise ConnectionError(f"Kline key is missing: {self.kline_socket_key}")
        except Exception as exc:
            log_warns.exception(exc)
            return {'msg': exc}

    def restart_stream(self, manager, socket_key):
        try:
            manager.stop_socket(conn_key=socket_key)
        except Exception as exc:
            log_warns.exception(exc)
        if socket_key == self.kline_socket_key:
            self.kline_socket_key = self.socket_manager.start_kline_socket(symbol=self.symbol, interval=self.interval,
                                                                           callback=self.callback)

    def check_order(self, order: Order):
        try:
            order_info = self.client.futures_get_order(
                symbol=self.symbol,
                timestamp=int(round(time()) * 1000) + self.time_offset,
                recvWindow=5000,
                origClientOrderId=order.id,
            )
        except Exception as exc:
            log_warns.exception(exc)
            return "Order does not exist"
        order.update(params=order_info)
        return order_info

    def get_klines(self, interval: str, limit: int = 500):
        """
        Gets trading info for symbol with required intervals

        :param interval: constant from KLINE_INTERVALS list
        :param limit: required amount of klines
        :return: list(list(ohlc_values), ..)
        """
        try:
            data = self.client.futures_klines(symbol=self.symbol,
                                              interval=interval,
                                              limit=limit)
        except Exception as exc:
            log_warns.exception(exc)
            return {'msg': exc}
        return data

    def get_exchange_info(self):
        """
        Gets all symbols exchange info and returns minimum price change value, sets up precision for price and qty

        :return: Decimal
        """
        ticksize = None
        try:
            data = self.client.futures_exchange_info()
        except Exception as exc:
            log_warns.exception(exc)
            return {'msg': exc}
        for symbol in data['symbols']:
            if symbol['symbol'] == self.symbol:
                self.precision = [symbol['pricePrecision'], symbol['quantityPrecision']]
                for filter_ in symbol['filters']:
                    if filter_['filterType'] == 'PRICE_FILTER':
                        ticksize = filter_['tickSize']
        return ticksize

    def get_account_information(self):
        """
        Gets account information, including balance and position

        :rtype: dict
        """
        try:
            info = self.client.futures_account(timestamp=int(round(time()) * 1000) + self.time_offset,
                                               recvWindow=5000)
        except Exception as exc:
            log_warns.exception(exc)
            return {'msg': exc}
        sorted_info = {}
        for key, value in info.items():
            if key == 'assets':
                for asset in info[key]:
                    if float(asset['walletBalance']) > 0:
                        sorted_info[asset['asset']] = asset
                        self.balance[asset['asset']] = asset['walletBalance']
            elif key == 'positions':
                for pos in info[key]:
                    if float(pos['positionAmt']) > 0 or float(pos['positionAmt']) < 0:
                        sorted_info[pos['symbol']] = pos
            else:
                sorted_info.setdefault(key, value)
        return sorted_info

    def get_account_balance(self):
        """
        Gets balance for every asset

        :rtype: dict(asset=balance, asset2= ...)
        """
        account_balance = {}
        try:
            balance = self.client.futures_account_balance(timestamp=int(round(time()) * 1000) + self.time_offset,
                                                          recvWindow=5000)
        except Exception as exc:
            log_warns.exception(exc)
            return {'msg': exc}
        for asset in balance:
            account_balance[asset['asset']] = asset['balance']
        self.balance = account_balance
        return balance

    def get_position(self):
        """
        Gets position for self.symbol

        :rtype: list
        """
        try:
            positions = self.client.futures_position_information(
                symbol=self.symbol,
                timestamp=int(round(time()) * 1000) + self.time_offset,
                recvWindow=5000
            )
        except Exception as exc:
            log_warns.exception('Position info pull failed %s ', exc)
            return {'msg': exc}
        return positions

    def get_quantity(self, leverage: int, open_position: bool = True):
        """
        Counts quantity using required leverage and account balance

        :param leverage: leverage to trade with
        :param open_position: True if order will open position, False otherwise
        :return: float
        """
        quantity = 0.0
        if self.ohlc:
            if open_position:
                self.get_account_balance()
                main_asset = float(self.balance["USDT"])
                close = float(self.ohlc[4])
                quantity = (leverage + 1) * main_asset / close
            else:
                positions = self.get_position()
                for position in positions:
                    if position["symbol"] == self.symbol:
                        quantity = abs(float(position["positionAmt"]))
        return quantity

    def place_order(self, order: Order, **kwargs):
        """
        Places an order with mandatory parameters:
        symbol str: trading symbol
        side str:   BUY or SELL
        type str:   types:                           additional mandatory parameters:
                    LIMIT	                       | timeInForce, quantity, price
                    MARKET	                       | quantity
                    STOP/TAKE_PROFIT	           | quantity, price, stopPrice
                    STOP_MARKET/TAKE_PROFIT_MARKET | stopPrice
                    TRAILING_STOP_MARKET	       | callbackRate
        """
        order.id, order.db = str(uuid1()), self.orders

        params = dict(
            **order.params,
            **kwargs,
            recvWindow=5000,
            timestamp=int(round(time()) * 1000) + self.time_offset,
            newClientOrderId=order.id,
        )
        if type == 'LIMIT':
            params['timeInForce'] = 'GTC'
        additional = ['price', 'stopPrice', 'activationPrice', 'quantity']
        for param, value in params.items():
            if param in additional:
                if param == 'quantity':
                    precision = self.precision[1]
                else:
                    precision = self.precision[0]
                params[param] = to_string(value=value, precision=precision)
        order.params = params
        order.time = datetime.utcnow()

        self.ui.main_window.write_event_value(key="Order", value=f"Placing order with params: {params}")
        try:
            self.client.futures_create_order(**params)
        except Exception as exc:
            log_warns.exception(exc)
            order.failed = True
            order.to_db()
            self.ui.main_window.write_event_value(key="Order", value=f"Failed placing order {order.id}")
            return {'msg': exc}

        self.long, self.short = order.long, order.short
        order.to_db()

    def close_positions(self):
        positions = self.get_position()
        for position in positions:
            pos_quantity = float(position["positionAmt"])
            if pos_quantity > 0:
                side = "SELL"
            elif pos_quantity < 0:
                side = "BUY"
            else:
                continue
            order = Order(
                params=dict(
                    side=side,
                    type='MARKET',
                    symbol=self.symbol,
                    quantity=abs(pos_quantity)
                ),
                long=False,
                short=False
            )
            self.place_order(order=order)

    def close_order(self, order: Order):
        try:
            order_info = self.client.futures_cancel_order(
                symbol=self.symbol,
                timestamp=int(round(time()) * 1000) + self.time_offset,
                recvWindow=5000,
                origClientOrderId=order.id,
            )
        except Exception as exc:
            log_warns.exception('Order cancel failed %s ', exc)
            return {'msg': exc}
        order.update(params=dict(**order_info, closed=True))
        return "closed"

    def order_update(self, response):
        """
        Updates order using self.user_data_stream (executionReport event) response
        """
        try:
            order = self.orders.get(self.orders.id == response['C'])
        except Exception as exc:
            log_warns.exception(exc)
            return {'msg': exc}
        if response['X'] == self.ORDER_STATUS_NEW:
            return
        else:
            order.status = response['X']
        if order.status == self.ORDER_STATUS_FILLED or order.status == self.ORDER_STATUS_PARTIALLY_FILLED:
            order.update(params=response, status=order.status)
        elif order.status == self.ORDER_STATUS_REJECTED:
            order.update(params=response, status=order.status)
        elif order.status == self.ORDER_STATUS_CANCELED or order.status == self.ORDER_STATUS_EXPIRED:
            order.delete()

    def callback(self, msg):
        """
        Handles messages from kline/candlestick websocket
        """
        kline_info = msg['k']
        self.ohlc = [kline_info['t'], kline_info['o'], kline_info['h'], kline_info['l'], kline_info['c']]


def main():
    symbol, interval, leverage, tracker, test = 'BTCUSDT', '5m', 7, 0.005, False
    ui = Interface()
    ui.start_window()
    bot = BinanceTrader(
        symbol=symbol,
        interval=interval,
        leverage=leverage,
        tracker=tracker,
        test=test,
        api_key=API_KEY,
        api_secret=API_SECRET,
        ui=ui,
        daemon=True
    )
    ui.run(bot=bot)


if __name__ == '__main__':
    main()
