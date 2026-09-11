# Praca lokalna i aplikacja desktopowa

Ten dokument opisuje główny, lokalny tryb pracy PicSyncra: aplikację desktopową uruchamianą na komputerze operatora.

## Działanie

W interfejsie wpisujesz nazwę, typ, model, kolory, dodatek i opcjonalny EAN produktu. Do formularza można przeciągać zdjęcia metodą drag-and-drop. Po zatwierdzeniu:

1. Pliki są kopiowane do katalogu `_ZDJECIA PRZEROBIONE_` i układane według struktury `NAZWA/TYP/MODEL/KOLOR1_KOLOR2_KOLOR3/DODATEK`.
2. Zdjęcia są optymalizowane, opcjonalnie skalowane, kompresowane, konwertowane i otrzymują ustrukturyzowaną nazwę zaczynającą się od `EAN_slot...`.
3. Jeżeli `enable_ftp_update` jest włączone, nowe pliki są wysyłane na FTP, a stare wersje o tym samym EAN mogą zostać usunięte.
4. Jeżeli `enable_sql_update` jest włączone, wykonywane jest zapytanie SQL aktualizujące ścieżki obrazów w bazie `sql` albo `mysql`.

Działania programu są zapisywane w `logs/changes_log.txt`, a błędy w `logs/error_log.txt`. Przy pierwszym uruchomieniu tworzony jest plik `config.json` z ustawieniami połączeń.

## Funkcje

- Formularz produktu z listami podpowiedzi dla nazwy, typu, modelu, kolorów i dodatków opartymi o plik Excel.
- Edytor list i pytania o dodanie brakujących wartości.
- Konfigurowalne pola produktu w ustawieniach desktopowych i webowych: nazwa, widoczność i wymaganie ośmiu pól.
- Opcjonalny EAN 13-cyfrowy z fallbackiem `BRAK-EAN`.
- Szybkie wczytywanie wpisów po EAN i skrót do otwarcia katalogu produktu.
- Sloty zdjęć z miniaturami, przenoszeniem zdjęć między slotami, statusem oraz oznaczeniami LOCAL/FTP/SQL.
- Automatyczna organizacja plików w `_ZDJECIA PRZEROBIONE_`.
- Skalowanie do maksymalnego wymiaru, kompresja jakości, limit maksymalnego rozmiaru pliku i opcjonalna konwersja TIFF.
- FTP: test połączenia, wysyłka nowych zdjęć, usuwanie starych wersji, sprawdzanie obecności i pobieranie brakujących plików.
- SQL: test połączenia, parametryzowane zapytanie aktualizujące, sprawdzanie obecności per slot, wykrywanie kolumn i mapowanie drag-and-drop.
- Konfigurowalne pola zdjęć z mapowaniem SQL i podpowiedziami tłumaczeń.
- Przełączanie języka interfejsu: `auto`, `pl`, `ua`, `eng`.
- Diagnostyka kodu/UI, testy błędów i log w aplikacji.

## Konfiguracja lokalna

Aplikacja zapisuje pliki robocze w katalogu zdefiniowanym w `local_settings.json`, znajdującym się obok `PicSyncra.pyw`. Plik tworzy się automatycznie przy pierwszym uruchomieniu. Jeżeli nie zawiera ścieżki, aplikacja poprosi o wskazanie folderu i zapisze wybór.

W ścieżkach na Windows można używać ukośników, np. `C:/TEST/GUI_ZDJ`, aby uniknąć podwójnego wpisywania ukośników odwrotnych. Jeżeli zapisany katalog stanie się niedostępny, aplikacja poprosi o wybór nowej lokalizacji.

Najważniejsze ustawienia:

- `base_dir_override` w `local_settings.json` - katalog startowy do zapisu danych.
- `language` w `local_settings.json` - preferowany język interfejsu.
- `APP_SECRET` - klucz szyfrowania danych konfiguracyjnych.
- `PORT` - domyślny port FTP.
- `SQL_UPDATE_TEMPLATE` - domyślne zapytanie SQL aktualizujące ścieżkę zdjęcia.
- `DEFAULT_CONFIG` - początkowe dane logowania FTP/SQL/MySQL oraz domyślne przełączniki integracji.

Sekcje `ftp`, `sql` i `mysql` zawierają odpowiednio pola `host` albo `server`, `port`, `user`, `pass` oraz `path` dla FTP. Pozostałe ważne klucze to `db_type`, `sql_query`, `enable_ftp_update` i `enable_sql_update`.

## Uruchomienie

```powershell
python PicSyncra.pyw
```

Wariant Qt slotów:

```powershell
python PicSyncra-QtSlots.pyw
```

## Zrzuty ekranu

<img width="1920" height="1040" alt="PicSyncra desktop" src="https://github.com/user-attachments/assets/8d2f9c31-1103-4368-bea2-7b6899d92761" />

<img width="1082" height="812" alt="Widok formularza" src="https://github.com/user-attachments/assets/48f3f87e-b4bd-402b-bcbf-16d5a160ed0d" />

<img width="838" height="419" alt="Widok ustawień" src="https://github.com/user-attachments/assets/f5ff136e-213e-4a43-baca-518905c447c6" />

<img width="1080" height="780" alt="Widok aplikacji" src="https://github.com/user-attachments/assets/953f09d3-e6f2-4c14-96a0-7193689fe16a" />

<img width="1082" height="812" alt="PicSyncra desktop" src="https://github.com/user-attachments/assets/0b5cbd68-d42e-49ed-b912-7542d6f965b8" />

<img width="842" height="417" alt="Widok ustawień" src="https://github.com/user-attachments/assets/4ee9558d-6ebf-4d57-84fc-004e2d2c9c8e" />
