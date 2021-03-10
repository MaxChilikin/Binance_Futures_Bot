Python 3.9

Install packages:
-pip install wheel
-pip install -r requirements.txt
-pip install D\path_to_Twisted.whl

Prepare your acc:
In order to use bot you will need binance api key and secret key that you can receive on platform in top right corner,
human icon -> API management
When you will get keys rename file "rename_as_credentials" and insert keys there

Finishing touch:
Then you will need to open BinanceFuturesBot, place symbol you want to trade in main() and choose quantity to trade with
If everything is fine you can remove log that write "info" level listings to not waste memory
Write me if you need help/Twisted.whl, I'll explain more

Highly recommend change this setting in regedit to prevent Binance timestamp exception:
HKLM\SYSTEM\CurrentControlSet\services\W32Time\TimeProviders\NtpClient
SpecialPollInterval > 3600 decimal or even less(this makes computer synch time every hour)
