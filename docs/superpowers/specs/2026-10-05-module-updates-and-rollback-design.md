# Aktualizacje modułów i zbiorcze cofanie wersji

Status: projekt do przeglądu użytkownika; brak implementacji opisanego rozszerzenia.
Data: 2026-10-05.

Dokument rozszerza projekt instalowanych aktualizacji z 2026-09-15. Zastępuje
wcześniejsze ograniczenie do zmiany całego wydania wymaganiem niezależnych
wersji modułów, blokad aktualizacji i zbiorczego cofania. Pozostałe wymagania
dotyczące podpisów, kopii danych, konserwacji i uprawnień nadal obowiązują.
Portable aktualizuje się przez pobranie nowego EXE.

## 1. Zachowanie uzgodnione z użytkownikiem

- WEB i GUI launchera udostępniają listę dostępnych wersji przy każdym
  aktualizowanym module, wersję obecną i najnowszą dostępną wersję.
- Wybór z listy przygotowuje operację. Nie instaluje, nie cofa ani nie
  przełącza modułu i nie pobiera jego plików.
- Przy wybranej wersji wyświetla się link do GitHub Release będącego źródłem
  jej plików. Wersja modułu może pochodzić z innego wydania niż pozostałe.
- Wybrany moduł jest wyłączony z aktualizacji. Jeden wspólny przycisk
  **Cofnij wersję modułu** zatwierdza wszystkie przygotowane wybory.
- Cofanie i aktualizacja sprawdzają zgodność całego wynikowego zestawu:
  z bazą, konfiguracją, innymi modułami, runtime i kontrolerem.
- Konflikt pokazuje konkretne moduły, wersje i wymagania. Użytkownik wybiera
  **Aktualizuj wszystko** albo **Nie aktualizuj**. Konflikt nie upoważnia
  programu do samodzielnej wymiany dodatkowych modułów.
- Aktualizacja jednym przyciskiem pobiera tylko potrzebną zawartość;
  niezmienione moduły, biblioteki i modele nie są pobierane ponownie.
- Launcher umożliwia cofanie także bez działającego backendu WEB.

## 2. Moduły i granice pakowania

Obecne `ModuleDefinition` opisuje zmiany źródeł, a nie rozłączne paczki.
Przykładowo „Aplikacja i dane” obejmuje całe `picsyncra`, „Ustawienia” całe
`picsyncra/web`, a „Sloty” jest częścią dużego `app.js`. FTP, SQL i Pimcore
są wbudowane w zamrożone aplikacje. Aktualne cztery paczki WEB, Migrator,
LOCAL i OCR nie zapewniają niezależnego cofania tych funkcji.

Założenie do przeglądu: wymaganie „każdy moduł” obejmuje także funkcje
wyświetlane w tabeli, takie jak FTP, SQL, Pimcore, Sloty i Tester OCR.
Generatory EXE są narzędziami budowania, nie zainstalowanymi funkcjami;
ich wersje pozostają informacją diagnostyczną poza listą aktualizacji.

Implementacja musi najpierw wyznaczyć rozłączne granice instalowanych modułów:
rdzeń/dane, funkcje integracji, interfejs i jego wydzielone funkcje,
ustawienia, OCR oraz osobne aplikacje. Każdy plik ma jednego właściciela.
Wspólne biblioteki i runtime stanowią jawne zależności, nie duplikaty
ukryte w kilku modułach. Runtime i modele OCR są wersjonowane osobno.

Kod funkcji, które mają być cofane niezależnie, musi być ładowany z wybranego
pakietu instalowanego modułu. Nie wolno pozostawić go wyłącznie wewnątrz EXE
i prezentować niezależnej zmiany wersji, która faktycznie wymienia całe WEB.
Wbudowany kod portable może pozostać budowany dotychczasową drogą.

