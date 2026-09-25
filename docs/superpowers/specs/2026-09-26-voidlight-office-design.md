# Voidlight Office - Design Spec (V1)

Tanggal: 2026-09-26
Status: Disetujui lewat sesi brainstorming (visual companion), siap masuk tahap implementation plan.

## 1. Ringkasan

Voidlight Office adalah dashboard lokal untuk memantau agent yang berjalan di ZCode. Analoginya: pandangan top-down sebuah kantor, di mana setiap project adalah ruangan kecil milik tim spesifik (team teraflow, team voidlight-codex, dst), dan setiap agent ZCode adalah "orang" yang bekerja di dalam ruangan itu.

Use case utama: dashboard terbuka permanen di monitor kedua (browser, auto-refresh), dilirik dari jauh sambil bekerja. Pertanyaan yang harus terjawab tanpa interaksi apa pun: "agent mana yang lagi kerja, lagi ngapain, dan udah seberapa jauh?"

Sumber data: satu file SQLite milik ZCode (`~/.zcode/cli/db/db.sqlite`), dibaca read-only. Dashboard tidak menulis ke mana pun dan tidak menyimpan state sendiri.

## 2. Keputusan Design (hasil brainstorming, sudah disetujui user)

| Keputusan | Pilihan | Alternatif yang ditolak |
|---|---|---|
| Gaya visual | Soft Rooms (kartu membulat, avatar agent, status ring) | Blueprint floor plan, Isometric game view |
| Layout halaman | Mission Control satu layar: rooms besar kiri, activity feed kanan, strip usage global di atas | Tab di bawah, full-screen + drill-down |
| Kepadatan info agent | Rich: ring status + aktivitas terakhir + model + token + tool calls + sparkline | Minimal, Standard |
| Form factor | Browser di PC, monitor kedua, selalu terbuka | Akses dari HP, TUI terminal |
| Pendekatan teknis | Python + polling 3 detik | Streaming SSE, desktop app Tauri/Electron |
| Nama project | voidlight-office | zcode-office |
| CLI | `voffice` (run / test / snapshot) | command lepas tanpa entry point |

Mockup visual dari sesi brainstorming tersimpan di `docs/superpowers/brainstorm-mockups/` (office-style.html = pilihan gaya, layout.html = pilihan layout, room-detail.html = pilihan kepadatan; file yang dipilih user: soft-rooms, mission-control, rich).

## 3. Sumber Data

Path db (Windows): `C:\Users\khayren\.zcode\cli\db\db.sqlite`. Mode WAL, jadi bisa dibaca sambil ZCode jalan, WAJIB dibuka read-only via URI `file:...?mode=ro`. ZCode terus menulis ke db ini; dashboard hanya pembaca.

Tabel yang dipakai (nama kolom sudah diverifikasi lewat query langsung ke db):

- `session`: `id` (contoh `sess_38c6010e-...` atau `sess_subagent_agent_...`), `parent_id` (terisi berarti subagent), `directory` (path workspace, contoh `C:\Users\khayren\voidlight\teraflow`), `title`, `time_created`, `time_updated`, `time_archived` (terisi berarti archived)
- `session_target`: `session_id`, `objective`, `status`, `token_budget`, `tokens_used`, `summary_title`, `active_run_started_at`, `active_run_last_seen_at`
- `turn_usage`: `session_id`, `turn_id`, `status`, `started_at`, `completed_at`, `input_tokens`, `output_tokens`, `computed_total_tokens`, `error_type`, `error_code`, `cancelled_by_user`
- `model_usage`: `session_id`, `model_id` (contoh `GLM-5.3-Flash`), `provider_id`, `started_at`, `completed_at`, `computed_total_tokens`, `error_type`, `cancelled_by_user`
- `tool_usage`: `session_id`, `turn_id`, `tool_name` (contoh `Bash`, `Edit`), `status`, `started_at`, `completed_at`, `exit_code`, `error_type`, `cancelled_by_user`

Timestamp di db berformat epoch milidetik (diverifikasi: nilai seperti 1790373040121).

## 4. Arsitektur

Tiga komponen, semuanya lokal:

```
db.sqlite (read-only) --> Collector (tiap 3s) --> /api/snapshot (JSON) --> Frontend (poll, render)
```

1. **Collector** (`src/voffice/collector.py`). Background thread, tiap 3 detik membuka db read-only, menjalankan query agregasi, menghasilkan satu objek JSON snapshot. Tidak menyimpan state antar tick; snapshot selalu dihitung fresh. Logika agregasi ditulis sebagai fungsi murni (input: rows/parameter, output: dict) agar mudah dites.
2. **Server** (`src/voffice/server.py`, FastAPI + uvicorn). Dua tugas: menyajikan frontend statis dari `static/`, dan endpoint `GET /api/snapshot` yang mengembalikan JSON snapshot terakhir. Bind `127.0.0.1:8787`. Dependency tambahan hanya fastapi + uvicorn.
3. **Frontend** (`src/voffice/static/index.html`). Satu file, vanilla JS, tanpa build step, tanpa framework. Poll `/api/snapshot` tiap 3 detik, render ulang seluruh dashboard. Sparkline digambar inline SVG. Kecerdasan ada di collector; frontend hanya menerima data final (konsekuensi: upgrade ke SSE nanti tidak mengubah struktur data).

