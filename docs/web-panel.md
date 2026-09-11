# Panel webowy w LAN

Repozytorium zawiera lokalny panel webowy dla użytkowników w tej samej sieci LAN. Panel nie zastępuje aplikacji desktopowej; zapisuje pliki do tej samej struktury `_ZDJECIA PRZEROBIONE_` i korzysta z tych samych ustawień roboczych.

## Zakres

Panel pozwala użytkownikom w przeglądarce:

- logować się i wgrywać zdjęcia do skonfigurowanych slotów,
- wyszukiwać i wczytywać wpisy po EAN,
- dopasowywać produkt po nazwie, typie i modelu,
- oglądać miniatury slotów i podglądy lokalne albo cache'owane FTP,
- przeciągać pliki między slotami,
- czyścić pojedyncze sloty,
- widzieć status LOCAL/FTP/SQL,
- wysyłać zdjęcia na FTP po przetworzeniu,
- zapisywać nowe i istniejące wpisy Excel,
- korzystać z historii webowej grupowanej po EAN,
- edytować listy, ustawienia, sloty i mapowanie SQL,
- wykonywać testy folderów lokalnych, FTP i SQL,
- zarządzać użytkownikami oraz hasłami.

Logowanie jest domyślnie włączone. Pierwsze konto to `admin` / `admin`. Hasło należy zmienić w **Ustawienia -> Użytkownicy** przed używaniem panelu poza zaufanym testem.

## Instalacja zależności

```powershell
python -m pip install -r requirements-web.txt
```

## Uruchomienie

Na Windows można użyć skryptów:

- `START_WEB.bat` - uruchamia panel, doinstalowuje brakujące zależności webowe, otwiera przeglądarkę i pokazuje adres LAN.
- `STOP_WEB.bat` - zatrzymuje panel uruchomiony na skonfigurowanym porcie.

Po potwierdzeniu zamknięcia w lokalnym menedżerze program kończy serwer panelu oraz kontrolowane procesy launchera. Jeżeli Windows nie zwolni portu, menedżer pozostaje otwarty i pokazuje błąd, aby można było ponowić zatrzymanie.

Ręczne uruchomienie backendu:

```powershell
python -m uvicorn picsyncra.web.app:app --host 0.0.0.0 --port 8000
```

Z innego komputera w tej samej sieci otwórz:

```text
http://IP_SERWERA:8000
```

Ustawienia są widoczne tylko dla użytkowników webowych z rolą `admin`.

## Pliki z podobnych produktów

Administrator włącza wykrywanie w **Ustawienia -> Podobne produkty** i wybiera sloty, dla których panel ma proponować pliki. Wyszukiwanie obejmuje wyłącznie lokalne warianty koloru tego samego produktu. Znalezione kandydaty nie są zapisywane ani wysyłane automatycznie.

Przy slocie znalezisko jest dostępne pod oznaczeniem **PODOBNE**, które przełącza podgląd na proponowany plik. Przycisk **Otwórz** otwiera aktualnie wybrane źródło podglądu. Dopiero **Wczytaj z podobnego** świadomie przyjmuje jeden plik do slotu; dopiero wtedy zostanie uwzględniony przy zwykłym zapisie lub przetwarzaniu produktu.

## Historia i obserwowalność administratora

Widok **Historia** pokazuje przebieg operacji produktu. Przycisk **Zmiany** otwiera bezpieczny podgląd wartości przed i po operacji, zmian plików, czasu wykonania oraz identyfikatora powiązanego zadania.

Administrator ma także widok **Logi** z kartami **Na żywo**, **Krytyczne**, **Błędy**, **Ostrzeżenia** i **Zadania**. Strumień na żywo obejmuje zdarzenia z ostatnich 24 godzin. Powiązane zdarzenia są grupowane w incydenty i zadania, a nieprzeczytane wpisy są sygnalizowane według najwyższego priorytetu: krytyczne, błędy, a następnie ostrzeżenia.

Karta incydentu pokazuje także ostatni stan jego powiadomienia e-mail: **Oczekuje**, **Wysłano**, **Fallback**, **Pominięto** albo **Błąd**. Po rozwinięciu widać wyłącznie kanał, czas lub kod próby, bezpieczny opis i liczbę odbiorców. Adresy odbiorców, treść wiadomości oraz dane konfiguracyjne nie są zwracane przez API logów. Nieudana wysyłka poczty nie zmienia ważności incydentu i nie zasłania pierwotnego błędu operacyjnego.

