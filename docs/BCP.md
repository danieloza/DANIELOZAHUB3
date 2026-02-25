# Business Continuity Plan (BCP) - Danex

## Wstęp
Ten dokument opisuje procedury na wypadek awarii krytycznej.

## 1. Brak Prądu / Internetu
- Uruchom bota na telefonie (LTE).
- Pobierz "Emergency PDF" z czatu (generowany o 7:00).
- Notuj wizyty na kartce, wpisz do systemu po powrocie zasilania.

## 2. Awaria Serwera
- Wejdź na Google Drive -> Folder "Backup".
- Pobierz ostatni plik `.bak`.
- Uruchom skrypt `scripts/restore_drill.py` na zapasowym laptopie.

## 3. Atak Hakerski
- Odłącz serwer od sieci.
- Uruchom `scripts/rotate_secrets.py`.
- Zmień hasła do Telegrama.
