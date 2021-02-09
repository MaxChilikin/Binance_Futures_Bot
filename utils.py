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


def check_user_input(bot):
    helper = "\nYou can type one of the following commands(or num):\n" \
             "1) 'stop' if you want to close all connections and terminate bot\n" \
             "2) 'orders' to see all session trade orders and their parameters\n" \
             "3) 'balance' to see amount of every asset on account\n" \
             "4) 'help' to see this message again\n"
    print(helper)
    while True:
        user_input = input()
        if user_input == 'stop' or user_input == '1':
            print("\nStopping bot")
            ask_user = input('\nWant close opened orders? (y/n?)\n')
            if ask_user == 'y':
                for order_id, order in bot.orders.items():
                    bot.close_order(order_id=order_id)
            break
        elif user_input == 'orders' or user_input == '2':
            if bot.orders:
                for order, params in bot.orders:
                    print(f"Order with id {order}:")
                    for k, v in params:
                        print(k, ':', v)
            else:
                print('\nNo orders yet\n')
        elif user_input == 'balance' or user_input == '3':
            print('\n', bot.get_account_data(), '\n')
        elif user_input == 'help' or user_input == '4':
            print(helper)
    return True


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
