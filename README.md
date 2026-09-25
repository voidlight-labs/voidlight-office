# voidlight-office

Dashboard lokal buat memantau agent yang jalan di ZCode. Analoginya pandangan
top-down sebuah kantor: setiap project adalah ruangan, setiap agent ZCode adalah
orang yang kerja di dalamnya. Buka di monitor kedua, dilirik dari jauh:
agent mana yang lagi kerja, lagi ngapain, udah jauh gimana.

## Install

Syarat: Python 3.12+, sekali saja setelah clone.

    python -m pip install -e ".[dev]"

## Pakai

    voffice run          # server di 127.0.0.1:8787 + buka browser; Ctrl+C untuk stop
    voffice snapshot     # print JSON snapshot sekali (debug tanpa browser)
    voffice test         # pytest

Flag `voffice run`: `--port N`, `--no-open`, `--db PATH` (override path db ZCode).
`voffice snapshot` juga punya `--db`.

Sumber data: db SQLite ZCode (`~/.zcode/cli/db/db.sqlite`), dibaca strict
read-only. Dashboard tidak menulis ke mana pun dan tidak menyimpan state sendiri.

## Config

Opsional: file `voffice.toml` di folder tempat `voffice` dijalankan. Tanpa file
ini semua default jalan. Contoh ada di root repo.

    [server]
    port = 8787
    poll_interval_seconds = 3

    [status]
    working_max_seconds = 90    # hijau (kerja)
    idle_max_seconds = 900      # kuning (idle); lebih tua = abu (quiet)
    agent_ttl_hours = 24        # sesi lebih tua dari ini tidak tampil

    [rooms]
    rename = { teraflow = "TF" }   # key = nama ruangan hasil derivasi
    hidden = ["zcode-workspace"]   # nama ruangan hasil derivasi

## Cara kerja

Collector thread baca db tiap 3 detik (WAL, read-only, aman selagi ZCode nulis),
bangun snapshot JSON via fungsi murni, server FastAPI menyajikannya di
`GET /api/snapshot`, frontend satu file HTML poll tiap 3 detik. Semua agregasi
di collector; frontend dumb. Fail soft: db hilang/schema berubah/server mati
hanya muncul banner, dashboard tidak crash.

## Test

    voffice test

Semua test pakai fixture db sintetis; tidak butuh db ZCode asli.
