# Instalator Windows, aktualizacje i restart PicSyncra

Status: specyfikacja dołączona do planu na podstawie decyzji użytkownika z 15.09.2026. Dokument opisuje przyszłe zachowanie; funkcje nie zostały wdrożone.

## 1. Cel i zakres

Zainstalowana PicSyncra ma być zwykłym programem Windows, z aktualizacją całego wydania z GitHub Releases, restartem z WEB, opcjonalnym OCR i możliwością powrotu do wybranego wcześniejszego wydania. Obecne portable EXE zachowują sposób budowania, uruchamiania i ręcznej aktualizacji.

### Wymagania uzgodnione z użytkownikiem

- Windows x64; instalator wymaga jednorazowej zgody administratora Windows.
- WEB i Migrator są składnikami obowiązkowymi instalatora.
- Instalator pyta o „Wersja lokalna (opcjonalna)”; domyślnie niezaznaczona.
- OCR nie jest pobierany domyślnie. Przycisk „Pobierz i zainstaluj OCR” pobiera runtime i modele zgodne z bieżącym wydaniem.
- GUI zawiera domyślnie wyłączony autostart backendu po uruchomieniu Windows, również bez zalogowanej osoby.
- Administrator aktualizuje całe wydanie jednym przyciskiem. Lista składników pozostaje informacją diagnostyczną.
- Aktualizator czeka na zadania, pokazuje oczekiwanie i umożliwia administratorowi wymuszenie ich zakończenia.
- Po zakończeniu zadań inni obecni użytkownicy otrzymują ostrzeżenie na 120 sekund. Administrator inicjujący operację nie jest liczony. Bez innych użytkowników i zadań operacja rusza natychmiast.
- Restart jest wywoływany z działającego panelu WEB; niezależny zdalny panel ratunkowy pozostaje poza zakresem.
- Po aktualizacji użytkownicy logują się ponownie, interfejs jest przeładowany, odtwarzalny cache wyczyszczony, a dane ponownie wczytane.
- Tokeny rozszerzenia przeglądarki zachowują ważność. Gdy jego wersja wymaga wymiany, użytkownik widzi komunikat i możliwość pobrania aktualnego ZIP.
- Dwa kanały: stable i dev; stable jest domyślny. Dostępna jest lista wydań z wybranego kanału, także starszych.
- Przed każdą zmianą wersji zawsze powstaje sprawdzona kopia bazy oraz konfiguracji. Błąd kopii blokuje operację; harmonogram kopii nie może tego wyłączyć.
- Cofnięcie niezgodne ze schematem bazy wymaga zgodnej kopii i osobnego potwierdzenia utraty późniejszych zmian. Brak bezpiecznej ścieżki oznacza blokadę.
- W istniejącej bazie wskazanej podczas instalacji zachowujemy dane; pytamy o pliki konfiguracji i sekretów, pozwalając pominąć import.
- Importowane pliki konfiguracji i sekretów są kopiowane do nowych plików zarządzanych przez instalację. Działanie konfiguracji nie może zależeć od pozostawienia katalogu portable.

## 2. Stan repozytorium istotny dla wdrożenia

- `.github/workflows/build-exe.yml` buduje portable LOCAL, WEB, WEB-OCR i Migrator. Budowanie po publikacji release oznacza okres, w którym release nie ma jeszcze kompletu pakietów.
- `picsyncra/services/module_build_status.py` oraz `picsyncra/web/static/module-build-status.js` opisują zgodność z kodem gałęzi; nie jest to katalog gotowych aktualizacji.
- `picsyncra/web_manager.py` uruchamia procesy, obsługuje lokalny restart i autostart przez `schtasks`. Nazwa „usługa” w obecnym GUI nie oznacza rzeczywistej usługi SCM.
- `picsyncra/settings.py` i `picsyncra/common.py` niezależnie rozwiązują ścieżkę `local_settings.json`. `common.py` wczytuje `APP_SECRET` już przy imporcie.
- Konfiguracja może pochodzić z JSON albo SQLite. Nie wolno tworzyć dwóch równorzędnych, rozchodzących się źródeł konfiguracji.
- Sesje webowe używają `session_version`, a rozszerzenie osobnego `extension_token_version`.
- Są już mechanizmy kopii SQLite, koordynacji dostępu do bazy i kolejek, które należy rozszerzyć zamiast zastępować.
- OCR posiada proces roboczy, ale jego uruchamianie przez multiprocessing nie stanowi jeszcze mechanizmu doinstalowywania oddzielnego runtime.

