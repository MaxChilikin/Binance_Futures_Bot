import logging
import os
import re
from plotly import graph_objs as go
from plotly.offline import plot


def configure_logging():
    log = logging.getLogger('info')
    log.setLevel(level='INFO')
    log_2 = logging.getLogger('warns')
    log_2.setLevel(level='WARNING')

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
    log_2.addHandler(file_handler)

    file_path = os.path.join(os.path.dirname(__file__), 'orders.log')
    file_handler_2 = logging.FileHandler(
        filename=file_path,
        mode='a',
        encoding='utf8',
    )
    file_handler_2.setFormatter(logging.Formatter(
        fmt='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M'
    ))
    file_handler_2.setLevel(level='INFO')
    log.addHandler(file_handler_2)
    return log, log_2


def get_interval(interval):
    checker = re.compile('^([0-9]{1,2})([mhdwM])$')
    result = re.match(checker, interval)
    int_interval = [int(result[1]), result[2]]
    return int_interval


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