Katalog interfejsu pochodzi z podpisanych manifestów rzeczywistych pakietów.
Wpis diagnostyczny bez niezależnego pakietu nie udaje dostępnej aktualizacji.
Brak deklaracji zgodności blokuje mieszanie wersji zamiast uznawać je za zgodne.

## 3. Wybór wersji, wyłączenia i wspólne przyciski

Każdy wiersz zawiera: nazwę modułu, aktywną wersję, najnowszą opublikowaną
wersję, status zgodności, status wyłączenia, listę wersji i link do wybranego
Release. Lista obejmuje bieżącą oraz opublikowane starsze wersje z wybranego
kanału. „Bez zmiany” usuwa przygotowany wybór, ale nie zmienia aktywnej wersji
ani już utrwalonej blokady. Niedostępne wydania mają widoczny powód.

Najpierw zmienia się wyłącznie stan wyboru w danym oknie. Dopóki jest wybór,
zwykła aktualizacja pomija ten wiersz i zachowuje jego **obecną** wersję.
Nie może przy okazji zainstalować przygotowanej starszej wersji. Stan wyboru
jest lokalny dla okna; wykonana operacja i utrwalone wyłączenia są wspólne
dla WEB i launchera.

Kliknięcie **Cofnij wersję modułu** wysyła cały zestaw wybranych wersji
do wspólnego planera. Inne moduły pozostają w aktywnych wersjach. Po udanej
transakcji wybrane moduły mają utrwalone blokady aktualizacji. Kolejne zwykłe
aktualizacje pomijają je także po restarcie i z drugiego interfejsu.

Zwykły przycisk **Aktualizuj** wybiera najnowszy kompletny podpisany zestaw
docelowego wydania i uwzględnia wyłączenia. Nie wybiera niezależnie
„najwyższej” wersji każdego modułu z różnych niepowiązanych wydań.

**Aktualizuj wszystko** w dialogu konfliktu przygotowuje pełny zestaw
docelowego wydania, również dla wyłączonych modułów. Dialog pokazuje,
które wybrane wersje i blokady zostaną zastąpione. Dopiero świadome
zatwierdzenie oraz pomyślna ponowna walidacja pozwalają wykonać ten plan.
Blokady zostają usunięte dopiero przy udanym zatwierdzeniu transakcji.

**Nie aktualizuj** zamyka dialog i zachowuje wybory, aktywne wersje oraz
utrwalone blokady. Przycisk cofania jest nieaktywny bez przygotowanych wyborów.

## 4. Podpisany manifest i sprawdzanie zgodności

Nowy format manifestu obejmuje dla każdej wersji modułu:

- trwały identyfikator modułu, wersję, identyfikator zawartości i źródłowy Release;
- platformę, architekturę, wymagany runtime oraz wersję protokołu kontrolera;
- zależności od innych modułów i obsługiwane zakresy ich interfejsów;
- obsługiwany schemat bazy i format konfiguracji;
- dostępne migracje wraz z warunkami wejścia i wynikiem;
- listę rozłącznych ścieżek plików, rozmiarów i hashy SHA256;
- podpisane lokalizacje paczek zawartości potrzebnych do odtworzenia tej wersji.

Wersja wydania i wersja modułu są odrębne. Niezmieniony moduł zachowuje swoją
wersję i zawartość w kolejnych wydaniach. Nie wolno przypisywać każdemu modułowi
nowej wersji tylko dlatego, że uruchomiono kolejny build. Hashy nie zastępuje
porównanie commitów ani dat ZIP. Zmiana wymaganej biblioteki jest zmianą
zależności nawet wtedy, gdy sam kod modułu się nie zmienił.

Wspólny planer odczytuje aktywne wersje, blokady, podpisany katalog i bazę
w trybie tylko do odczytu. Dla całego docelowego zestawu sprawdza:

1. Autentyczność, kompletność i dostępność manifestów i zawartości.
2. Platformę, runtime i minimalny zgodny kontroler/launcher.
3. Wszystkie deklarowane zależności i konflikty między modułami.
4. Integralność bazy, schemat oraz zgodność konfiguracji.
5. Pełną ścieżkę wymaganych migracji; zgodność każdego modułu z końcową bazą.
6. Dostępne miejsce i możliwość utworzenia sprawdzonej kopii oraz stagingu.

To wspólna polityka dla obu interfejsów, nie dwie implementacje walidatora.
Plan zawiera aktywną rewizję instalacji, konkretne docelowe wersje, zmiany
blokad, migracje, pliki do pobrania i rozmiar transferu. Kontroler ponownie
sprawdza plan po uzyskaniu wyłącznego dostępu, przed zmianą danych i kodu.
Zmiana aktywnego zestawu lub warunków zgodności unieważnia plan.

Przykład komunikatu, z ilustracyjnymi numerami wersji:
„Pimcore 2.4 wymaga SQL >= 3.0; wybrano SQL 2.8. Rdzeń 5.0 obsługuje
schemat 12, a baza ma schemat 14. Nie wykonano zmian.” Komunikat obejmuje
wszystkie wykryte konflikty, a nie tylko pierwszy.

Wariant **Aktualizuj wszystko** jest dostępny do wykonania tylko wtedy,
gdy pełny zestaw przejdzie te same kontrole. Nie omija niezgodności bazy,
brakujących plików ani nieprawidłowego podpisu.

## 5. Minimalne pobieranie i pomijanie pośrednich wydań

Rozważone sposoby dystrybucji:

1. ZIP całego zmienionego modułu: prostszy, ale ponownie pobiera niezmienione
   duże biblioteki i modele znajdujące się w tej samej paczce.
2. **Zawartość identyfikowana hashami i pełne manifesty wersji — proponowane.**
   Umożliwia ponowne wykorzystanie posiadanych plików i skok do dowolnego
   dostępnego docelowego zestawu bez kolejnych instalacji pośrednich.
3. Binarne łatki między każdą parą wersji: mniejszy transfer wewnątrz zmienionych
   plików, ale znacznie więcej artefaktów i ścieżek awarii; poza zakresem.

Wybrana metoda oznacza minimalność na poziomie plików: zmieniony plik może
zostać pobrany w całości. Nie obiecujemy przesyłania tylko zmienionych bajtów.
Release publikuje podpisany opis pełnej zawartości i paczki, które pozwalają
pobrać brakującą zawartość bez wymuszania ponownego transferu plików już
zweryfikowanych lokalnie. Modele OCR i duże zależności są osobnymi zasobami.

Planer porównuje docelowe hashe z plikami instalacji i chronionego cache.
Posiadana zawartość jest weryfikowana przed ponownym użyciem; uszkodzony plik
wymaga pobrania. Brakujące pliki są pobierane do stagingu i weryfikowane.
Usunięty plik nie przechodzi do nowej wersji. Program nie nadpisuje aktywnego
katalogu: przygotowuje nowy kompletny zestaw i atomowo go aktywuje.

Przejście z wersji 1 do 5 pobiera tylko brakującą zawartość wersji docelowych,
bez pakietów aplikacji 2–4. Jeżeli baza wymaga kolejnych migracji, ich komplet
musi być dostępny w podpisanym zestawie migracji; brak ścieżki blokuje zmianę.
OCR i LOCAL nie są doinstalowywane, jeżeli użytkownik ich nie ma i nie zlecił
ich instalacji. Pobranie OCR jest osobną jawną operacją.

## 6. Transakcja, awarie i odzyskiwanie z launchera

Jeden kontroler wykonuje plan dla WEB i launchera. Klienci przekazują
identyfikatory modułów, wersji i planu, nigdy dowolne komendy, ścieżki ani URL.
WEB wymaga uwierzytelnionego administratora i CSRF; launcher używa chronionego
lokalnego kanału kontrolera oraz uprawnień administratora Windows.