## 3. Wybrana architektura

### Rozważone warianty

1. **Instalator + osobny kontroler + pakiety w katalogach wersji — wybrany.** Umożliwia zdalne wykonanie, kontrolę restartu i przywrócenie wersji.
2. Uruchamianie pobranego instalatora przy każdej aktualizacji: prostsze początkowo, lecz samo nie zapewnia koordynacji zadań, sesji ani wycofania danych.
3. Niezależna wymiana plików poszczególnych modułów: odrzucona, ponieważ zwiększa liczbę niezgodnych kombinacji zależności i nie odpowiada zaakceptowanej aktualizacji całego wydania.

### Składniki i uprawnienia

- Inno Setup tworzy skróty, deinstalator, wpis aplikacji, katalogi z uprawnieniami, rejestrację instalacji i usługi.
- Pakiety instalowane używają PyInstaller `onedir`. Portable nadal używa swoich obecnych ustawień `onefile`.
- Mała usługa kontrolera Windows obsługuje wyłącznie start, stop, restart i transakcje aktualizacji własnej instalacji. Implementacja Python/pywin32, zależność wydzielona do builda instalowanego.
- Backend działa jako odrębna usługa z ograniczonym kontem, domyślnie LocalService. Konto z dostępem do sieci można wskazać lokalnie w konfiguracji instalacji/usługi. Backend nie otrzymuje uprawnień do wymiany kodu.
- Usługa backendu ma start ręczny albo automatyczny zgodnie z opcją GUI. Obecność kontrolera nie oznacza automatycznego uruchamiania backendu.
- Lokalny launcher otwiera GUI w sesji użytkownika i komunikuje się z kontrolerem; usługa nie otwiera okien w sesji 0.
- Kontroler zleca wymianę własnych plików odrębnemu helperowi uruchomionemu z chronionego katalogu. Helper działa niezależnie od aktualizowanego backendu i kontrolera.
- Komunikacja lokalna: nazwany potok z ACL i kontrolą tożsamości procesu. Brak nowego portu zarządzającego dostępnego z sieci.
- Helper ponownie weryfikuje podpisy i ścieżki. WEB przekazuje identyfikator zatwierdzonego wydania, nigdy dowolną komendę, URL, ścieżkę EXE albo skrypt.
- API wymaga rzeczywiście uwierzytelnionego administratora i CSRF również wtedy, gdy zwykłe logowanie WEB jest opcjonalnie wyłączone. Tryb anonimowy nie udostępnia zarządzania instalacją.

### Katalogi

```text
%ProgramFiles%/PicSyncra/
  launcher/                         # stabilny punkt wejścia
  controller/                       # kontroler i chroniony helper
  versions/<release-id>/            # WEB, Migrator, opcjonalny LOCAL
  components/ocr/<component-id>/     # runtime i modele OCR
  active.json                       # atomowo podmieniany wybór kompletu

%ProgramData%/PicSyncra/<installation-id>/
  config/                           # local_settings.json i importowane pliki
  data/                             # domyślna baza; może mieć wskazaną inną lokalizację
  logs/
  cache/                            # tylko odtwarzalne dane
  backups/<operation-id>/           # spójna baza, konfiguracja i metadane
  control/                          # ACL kontrolera, dziennik i epoka sesji
  staging/                          # chronione, nieaktywne pakiety
```

Wpis HKLM instalatora wskazuje identyfikator i katalogi. Resolver bez importów aplikacji odczytuje go przed `common.py`. Sam `sys.frozen`, zmienna środowiskowa lub położenie EXE nie daje uprawnień do aktualizacji. Resolver sprawdza zgodność uruchomionej ścieżki z rejestracją. Brak ważnej rejestracji oznacza dotychczasowy tryb portable/development.

Katalog kodu, `active.json`, dziennik kontrolera i zaakceptowane pakiety nie są zapisywalne przez zwykłych użytkowników ani backend. Dane mają uprawnienia niezbędne dla skonfigurowanego konta backendu i lokalnych użytkowników aplikacji. Hasła nie trafiają do argumentów procesów ani logów.

## 4. Instalacja i import

