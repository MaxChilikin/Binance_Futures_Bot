import PySimpleGUI as sg


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

    def run(self, bot, window):
        bot.start()
        while True:
            event, values = window.read()
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
                        window['out'+sg.WRITE_ONLY_KEY].print(f"Order with id {order}:")
                        for k, v in params:
                            window['out'+sg.WRITE_ONLY_KEY].print(f"{k} ':' {v}")
                else:
                    window['out'+sg.WRITE_ONLY_KEY].print("\nNo orders yet\n")
            elif event == "Balance":
                window['out'+sg.WRITE_ONLY_KEY].print(f"\n{bot.get_account_data()}\n")
            else:
                window['out'+sg.WRITE_ONLY_KEY].print(values)
        bot.socket_manager.close()
        bot.join(timeout=5)
        window.close()

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
        multiline = sg.MLine(size=(105, 15), key="out"+sg.WRITE_ONLY_KEY)
        multiline.reroute_stdout_to_here()
        multiline.reroute_stderr_to_here()
        self.layout.append([multiline])

        window = sg.Window(
            title=self.title,
            layout=self.layout,
            default_button_element_size=(10, 2),
            size=(800, 500),
            element_padding=(10, 10),
            auto_size_buttons=False,
        )
        return window
