# Dashboard Iteration Plan (Fitur 1-4 + Visual Penuh + Sisa Temuan)

> **For agentic workers:** implement via superpowers:executing-plans, task-by-task, checkbox tracking.

**Goal:** Iterasi kedua dashboard voidlight-office: (Wave 1) preserve state render, lookup subagent nested, visibilitas error, durasi sesi, plus perombakan visual menyeluruh (responsif, token tipografi, disiplin warna, animasi mikro, empty/loading state, split file frontend); (Wave 2) sisa temuan audit: name pool, search global, judul tab dinamis, persist view state, hygiene.

**Baseline:** branch `feat/dashboard` (PR #3), 91 test hijau setelah fix time-bomb fixture.

**Spec induk:** `docs/superpowers/specs/2026-09-26-voidlight-office-design.md`; plan V1: `2026-09-26-voidlight-office.md`. Plan ini menambah, tidak menarik ulang interpretasi lama.

## Interpretasi Spec (pin keputusan iterasi ini)

1. **Preserve state render (Fitur 1):** pendekatan pragmatis, bukan diff-render penuh. (a) Skip render jika snapshot tidak berubah: bandingkan serialisasi `rooms + activity + usage`, abaikan `generated_at` dan `meta` (meta boleh berubah tanpa efek visual utama). (b) Restore scroll `window.scrollY`, `.feed`, `.slideover` di sekitar penggantian innerHTML. STATE accordion/filter sudah persist di objek `STATE`; yang hilang hanya scroll dan stale-click, keduanya ketutup di sini.
2. **Subagent nested (Fitur 2):** backend sudah membangun tree rekursif benar; perbaikan hanya di `findAgent` frontend: telusuri `subagents` secara rekursif, bukan satu level.
3. **Error visibility (Fitur 3):** field agent baru `error_count` = jumlah turn dengan `error_type` terisi + jumlah tool dengan `error_type` terisi. `cancelled_by_user` TIDAK dihitung error (cancel keputusan user). Perilaku status merah dari turn terakhir (pin V1 no. 3) tidak berubah. UI: chip merah `N err` di tile agent + baris kv di slideover; feed sudah menampilkan error via warna dot.
4. **Durasi sesi (Fitur 4):** field agent baru `age_ms` = `now_ms - session.time_created` (None jika `time_created` kosong). Semantik = umur sesi sejak dibuat (wall clock), bukan akumulasi waktu aktif. Format di frontend (`Xs`, `Xm Ys`, `Xh Ym`) konsisten dengan durasi tool yang juga diformat frontend. Tampil di meta tile (setelah nama) dan `umur:` di slideover.
5. **Split file (Visual 7) mendahului perubahan visual:** `index.html` murni markup; CSS pindah ke `styles.css`, JS ke `app.js`. Pemindahan murni tanpa perubahan perilaku, diverifikasi sebelum lanjut. Constraint V1 "satu file index.html" resmi diganti oleh keputusan ini. Server tidak berubah: `StaticFiles(directory=...)` otomatis melayani file baru; inline `onclick` tetap jalan dengan `<script src>` biasa.
6. **Animasi mikro bergantung skip-render:** fade-in/pulse tidak di-restart tiap 3 detik karena render di-skip saat snapshot identik. Konten accordion pakai fade-in, bukan animasi height (innerHTML world, kompleksitas tidak sebanding).
7. **Disiplin warna:** merah eksklusif error; kuning = idle/running/warning; cyan `--accent` eksklusif elemen interaktif + brand. Role badge: hue role dipertahankan untuk pengenalan cepat, tapi kekuatan visual diturunkan via alpha (border + background tinted, bukan border penuh).
8. **Tipografi:** token `--fs-xs..--fs-lg`; ukuran minimum 11.5-12px (naikkan `.role-badge` 10.5px, `.content-label` 10px, `.pre` 11px). `font-variant-numeric: tabular-nums` global supaya angka yang update tiap 3 detik tidak jitter.
9. **Responsif:** `.rooms` pakai `minmax(min(480px, 100%), 1fr)`; breakpoint 980px: main 1 kolom, feed max-height terbatas, topbar wrap. Slideover sudah aman (max-width 90vw).
10. **Skeleton & empty state:** saat `STATE.snap` masih null → skeleton room card ber-shimmer; rooms kosong → empty state dengan subteks arahan. Banner error existing tetap.
11. **Time-bomb fixture:** konstanta `NOW` beku (2026-09-26) + jalur real-clock (`Collector.tick`, CLI snapshot, intelligence scope today) = test pecah setelah TTL lewat. Fixture `NOW` jadi dinamis (`int(time.time() * 1000)`).
12. **Wave 2 keputusan:** name pool diperluas + suffix deterministik saat habis; search global client-side di topbar (nama agent/tool/kata objective); judul tab `(N kerja) Voidlight Office`; persist `filterRoom`/`expandedAgent` ke localStorage; hygiene: disable `/docs` + `/redoc`, update README, checkbox plan V1 tetap (arsip, tidak dimodifikasi retroaktif).

## Global Constraints (mewarisi plan V1)

- Semua timestamp epoch milidetik; db ZCode read-only; bind 127.0.0.1.
- Copy UI bahasa Indonesia kasual, tanpa em dash.
- Conventional commits; test command `python -m pytest` dari root worktree.
- Match gaya existing: dict-based, `.get`, docstring Indonesia, f-string hanya dengan placeholder, tanpa TODO stub.

---

### Task 1: Fix time-bomb fixture timestamp (done di awal eksekusi)

- [x] `tests/test_collector.py`: `NOW` dinamis dari `time.time()`.
- [x] `tests/test_cli.py`: `NOW` dinamis + `import time`.
- [x] `tests/test_server.py`: `now` di `test_intelligence_endpoint` dinamis.
- [x] `python -m pytest` 91 passed.

### Task 2: Split static frontend (Visual 7)

- [ ] Ekstrak CSS → `src/voffice/static/styles.css`, JS → `src/voffice/static/app.js`.
- [ ] `index.html` jadi markup + `<link rel="stylesheet" href="styles.css">` + `<script src="app.js"></script>`.
- [ ] Verifikasi identitas perilaku (server 8789 + halaman render normal).

### Task 3: Lookup subagent rekursif (Fitur 2)

- [ ] `findAgent` di app.js telusuri subagents rekursif.

### Task 4: Field backend error_count + age_ms (Fitur 3-4)

- [ ] `build_agent` (src/voffice/collector.py): tambah `error_count`, `age_ms`.
- [ ] Test baru di `tests/test_collector.py`: hitungan turn error + tool error, cancelled tidak terhitung, age_ms normal, age_ms None tanpa time_created.

### Task 5: Frontend preserve state + chip error + durasi (Fitur 1, 3, 4)

- [ ] `tick()`: skip render jika signature snapshot identik.
- [ ] `render()`: simpan + restore scroll window/feed/slideover.
- [ ] `agentRow`: chip `N err` (hanya jika > 0) + durasi sesi di meta; slideover: kv `umur` + `error`.

### Task 6: Visual pass (V1-V6)

- [ ] Token tipografi + naikkan ukuran minimum; tabular-nums global.
- [ ] Role badge tinted alpha; merah eksklusif error.
- [ ] Responsive: `minmax(min(480px, 100%), 1fr)` + breakpoint 980px + topbar wrap.
- [ ] Animasi: pulse dot/avatar kerja, fade-in card + konten accordion, skeleton shimmer konten.
- [ ] Skeleton saat belum ada snapshot; empty state rooms.

### Task 7: Verifikasi Wave 1

- [ ] pytest penuh hijau.
- [ ] Server 8789 + Playwright: desktop + sempit, accordion/state lintas tick, screenshot.

### Task 8: Commit + push Wave 1 → PR #3

### Task 9: Wave 2 implement + verifikasi + push

- [ ] Name pool + suffix deterministik + test.
- [ ] Search global client-side.
- [ ] Judul tab dinamis.
- [ ] Persist filterRoom/expandedAgent ke localStorage.
- [ ] Hygiene: `FastAPI(docs_url=None, redoc_url=None)`, update README.
- [ ] pytest + Playwright + push.
