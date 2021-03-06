import PySimpleGUI as sg
from twisted.internet import reactor


class Interface:

    def __init__(self):
        self.title = 'Binance Futures Bot'
        self.theme = 'DarkAmber'
        self.options = {
            "Stop": "Close all connections and terminate bot",
            "Orders": "Show all session trade orders and their parameters",
            "Balance": "Show amount of every asset on account",
        }
        self.layout = list()
        self.main_window = None

    def run(self, bot):
        bot.start()
        while True:
            event, values = self.main_window.read()
            if event == sg.WIN_CLOSED:
                break
            elif event == "Stop":
                popup = self.popup_window(
                    text="Want close opened orders?",
                    title="Bot",
                    options=["Yes", "No"]
                )
                pop_event, pop_value = popup.read()
                if pop_event == "Yes":
                    for order_id, order in bot.orders.items():
                        bot.close_order(order_id=order_id)
                elif pop_event == "No":
                    pass
                popup.close()
                break
            elif event == "Orders":
                if bot.orders:
                    for order, params in bot.orders:
                        self.main_window[self.ml_key].print(f"Order with id {order}:")
                        for k, v in params:
                            self.main_window[self.ml_key].print(f"{k} ':' {v}")
                else:
                    self.main_window[self.ml_key].print("\nNo orders yet\n")
            elif event == "Balance":
                self.main_window[self.ml_key].print(f"\n{bot.get_account_data()}\n")
            else:
                self.main_window[self.ml_key].print(values)
        bot.socket_manager.close()
        bot.join(timeout=5)
        reactor.stop()
        self.main_window.close()

    @property
    def ml_key(self):
        return "out" + sg.WRITE_ONLY_KEY

    def popup_window(self, text, title, options):
        sg.theme(self.theme)
        layout = [[sg.Text(text=text)], [sg.Button(button_text=option) for option in options]]

        size = 60 * len(layout)
        popup = sg.Window(
            title=title,
            layout=layout,
            default_button_element_size=(10, 2),
            size=(size * 2, size),
            element_padding=(10, 10),
            auto_size_buttons=False,
        )
        return popup

    def start_window(self):
        sg.theme(self.theme)

        for option, desc in self.options.items():
            self.layout.append([sg.Button(button_text=option), sg.Text(text=desc)])
        multiline = sg.MLine(size=(105, 15), key=self.ml_key)
        self.layout.append([multiline])

        window = sg.Window(
            title=self.title,
            layout=self.layout,
            default_button_element_size=(10, 2),
            size=(800, 500),
            element_padding=(10, 10),
            auto_size_buttons=False,
        )
        self.main_window = window