1. Wybór folderu programu, danych/bazy, opcjonalnego LOCAL i autostartu. OCR widoczny jako dostępny do późniejszego pobrania.
2. Wykrycie istniejącej bazy i jej schematu bez uruchamiania migrującego backendu.
3. Przy wykrytej bazie pytanie o konfigurację: `local_settings.json`, `config.json` i powiązane pliki sekretów/certyfikatów wskazane przez konfigurację. Można pominąć.
4. Przed modyfikacją istniejącej bazy: wyłączny dostęp, kopia bazy i dotychczasowej konfiguracji. Nie modyfikować bazy używanej przez inną instancję portable, LOCAL lub Migrator.
5. Kopia konfiguracji do katalogu tymczasowego instalacji, kontrola parsowania i odszyfrowania, przepisanie odwołań do skopiowanych plików, a następnie atomowe zatwierdzenie. Oryginały pozostają nietknięte.
6. Zachowanie logicznej wartości sekretów i istniejących tokenów. Jeżeli sposób zapisu jest zależny od komputera/konta, po odczytaniu zapisać go ponownie w formacie działającym dla docelowego konta. Nierozpoznany sekret wymaga uzupełnienia, a nie cichego zastąpienia.
7. Konfiguracja przechowywana już w bazie pozostaje w bazie; kopiujemy pliki startowe i materiał potrzebny do jej odczytania. Import zewnętrznego JSON nie nadpisuje automatycznie bogatszej konfiguracji istniejącej bazy.
8. Pominięty import tworzy nową lokalną konfigurację instalacji; niedostępne sekrety mają status „Wymaga konfiguracji”. Nie wysyłamy żądań integracyjnych z przypadkowo odczytanym hasłem.
9. Ustawienia nie odwołują się do starego katalogu konfiguracyjnego. Ścieżki zdjęć, udziałów i jawnie wybranej bazy pozostają zgodne z wyborem użytkownika — nie kopiujemy bez pytania kolekcji zdjęć.

Wybranie bazy wewnątrz starego katalogu portable nadal wiąże jej życie z tym katalogiem. Instalator pokazuje rzeczywistą lokalizację bazy oddzielnie od nowej konfiguracji; domyślna lokalizacja nowej bazy znajduje się w katalogu danych instalacji. Nie obiecuje możliwości usunięcia plików bazy pozostawionych świadomie w portable.

Kontrola dostępu do zdjęć i SQL odbywa się w docelowym kontekście backendu. Mapowane litery dysków proponujemy zamienić na rozpoznane UNC, z potwierdzeniem użytkownika. Brak dostępu blokuje aktywację autostartu zależnego od tych zasobów i daje instrukcję wskazania konta. Nie przełączamy bez pytania na pusty katalog lokalny.

Deinstalator zatrzymuje tylko własne procesy/usługi, usuwa własną rejestrację i kod, a domyślnie zachowuje bazę, konfigurację i kopie.

## 5. OCR na żądanie

- Osobny, samowystarczalny runtime OCR z interpreterem, bibliotekami natywnymi i modelami. Nie uruchamiamy `pip` u użytkownika i nie dokładamy przypadkowych bibliotek do zamrożonego WEB EXE.
- Dla instalowanego WEB adapter uruchamia zaufany OCR EXE przez prywatny protokół JSON po stdin/stdout. Zachowujemy semantykę obecnych komunikatów, limity zasobów, anulowanie i diagnostykę.
- Zwykły WEB sprawdza dostępność przez handshake runtime, a nie wyłącznie import PaddleOCR w swoim procesie. Wszystkie ścieżki OCR, w tym tester, skanowanie slotów i rozpoznawanie wymiarów, przechodzą przez adapter.
- Portable nadal używa dotychczasowego procesu i bundlowanych bibliotek/modeli.
- OCR jest przypięty w manifeście do wydania i wersji protokołu. Pierwsze pobranie dobiera OCR dla aktualnie działającego wydania, nie dla najnowszego taga.
- Instalacja OCR stosuje tę samą konserwację, kopię i kontrolę aktywacji co zmiana programu. Błąd pozostawia działający WEB bez nowego OCR.
- Aktualizacja kompletu zawiera OCR, jeśli był zainstalowany. Brak zgodnego OCR blokuje aktualizację; nie wyłączamy go po cichu. Modele o niezmienionych hashach nie są ponownie pobierane.
- Czyszczenie cache nie usuwa modeli, źródłowych zdjęć, konfiguracji, kopii ani plików zadań potrzebnych do rozliczenia przerwanej operacji.

## 6. Wydania, kanały i zaufanie

