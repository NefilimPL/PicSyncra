# Diagnostyka narastania RAM

W zwykłych wydaniach portable i instalowanych oraz przy uruchamianiu ze źródeł
raportowanie pamięci jest domyślnie wyłączone. Włącza je zmienna środowiskowa
`PICSYNCRA_MEMORY_REPORT=1`. Poprawki wycieków działają niezależnie od raportowania.
Zbieranie nie wymaga logowania do panelu ani otwartej przeglądarki. Raport jest
narzędziem diagnostycznym; sam nie dowodzi przyczyny wzrostu RAM.

Wcześniejsze testowe EXE `v0.5.6-ram-diagnostic-20261016` oraz
`v0.5.6-ram-fix-20261019` miały raportowanie domyślnie włączone. Zmiana ustawienia
domyślnego dotyczy kolejnych kompilacji.

## Zbieranie na urządzeniu testowym

1. Przed uruchomieniem ustaw `PICSYNCRA_MEMORY_REPORT=1` w środowisku procesu.
   Przykład dla portable w PowerShell:

   ```powershell
   $env:PICSYNCRA_MEMORY_REPORT = "1"
   .\PicSyncra-WEB.exe
   ```

   Uruchom nowy portable w osobnym katalogu. Zachowaj tę samą konfigurację,
   dane, ustawienia OCR i sposób używania co przy v0.5.5. Backendów porównywanych
   wersji nie uruchamiaj jednocześnie: konkurowałyby o RAM i port serwera.
2. Sprawdź, czy w `logs/memory` obok EXE pojawiają się pliki
   `memory-backend-<PID>-<czas>.jsonl` i, zależnie od uruchomionych funkcji,
   `memory-manager-…`, `memory-ocr-…` lub `memory-application-…`.
   W instalacji zarządzanej jest to `logs/memory` w katalogu stanu instalacji.
3. Pozostaw aplikację działającą jak wcześniej. Każdy proces zapisuje próbkę
   od razu, a następne co 60 sekund. Uśpienie komputera wstrzymuje zbieranie;
   po wznowieniu pozostanie naturalna przerwa w znacznikach czasu.
4. Gdy RAM wzrośnie, skopiuj cały katalog `logs/memory`, łącznie z plikami
   `.jsonl.1` i `.jsonl.2`, przed ponownym uruchomieniem programu. Pliki można
   kopiować podczas pracy: zapisywane są pojedyncze wiersze JSON. Jeżeli ostatni
   wiersz jest niepełny, pomiń go podczas analizy.

Usługa lub zadanie uruchomione wcześniej nie dziedziczy zmiennych z nowego okna
PowerShell. W instalacji zarządzanej zmienna musi być dostępna w środowisku
uruchamiającym właściwy backend; po jej ustawieniu uruchom go ponownie.

Raport pozostaje na tym komputerze; aplikacja go nie wysyła. Zawiera nazwy
plików kodu i bibliotek, PID-y, wersję aplikacji i Pythona, czasy oraz liczniki.
Nie zbiera zawartości obrazów, rozpoznanego tekstu, haseł, konfiguracji, argumentów
procesów ani pełnych ścieżek profilu użytkownika.

## Co oznaczają pomiary

- `processes`: bieżący proces oraz jego potomkowie, z osobnymi PID-ami i czasami
  utworzenia. `rss_bytes` to pamięć rezydentna; `private_bytes` na Windows to
  prywatna pamięć zadeklarowana, która może obejmować pamięć stronicowaną.
  `virtual_bytes` nie oznacza ilości zajętego fizycznego RAM. Uchwyty i wątki
  pozwalają zauważyć również wyciek tych zasobów. Nie sumuj RSS procesów jako
  dokładnej ilości fizycznego RAM: część stron jest współdzielona.
- `python_traced_bytes`, `python_peak_bytes`, `tracer_bytes`: bieżące i szczytowe
  alokacje śledzone przez Pythona oraz narzut metadanych śledzenia. Wzrost
  prywatnej pamięci przy stabilnych alokacjach Pythona wskazuje kierunek dalszej
  analizy bibliotek natywnych, buforów lub alokatora; sam nie dowodzi wycieku.