Przebieg: walidacja planu, pobranie brakującej zawartości, weryfikacja,
konserwacja i zakończenie zadań, wyłączny dostęp, ponowna walidacja,
sprawdzona kopia bazy i konfiguracji, przygotowanie modułów/migracje,
aktywacja całego zestawu, restart i test zdrowia, zatwierdzenie.
Wybrane wersje oraz blokady są częścią jednej transakcji. Awaria drugiego
modułu nie może pozostawić zatwierdzonego cofnięcia pierwszego.

Powrót do starszego modułu zgodnego z obecną bazą zachowuje aktualne dane.
Gdy potrzebne jest przywrócenie starszej bazy, konieczna jest zgodna,
zweryfikowana kopia i osobne potwierdzenie utraty późniejszych zmian.
Samo kliknięcie „Cofnij wersję modułu” ani „Aktualizuj wszystko” nie udziela
zgody na utratę danych. Bez bezpiecznej drogi cofanie pozostaje zablokowane.

Automatyczne wycofanie nieudanej transakcji odtwarza poprzedni zestaw,
blokady, konfigurację i bazę, jeżeli ta została zmieniona. Gdy wycofanie
nie może się zakończyć, kontroler utrwala stan wymagający odzyskiwania
i nie uruchamia niezgodnego zestawu.

Stabilny launcher znajduje się poza zmiennymi katalogami modułów i nie
potrzebuje działającego WEB do odczytania stanu, katalogu lokalnie zachowanych
wersji, przygotowania planu oraz wykonania cofania przez kontroler. Cofanie
do kompletnego, zweryfikowanego zestawu z dysku działa bez Internetu;
brakujące pliki wymagają dostępu do Release.

## 7. Kryteria odbioru

1. W WEB i launcherze wybór z listy nie uruchamia pobierania ani zmiany wersji;
   aktualizuje link do właściwego źródłowego Release i wyłącza wiersz z aktualizacji.
2. Jeden przycisk stosuje wszystkie wybrane cofnięcia, a wynik i blokady
   są widoczne w obu interfejsach oraz po restarcie.
3. Cofnięcie dwóch modułów wykonuje się w całości albo zostaje wycofane w całości.
4. Aktualizacja pomija utrwalone blokady oraz nie stosuje niezatwierdzonych
   wyborów cofania. Moduły bez zmiany zawartości zachowują wersję.
5. Niekompatybilne zależności, baza lub konfiguracja blokują zarówno cofanie,
   jak i aktualizację przed modyfikacją kodu/danych i pokazują konkretne konflikty.
6. „Nie aktualizuj” zachowuje stan; „Aktualizuj wszystko” sprawdza nowy plan
   i nie usuwa blokad przed pomyślnym zatwierdzeniem operacji.
7. Przejście przez kilka pominiętych wydań pobiera tylko brakujące pliki
   docelowego zestawu. Niezmienione modele i biblioteki nie generują transferu.
8. Uszkodzony cache jest wykrywany. Nieprawidłowy podpis, brak paczki,
   niewspierany kontroler lub brak ścieżki migracji blokują wykonanie.
9. Awaria lub zamknięcie WEB nie uniemożliwia cofania z niezależnego launchera.
   Zmiana instalacji z drugiego klienta unieważnia wcześniej przygotowany plan.
10. Przywracanie starej bazy wymaga osobnego potwierdzenia; błąd kopii blokuje
    operację; nieudana migracja odtwarza stan sprzed operacji.
11. Actions publikuje rzeczywiste pakiety modułów, zawartość i podpisy;
    katalog nie oferuje niekompletnych lub niezweryfikowanych wersji.
12. Zamrożony pakiet instalowany potrafi uruchomić wybrany mieszany zestaw
    zgodnych modułów. Portable zachowuje dotychczasową dystrybucję EXE.
