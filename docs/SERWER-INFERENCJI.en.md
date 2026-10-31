# Central model server (administrator's guide)

[Polski](SERWER-INFERENCJI.md) · **English**

One machine on the local network holds the models and detects personal data, while the users'
applications send text to it over the network. The user does not download model packages.

## What the server sees and what it does not

| The server sees | The server does NOT see and does not do |
|---|---|
| text sent for detection (in memory, for the duration of processing) | map keys, maps, restoring data |
| text length, level, time (in the log, without content) | writing text to disk, content in logs |
| | fixed lists, corrections and result checks (these stay with the user) |

The document is loaded, hidden and encrypted (the map) on the user's computer.
Text fragments go to the server, and a list of spans (start, end, type) comes back.
That is why the server may listen on the local network, unlike the user's application,
which listens only on `127.0.0.1`.

## Requirements

- Python with Niewidka (`uv sync` in the repository folder), models downloaded to the models directory
  (the same packages as on the user's side, verified with SHA-256 checksums).
- A processor is enough (default). For an NVIDIA card: `pip install onnxruntime-gpu`
  (instead of `onnxruntime`), with a driver and CUDA matching the onnxruntime release. On Windows
  with a card from another vendor: `onnxruntime-directml`.
- A TLS certificate (see below) or an isolated network.

## Starting in 3 steps

1. Copy `konfiguracja/serwer-inferencji.przyklad.toml` as `serwer-inferencji.toml`
   and adjust the paths. Every option has a comment there.
2. Generate a token: `python -m niewidka.serwer_inferencji nowy-token /etc/niewidka/token`.
3. Start: `python -m niewidka.serwer_inferencji --konfig serwer-inferencji.toml`.

At startup the server loads all the specified levels. Missing models, a missing token, no GPU
with `urzadzenie = "gpu"`, or a network address without TLS end startup with a clear message
(exit code 2). The server never starts half-ready.

## CPU or graphics card

In `[modele]`: `urzadzenie = "auto"` (best available, falling back to the processor),
`"cpu"` or `"gpu"` (CUDA, and on Windows also DirectML; without a GPU the server does not start).
`watki` limits the computation threads on the processor (0 = automatic), `rownolegle` sets
how many texts are processed at the same time. The provider actually used is visible in `GET /v1/stan`.

## Token and users

The token is a file (base64, 0600 permissions on Linux). The server checks it against the
`Authorization: Bearer <token>` header with a timing-attack-resistant comparison. Without a token
file the server will not start. The token value is never written to the TOML file or to logs.

Distribution: give users the same file through a secure channel (a share with permissions,
a password manager, a deployment tool) and point to it in their `niewidka.toml`
(`konfiguracja/klient-web.przyklad.toml`, section `[inferencja]`). To rotate the token:
generate a new file, replace it on the server and on the users' machines, restart the server.

## TLS with an internal certificate authority

1. Issue a server certificate in the internal certificate authority for the name users use
   (e.g. `niewidka-serwer.firma.local`).
2. Set `cert_plik` and `klucz_plik` (PEM) in `[siec]`; keep the private key accessible
   only to the service account.
3. Give users the CA file (PEM) and point to it in `ca_plik`, unless the CA is already trusted
   in their system. Certificate verification on the application side is always on.

Outside loopback, a server without TLS refuses to start. Only for an isolated network or a test
can you set `zezwol_bez_tls = true` (a warning appears in the log), and the user
must then have `zezwol_bez_tls = true` in `[inferencja]`.

## systemd service (Linux)

```ini
# /etc/systemd/system/niewidka-serwer.service
[Unit]
Description=Niewidka, serwer modeli
After=network-online.target

[Service]
User=niewidka
WorkingDirectory=/opt/niewidka
ExecStart=/opt/niewidka/.venv/bin/python -m niewidka.serwer_inferencji --konfig /etc/niewidka/serwer-inferencji.toml
Restart=on-failure
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

`systemctl enable --now niewidka-serwer`. Logs: `journalctl -u niewidka-serwer`.

## Scheduled task (Windows)

```
schtasks /Create /TN "Niewidka serwer" /SC ONSTART /RU SYSTEM /RL HIGHEST ^
  /TR "C:\Niewidka\.venv\Scripts\python.exe -m niewidka.serwer_inferencji --konfig C:\Niewidka\serwer-inferencji.toml"
```

Put the token file and the TLS key in a directory accessible only to the service account.

## Interface (for deployment engineers)

- `POST /v1/wykryj`, body `{"tekst": "...", "poziom": 1}`; response
  `{"zakresy": [{start, koniec, typ, pewnosc, zrodlo, suma_kontrolna, podejrzana}]}`.
  Errors: 401 (token), 413 (text above `max_tekst_mb`), 422 (level not in the list), 503 (queue full).
- `GET /v1/stan`: `{wersja, poziomy, urzadzenie}`.

## What the user sees when the server goes down

The application does not hide a document "without a model": it answers with the message „Serwer modeli nie
odpowiada” (Model server is not responding) (code 503) and returns nothing. The status screen then shows
that no levels are available.
Each document is many short requests (one per paragraph), so network latency
translates into hiding time; keep the server on the same local network as the users.
