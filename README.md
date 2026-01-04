# Joblock 🧠🪟

**Joblock** é um overlay invisível para desktop que permite interagir com LLMs
através de **screenshot**, **áudio** e **texto**, sem aparecer em gravações de tela
ou compartilhamentos de vídeo.

## ✨ Principais recursos

- Overlay transparente e sempre no topo
- Invisível para screen sharing (Windows)
- Screenshot inteligente (F9)
- Captura de áudio + transcrição (F8)
- Caixa de perguntas manual (F7 / F6)
- Memória de curto prazo (contexto)
- Editor de prompts em runtime (F12)
- Totalmente offline no UI (API apenas para LLM)

## ⌨️ Atalhos

| Tecla | Ação |
|-----|-----|
| F9 | Analisar screenshot |
| F8 | Gravar / parar áudio |
| F7 | Focar caixa de pergunta |
| F6 | Enviar pergunta |
| F10 | Limpar memória |
| F1 | Mostrar ajuda |
| F12 | Editar prompts |
| ESC | Esconder overlays |
| Ctrl+Shift+Q | Sair |

## 🖥️ Plataformas

- Windows 10 / 11
- Python 3.10+

## ⚠️ Aviso legal

Este projeto utiliza APIs de terceiros (por exemplo, OpenAI),
que podem gerar custos financeiros.

O autor **não se responsabiliza** por:
- custos de uso da API
- chaves de API expostas
- uso indevido do software

Você é totalmente responsável por suas próprias chaves e gastos.
O autor não se responsabiliza por custos ou uso indevido.

## 🚀 Instalação

```bash
git clone https://github.com/diogopo12/joblock.git
cd joblock
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pythonw main.py


## 🚀 Execução

Após instalar as dependências, você pode executar o Joblock de duas formas:

### ▶️ Execução normal (com terminal)

```bash
python main.py

### ▶️ Execução em background (sem janela de terminal) (recomendado)

```bash
pythonw main.py