GitHub Release zawiera osobne artefakty portable oraz instalowane: instalator bazowy, pakiet aplikacji, opcjonalny LOCAL, runtime/model OCR i podpisany manifest. Migrator jest zawsze częścią kompletu podstawowego. Instalator zawiera LOCAL do opcjonalnego wyboru, ale nie zawiera ani nie pobiera domyślnie OCR.

Manifest schema 1 zapisuje: repozytorium, release ID, tag, commit SHA, gałąź źródłową, kanał, datę, Windows/x64, wersję aplikacji, minimalną wersję kontrolera, schemat bazy obsługiwany do odczytu/zapisu, dozwolone migracje, protokół rozszerzenia/OCR oraz nazwy, rozmiary i SHA-256 pakietów. Podpis Ed25519 obejmuje dokładne bajty manifestu; klucz prywatny jest dostępny tylko zaufanemu jobowi podpisującemu. Klient ma wbudowany zestaw zaufanych kluczy i identyfikatory kluczy do rotacji.

- `main` daje kanał `stable`; pozostałe jawnie wybrane gałęzie dają `dev`. Lista dev pokazuje też źródłową gałąź.
- Stable wymaga `prerelease=false`, dev wymaga `prerelease=true`. Sprzeczność jest błędem wydania, nie cichą korektą kanału.
- Dla istniejącego taga workflow weryfikuje rzeczywisty commit i źródłową gałąź. `target_commitish` samo w sobie nie stanowi dowodu pochodzenia. Gdy gałęzi nie da się rozstrzygnąć, publikujący podaje ją jawnie w workflow i sprawdzamy osiągalność commita.
- Budujemy dokładny commit taga. Podpisany manifest jest publikowany jako ostatni znacznik gotowości po udanym przesłaniu i sprawdzeniu załączników.
- Katalog korzysta z paginowanej listy releases. Pomija drafts, niekompletne, niepodpisane, niezgodne i obce pakiety. Obsługuje limity API, ETag, timeout, retry i błąd offline bez zatrzymywania aplikacji.
- Lista pokazuje także starsze zgodne wydania; niedostępne do bezpiecznej instalacji pozycje mają powód blokady. Stare portable-only releases nie staną się instalowalne bez przygotowania zgodnych pakietów.
- Przełącznik kanału wyłącznie zmienia katalog. Instalacja następuje dopiero po świadomym wyborze wydania. Wybrana stara wersja nie aktualizuje się sama z powrotem.
- Pobranie przypina release ID, commit, rozmiary i hashe. Przekierowania dopuszczają jedynie HTTPS i zdefiniowane hosty GitHub/CDN. Nie wolno rozpakowywać ścieżek absolutnych, `..`, linków/reparse points ani nadpisywać plików poza staging.
- Manifest, podpis i hash są weryfikowane ponownie w chronionym staging przez helper. Podmiana pliku między pobraniem a uruchomieniem nie może ominąć kontroli.

## 7. Transakcja aktualizacji i restartu

```text
idle -> downloading -> verified -> draining -> countdown
     -> stopping -> backing_up -> installing -> migrating
     -> validating -> committed
                         |
                         +-> rolling_back -> rolled_back / recovery_required
```

Restart pomija pobieranie i wymianę kodu, ale korzysta z kolejki konserwacji, unieważnienia sesji, zatrzymania, obowiązkowej kopii i kontroli gotowości. Nazwy stanów są wspólne z planem implementacji.

### Zadania i obecność

