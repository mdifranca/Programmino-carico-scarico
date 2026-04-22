# Magazzino Lounge Bar

Applicazione web locale con database `SQLite` per gestire:

- anagrafica prodotti
- carico e scarico magazzino
- alert di riordino
- import da `PDF`, `TXT` e `CSV`
- OCR per PDF scannerizzati
- riconoscimento testo tipo `bott`, `bt`, `cass`, `cassa`, `casse`
- export `CSV` e backup `JSON`

## Avvio

1. Apri il terminale nella cartella del progetto.
2. Avvia il server:

```bash
python3 server.py
```

3. Apri nel browser [http://localhost:8000](http://localhost:8000).

## Accesso via internet

Per renderla accessibile davvero via internet serve pubblicarla su un hosting.
Ho preparato il progetto per deploy con Docker e Render:

- [Dockerfile](/Users/m.difranca/Documents/Codex/2026-04-22-fammi-un-programmino-di-carico-scarico/Dockerfile)
- [render.yaml](/Users/m.difranca/Documents/Codex/2026-04-22-fammi-un-programmino-di-carico-scarico/render.yaml)

### Deploy rapido su Render

1. carica questa cartella su GitHub
2. crea un account su [Render](https://render.com)
3. scegli `New +` > `Blueprint`
4. collega il repository
5. Render usera `render.yaml` e creera:
   un servizio web pubblico
   un disco persistente per il database SQLite

Configurazione scelta:

- regione `frankfurt`
- database SQLite su disco persistente Render in `/data`
- OCR PDF compatibile con Linux tramite `pdftotext`, `pdftoppm` e `tesseract`

Alla fine avrai un URL pubblico tipo:

```text
https://magazzino-lounge-bar.onrender.com
```

## Nota importante sul database

Per uso via internet SQLite va bene per partire, soprattutto con disco persistente.
Se poi vuoi multiutente serio, backup migliori e piu affidabilita, il passo successivo giusto e passare a PostgreSQL.

## Logica casse

- prodotti categoria `soft`: cassa predefinita `24`
- prodotti categoria `alcol`: cassa predefinita `6`
- ogni prodotto puo avere una cassa personalizzata

Esempi riconosciuti:

- `Campari 2 cass`
- `3 bott Gin della casa`
- `Tonica premium 1 cassa`
- `6 bt Prosecco DOC`

## File principali

- [server.py](/Users/m.difranca/Documents/Codex/2026-04-22-fammi-un-programmino-di-carico-scarico/server.py)
- [app.js](/Users/m.difranca/Documents/Codex/2026-04-22-fammi-un-programmino-di-carico-scarico/app.js)
- [ocr_pdf.swift](/Users/m.difranca/Documents/Codex/2026-04-22-fammi-un-programmino-di-carico-scarico/ocr_pdf.swift)
