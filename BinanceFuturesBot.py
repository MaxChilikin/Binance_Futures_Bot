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
from decimal import Decimal
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
                 *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.symbol = symbol
        self.interval = interval
        self.leverage = leverage
        self.balance = {}
        self.ohlc = []
        self.test = test
        self.long = False
        self.short = False
        self.time_offset = 500
        self.precision = None
        self.ui = ui

        self.orders = Orders
        self.api_key = api_key
        self.api_secret = api_secret
        self.client = Client(self.api_key, self.api_secret)
        self.socket_manager, self.user_socket_manager = None, None
        self.kline_socket_key, self.user_socket_key = None, None

    def run(self):
        ticksize = self.get_exchange_info()
        klines = self.get_klines(interval=self.interval)
        self.get_account_data()
        strategy = Strategy(klines=klines, symbol=self.symbol, leverage=self.leverage, quantity=self.get_quantity)
        self.start_streams()
        sleep(5)
        while True:
            sleep(0.25)
            utc_time = datetime.utcnow()
            time_check = strategy.timer(time=utc_time)
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
            sl = strategy.stoploss(ohlc=self.ohlc, ticksize=ticksize, on_long=self.long, on_short=self.short)
            if sl:
                self.place_order(order=sl, test=self.test)
            if utc_time.minute % 50 == 0 and utc_time.second == 0:
                self.tackle()

    def tackle(self):
        """ Checks streams """
        import requests
        import json
        url = 'https://api.binance.com/api/v3/userDataStream'
        headers = {"X-MBX-APIKEY": self.api_key}
        params = {"listenKey": self.user_socket_key}
        try:
            response = requests.put(url, params=params, headers=headers)
            data = json.loads(response.text)
            data['url'] = url
        except Exception as exc:
            data = {'code': '-1', 'url': url, 'msg': exc}
        self.ui.main_window.write_event_value(key="user_stream_check", value=data)
        kline_stream_check = self.socket_manager.is_alive()
        self.ui.main_window.write_event_value(key="kline_stream_check", value=kline_stream_check)

    def start_streams(self):
        try:
            self.socket_manager = BinanceSocketManager(client=self.client, user_timeout=60)
            self.user_socket_manager = BinanceSocketManager(client=self.client, user_timeout=60)
            self.kline_socket_key = self.socket_manager.start_kline_socket(symbol=self.symbol, interval=self.interval,
                                                                           callback=self.callback)
            self.user_socket_key = self.user_socket_manager.start_user_socket(callback=self.user_data_callback)
            if self.kline_socket_key and self.user_socket_key:
                self.socket_manager.start()
                self.user_socket_manager.start()
            else:
                raise ConnectionError(f"One of the following keys is missing: User socket key {self.user_socket_key},"
                                      f" Klines socket key {self.kline_socket_key}")
        except Exception as exc:
            log_warns.exception(exc)
            return {'msg': exc}

    def restart_stream(self, socket_key, manager):
        try:
            manager.stop_socket(conn_key=socket_key)
        except Exception as exc:
            log_warns.exception(exc)
        if socket_key == self.user_socket_key:
            self.user_socket_key = self.user_socket_manager.start_user_socket(callback=self.user_data_callback)
        elif socket_key == self.kline_socket_key:
            self.kline_socket_key = self.socket_manager.start_kline_socket(symbol=self.symbol, interval=self.interval,
                                                                           callback=self.callback)

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

    def get_account_data(self):
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

    def get_quantity(self, leverage: int):
        """
        Counts quantity using required leverage and account balance

        :param leverage: leverage to trade with
        :return: float
        """
        if self.ohlc:
            # TODO MORE CONVENIENT? >
            main_asset = Decimal(self.balance['USDT'])
            coin = round(Decimal(self.balance['BAT']), self.precision[1])
            close = Decimal(self.ohlc[4])
            if coin and coin > 0.0:
                quantity = coin
            else:
                quantity = (leverage + 1) * main_asset / close
        else:
            quantity = 0.0
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
        additional = ['price', 'stopPrice', 'quantity']
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

    def close_orders(self):
        try:
            self.client.futures_cancel_all_open_orders(
                symbol=self.symbol,
                timestamp=int(round(time()) * 1000) + self.time_offset,
                recvWindow=5000
            )
        except Exception as exc:
            log_warns.exception('Order cancel failed %s ', exc)
            return {'msg': exc}

    def order_update(self, response):
        """
        Gets order status from server and repeats it if rejected
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

    def check_profit_loss(self):
        """
        Counts profit/loss based of filled/partially filled orders

        :return: float
        """
        bought = 0
        sold = 0
        all_orders = self.orders.select()
        if all_orders:
            for order in self.orders.select():
                if order.params['status'] and order.params['status'] == self.ORDER_STATUS_FILLED or \
                   order.params['status'] == self.ORDER_STATUS_PARTIALLY_FILLED:
                    if order.params['side'] == 'BUY':
                        bought += float(order.params['price']) * float(order.params['executedQty'])
                    if order.params['side'] == 'SELL':
                        sold += float(order.params['price']) * float(order.params['executedQty'])
            profits = sold - bought
            return round(profits, 2)

    def callback(self, msg):
        """
        Handles messages from kline/candlestick websocket
        """
        kline_info = msg['k']
        self.ohlc = [kline_info['t'], kline_info['o'], kline_info['h'], kline_info['l'], kline_info['c']]

    def user_data_callback(self, msg):
        """
        Handles messages from user data websocket
        """
        event_type = msg['e']
        self.ui.main_window.write_event_value(key="User_stream", value=msg)
        if event_type == "listenKeyExpired":
            self.restart_stream(socket_key=self.user_socket_key, manager=self.user_socket_manager)
        elif event_type == "balanceUpdate":
            updated_asset = msg['a']
            self.balance[updated_asset] = Decimal(self.balance[updated_asset]) - Decimal(msg['d'])
        elif event_type == "outboundAccountPosition":
            balances_array = msg['B']  # list with dicts
            #   "B": [                          //Balances Array
            #     {
            #       "a": "ETH",                 //Asset
            #       "f": "10000.000000",        //Free
            #       "l": "0.000000"             //Locked
            #     }
            #   ]
        elif event_type == "MARGIN_CALL":
            # TODO DO SOMETHING? pre-liquidation event
            pass
        elif event_type == "executionReport":
            # TODO WORK WITH IT IF "balanceUpdate" AND "outboundAccountPosition" ARE GARBO
            self.order_update(response=msg)


def main():
    symbol, interval, leverage, test = 'BATUSDT', '5m', 7, False
    ui = Interface()
    ui.start_window()
    bot = BinanceTrader(
        symbol=symbol,
        interval=interval,
        leverage=leverage,
        test=test,
        api_key=API_KEY,
        api_secret=API_SECRET,
        ui=ui,
        daemon=True
    )
    ui.run(bot=bot)


if __name__ == '__main__':
    main()
