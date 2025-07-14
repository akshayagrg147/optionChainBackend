import json

def get_instrument_key_by_trading_symbol(file_path, trading_symbol_input):
    with open(file_path, 'r') as file:
        data = json.load(file)

    for instrument in data:
        symbol_in_file = instrument.get('trading_symbol', '').replace(" ", "").upper()
        input_symbol = trading_symbol_input.replace(" ", "").upper()

        if symbol_in_file == input_symbol:
            return instrument.get('instrument_key')

    return "Instrument key not found for given trading symbol."



file_path = r'C:\Users\PRATEEK SINGH\OneDrive\Desktop\option.py\trading\nse.json'

trading_symbol = 'JPYINR61CE27MAR26'  # Input symbol without spaces
instrument_key = get_instrument_key_by_trading_symbol(file_path, trading_symbol)

print("Instrument Key:", instrument_key)
