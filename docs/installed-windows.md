# PicSyncra instalowana na Windows

Wersja instalowana działa jako zwykły program Windows. WEB i Migrator są
instalowane zawsze, a komponent LOCAL jest opcjonalny. OCR nie jest częścią
instalacji bazowej: administrator pobiera go z zakładki **Wersje modułów**.
Przycisk **Pobierz OCR** w WEB lub launcherze pobiera silnik i modele
z Release odpowiadającego aktywnemu wydaniu aplikacji. Wymaga opublikowanego
pakietu OCR oraz publicznego klucza podpisu wbudowanego w instalowaną aplikację.
Samo lokalne wygenerowanie EXE nie zapewnia źródła tego pakietu.

## Dane i konfiguracja

Podczas instalacji można wskazać istniejącą bazę. Import konfiguracji portable
jest osobną, domyślnie niezaznaczoną opcją. Po jej zaznaczeniu instalator prosi
o istniejący katalog konfiguracji. Wybrane pliki są kopiowane do katalogu
zarządzanego przez instalację, więc usunięcie starego folderu portable nie
usuwa sekretów ani ustawień używanych przez zainstalowaną aplikację.
Bez importu aplikacja korzysta z domyślnej konfiguracji w ProgramData.

Lokalizacja zdjęć może nadal wskazywać udział sieciowy. Konto usługi musi mieć
do niego dostęp; WEB instalowany przez kontroler działa jako `SYSTEM`. Użyj
ścieżki UNC (na przykład `\\serwer\\zdjecia`) i nadaj uprawnienie kontu
komputera lub skonfiguruj dostęp do udziału dla `SYSTEM`. Dyski mapowane tylko
w sesji osoby instalującej nie są widoczne dla usługi.

## Aktualizacje

Aktualizacje modułów są dostępne w zainstalowanej aplikacji, w zakładce
**Wersje modułów** oraz w niezależnym launcherze. Każdy wiersz pokazuje wersję
obecną, najnowszą i listę wersji do cofnięcia. Link **Wydanie na GitHub**
wskazuje Release będący źródłem wybranej wersji. Portable nadal aktualizuje
się ręcznie przez pobranie nowego EXE.

Samo wybranie wersji niczego nie instaluje ani nie pobiera. Przygotowany
wiersz jest pomijany przez **Aktualizuj moduły**, ale dotychczasowy kod nadal
działa. Jeden przycisk **Cofnij wersję modułu** przygotowuje plan wszystkich
wybranych cofnięć. Po kontroli zgodności i zatwierdzeniu całość jest
instalowana jako jeden zestaw. Cofnięte moduły pozostają wyłączone z kolejnych
zwykłych aktualizacji, także po restarcie i w drugim interfejsie.

Kontroler sprawdza zależności API między modułami, schemat bazy, format
konfiguracji, ABI runtime oraz wersje kontrolera i launchera. Przy konflikcie
pokazuje wersje i wymagania. **Nie aktualizuj** zachowuje wybory i instalację.
**Aktualizuj wszystko** przygotowuje nowy, ponownie sprawdzany plan; blokady
są usuwane dopiero po jego pomyślnym wykonaniu. Nie omija to kontroli bazy.

Aktualizacja przechodzi bezpośrednio do docelowego wydania. Każdy plik ma
właściciela, rozmiar i SHA256; zweryfikowane pliki są ponownie używane z
lokalnego cache. Pobierane są tylko brakujące bajty, jako zakresy HTTP z
podpisanych paczek zawartości. Brak obsługi zakresów zatrzymuje operację,
zamiast powodować pobranie całej paczki. Modele OCR i biblioteki nie są
pobierane ponownie, jeżeli ich zawartość się nie zmieniła.