## Powiadomienia e-mail

Administrator konfiguruje pocztę w **Ustawienia -> Poczta**. Jedna konfiguracja przechowuje dwa możliwe kanały:

- **Microsoft Entra / Graph**: Tenant ID, Client ID, Client Secret oraz adres nadawcy (**Od**),
- **SMTP**: host, port, tryb połączenia `TLS`, `STARTTLS` albo `bez szyfrowania`, opcjonalny login i hasło oraz adres i nazwa nadawcy.

Należy wybrać kanał podstawowy. Opcjonalny fallback wykonuje najwyżej jedną natychmiastową próbę drugim kanałem, gdy kanał podstawowy jest niedostępny. Obie próby należą do tej samej logicznej wiadomości. Hasła i Client Secret są szyfrowane w istniejącej bazie SQLite i nie są odsyłane do przeglądarki.

Dla każdego poziomu **Informacja**, **Ostrzeżenie**, **Błąd** i **Krytyczny** dostępny jest osobny blok reguł. W każdym bloku można:

- włączyć lub wyłączyć wysyłanie,
- podać listę adresów rozdzielonych przecinkami,
- zaznaczyć wysłanie także do użytkownika powiązanego z incydentem, jeżeli jego konto ma uzupełniony adres e-mail.

Powtarzające się wystąpienia tego samego incydentu są grupowane, a kolejne powiadomienie może zostać utworzone najwcześniej po 15 minutach. Przycisk wysyłki testowej pozwala sprawdzić kanał podstawowy, Entra albo SMTP oraz opcjonalny fallback. Test nie tworzy incydentu ani trwałego zadania dostawy.

Integracja Graph korzysta z uprawnienia aplikacyjnego Microsoft Graph `Mail.Send`. W dzierżawie Microsoft Entra administrator musi nadać tej aplikacji zgodę administracyjną (**admin consent**), a skonfigurowany adres **Od** musi być skrzynką, z której aplikacja może wysyłać. Dla SMTP można użyć dowolnego dostawcy, między innymi firmowej poczty, Gmaila, Onetu lub O2. Dostawca może wymagać włączenia SMTP i wygenerowania osobnego hasła aplikacji zamiast zwykłego hasła do konta. Preferowane jest połączenie TLS albo STARTTLS; tryb bez szyfrowania powinien być używany wyłącznie w kontrolowanej sieci.

## Stan backendu w nagłówku

Obok nazwy aplikacji widoczny jest tekstowy stan backendu z kropką i medianą czasu odpowiedzi z pięciu ostatnich udanych pomiarów. Szczegóły po najechaniu, ustawieniu fokusu lub kliknięciu pokazują stan backendu, SQLite, procesora zadań oraz ostatni znany stan FTP, SQL, profili SQL i Pimcore. Panel pokazuje wyłącznie znormalizowane stany, bez ścieżek, sekretów i treści wyjątków.

- **Online**: lokalne komponenty odpowiadają prawidłowo, mediana jest poniżej 300 ms i brak stanu ograniczonego.
- **Wolno**: mediana wynosi co najmniej 300 ms albo któryś komponent ma stan ograniczony.
- **Krytyczny**: backend lub SQLite zgłasza problem albo mediana przekracza 1000 ms.
- **Offline**: trzy kolejne próby pobrania stanu zakończyły się błędem; szczegóły zachowują ostatni znany stan komponentów z poprzedniego udanego pomiaru.

Pomiar jest wykonywany co pięć sekund. Przeglądarka wstrzymuje go w ukrytej karcie i odświeża stan natychmiast po powrocie.

## Strefa czasu panelu

Administrator wybiera w **Ustawienia -> Aplikacja** jedną strefę czasu IANA wspólną dla całej instalacji. Wybrana globalna strefa czasu obowiązuje wszystkich użytkowników panelu, a bezpieczną wartością domyślną jest `UTC`. Przykładowa strefa `Europe/Warsaw` automatycznie stosuje czas standardowy i letni CET/CEST zgodnie z regułami IANA; administrator nie przełącza jej ręcznie przy zmianie czasu.

To ustawienie zmienia wyłącznie sposób prezentowania dat i godzin w panelu. Nie modyfikuje znaczników czasu przechowywanych w UTC, progów monitorowania ani kolejności zdarzeń.

