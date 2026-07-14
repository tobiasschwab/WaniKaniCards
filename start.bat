pip install -r requirements.txt
set WANIKANI_API_TOKEN=03c1d900-b11b-40b9-aae0-7a6434091e3f
set WEASYPRINT_DLL_DIRECTORIES=C:\msys64\mingw64\bin

#python kanji_cards.py 1 --type radicals --layout a6 -o radicals_a6_level1.pdf
python kanji_cards.py 1 --type kanji --layout a6 -o kanjis_a6_level1.pdf

# Druckeinstellungen 5-26
# Dialog verwenden -> Seite einrichten
# Benutzerdefiniertes Format 105*149, Querformat, Duplex (Längsseite heften Links)
# Nach der Hälfte für Duplex auf die Linke Seite drehen