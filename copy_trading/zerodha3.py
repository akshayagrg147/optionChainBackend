from kiteconnect import KiteConnect

kite = KiteConnect(api_key="a44a8d2b1wq4&v=l25c3")
# Open login URL
print(kite.login_url())
# After login, get request_token from redirect URL
data = kite.generate_session("Teta8pbAJv70KW43YTZ5Gd7mi9OE3h5O", api_secret="ij9jt934zw4bjmgo943vm5p2ksbtbyhy")
access_token = data["access_token"]
print("Access token:", access_token)