## Zasoby backendu

Pod stanem backendu znajduje się kompaktowy wskaźnik odświeżany co pięć sekund. Pierwszy wiersz, **Zasoby systemu**, pokazuje CPU, RAM i aktywność dysku całego hosta: procent czasu obsługi operacji I/O, nie stopień zapełnienia przestrzeni dyskowej. Drugi wiersz pokazuje łączne CPU, RAM i transfer dyskowy I/O bieżącego procesu backendu oraz, wyłącznie podczas ograniczonego testu rzeczywistego, zarejestrowanego pomocniczego procesu testowego. Nie obejmuje dowolnego drzewa procesów potomnych. Szczegóły zawierają też liczbę aktywnych i oczekujących zadań i klientów. **Aktywni w ostatnich 3 min** to liczba rozpoznanych klientów panelu, którzy w tym okresie wykonali obsłużone żądanie HTTP; nie oznacza liczby jednocześnie otwartych połączeń ani obecnie zalogowanych osób.

Administrator może w **Ustawienia -> Monitor** ukryć sam wskaźnik oraz ustawić progi CPU, RAM i I/O backendu. Metryki hosta służą wyłącznie do diagnozy; progi i alerty dotyczą wyłącznie metryk backendu. Domyślne progi to odpowiednio 25%, 20% i 8 MiB/s; dopuszczalne zakresy to 10–90%, 1–90% i 1–256 MiB/s. Przekroczenie oznacza wartość większą od progu. Pierwsze przekroczenie jest widoczne jako **Alarm oczekujący (1. próbka)**. Dopiero gdy monitor zobaczy przekroczenie w dwie kolejne próbki, etap zmienia się na **Alarm aktywny (2 próbki)**, alarm zostaje zatrzaśnięty i powstaje incydent `backend.resource_high`; pojedynczy skok nie tworzy incydentu. Zatrzask zapobiega powtarzaniu tego samego alertu podczas ciągłego przeciążenia i jest zwalniany po dwóch kolejnych próbkach na poziomie nieprzekraczającym progu.

Wartość **brak danych** oznacza, że dany licznik nie jest dostępny; dotyczy to w szczególności licznika aktywności dysku podczas jego rozgrzewania albo gdy Windows nie udostępnia poprawnego odczytu. Brak wartości nie jest zerem ani informacją o wolnej przestrzeni. Przerywa rozpoczętą serię wysokich albo normalnych próbek, ale sama nie tworzy ani nie zwalnia zatrzaśniętego alertu. API udostępnia tylko dozwolone, znormalizowane metryki i krótki powód niedostępności. Nie zwraca ścieżek katalogów tymczasowych, sekretów ani treści wyjątków.

Testy monitora wymagają autoryzacji administracyjnej:

- **Bezpieczna symulacja** nie obciąża zasobów i nie tworzy incydentu. Zapisuje wyłącznie informacyjne zdarzenie testowe z bezpiecznym, bieżącym obrazem metryk i zwraca pomyślny wynik trybu `safe` tylko po trwałym zapisie tego zdarzenia. Brak zapisu zwraca `persistence_failed`.
- **Test rzeczywisty** uruchamia osobno kontrolowane obciążenie CPU, RAM albo dysku. W danej chwili może działać tylko jeden test. Trwa najwyżej około 20 sekund i używa procesu roboczego z twardymi limitami 25% CPU, 256 MiB RAM i 128 MiB danych dyskowych. Na czas testu monitor wyznacza osobny, osiągalny próg z bieżącej wartości i bezpiecznego limitu testu; nie zmienia zapisanego progu produkcyjnego, więc jego normalna wartość nie blokuje CPU ani RAM. Wytworzone obciążenie obserwuje normalny, pięciosekundowy próbnik i ocenia ten sam detektor progów co podczas zwykłej pracy. Sam endpoint testowy nie tworzy incydentu. Błąd procesu roboczego jest zapisywany jako zdarzenie `backend.resource_test_failed` i przekazywany do mechanizmu powiadomień, ale odpowiedź API nie zawiera ścieżki, sekretu ani tracebacku. Po każdym wyniku monitor próbuje zatrzymać proces i usunąć katalog `picsyncra_resource_test_*`; gdy sprzątanie się powiedzie, rejestracja testu jest zwalniana. Wynik `cleanup_failed` oznacza, że monitor zachowuje rezerwację procesu lub katalogu i blokuje następny test rzeczywisty, dopóki późniejsze zatrzymanie lub ponowiona próba sprzątania nie zakończy się powodzeniem. Sprzątanie nie jest więc gwarantowane przy każdym wyniku.

