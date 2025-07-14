import csv
import os





def get_instrument_key_by_trading_symbol(file_path, trading_symbol_input):
        print("🔍 Raw input symbol:", trading_symbol_input)

        if not os.path.exists(file_path):
            print("❌ CSV file not found at path:", file_path)
            return "CSV file not found."

        input_symbol = trading_symbol_input.replace(" ", "").upper()
        print("🔍 Normalized input symbol:", input_symbol)

        try:
            with open(file_path, newline='') as csvfile:
                reader = csv.DictReader(csvfile)
                row_count = 0
                for row in reader:
                    row_count += 1
                    symbol_in_file = row.get('tradingsymbol')
                    if symbol_in_file == input_symbol:
                        print("✅ Match found:", symbol_in_file)
                        return row.get('instrument_key')
            print(f"Checked {row_count} rows.")
        except Exception as e:
            print("❌ Error reading CSV:", str(e))
            return "CSV read error."

        print("❌ No match found after checking all entries.")
        return "Instrument key not found for given trading symbol."
    
    

file_path = r'C:\Users\PRATEEK SINGH\OneDrive\Desktop\option.py\trading\nse.csv'

trading_symbol = 'NIFTY27DEC30000CE' 
instrument_key = get_instrument_key_by_trading_symbol(file_path, trading_symbol)

print("Instrument Key:", instrument_key)