- `details.python.top_allocations`: 20 największych miejsc alokacji, z plikiem,
  linią, liczbą bloków i bajtami. `growth` pokazuje dodatnią zmianę względem
  poprzedniego szczegółowego pomiaru; pierwszy pomiar ma pustą bazę odniesienia.
  Porównywane są maksymalnie 4096 największych miejsc; ograniczenie jest oznaczone
  w raporcie, a nieznane wcześniejsze wartości nie są uznawane za przyrost.
- `details.memory_maps`: 20 największych mapowań pamięci bieżącego procesu,
  w zakresie danych dostępnych przez system. Biblioteki Paddle/NumPy/OpenCV
  mogą alokować pamięć poza śledzeniem Pythona. Lista mapowań nie przypisuje
  całego prywatnego sterty do konkretnej biblioteki ani funkcji C/C++.
- `application`: liczniki zadań, wyników i zdarzeń OCR, zadań przetwarzania,
  cache skanowania uploadów i aktywnych klientów backendu. Zbierane są liczby,
  bez zawartości tych kolekcji. Pozwalają sprawdzić korelację z przyrostem RAM.

Szczegóły zbierane są co 10 minut oraz wcześniej po wzroście pamięci procesu
o co najmniej 32 MiB od ostatniego szczegółowego pomiaru. Każdy instrumentowany
proces zbiera własne alokacje: menedżer, backend, worker OCR, aplikacja desktopowa,
a w instalacji także kontroler i oddzielny runtime OCR. Procesy pomocnicze,
w tym bootloader EXE, są widoczne jako potomkowie, gdy należą do obserwowanego
drzewa. Raport obejmuje też nadrzędny bootloader o tej samej ścieżce EXE;
bootloader nie ma własnego stosu Pythona do raportowania.

## Narzut i ograniczenia

Śledzenie używa jednej ramki stosu i nie wykonuje zrzutów całej sterty, nie
skanuje zawartości obiektów i nie wymusza `gc.collect()`. Samo śledzenie alokacji
ma koszt CPU i RAM, dlatego porównanie z nieinstrumentowaną v0.5.5 nie jest
idealnie równoważne. `tracer_bytes` i `sample_duration_ms` pomagają ocenić ten
koszt, ale nie obejmują wszystkich chwilowych alokacji podczas tworzenia
szczegółowej próbki. Gdy metadane własnego tracera przekroczą 64 MiB, raporter
wyłącza śledzenie do końca tego uruchomienia i zapisuje przyczynę; pomiary
procesów nadal działają.

Każdy proces ma plik do 4 MiB i dwie kopie rotacyjne (pojedynczy kompletny wiersz
może przekroczyć limit). Raporty starsze niż 14 dni są sprzątane co godzinę;
starsze, od co najmniej godziny niezmieniane pliki są też usuwane przy sumie
powyżej 256 MiB. Pliki aktualnie zapisywane oraz niedostępne do usunięcia mogą
czasowo przekroczyć ten wspólny limit. W razie błędu odczytu procesu zapisywany
jest typ błędu; zakończenie workera nie zatrzymuje raportowania backendu.

Opcje środowiska, ustawiane przed uruchomieniem aplikacji:

| Zmienna | Znaczenie |
| --- | --- |
| `PICSYNCRA_MEMORY_REPORT=0` | Wyłącz raportowanie (ustawienie domyślne). |
| `PICSYNCRA_MEMORY_REPORT=1` | Włącz w portable, instalacji zarządzanej lub przy uruchamianiu ze źródeł. |
| `PICSYNCRA_MEMORY_TRACE=0` | Zbieraj metryki procesów bez uruchamiania tracera Pythona. |
| `PICSYNCRA_MEMORY_REPORT_DIR` | Wspólny katalog raportów, dziedziczony przez proces OCR. |

Bez jawnego włączenia żaden wariant nie uruchamia wątku raportera ani tracera
i nie tworzy katalogu raportów. Tracer nie obejmuje alokacji sprzed
jego uruchomienia; zaczyna pracę przed obsługą zadań, a w workerze OCR przed
załadowaniem modeli. Starsze EXE v0.5.5 nie otrzymują raportera przez podmianę
samego pliku konfiguracyjnego — potrzebna jest nowa kompilacja.