Semua kecerdasan agregasi di collector, frontend bodoh. Ini keputusan yang sengaja diambil agar upgrade transport (SSE) tidak menyentuh struktur data.

## 5. Pemetaan Data

### Ruangan = workspace project

- Sesi dikelompokkan dari kolom `session.directory`: ambil nama folder terakhir sebagai nama ruangan. Contoh: `C:\Users\khayren\voidlight\teraflow` menjadi ruangan "teraflow".
- Kasus khusus: sesi dengan directory di bawah `~\.zcode\workspace\` (nama folder terakhirnya generik seperti `default`) diberi nama ruangan "zcode-workspace".
- Ruangan muncul otomatis saat ada sesi yang memenuhi syarat tampil. Tidak perlu setup.
- Config opsional boleh me-rename atau menyembunyikan ruangan (lihat Section 8).

### Agent = sesi

- Satu sesi = satu agent tile.
- Filter tampil: `time_archived` harus NULL, dan ada aktivitas dalam 24 jam terakhir (aktivitas = max timestamp antara `turn_usage`, `model_usage`, `tool_usage`, atau `time_updated`).
- Sesi dengan `parent_id` terisi = subagent: dirender sebagai chip kecil menempel di tile parent-nya, satu tingkat nesting saja. Ruangan menampilkan "R1 + 3 sub" tanpa tile palsu.

### Ring status agent

Diturunkan dari aktivitas terakhir (max timestamp antara ketiga tabel usage):

| Warna | Arti | Aturan |
|---|---|---|
| Hijau `#22c55e` | Kerja | aktivitas terakhir < 90 detik |
| Kuning `#eab308` | Idle | 90 detik s/d 15 menit, label "idle Xm" |
| Abu `#64748b` | Quiet | > 15 menit, sesi masih ada tapi diam |
| Merah `#ef4444` | Error | turn terakhir berakhir dengan `error_type` terisi atau `cancelled_by_user` |

Catatan aturan merah: prioritas di atas warna lain; dicek dari turn/model/tool usage terakhir sesi. Threshold 90 detik dan 15 menit adalah default yang bisa diubah via config.

### Baris "lagi ngapain"

Dari `tool_usage` terakhir sesi: `tool_name` + status + durasi. Contoh: "Bash: npm test (2s)", "Edit: auth/middleware.ts". Jika tidak ada tool call, tampilkan status turn ("mikir...", "nunggu input").

### Progress & budget

- Per agent: dari `session_target` terbaru sesi itu (urut waktu update). `objective` jadi label, `tokens_used / token_budget` jadi persentase bar. Jika tidak ada target atau budget 0, bar disembunyikan, token tetap tampil.
- Header ruangan: objective dari target paling baru di antara agent-nya, plus akumulasi token seluruh agent.

### Sparkline per agent

20 turn terakhir dari `turn_usage` (urut `started_at`), plot `output_tokens` per turn. SVG polyline sederhana.

### Activity feed (kolom kanan)

30 baris `tool_usage` terbaru lintas semua ruangan, terbaru di atas. Format baris: `[ruangan/agent] tool_name status durasi`. Warna kecil: sukses hijau, gagal merah, jalan kuning.

### Strip usage global (atas)

- Total token hari ini (kalender lokal) dari `model_usage.started_at >= tengah malam` lokal: sum `computed_total_tokens`.
- Pecahan per `model_id`.
- Jumlah agent yang sedang kerja (status hijau).

### Bentuk JSON snapshot

```json
{
  "version": 1,
  "generated_at": 1790373040121,
  "meta": { "db_path": "...", "partial": false, "errors": [] },
  "rooms": [
    {
      "name": "teraflow",
      "directory": "C:\\Users\\khayren\\voidlight\\teraflow",
      "agents": [
        {
          "id": "sess_...",
          "title": "Check Development Progress",
          "short_name": "R1",
          "parent_id": null,
          "status": "kerja|idle|quiet|error",
          "status_detail": "idle 4m",
          "last_activity": 1790373040121,
          "current_tool": "Bash: npm test (2s)",
          "model": "GLM-5.3-Flash",
          "tokens": 128000,
          "tool_calls": 33,
          "sparkline": [120, 340, 90],
          "objective": "migrasi auth",
          "target_used": 80000,
          "target_budget": 130000,
          "subagents": []
        }
      ]
    }
  ],
  "activity": [ { "room": "teraflow", "agent": "R1", "tool": "Bash", "status": "ok", "duration_ms": 2000, "at": 1790373040121 } ],
  "usage": { "today_total": 1200000, "per_model": { "GLM-5.3-Flash": 1200000 }, "working_count": 3 }
}
```

`short_name` (R1, R2, V1) diturunkan deterministik: inisial ruangan + nomor urut per ruangan, stabil per urutan `time_created` sesi. Tujuannya identitas singkat yang kebaca di tile dan feed.

## 6. CLI `voffice`

