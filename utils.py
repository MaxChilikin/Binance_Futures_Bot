import logging
import os
import re
import pandas as pd
import decimal
from plotly import graph_objs as go
from plotly.offline import plot


class Order:

    def __init__(self, params: dict, id_: str = None, long: bool = False, short: bool = False, time: str = None,
                 failed: bool = False, db=None):
        """

        :param id_: orderId or newClientOrderId
        :param params: parameters that will be sent to the server (or received from it)
        :param long: True if order will change market position to long, False otherwise
        :param short: True if order will change market position to short, False otherwise
        :param time: departure time in UTC
        :param db: DataBase
        """
        self.id = id_
        self.params = params
        self.long = long
        self.short = short
        self.time = time
        self.failed = failed
        self.status = "NEW"
        self.db = db

    def to_db(self):
        self.db.create(id=self.id, params=self.params, long=self.long, short=self.short, time=self.time,
                       failed=self.failed, status=self.status)

    def update(self, **kwargs):
        self.db.update(kwargs).where(self.db.id == self.id).execute()

    def delete(self):
        to_del = self.db.get(self.db.id == self.id)
        to_del.delete_instance()


def configure_logging():
    log = logging.getLogger('warns')
    log.setLevel(level='WARNING')

    file_path = os.path.join(os.path.dirname(__file__), 'botwarns.log')
    file_handler = logging.FileHandler(
        filename=file_path,
        mode='a',
        encoding='utf8',
    )
    file_handler.setFormatter(logging.Formatter(
        fmt='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M'
    ))
    file_handler.setLevel(level='WARNING')
    log.addHandler(file_handler)

    return log


def get_interval(interval):
    checker = re.compile('^([0-9]{1,2})([mhdwM])$')
    result = re.match(checker, interval)
    int_interval = [int(result[1]), result[2]]
    return int_interval


def to_dataframe(data):
    df = pd.DataFrame.from_records(data)
    df = df.drop(range(5, 12), axis=1)
    col_names = ['time', 'open', 'high', 'low', 'close']
    df.columns = col_names
    for col in col_names:
        df[col] = df[col].astype(float)
    df['date'] = pd.to_datetime(df['time'] * 1000000, infer_datetime_format=True)
    return df


def to_string(value, precision):
    context = decimal.Context()
    context.prec = 12
    new_value = round(context.create_decimal(repr(value)), precision)
    return format(new_value, "f")


def plot_data(df, symbol, graphs=None):
    candle = go.Candlestick(
        x=df['date'],
        open=df['open'],
        close=df['close'],
        high=df['high'],
        low=df['low'],
        name="Candlesticks")
    data = [candle]

    if graphs:
        for graph in graphs:
            if graph['dot']:
                dot = go.Scatter(
                    x=[i[0] for i in graph['values']],
                    y=[i[1] for i in graph['values']],
                    name=graph['name'],
                    mode='markers',
                    marker={'color': graph['color'], 'size': 10},
                )
                data.append(dot)
            else:
                line = go.Scatter(
                    x=df['date'],
                    y=graph['values'],
                    name=graph['name'],
                    line={'color': graph['color']}
                )
                data.append(line)

    layout = go.Layout(
        title=symbol,
        xaxis={"title": symbol, "rangeslider": {"visible": False}, "type": "date"},
        yaxis={"fixedrange": False}
    )

    fig = go.Figure(data=data, layout=layout)
    plot(fig, filename=symbol + '.html')