- Po `verified` wyłączamy przyjmowanie nowych zadań zapisujących, nowe zadania harmonogramów, importy rozszerzenia i mutujące operacje API. Operacje już przyjęte, także oczekujące w kolejce, mogą się zakończyć; odczyt i śledzenie statusu pozostają dostępne.
- Licznik obejmuje upload HTTP, przetwarzanie obrazów, FTP, OCR, import/eksport, synchronizacje i zadania okresowe. Nie wystarczy liczba zadań jednej kolejki.
- Obecność opieramy na heartbeat aktywnych sesji WEB co 15 s, z TTL 60 s i odświeżeniem po odzyskaniu widoczności karty. Ukryte/uśpione karty przy powrocie najpierw sprawdzają stan instalacji i nie wysyłają starych zapisów.
- Administrator inicjujący, także jego inne sesje, jest wyłączony z liczby odbiorców powodujących odliczanie. Backend i automatyczne integracje nie są użytkownikami.
- Po opróżnieniu kolejek, jeśli są inni użytkownicy, zapisujemy trwały termin za 120 s i pokazujemy baner wszystkim. Rozpoczętego odliczania nie skracamy, gdy użytkownicy wyjdą. Nowe logowanie w tym czasie prowadzi do ekranu konserwacji.
- Nieznany stan kolejki, klienta LOCAL lub dostępu do bazy traktujemy jako przeszkodę, nie dowód bezczynności.
- „Wymuś zakończenie” najpierw zgłasza anulowanie, następnie po 30 s zatrzymuje wyłącznie zarejestrowane procesy instalacji. Nie pomija 120 s ostrzeżenia, kopii, integralności bazy ani weryfikacji pakietu.
- Niedokończony upload/FTP/OCR jest przerwany albo wymaga sprawdzenia. Nie ponawiamy automatycznie operacji o nieznanym wyniku zewnętrznym i nie deklarujemy cofnięcia zmian na FTP/SQL/Pimcore.
- LOCAL i Migrator korzystający z tej instalacji muszą respektować konserwację i zamknąć uchwyty. Nieznany proces zewnętrzny korzystający ze wspólnej bazy blokuje zmianę, zamiast być przymusowo zabity.

### Kopia i przełączenie

- Zewnętrzny kontroler posiada wyłączną blokadę instalacji i bazy. Spójna kopia SQLite uwzględnia WAL przez SQLite Backup API; nie kopiujemy samego otwartego pliku `.sqlite`.
- Kopia zawiera integralną bazę, konfigurację, sekrety, listę komponentów, schemat, wersję/commit i identyfikator operacji. Kontrola integralności i możliwość odczytu konfiguracji są warunkiem postępu.
- Kopie aktualizacyjne mają osobną retencję od harmonogramu. Nie usuwa się automatycznie kopii powiązanej z aktywną transakcją i ostatnim działającym wydaniem; inne kopie usuwa administrator jawnie.
- Przed doinstalowaniem OCR, aktualizacją, cofnięciem, przywróceniem kopii i migracją istniejącej bazy powstaje świeża kopia stanu zastępowanego. Nie ma opcji „kontynuuj bez kopii”. Przy pierwszej instalacji pustej bazy odnotowujemy brak wcześniejszego stanu.
- Przy automatycznym rollbacku zachowujemy także kopię stanu po nieudanej migracji. Jeżeli nie da się jej zabezpieczyć, nie nadpisujemy tej bazy; przechodzimy w `recovery_required` z zachowaną kopią sprzed operacji.
- Nowa wersja znajduje się w osobnym katalogu. Atomowo przełączamy mały plik wyboru kompletu i uruchamiamy dokładnie ten build w trybie konserwacji. Dziennik operacji zapisujemy atomowo przed/po każdym nieodwracalnym kroku.
- Migracje startują dopiero po kopii. Migracje usuwające dane wymagają jawnego opisu wpływu i potwierdzenia administratora przed rozpoczęciem operacji; zwykła aktualizacja pozostaje jednym przyciskiem.
- Gotowość wymaga właściwego release/commit, zgodności schematu, odczytu konfiguracji, integralności SQLite i gotowego procesora zadań; z OCR również jego poprawnego handshake. Sam HTTP 200 nie wystarcza.
- Dane źródłowe wczytujemy według istniejących ustawień. Budujemy potrzebne indeksy/cache, bez masowych zapisów do źródeł zewnętrznych. Chwilowa niedostępność FTP/SQL/Pimcore daje jawny stan ograniczony; nie uruchamia pętli rollbacków poprawnego programu.
- Po utracie zasilania kontroler odczytuje dziennik przed uruchomieniem backendu i kończy aktywację lub przywraca poprzedni komplet. Nie dopuszcza dwóch wersji do jednoczesnego zapisu.
- Aktualizacja kontrolera/helpera wymaga zgodności protokołu bootstrap; osobny helper zatrzymuje kontroler, podmienia go i sprawdza start. Kontroler nie podmienia działającego własnego EXE.

### Cofnięcie wersji

Zgodny schemat pozwala zachować bieżące dane. Niezgodny schemat wymaga zgodnej kopii i pokazania jej daty oraz utraty późniejszych zmian; bez potwierdzenia operacja nie startuje. Przed jej odtworzeniem zawsze zabezpieczamy stan bieżący. Przywracamy dopasowane komponenty, konfigurację i sekrety, ale nigdy nie zmniejszamy epoki unieważnienia sesji.

