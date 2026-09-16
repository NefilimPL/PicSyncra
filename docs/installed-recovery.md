# Odzyskiwanie instalowanej PicSyncra

Jeżeli komputer lub proces zostanie przerwany podczas aktualizacji, kolejny
start oznacza operację jako `recovery_required` i blokuje kolejne aktualizacje.
Nie uruchamiaj ręcznie obu wersji programu ani nie podmieniaj `active.json`.

1. Zachowaj katalog danych, konfiguracji, `backups/operations` i
   `operations.json`.
2. Sprawdź ostatnią kopię operacji i stan aktywnego wydania.
3. Przywróć poprzednie wydanie tylko przez mechanizm odzyskiwania oraz
   zweryfikowaną kopię bazy, gdy migracja zmieniła schemat.
4. Uruchom backend przez zadanie `PicSyncra Controller primary-installation`
   lub lokalny kontroler, nie przez `taskkill`. Kontroler uruchomi WEB z
   wydania wskazanego w `active.json`.

Nieudane odzyskanie pozostawia dane w miejscu do czasu ręcznej analizy.
Zgłoszenie powinno zawierać identyfikator operacji, etap z dziennika i wersję
wydania, bez sekretów ani kopii konfiguracji.
