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
        ticksize = self.get_exchange_info()
        klines = self.get_klines(interval=self.interval)
        self.get_account_balance()
        strategy = Strategy(klines=klines, symbol=self.symbol, leverage=self.leverage, quantity=self.get_quantity)
        self.start_stream()
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

    def tackle(self):
        """ Checks stream """
        kline_stream_check = self.socket_manager.is_alive()
        if kline_stream_check:
            msg = "Alive"
        else:
            msg = "Down"
        self.ui.main_window.write_event_value(key="kline_stream_check", value=msg)

    def start_stream(self):
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

    def restart_stream(self, socket_key, manager):
        try:
            manager.stop_socket(conn_key=socket_key)
        except Exception as exc:
            log_warns.exception(exc)
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

    def get_account_information(self):
        """
        Gets account information, including balance and position
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
                    if Decimal(asset['walletBalance']) > 0:
                        sorted_info[asset['asset']] = asset
                        self.balance[asset['asset']] = asset['walletBalance']
            elif key == 'positions':
                for pos in info[key]:
                    if Decimal(pos['positionAmt']) > 0 or Decimal(pos['positionAmt']) < 0:
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

    def get_quantity(self, leverage: int):
        """
        Counts quantity using required leverage and account balance

        :param leverage: leverage to trade with
        :return: float
        """
        if self.ohlc:
            self.get_account_balance()
            main_asset = float(self.balance['USDT'])
            close = float(self.ohlc[4])
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
        try:
            positions = self.client.futures_position_information(
                symbol=self.symbol,
                timestamp=int(round(time()) * 1000) + self.time_offset,
                recvWindow=5000
            )
        except Exception as exc:
            log_warns.exception('Position info pull failed %s ', exc)
            return {'msg': exc}
        for position in positions:
            pos_quantity = Decimal(position["positionAmt"])
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
                    quantity=position["positionAmt"]
                ),
                long=False,
                short=False
            )
            self.place_order(order=order)

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


def main():
    symbol, interval, leverage, test = 'BTCUSDT', '5m', 7, False
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