## 8. Sesje, przeglądarki i rozszerzenie

- Monotoniczna epoka instalacji w chronionym stanie kontrolera jest niezależna od przywracanej bazy. Instalowane tokeny sesji zawierają epokę; jej zwiększenie unieważnia wszystkich, w tym inicjatora. Istniejący `session_version` nadal działa dla pojedynczego konta.
- Epoka nie jest `APP_SECRET`: nie zmieniamy sekretu szyfrującego konfigurację dla potrzeb wylogowania.
- Nowy backend nie przyjmuje tokenów sprzed epoki ani mutacji z innym build ID. Nieotwarte/uśpione karty tracą możliwość zapisu także bez odebrania banera.
- Publiczny status konserwacji jest minimalny: stan, przewidywany powrót i identyfikator buildu/epoki, bez ścieżek, kont, błędów wewnętrznych i logów.
- HTML ma rewalidację/no-store, statyczne zasoby mają build ID w adresie. Klient reaguje na zmianę buildu lub epoki przeładowaniem strony i logowaniem, czyszcząc stan aplikacji, nie inne dane przeglądarki.
- Rozszerzenie zachowuje swój token. API ping zgłasza wersję protokołu i wymagany zakres wersji klienta; stare rozszerzenia są traktowane jako protokół legacy, dopóki serwer go obsługuje.
- Podczas konserwacji również rozszerzenie nie może zapisywać. Niezgodny klient otrzymuje odpowiedź wymagającą aktualizacji, a zalogowany użytkownik komunikat z ZIP. Brak obietnicy automatycznej wymiany rozpakowanego rozszerzenia.

## 9. Kryteria odbioru

1. Czysty Windows bez Pythona: WEB i Migrator działają; LOCAL zależy od wyboru; OCR nie zajmuje miejsca przed pobraniem.
2. OCR działa offline po pobraniu, również w testerze i kolejce; aktualizacja/cofnięcie zachowuje zgodność komponentów.
3. Autostart wyłączony nie uruchamia backendu po restarcie Windows; włączony uruchamia go bez logowania i z prawidłowym dostępem do udziałów.
4. Import zachowuje dane i sekrety; po usunięciu źródłowego katalogu konfiguracji portable program czyta wyłącznie nowe pliki. Baza i zdjęcia w jawnie wybranych zewnętrznych lokalizacjach pozostają tam.
5. Aktualizacja, restart i downgrade zawsze wykonują kopię; brak miejsca lub błąd integralności zatrzymuje transakcję.
6. Testy uploadu/FTP/OCR potwierdzają drain i force; żadna przerwana operacja nie zostaje oznaczona jako udana.
7. Jeden administrator bez zadań nie czeka 120 s; inna obecna osoba powoduje pełne odliczanie po zakończeniu zadań.
8. Stare sesje są odrzucone po aktualizacji, restarcie i rollbacku; stare karty i zasoby nie mogą zapisywać jako aktualny build.
9. Stabilne/testowe i wcześniejsze wydania są prawidłowo filtrowane; niekompletny release, zły podpis, hash, architektura lub schemat blokuje instalację.
10. Awaria w każdym stanie transakcji kończy się kompletną poprzednią/nową wersją albo jawnym trybem odzyskiwania, nigdy mieszanym zestawem.
11. Wyłączone logowanie, zwykły użytkownik, błędny CSRF i obcy proces lokalny nie uzyskują możliwości restartu ani wykonania pobranego kodu.
12. Portable ma dotychczasowe ścieżki, sesje, OCR, GUI i ręczną aktualizację; nie dostaje usług ani API zarządzania instalacją.

## 10. Źródła decyzji technicznych

- Inno Setup obsługuje instalację administracyjną: https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm
- PyInstaller opisuje samowystarczalne pakiety onedir/onefile; dla chronionych komponentów wybieramy onedir: https://pyinstaller.org/en/stable/operating-mode.html
- Usługi Windows używają UNC i uprawnień własnego konta, a nie mapowań interaktywnej sesji: https://learn.microsoft.com/en-us/windows/win32/services/services-and-redirected-drives
- GitHub Releases API rozróżnia tag, target_commitish, draft i prerelease: https://docs.github.com/en/rest/releases/releases
- Rozpakowane rozszerzenie nie daje standardowego kanału automatycznej dystrybucji do publicznych użytkowników Chrome: https://developer.chrome.com/docs/extensions/how-to/distribute