Wynik testu rzeczywistego rozróżnia wykryte przekroczenie, brak wykrycia, błąd trwałego zapisu zdarzenia (`persistence_failed`), błąd uruchomienia lub wykonania, przekroczenie czasu, anulowanie i błąd sprzątania. Wynik **wykryto** oraz alert pojawiają się tylko wtedy, gdy detektor zwykłego próbnika sam zarejestruje rzeczywiste przekroczenie progu backendu w dwie kolejne próbki i trwale zapisze normalne zdarzenie `backend.resource_high`.

## Diagnostyka OCR

W `Ustawienia > OCR` tester łączy wynik szybkiego modelu z wynikiem dokładnego
modelu dla tego samego wycinka. Dwie kolumny są widoczne podczas skanowania i
po jego zakończeniu. Po najechaniu wiersza widoczne są surowe odczyty, pola,
pewności, przyczyna decyzji i czasy etapów.

Próg dokładnego skanowania ma zakres 0-100 i działa jako `pewność <= próg`.
Domyślne `99` pomija tylko odczyty 100%; `100` skanuje wszystkie wycinki.
Porównanie OCR zachowuje części dziesiętne i uznaje `23,4` oraz `23.4` za tę
samą wartość. Wycinek dokładnego modelu powstaje z pola szybkiego modelu,
z symetrycznym marginesem 25% dłuższego boku (minimum 8 px, maksimum 64 px).

### Kolejka dopracowywania OCR

Kolejka jest widoczna bezpośrednio pod zwykłą kolejką po lewej stronie głównego
widoku. Pokazuje najwyżej pięć pozycji: sam wycinek i wynik OCR; licznik
`+N kolejnych` informuje o dalszych zadaniach. Ukończony wynik oraz jego
pomocniczy wycinek są usuwane po 10 sekundach, więc nie zalegają w panelu ani
w cache. Wycinek zawiera dodatkowe 8 px kontekstu z każdej strony, gdy pozwala
na to granica obrazu, a miniatura zachowuje proporcje bez przycinania.

Administrator widzi tę kolejkę zawsze. W `Ustawienia > OCR` może włączyć
widoczność także zwykłym użytkownikom. Samo przeglądanie danych, ustawień,
Pimcore, logów i statusów nie zatrzymuje pracy kolejki. Bezczynność resetują
wyłącznie upload lub zastąpienie zdjęcia, przeniesienie albo zamiana slotów,
usunięcie slotu, `Synchronizuj`/`Aktualizuj` i rozpoczęcie wczytywania produktu
lub jego zdjęć. Usunięcie slotu anuluje oczekujące wycinki tego samego obrazu.

## Bezpieczeństwo LAN

Panel jest przeznaczony do zaufanej sieci LAN albo VPN. Nie wystawiaj tego panelu bezpośrednio do publicznego internetu bez dodatkowej warstwy zabezpieczeń, aktualizacji haseł, kontroli dostępu i przeglądu konfiguracji serwera.

## Zrzuty ekranu

<img width="1912" height="922" alt="Panel webowy" src="https://github.com/user-attachments/assets/1cdeae0d-db34-488f-9565-ad791805cf83" />

<img width="1912" height="922" alt="Panel webowy" src="https://github.com/user-attachments/assets/6f66ecca-6e23-40c5-a46e-63693d1eea40" />

<img width="1283" height="631" alt="Panel webowy" src="https://github.com/user-attachments/assets/e7a44084-5694-4968-a632-6465818b65f2" />

<img width="1275" height="864" alt="Panel webowy" src="https://github.com/user-attachments/assets/613d7141-305a-436c-a7fd-32f72fbdd50e" />

<img width="1272" height="307" alt="Panel webowy" src="https://github.com/user-attachments/assets/24eabef8-57e5-431a-9945-52e14d0eb63b" />

<img width="1249" height="362" alt="Panel webowy" src="https://github.com/user-attachments/assets/16118148-3323-4868-8038-75825fbfa1ca" />
