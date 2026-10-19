# Wzrost pamięci portable: pomiary 16–19 października 2026

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

## Ponowny test na urządzeniu użytkownika

Nowy portable `v0.5.6-ram-fix-20261019` nadal zbiera raporty opisane w
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
