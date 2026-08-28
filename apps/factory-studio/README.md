# Estúdio — Fábrica de imagem

Painel local em Rust da Image Production Factory. Não reimplementa a geração:
dispara o mesmo script Python da corrida em português.

```
cd apps/factory-studio
cargo run
```

Abre `http://127.0.0.1:7420/`.

Requisitos: Rust, Python com `httpx` e `Pillow` (o venv da máquina já serve).
O binário encontra a raiz do repo sozinho (`ALVOS/` + a skill da fábrica).
