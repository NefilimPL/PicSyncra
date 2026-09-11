# Pimcore 6.6 REST

PicSyncra może korzystać z Pimcore 6.6 REST do odczytu konfiguracji klas, wyszukiwania produktu po EAN oraz tworzenia brakujących obiektów produktu.

## Konfiguracja

1. W Pimcore włącz `Settings > System Settings > Web Service API`.
2. Utwórz albo wybierz dedykowanego użytkownika Pimcore i skopiuj jego klucz API.
3. Nadaj temu użytkownikowi uprawnienia REST do odczytu informacji o serwerze, listy klas, definicji klasy, folderów i obiektów.
4. Do pracy runtime dodaj uprawnienia tworzenia i aktualizacji obiektów.
5. Uprawnienie usuwania jest potrzebne tylko dla testu zapisu z opcją `Usun po tescie`.
6. W PicSyncra otwórz `Ustawienia > Pimcore`.
7. Pierwsza konfiguracja jest czteroetapowym kreatorem dla administratora: połączenie, klasa i folder obiektów, pola produktu oraz test i zapis.

Kreator potrafi pobrać klasy, foldery z drzewa `Objects` oraz pola klasy. Ręczne wpisanie klasy albo parenta jest tylko awaryjnym fallbackiem. Folder docelowy oznacza parent w drzewie obiektów Pimcore, a nie katalog zdjęć, assetów ani folder systemu plików.

## Mapowanie pól

EAN musi być mapowany jako wymagane pole. Wyszukiwanie EAN obejmuje całą skonfigurowaną klasę, niezależnie od folderu. Folder docelowy jest używany tylko podczas tworzenia nowego obiektu.

Dla tekstowego pola mapowania przycisk `Konstruuj` otwiera kreator automatycznej wartości. Szablon może korzystać z danych produktu, innych mapowań Pimcore, funkcji tekstowych, grup warunkowych oraz opcjonalnego tłumaczenia. Zmiany są zapisywane razem z ustawieniami Pimcore.

Przykład szablonu:

```text
{NAZWA} - {TYP} {KOLOR 1}(/{KOLOR 2})(/{KOLOR 3})
```

Tekst i znaki poza placeholderami są kopiowane do wyniku. Grupa `(...)` znika w całości, jeżeli któryś zawarty w niej placeholder jest pusty. Wielkość zapisu aliasu steruje wielkością liter (`{NAZWA}`, `{Nazwa}`, `{nazwa}`), a funkcje dopisuje się po `|`, np. `{Nazwa|trim|upper}`.

Dostępne funkcje: `keep`, `trim`, `normalize_spaces`, `upper`, `lower`, `title`, `capitalize`, `replace`, `default`, `substring`, `truncate`, `strip_diacritics`, `slug`, `number`, `filled`, `any_filled`, `count_filled` i `if_filled`.

### Walidacja OCR

Przy mapowaniu pola zaznacz `Porównuj wynik z OCR`, aby kontrolować ręcznie wpisaną albo wyliczoną wartość względem wszystkich aktualnie wybranych slotów OCR. Porównanie normalizuje przecinek do kropki, ale zachowuje całą część dziesiętną: `23,4` i `23.4` są zgodne, natomiast `23,4` i `23` nie. Każdy znak specjalny jest traktowany jako `?`: `120/140` oraz `120-140` są więc zgodne, a `120--140` pozostaje odrębnym `120??140`.

Gdy gotowy wynik OCR nie pasuje, pole jest oznaczone na czerwono. Podpowiedź pokazuje wszystkie wartości znalezione na zdjęciach, a przyciski ✓ i × odpowiednio potwierdzają wpis albo przywracają poprzednią wartość (lub czyszczą nowe pole). Obraz jest analizowany wyłącznie lokalnie; nie trafia do zewnętrznego API.