Workflow `.github/workflows/build-installer.yml` buduje rzeczywiste moduły
FTP, SQL, Pimcore, Sloty, Ustawienia, WEB, OCR i pozostałe składniki. Publikuje
`content-<SHA256>.bin`, bazowy `PicSyncra-Setup-<ID>.exe`, a na końcu
`PicSyncra-modules-manifest.json`, podpis `.sig` i `.key-id`. Manifest opisuje
niezależne wersje; liczba paczek nie odpowiada liczbie modułów. Przy ręcznym
uruchomieniu Actions kod pochodzi z taga wskazanego Release.

Stara instalacja z manifestem całego wydania wymaga jednorazowego przejścia
przez pełny nowy instalator. Nie można bezpiecznie mieszać jej modułów bez
deklaracji zgodności. Naprawa istniejącej instalacji modułowej zachowuje jej
aktywny zestaw i blokady.

Publikowanie tych paczek wymaga aktywnego workflow w repozytorium oraz
konfiguracji środowiska `installed-release-signing`: publicznych kluczy
`PICSYNCRA_RELEASE_PUBLIC_KEYS` i prywatnego sekretu
`PICSYNCRA_RELEASE_SIGNING_KEY`. Lokalny build bez wstrzykniętych publicznych
kluczy nie akceptuje aktualizacji. Same pliki portable EXE w Release nie
wystarczają do aktualizacji instalowanej aplikacji.

Przed zmianą wydania powstaje kopia bazy i konfiguracji. Aplikacja zatrzymuje
przyjmowanie nowych zadań, czeka na zakończenie aktualnych, a pozostałym
użytkownikom wyświetla dwuminutowe ostrzeżenie. Zajęte zadania blokują zmianę
kodu; po przekroczeniu czasu oczekiwania operacja jest zatrzymywana.

Awaryjne cofnięcie można wykonać z launchera również przy niedziałającym
WEB. Bez Internetu wymagany jest lokalny, ponownie zweryfikowany podpisany
katalog oraz wszystkie pliki docelowych modułów. Brakujące pliki wymagają
połączenia. Niepodpisane i niekompletne wydania nie są wybierane do instalacji.

Przy cofnięciu nie następuje automatyczne odtworzenie starej bazy. Jeżeli
potrzebna jest wcześniejsza baza, wybierz zweryfikowaną kopię w polu
**Awaryjne odtworzenie bazy**. Plan sprawdza zgodność także z tą kopią, a przed
wykonaniem wymaga osobnego potwierdzenia utraty nowszych danych. Nieudana
operacja i przerwanie zasilania uruchamiają odzyskanie poprzedniego zestawu,
blokad oraz zmienionych danych z obowiązkowej kopii sprzed operacji.

Jeżeli OCR był już doinstalowany, aktualizacja uwzględnia jego zgodność,
pobierając wyłącznie zmienione pliki runtime lub modeli. Instalacja bez OCR
nie pobiera silnika ani modeli automatycznie. Obecne deklaracje zgodności
znajdują się w `installer/module-compatibility.json`; zmiana schematu wymaga
podpisanej, jawnie zarejestrowanej migracji wykonywanej w osobnym hoście.

Restart backendu i autostart są dostępne z WEB wyłącznie dla administratora.
Instalator rejestruje zadanie `PicSyncra Controller primary-installation`,
które jest właścicielem tylko uruchomionego przez siebie procesu WEB. Kontroler
najpierw potwierdza żądanie administracyjne, a następnie restartuje WEB z
aktywnego wydania; nie używa `taskkill` ani nie zatrzymuje procesu zajmującego
ten sam port.

Lokalne okno zarządzania WEB może zatrzymywać lub uruchamiać backend po
uruchomieniu jako administrator. Zwykły użytkownik nie ma dostępu do pipe’a
kontrolera; zdalny restart pozostaje operacją administratora zalogowanego w
WEB.

Jeżeli menedżer zgłasza błąd kontrolera, uruchom go opcją **Uruchom jako
administrator** i sprawdź zadanie `PicSyncra Controller primary-installation`
w Harmonogramie zadań. Instalator sprawdza teraz wynik utworzenia i uruchomienia
tego zadania; błąd rejestracji przerywa instalację z komunikatem zamiast
pozostawiać instalację bez kontrolera.
