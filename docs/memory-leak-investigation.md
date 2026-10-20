# Wzrost pamięci portable: pomiary 16–20 października 2026

Raporty `logs/memory` z wersji `v0.5.6-ram-diagnostic-20261016` obejmowały
około 67 godzin. Po pierwszej godzinie backend zajmował 244 MiB RAM (RSS),
a na końcu 604 MiB. Menedżer wzrósł odpowiednio ze 125 do 843 MiB. Liczba
uchwytów menedżera wzrosła z 219 przy uruchomieniu do 24 387. W raportach
backendu nie było zadań przetwarzania ani wyników cache uploadów.

## Potwierdzone przyczyny i poprawki

### Typy ctypes tworzone przy każdym dostępie do SQLite

`sqlite_coordination._database_file_lock` definiował nową klasę `_Overlapped`
i jej typ wskaźnika podczas każdej blokady. `ctypes` przechowuje typy wskaźników
w cache procesu. To utrzymywało struktury w pamięci także po zwolnieniu blokady,
zamknięciu deskryptora i odśmiecaniu obiektów Pythona. Mechanizm był identyczny
w v0.5.5 i w pierwszym portable diagnostycznym.

Raporty wskazywały dawną linię 91 (klasa struktury) i 108 (typ wskaźnika).
Próba 3000 dostępów do jednej testowej bazy zachowała około 19 MiB alokacji
Pythona i 3000 nowych wpisów w cache typów wskaźników.

Poprawka definiuje strukturę oraz sygnatury `LockFileEx` i `UnlockFileEx`
raz na proces. Każda blokada nadal ma własną instancję struktury. Zachowana
jest współdzielona blokada normalnej pracy i wyłączna blokada przenoszenia
bazy. Po poprawce próba 3000 operacji nie zwiększała cache typów ani pamięci
w kolejnych partiach. Test regresyjny sprawdza ten warunek, a istniejące testy
sprawdzają współpracę i wykluczanie pomiędzy procesami.

### Powiadomienia Tkinter z nowych wątków menedżera

Menedżer odświeża status co 10 sekund w nowym wątku. Dotychczas wątek przekazywał
wynik przez `root.after`, co wymagało wywołania Tcl z tego wątku. Bezokienkowa
próba tego wzorca na Windows zwiększyła liczbę uchwytów ze 168 do 470 przy
300 nowych wątkach. Przyrost odpowiada około jednemu uchwytowi na odświeżenie
obserwowanemu w weekendowych raportach.

Poprawka przekazuje wyniki i komunikaty przez kolejkę Pythona. Tylko główny
wątek okna wywołuje Tkinter i co 100 ms odbiera oczekujące komunikaty. Zmieniono
także analogiczne powiadomienia po akcjach, zamykaniu i kliknięciach zasobnika.
Próba 300 powiadomień z nowych wątków po poprawce utrzymywała liczbę uchwytów
na poziomie 172 w każdej partii. Testy sprawdzają przekazanie wyniku w głównym
wątku i brak wywołań Tk z wątku odświeżającego.

## Weryfikacja na urządzeniu użytkownika: 19–20 października

Nowe raporty `v0.5.6-ram-fix-20261019` obejmują około 23 godziny, od
19 października 06:52 UTC do 20 października 05:49 UTC. To krótszy okres niż
67 godzin starej wersji, dlatego ważniejszy od samych wartości końcowych jest
trend po rozgrzaniu aplikacji.

| Pomiar | Backend | Menedżer |
| --- | --- | --- |
| Pamięć prywatna po ok. godzinie | 210 MiB | 100 MiB |
| Pamięć prywatna na końcu | 227 MiB | 116 MiB |
| Trend pamięci prywatnej w ostatnich 12 h | +0,17 MiB/h | +0,08 MiB/h |
| Uchwyty po pierwszej godzinie (zakres) | 402–404 | 280–289 |

Alokacje śledzone przez Pythona kończą się na około 47 MiB w backendzie
i 13 MiB w menedżerze. Liczniki zadań i cache backendu pozostają zerowe.
Zniknęły charakterystyczne alokacje kolejnych typów `ctypes` z blokady SQLite
oraz wzrost liczby uchwytów menedżera o około 360 na godzinę. Dla porównania
stare raporty w ostatnich 12 godzinach wykazywały wzrost pamięci prywatnej
o około 6,9 MiB/h w backendzie i 11,2 MiB/h w menedżerze.

Wyniki potwierdzają usunięcie dwóch odtworzonych mechanizmów wycieku. Nie są
dowodem braku wszystkich możliwych wycieków przy innych zadaniach aplikacji.

## Włączenie poprawek w zwykłych wydaniach

Obie poprawki są we wspólnych plikach `picsyncra/sqlite_coordination.py`
i `picsyncra/web_manager.py`. Portable pakuje te moduły ze źródeł, a wydanie
instalowane dostarcza je w obowiązkowym module `core`. Nie zależą od nazwy EXE,
flagi diagnostycznej ani obecności OCR. Test pakowania odtwarza zawartość tych
plików z wygenerowanego pakietu `core` i porównuje ją z bieżącymi źródłami.

W kolejnych zwykłych wydaniach raportowanie jest domyślnie wyłączone, także
w EXE. Opcjonalne włączenie opisuje [memory-diagnostics.md](memory-diagnostics.md).
Wyłączenie raportowania nie wyłącza poprawek. Istniejące EXE wymagają aktualizacji;
sama zmiana konfiguracji nie zmienia ich kodu.

## Zachowanie testowego portable

Testowy portable `v0.5.6-ram-fix-20261019` nadal zbiera raporty opisane w
[memory-diagnostics.md](memory-diagnostics.md). Zatrzymaj poprzedni backend
i menedżer przed podmianą EXE. Zachowaj stare raporty oraz tę samą konfigurację
i dane. Nie uruchamiaj obu backendów jednocześnie.

W archiwum poprawione EXE zachowuje dotychczasową nazwę
`PicSyncra-WEB-RAM-diagnostic.exe`. Można podmienić je w tym samym katalogu,
zachowując istniejące ustawienia i ścieżki uruchamiania. Numer wersji w nowym
raporcie pozwala odróżnić pomiary sprzed poprawki i po niej.

Po rozgrzaniu aplikacji porównuj trend przez co najmniej 24 godziny, a najlepiej
przez taki sam okres jak poprzednio. Szczególnie istotne są pamięć prywatna,
alokacje Pythona oraz uchwyty menedżera. Pojedynczy wzrost po załadowaniu funkcji
nie dowodzi wycieku. Krótkie testy odtwarzają oba potwierdzone mechanizmy;
wielodniowy test aplikacji pozwoli sprawdzić, czy występują jeszcze inne źródła
wzrostu pamięci.
