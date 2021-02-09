from binance.client import Client
import pandas as pd
import decimal
from time import time, sleep
from binance.websockets import BinanceSocketManager
from datetime import datetime
from strategy import strategy, stoploss
from utils import configure_logging, check_user_input
from uuid import uuid1
from threading import Thread
from credentials import API_KEY, API_SECRET

log, log_warns = configure_logging()[0], configure_logging()[1]
decimal.getcontext().prec = 12


class BinanceTrader(Thread):
    REQUEST_DELAY = 500

    ORDER_STATUS_NEW = 'NEW'
    ORDER_STATUS_PARTIALLY_FILLED = 'PARTIALLY_FILLED'
    ORDER_STATUS_FILLED = 'FILLED'
    ORDER_STATUS_REJECTED = 'REJECTED'
    ORDER_STATUS_CANCELED = 'CANCELED'
    ORDER_STATUS_EXPIRED = 'EXPIRED'

    KLINE_INTERVALS = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w', '1M']

    def __init__(self, symbol: str, api_key: str, api_secret: str, test: bool, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.symbol = symbol
        self.ohlc = []
        self.orders = {}
        self.test = test
        self.long = False
        self.short = False

        self.api_key = api_key
        self.api_secret = api_secret
        self.client = Client(self.api_key, self.api_secret)
        self.socket_manager = BinanceSocketManager(client=self.client, user_timeout=60)

    def run(self):
        ticksize = self.get_exchange_info()
        _, high, low, _, _ = strategy(symbol=self.symbol, klines=self.get_klines, on_long=self.long,
                                      on_short=self.short,
                                      quantity=self.get_quantity)
        self.socket_manager.start_kline_socket(symbol=self.symbol, callback=self.callback)
        self.socket_manager.start()
        sleep(5)
        while True:
            utc_time = datetime.utcnow()
            if utc_time.minute == 0 and utc_time.second == 0:
                sleep(2)
                signals, high, low, self.long, self.short = strategy(
                    symbol=self.symbol, klines=self.get_klines, on_long=self.long, on_short=self.short,
                    quantity=self.get_quantity
                )
                if signals:
                    for signal in signals:
                        self.place_order(**signal, test=self.test)
            sl, self.long, self.short = stoploss(ohlc=self.ohlc, ticksize=ticksize, symbol=self.symbol, high=high,
                                                 low=low,
                                                 on_long=self.long, on_short=self.short, quantity=self.get_quantity)
            if sl:
                self.place_order(**sl, test=self.test)
            if self.orders:
                if utc_time.minute % 10 == 0 and utc_time.second == 0:
                    sleep(2)
                    for order_id, order in self.orders.items():
                        self.check_order(order_id=order_id)

    def get_klines(self, interval: str, limit: int = 500):
        """
        Gets trading info for symbol with required intervals

        :param interval: constant from KLINE_INTERVALS list
        :param limit: required amount of klines
        :return: pd.DataFrame obj.
        """
        try:
            data = self.client.futures_klines(symbol=self.symbol,
                                              interval=interval,
                                              limit=limit)
        except Exception as exc:
            log_warns.exception(exc)
            return {'msg': exc}
        df = pd.DataFrame.from_records(data)
        df = df.drop(range(5, 12), axis=1)
        col_names = ['time', 'open', 'high', 'low', 'close']
        df.columns = col_names
        for col in col_names:
            df[col] = df[col].astype(float)
        df['date'] = pd.to_datetime(df['time'] * 1000000, infer_datetime_format=True)
        return df

    def get_exchange_info(self):
        """
        Gets all symbols exchange info and returns minimum price change value

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
            balance = self.client.futures_account_balance(timestamp=int(round(time()) * 1000) + self.REQUEST_DELAY)
        except Exception as exc:
            log_warns.exception(exc)
            return {'msg': exc}
        for asset in balance:
            account_balance[asset['asset']] = asset['balance']
        return account_balance

    def get_quantity(self, leverage: int):
        """
        Counts quantity using required leverage and account balance

        :param leverage: leverage to trade with
        :return: float
        """
        if self.ohlc:
            balance = self.get_account_data()
            close = self.ohlc[3]
            quantity = (leverage + 1) * float(balance['USDT']) / float(close)
        else:
            quantity = 0.0
        return quantity

    def place_order(self, **kwargs):
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
        order_id = str(uuid1())
        params = dict(
            **kwargs,
            recvWindow=5000,
            timestamp=int(round(time()) * 1000) + self.REQUEST_DELAY,
            newClientOrderId=order_id,
        )
        if type == 'LIMIT':
            params['timeInForce'] = 'GTC'
        additional = ['price', 'stopPrice']
        for param, value in params.items():
            if param in additional:
                params[param] = decimal.Decimal(value)
            elif param == 'quantity':
                params[param] = str(value)
        try:
            self.client.futures_create_order(**params)
        except Exception as exc:
            log_warns.exception(exc)
            return {'msg': exc}
        self.orders[order_id] = params
        t = datetime.utcnow()
        log.info(f"Order with id: %s , params %s , placed time: %s ", order_id, kwargs, t)

    def close_order(self, order_id):
        try:
            self.client.futures_cancel_order(
                symbol=self.symbol,
                origClientOrderId=order_id,
                timestamp=int(round(time()) * 1000) + self.REQUEST_DELAY
            )
        except Exception as exc:
            log_warns.exception('Order cancel failed %s ', exc)
            return {'msg': exc}

    def check_order(self, order_id):
        """
        Gets order status from server and repeats it if rejected
        """
        try:
            order = self.client.futures_get_order(symbol=self.symbol,
                                                  origClientOrderId=order_id,
                                                  timestamp=int(round(time())), )
            if order['status'] == self.ORDER_STATUS_NEW:
                pass
            elif order['status'] == self.ORDER_STATUS_FILLED or order['status'] == self.ORDER_STATUS_PARTIALLY_FILLED:
                self.orders[order_id] = dict(status=order['status'], type=order['origType'], price=order['price'],
                                             cumQty=order['cumQty'], side=order['side'])
            elif order['status'] == self.ORDER_STATUS_REJECTED:
                log.warning('ORDER REJECTED')
                self.place_order(**self.orders[order_id])
                del self.orders[order_id]
            elif order['status'] == self.ORDER_STATUS_CANCELED or order['status'] == self.ORDER_STATUS_EXPIRED:
                log.warning('ORDER CANCELED/EXPIRED')
                del self.orders[order_id]
            log.info(f"Check order with id: %s , params: %s ", order_id, order)
        except Exception as exc:
            log_warns.exception(exc)
            return {'msg': exc}

    def check_profit_loss(self):
        """
        Counts profit/loss based of filled/partially filled orders

        :return: Decimal
        """
        bought = 0
        sold = 0
        for order in self.orders.values():
            if order['status'] and order['status'] == self.ORDER_STATUS_FILLED or order['status'] == self.ORDER_STATUS_PARTIALLY_FILLED:
                if order['side'] == 'BUY':
                    bought = order['price'] * order['cumQty']
                if order['side'] == 'SELL':
                    sold = order['price'] * order['cumQty']
        profits = decimal.Decimal(sold - bought)
        return profits

    def save_orders(self):
        """
        Saves all unfilled orders

        :return: dict(order_id=dict(**order_parameters))
        """
        orders = {}
        for id_, order in self.orders.items():
            if not order['status']:
                orders.setdefault(id_, order)
        return orders

    def callback(self, msg):
        """
        Handles messages from websocket
        """
        kline_info = msg['k']
        self.ohlc = [kline_info['o'], kline_info['h'], kline_info['l'], kline_info['c']]
        print(f"Time: {time()} - Close: {kline_info['c']} - High: {kline_info['h']} - Low: {kline_info['l']}   ",
              flush=True)


def main():
    symbol = 'BTCUSDT'
    test = True
    bot = BinanceTrader(
        symbol=symbol,
        test=test,
        api_key=API_KEY,
        api_secret=API_SECRET,
    )
    bot.start()
    if check_user_input(bot=bot):
        bot.socket_manager.close()
        bot.join(timeout=5)
        print("STOP")


if __name__ == '__main__':
    main()