Jednorazowo zainstaluj lokalny OCR w środowisku aplikacji:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-vision.txt
```

Jeżeli w slocie nie ma obrazu albo OCR nie jest dostępny, wynik pozostaje bez automatycznego potwierdzenia. OCR zbiera wszystkie wartości liczbowe ze wskazanych slotów; nie przypisuje ich do szerokości, głębokości ani wysokości.

### Tester OCR i warianty EXE

Administrator może sprawdzić jakość odczytu w `Ustawienia > OCR`, wskazać sloty do zbierania danych i uruchomić test obrazu. Tester pokazuje na żywo sektory wykryte przez profil szybki oraz kolejne wycinki przekazywane do profilu dokładnego; można poprosić o zatrzymanie po bezpiecznym zakończeniu bieżącego etapu. Ten sam proces OCR obsługuje tester, początkowe skanowanie slotów i dopracowywanie wycinków.

Przy włączonych obu profilach każdy wiersz diagnostyki ma dwie sparowane kolumny: po lewej odczyt szybkiego modelu, a po prawej odczyty dokładnego modelu z **tego samego wycinka**. Widok na żywo i wynik końcowy mają ten sam układ. Najechanie kursorem lub fokus wiersza podświetla odpowiadające pola na obrazie i pokazuje surowy tekst, wartość porównawczą, pewność, pole źródłowe, faktyczny wycinek, pola wynikowe oraz czas szybkiego OCR, przygotowania wycinka, dokładnego OCR i całego przebiegu. Podpisy pól są rozmieszczane kolejno nad, pod, z prawej lub lewej strony, a następnie na wolnej krawędzi obrazu, aby się nie nakładały.

Pole `Skanuj dokladnym modelem przy pewnosci szybkiego do (%)` ma suwak i pole liczbowe od 0 do 100; domyślna wartość to `99`. Dokładny model skanuje wycinek, gdy pewność szybkiego modelu jest **mniejsza lub równa** progowi. Dlatego `100` skanuje wszystkie wycinki (także odczyt o 100%), a `50` tylko odczyty do 50%. Wycinek zawsze pochodzi z regionu szybkiego modelu; otrzymuje symetryczny margines równy 25% dłuższego boku, zaokrąglony do pikseli i ograniczony do 8–64 px przed przycięciem do granic obrazu. Pominięcie przez próg, pusty wynik dokładnego modelu i niepoprawny region są wyświetlane z konkretną przyczyną, a nie jako pusta kolumna.

Limit CPU jest twardym limitem procesu OCR przez Windows Job Object i obowiązuje przez całą pracę modelu. Próg `Nie uruchamiaj powyżej CPU` jest niezależną bramką dla następnego etapu/zadania. RAM można ustawić jako procent lub GB **aktualnego użycia**, a aktywność dysku jako procent czasu I/O (nie zajętego miejsca). Przekroczenie RAM/dysku spowalnia OCR między etapami; uruchomione wywołanie modelu nie jest brutalnie przerywane. Kolejka działa od ostatniej aktywności użytkownika przez 60 minut i każde zakończone zadanie dodaje następne 30 minut.

Karta pokazuje także wersję użytego silnika PaddleOCR, nazwę i wariant modelu (`lang=en`), stan modelu oraz odnośnik do oficjalnego projektu na GitHubie. Test używa wyłącznie lokalnego silnika i tymczasowego cache uploadu aplikacji.

### Kolejka dopracowywania OCR

W głównym widoku, pod zwykłą kolejką zadań po lewej stronie, widoczna jest
krótka kolejka dopracowywania OCR. Ma najwyżej pięć pozycji i pokazuje tylko
wycinek oraz wynik; `+N kolejnych` oznacza dalsze oczekujące pozycje. Wynik
ukończonego wycinka i pomocniczy plik znikają po 10 sekundach. Wycinek dostaje
8 px marginesu z każdej strony, jeżeli mieści się w obrazie, a jego podgląd nie
jest obcinany do kwadratu.

Administrator widzi kolejkę zawsze; przełącznik w `Ustawienia > OCR` pozwala
pokazać ją zwykłym użytkownikom. Przeglądanie ustawień, danych i Pimcore nie
blokuje skanowania w tle. Okres bezczynności resetują wyłącznie upload lub
zamiana zdjęcia, przeniesienie slotu, usunięcie slotu, zapis przez
`Synchronizuj`/`Aktualizuj` oraz rozpoczęcie wczytywania produktu albo zdjęć.
Usunięty slot anuluje oczekujące wycinki tego samego obrazu.

Są cztery proste pliki BAT do budowania:

```powershell
.\Generator exe\BUILD_ALL_EXE.bat
.\Generator exe\BUILD_LOCAL_EXE.bat
.\Generator exe\BUILD_WEB_EXE.bat
.\Generator exe\BUILD_WEB_EXE_OCR.bat
```

`BUILD_ALL_EXE` buduje wszystkie trzy wydania. `BUILD_LOCAL_EXE` tworzy lokalny EXE bez OCR. `BUILD_WEB_EXE` tworzy lżejsze web EXE bez funkcji, interfejsu i zależności OCR. `BUILD_WEB_EXE_OCR` tworzy web EXE z silnikiem i modelami OCR osadzonymi w paczce, gotowy do pracy offline. Wariant offline jest wyraźnie większy.

### Sprawdzanie wypełnienia pól

`filled` zamienia wypełnione pole na `1`, a puste pole na `0`. Dzięki temu można policzyć paczki po wpisanej szerokości:

```text
{PIMCORE:parcel_1_width|filled}+{PIMCORE:parcel_2_width|filled}+{PIMCORE:parcel_3_width|filled}+{PIMCORE:parcel_4_width|filled}+{PIMCORE:parcel_5_width|filled}+{PIMCORE:parcel_6_width|filled}+{PIMCORE:parcel_7_width|filled}+{PIMCORE:parcel_8_width|filled}+{PIMCORE:parcel_9_width|filled}+{PIMCORE:parcel_10_width|filled}+{PIMCORE:parcel_11_width|filled}
```

`any_filled` zwraca `1`, gdy jego pole lub któreś z dodatkowych pól ma wartość. Dodatkowe źródła wpisuje się w cudzysłowach. Przykład dla paczki, która ma być liczona po dowolnym wymiarze:

```text
{PIMCORE:parcel_1_depth|any_filled:"PIMCORE:parcel_1_height","PIMCORE:parcel_1_weight","PIMCORE:parcel_1_width"}
```

`count_filled` liczy wszystkie wypełnione pola w tej samej składni. `if_filled:"tekst gdy jest","tekst gdy brak"` zwraca jeden z dwóch tekstów zależnie od tego, czy dane pole jest wypełnione.

## Testy i zapis

`Sprawdz konfiguracje` wykonuje test read-only i pokazuje szczegóły techniczne w rozwijanych blokach.

`Testowo dodaj obiekt` pobiera za każdym razem nowe, unikalne i nadal edytowalne wartości. Opcja `Usun po tescie` próbuje potem usunąć obiekt.

Normalne tworzenie brakującego produktu z głównego panelu automatycznie przelicza zapisane szablony i publikuje obiekt. Edycja pokazuje aktualne wartości bez nadpisywania; tylko `Przelicz pole` stosuje szablon do wybranego pola. Zapis odrzuca zmianę, jeżeli obiekt został w międzyczasie zmieniony w Pimcore.

Zwykli użytkownicy nie widzą kreatora ani ustawień Pimcore. Gdy integracja jest wyłączona albo konfiguracja jest niekompletna, panel nie pokazuje kontrolek runtime Pimcore, nie odpala lookupu EAN i nie pokazuje promptu tworzenia produktu.

## Profile SQL dla Pimcore

Domyślny profil SQL jest zawsze używany przez Sloty. Dodatkowe profile SQL można tworzyć w zakładce ustawień SQL i wybierać tylko w mapowaniach Pimcore, których pole szablonu jest ustawione na `SQL`.

W tym trybie mapowanie używa osobnego pola zapytania SQL i zapisuje pierwszą kolumnę pierwszego wiersza do formularza Pimcore. Formularze tworzenia i testu stosują wyniki SQL tylko do pustych pól. Formularze edycji wymagają jawnego przeliczenia i pokazują różnice względem wartości ręcznie wpisanej przed zastosowaniem wyliczonej wartości.

## Sekrety i audyt

Klucz API jest przechowywany w postaci zaszyfrowanej. Standardowy endpoint ustawień ani logi operacji Pimcore nigdy go nie zwracają.

Operacje tworzenia, testu i edycji zapisują zredagowany audyt z ID, kluczem albo ścieżką obiektu, gdy są znane. Jeżeli automatyczne usuwanie obiektu testowego się nie powiedzie, użyj danych z raportu operacji, aby usunąć go ręcznie w Pimcore.
