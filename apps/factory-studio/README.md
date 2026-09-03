# Estúdio — Fábrica de imagem

Painel local em Rust da Image Production Factory. Não reimplementa a geração:
dispara o mesmo script Python da corrida em português.

```
cd apps/factory-studio
cargo run
```

A janela abre sozinha. O motor local prefere `http://127.0.0.1:7420/`.
Se essa porta já estiver ocupada, o app escolhe outra e grava o endereço
em `%LOCALAPPDATA%\Estudio\instance.json` (ou `~/.local/share/estudio/`).
Uma segunda abertura foca a janela que já está no ar.

Clientes (ImageGenSource ou outro) devem descobrir o endereço assim:
`GET /api/instance` em `127.0.0.1:7420`, ou o JSON em
`%LOCALAPPDATA%\Estudio\instance.json`.

Requisitos: Rust, Python com `httpx` e `Pillow` (o venv da máquina já serve).
O binário encontra a raiz do repo sozinho (`ALVOS/` + a skill da fábrica).

```
rustc --edition 2021 --test src/instance.rs -o /tmp/estudio-instance-tests
/tmp/estudio-instance-tests
```