Project adalah Python package (`pyproject.toml`, console script `voffice = voffice.cli:main`). Syarat sekali saja setelah clone/buat: `pip install -e .` di folder project (user-level, tanpa admin; itulah yang mendaftarkan command `voffice` ke PATH). Python target 3.12+.

```
voffice run        # server di 127.0.0.1:8787 + buka browser otomatis; foreground, Ctrl+C untuk stop
voffice test       # pytest
voffice snapshot   # print JSON snapshot sekali ke stdout (debug tanpa browser)
```

Flag `voffice run`: `--port` (default 8787), `--no-open` (jangan buka browser), `--db` (override path db ZCode; wajib ada untuk testing).

Sengaja tidak ada `voffice stop`: run bersifat foreground, tidak ada daemon.

## 7. Struktur Folder

```
voidlight-office/
  pyproject.toml
  README.md
  voffice.toml              # config default, di-commit
  src/voffice/
    __init__.py
    cli.py                  # argparse, entry point
    collector.py            # query db + fungsi murni agregasi
    server.py               # FastAPI, serve static + /api/snapshot
    static/index.html       # frontend
  tests/
    conftest.py             # fixture db sintetis (subset schema ZCode)
    test_collector.py
  docs/superpowers/
    specs/2026-09-26-voidlight-office-design.md
    brainstorm-mockups/
```

## 8. Config (`voffice.toml`)

Opsional; tanpa file ini semua default jalan. Key dan default:

```toml
[server]
port = 8787
poll_interval_seconds = 3

[status]
working_after_seconds = 90      # batas bawah hijau (aktivitas lebih muda dari ini = hijau)
idle_after_seconds = 900        # 15 menit, batas kuning
agent_ttl_hours = 24            # sesi tanpa aktivitas selebih ini tidak tampil

[rooms]
rename = { }                    # contoh: { "default" = "zcode-workspace" }
hidden = []                     # daftar nama ruangan yang disembunyikan
```

Loader pakai `tomllib` (stdlib, Python 3.11+). Config tidak wajib ada.

## 9. Perilaku Refresh & Umur Data

- Collector tick tiap 3 detik di background thread; query murah (db beberapa MB).
- Frontend fetch tiap 3 detik dan selalu menampilkan umur data ("diperbarui 2s lalu"). Data beku = indikator umur membesar.
- Jika fetch gagal (server mati), tampilkan banner kecil tanpa menghilangkan render terakhir.

## 10. Interaksi (V1, sengaja minim)

- Klik agent tile: panel slide-over berisi objective, progress, daftar turn terakhir dengan token, daftar tool call, breakdown per model. Data dari snapshot yang sama, tidak ada endpoint tambahan.
- Klik header ruangan: activity feed terfilter ke ruangan itu; klik lagi untuk kembali ke semua.
- Tidak ada interaksi lain di V1.

## 11. Error Handling (fail soft)

| Keadaan | Perilaku |
|---|---|
| db sibuk / lock sesaat | Tick dilewati, tick berikutnya sukses (WAL read-only praktisnya tidak pernah keblokir) |
| ZCode mati | Snapshot terakhir tetap tampil, umur data terlihat membesar |
| Schema db berubah (ZCode update) | Query yang gagal dilewati, `meta.partial = true` + `meta.errors` terisi, banner "data parsial" muncul, dashboard tidak crash |
| db tidak ada / path salah | Banner error menyebut path yang dicoba |
| ZCode db kosong baru dibuat | Dashboard tampil kosong dengan pesan "belum ada aktivitas", bukan error |

## 12. Testing

- Logika agregasi (grup ruangan, penamaan ruangan + kasus khusus zcode-workspace, derivasi status beserta boundary 89s/91s/14m/16m, status error, filter archived, nesting subagent, agregasi token, sparkline) = fungsi murni, dites pytest.
- Fixture: db SQLite sintetis dibuat di test dengan subset schema ZCode (tabel + kolom yang dipakai saja), timestamp dikontrol sehingga semua cabang status teruji deterministik.
- Frontend diuji manual (nilainya di visual); collector diuji sampel via `voffice snapshot` terhadap db asli sebagai smoke test manual.
- `voffice test` harus hijau tanpa db ZCode asli (semua test pakai fixture).

## 13. Non-Goals V1

- Tidak ada akses remote (bind 127.0.0.1 saja) dan tidak ada auth.
- Tidak ada penyimpanan histori sendiri; semua dihitung fresh dari db ZCode.
- Tidak ada notifikasi/alert.
- Tidak ada streaming SSE (upgrade path terbuka: struktur snapshot JSON tetap).
- Tidak ada editing apa pun ke db ZCode; dashboard strict read-only.

## 14. Konteks Ekonomi Project (untuk sesi berikutnya)

- Machine: Windows tanpa admin, Git Bash, Python 3.13 dan 3.12 tersedia, node via nvm4w (tidak relevan untuk stack ini).
- User preferensi komunikasi: casual Indonesian, tanpa em dash, technical terms in English.
- Langkah berikutnya setelah spec ini: implementation plan via writing-plans skill, lalu implementasi dengan TDD pada collector.
