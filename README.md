# Grupos TS3 — Frost Developer

Painel para setar grupos (tags) do TeamSpeak 3 mais rápido, via ClientQuery.
Funciona com as **suas permissões** no servidor; não consegue passar por cima delas.

## Usar
- **Mac:** `./build_app.sh` gera o `Grupos TS3.app`.
- **Windows:** instalador em `windows/` (precisa do arquivo local `senha.nsh`, que não vai para o GitHub).
- No TeamSpeak ative o plugin **ClientQuery** (Preferências → Suplementos → Browse online) e copie a API key para o app.

## Atualização automática
O app lê o `manifest.json` deste repositório ao abrir (e a cada 6 h). Se há versão nova, baixa os arquivos,
confere o SHA-256 de cada um e pede para reiniciar. Nada é instalado na pasta do app; fica em `<dados>/current`.

Publicar uma versão nova:
```bash
./publicar.sh 1.3 "o que mudou"
```

## Segurança
- `config.json` (API key), presets e a senha do instalador **nunca** entram no repositório (`.gitignore`).
- Quem controla este repositório controla o que o app executa ao atualizar: mantenha a conta com 2FA.
