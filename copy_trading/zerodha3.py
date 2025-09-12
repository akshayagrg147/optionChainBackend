from kiteconnect import KiteConnect

kite = KiteConnect(api_key="a44a8d2b1l25cwq4")
# Open login URL
print(kite.login_url())
# After login, get request_token from redirect URL
data = kite.generate_session("Gnkdp8TIPbDYRNoktBEoVx7zBv4p9nHU", api_secret="ij9jt934zw4bjmgo943vm5p2ksbtbyhy")
access_token = data["access_token"]
print("Access token:", access_token)