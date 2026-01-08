# Joblock - Invisible AI Overlay Assistant
# Copyright (C) 2026 Diogo Pasi de Oliveira
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import sys
import time
import io
import wave
import threading
import ctypes
from pathlib import Path
from ctypes import wintypes
from collections import deque

import keyboard
import mss
import mss.tools
import pyaudio
import yaml

from PySide6 import QtWidgets, QtCore, QtGui

from llm_graph import ask_llm
from openai import OpenAI

client = OpenAI()

# =========================
# MEMÓRIA CURTA (últimas 20 interações)
# =========================
MEMORY_MAX_TURNS = 20
memory = deque(maxlen=MEMORY_MAX_TURNS)
memory_lock = threading.Lock()


def memory_add(user_text: str, assistant_text: str):
    with memory_lock:
        memory.append({"q": user_text, "a": assistant_text})


def build_messages_with_memory(system_prompt: str, user_text: str):
    messages = [{"role": "system", "content": system_prompt}]
    with memory_lock:
        items = list(memory)
    for item in items:
        messages.append({"role": "user", "content": item["q"]})
        messages.append({"role": "assistant", "content": item["a"]})
    messages.append({"role": "user", "content": user_text})
    return messages


# =========================
# LIMITES (Audio)
# =========================
MAX_AUDIO_BYTES = 23 * 1024 * 1024  # margem abaixo de 25MB
MAX_AUDIO_SECONDS_HARD = 15 * 60

TRANSCRIBE_MODEL = "whisper-1"
TEXT_MODEL = "gpt-4.1-mini"
VISION_MODEL = "gpt-4.1-mini"

AUDIO_RATE = 16000
AUDIO_CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2  # 16-bit

# ✅ Agora editável via PromptOverlay (F12)
SYSTEM_PROMPT_TEXT = "Você é um assistente útil. Use o histórico como contexto quando for relevante."

# =========================
# PROMPTS editáveis via PromptOverlay (F12)
# =========================
prompts = {
    "screenshot": "Analise o screenshot e responda em português com um resumo claro e ações práticas.",
    "audio": "Com base no áudio capturado, responda em português com um resumo e próximos passos. Liste tarefas em bullets.",
}

DEFAULT_SHORTCUTS = {
    "screenshot": "F9",
    "audio_toggle": "F8",
    "focus_input": "F7",
    "send_input": "F6",
    "clear_memory": "F10",
    "show_help": "F1",
    "edit_prompts": "F12",
    "edit_settings": "F11",
    "hide": "esc",
    "quit": "ctrl+shift+q",
}

SHORTCUT_LABELS = {
    "screenshot": "Screenshot (analisar imagem)",
    "audio_toggle": "Gravar/Parar áudio (enviar para LLM)",
    "focus_input": "Focar na caixa de pergunta",
    "send_input": "Enviar a pergunta digitada",
    "clear_memory": "Limpar memória/histórico",
    "show_help": "Mostrar esta tela de atalhos (fixo)",
    "edit_prompts": "Editar prompts (Screenshot/Áudio/System)",
    "edit_settings": "Configurações do sistema (modelos)",
    "hide": "Esconder janelas (não fecha) (fixo)",
    "quit": "Sair",
}

SHORTCUT_FIXED_KEYS = {"show_help", "hide"}

CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"


def _default_config() -> dict:
    return {
        "system_prompt": SYSTEM_PROMPT_TEXT,
        "prompts": {
            "screenshot": prompts["screenshot"],
            "audio": prompts["audio"],
        },
        "models": {
            "vision": VISION_MODEL,
            "text": TEXT_MODEL,
            "transcribe": TRANSCRIBE_MODEL,
        },
        "shortcuts": dict(DEFAULT_SHORTCUTS),
    }


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return _default_config()
    try:
        data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return _default_config()
    base = _default_config()
    if isinstance(data, dict):
        base["system_prompt"] = data.get("system_prompt", base["system_prompt"])
        prompts_data = data.get("prompts", {})
        if isinstance(prompts_data, dict):
            base["prompts"]["screenshot"] = prompts_data.get("screenshot", base["prompts"]["screenshot"])
            base["prompts"]["audio"] = prompts_data.get("audio", base["prompts"]["audio"])
        models_data = data.get("models", {})
        if isinstance(models_data, dict):
            base["models"]["vision"] = models_data.get("vision", base["models"]["vision"])
            base["models"]["text"] = models_data.get("text", base["models"]["text"])
            base["models"]["transcribe"] = models_data.get("transcribe", base["models"]["transcribe"])
        shortcuts_data = data.get("shortcuts", {})
        if isinstance(shortcuts_data, dict):
            for key, default_value in base["shortcuts"].items():
                value = shortcuts_data.get(key, default_value)
                if value:
                    base["shortcuts"][key] = value
    return base


def save_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    yaml.safe_dump(config, CONFIG_PATH.open("w", encoding="utf-8"), sort_keys=False, allow_unicode=True)


config = load_config()
SYSTEM_PROMPT_TEXT = config["system_prompt"]
prompts["screenshot"] = config["prompts"]["screenshot"]
prompts["audio"] = config["prompts"]["audio"]
VISION_MODEL = config["models"]["vision"]
TEXT_MODEL = config["models"]["text"]
TRANSCRIBE_MODEL = config["models"]["transcribe"]
shortcuts = config["shortcuts"]
for key in SHORTCUT_FIXED_KEYS:
    shortcuts[key] = DEFAULT_SHORTCUTS[key]


def persist_config() -> None:
    save_config(
        {
            "system_prompt": SYSTEM_PROMPT_TEXT,
            "prompts": {
                "screenshot": prompts["screenshot"],
                "audio": prompts["audio"],
            },
            "models": {
                "vision": VISION_MODEL,
                "text": TEXT_MODEL,
                "transcribe": TRANSCRIBE_MODEL,
            },
            "shortcuts": shortcuts,
        }
    )

# =========================
# Windows: exclude from capture
# =========================
if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    WDA_EXCLUDEFROMCAPTURE = 0x11
    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.SetWindowDisplayAffinity.restype = wintypes.BOOL

    def exclude_from_capture(hwnd: int):
        try:
            user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
        except Exception:
            pass
else:
    def exclude_from_capture(hwnd: int):
        return


# =========================
# Screenshot
# =========================
def capture_screen() -> bytes:
    with mss.mss() as sct:
        if not sct.monitors:
            raise RuntimeError("Nenhum monitor disponível para captura.")
        monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        img = sct.grab(monitor)
        return mss.tools.to_png(img.rgb, img.size)


# =========================
# OpenAI helpers
# =========================
def transcribe_wav_bytes(wav_bytes: bytes) -> str:
    f = io.BytesIO(wav_bytes)
    f.name = "audio.wav"
    tr = client.audio.transcriptions.create(
        model=TRANSCRIBE_MODEL,
        file=f,
    )
    return tr.text


def ask_text_with_memory(user_text: str) -> str:
    global SYSTEM_PROMPT_TEXT
    resp = client.chat.completions.create(
        model=TEXT_MODEL,
        messages=build_messages_with_memory(SYSTEM_PROMPT_TEXT, user_text),
        temperature=0.2,
    )
    answer = resp.choices[0].message.content
    memory_add(user_text, answer)
    return answer


def describe_image_textually_from_answer(image_answer: str) -> str:
    system_prompt = "Você descreve imagens de forma objetiva e curta."
    user_text = (
        "Com base na imagem que você acabou de analisar, gere uma descrição objetiva do conteúdo visual "
        "em 1 a 4 frases. Não inclua conselhos, apenas o que aparece."
    )
    resp = client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": image_answer},
        ],
        temperature=0.1,
    )
    return resp.choices[0].message.content.strip()


# =========================
# Texto de atalhos
# =========================
def shortcuts_text() -> str:
    def format_line(key: str, label: str) -> str:
        return f"{key:<12} - {label}\n"

    return (
        "JOBLOCK — ATALHOS\n"
        "----------------\n"
        f"{format_line(shortcuts['screenshot'], SHORTCUT_LABELS['screenshot'])}"
        f"{format_line(shortcuts['audio_toggle'], SHORTCUT_LABELS['audio_toggle'])}"
        f"{format_line(shortcuts['focus_input'], SHORTCUT_LABELS['focus_input'])}"
        f"{format_line(shortcuts['send_input'], SHORTCUT_LABELS['send_input'])}"
        f"{format_line(shortcuts['clear_memory'], SHORTCUT_LABELS['clear_memory'])}"
        f"{format_line(shortcuts['show_help'], SHORTCUT_LABELS['show_help'])}"
        f"{format_line(shortcuts['edit_prompts'], SHORTCUT_LABELS['edit_prompts'])}"
        f"{format_line(shortcuts['edit_settings'], SHORTCUT_LABELS['edit_settings'])}"
        f"{format_line(shortcuts['hide'], SHORTCUT_LABELS['hide'])}"
        f"{format_line(shortcuts['quit'], SHORTCUT_LABELS['quit'])}"
        "Botão (F1) - Configurar atalhos (F1 e ESC são fixos)\n"
    )


# =========================
# UI: Overlay de RESPOSTA + input
# =========================
class Overlay(QtWidgets.QWidget):
    ask = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)

        self.text = QtWidgets.QTextEdit(readOnly=True)
        self.text.setStyleSheet("""
            QTextEdit {
                background: rgba(0,0,0,170);
                color: white;
                border-radius: 12px;
                padding: 12px;
                font-size: 14px;
            }
        """)

        self.input = QtWidgets.QLineEdit()
        self.input.setPlaceholderText("Digite uma pergunta e pressione Enter (ou F6)…")
        self.input.setStyleSheet("""
            QLineEdit {
                background: rgba(20,20,20,200);
                color: white;
                border-radius: 8px;
                padding: 8px;
                font-size: 13px;
            }
        """)
        self.input.returnPressed.connect(self._on_enter)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(self.text)
        layout.addWidget(self.input)

        self.resize(560, 390)
        self.hide()

    def showEvent(self, event):
        super().showEvent(event)
        exclude_from_capture(int(self.winId()))

    def _on_enter(self):
        value = self.input.text().strip()
        if not value:
            return
        self.input.clear()
        self.ask.emit(value)

    @QtCore.Slot()
    def focus_input(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    @QtCore.Slot()
    def send_input(self):
        self._on_enter()

    @QtCore.Slot(str)
    def set_text(self, text: str):
        self.text.setPlainText(text)

    @QtCore.Slot()
    def move_to_bottom_right(self):
        screen = QtGui.QGuiApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        margin = 20
        x = geo.x() + geo.width() - self.width() - margin
        y = geo.y() + geo.height() - self.height() - margin
        self.move(x, y)


# =========================
# UI: HelpOverlay (igual ao overlay)
# =========================
class HelpOverlay(QtWidgets.QWidget):
    configure_shortcuts = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)

        self.box = QtWidgets.QWidget()
        self.box.setStyleSheet("""
            QWidget {
                background: rgba(0,0,0,170);
                color: white;
                border-radius: 12px;
            }
            QTextEdit {
                background: transparent;
                color: white;
                border-radius: 0px;
                padding: 12px;
                font-size: 14px;
            }
            QPushButton {
                background: rgba(40,40,40,220);
                color: white;
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QPushButton:hover { background: rgba(60,60,60,220); }
        """)

        self.text = QtWidgets.QTextEdit(readOnly=True)
        self.btn_shortcuts = QtWidgets.QPushButton("Configurar atalhos")
        self.btn_shortcuts.clicked.connect(self.configure_shortcuts.emit)

        form = QtWidgets.QVBoxLayout(self.box)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(10)
        form.addWidget(self.text)

        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_shortcuts)
        form.addLayout(row)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.addWidget(self.box)

        self.resize(600, 380)

    def showEvent(self, event):
        super().showEvent(event)
        exclude_from_capture(int(self.winId()))

    def set_text(self, t: str):
        self.text.setPlainText(t)

    def move_center(self):
        screen = QtGui.QGuiApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + (geo.height() - self.height()) // 2
        self.move(x, y)


# =========================
# UI: PromptOverlay (igual ao overlay) com 3 prompts
# =========================
class PromptOverlay(QtWidgets.QWidget):
    saved = QtCore.Signal(dict)  # {"screenshot":..., "audio":..., "system":...}

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)

        # Container visual
        self.box = QtWidgets.QWidget()
        self.box.setStyleSheet("""
            QWidget {
                background: rgba(0,0,0,170);
                color: white;
                border-radius: 12px;
            }
            QLabel { color: white; font-size: 13px; }
            QTextEdit {
                background: rgba(20,20,20,220);
                color: white;
                border-radius: 8px;
                padding: 8px;
                font-size: 13px;
            }
            QPushButton {
                background: rgba(40,40,40,220);
                color: white;
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QPushButton:hover { background: rgba(60,60,60,220); }
        """)

        self.ss = QtWidgets.QTextEdit()
        self.au = QtWidgets.QTextEdit()
        self.sy = QtWidgets.QTextEdit()

        lbl1 = QtWidgets.QLabel("Prompt Screenshot (F9):")
        lbl2 = QtWidgets.QLabel("Prompt Áudio (F8):")
        lbl3 = QtWidgets.QLabel("System Prompt (histórico/memória):")

        self.btn_save = QtWidgets.QPushButton("Salvar")
        self.btn_cancel = QtWidgets.QPushButton("Cancelar")

        self.btn_save.clicked.connect(self._save)
        self.btn_cancel.clicked.connect(self.hide)

        form = QtWidgets.QVBoxLayout(self.box)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(10)
        form.addWidget(lbl1)
        form.addWidget(self.ss)
        form.addWidget(lbl2)
        form.addWidget(self.au)
        form.addWidget(lbl3)
        form.addWidget(self.sy)

        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_save)
        form.addLayout(row)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.addWidget(self.box)

        self.resize(720, 620)
        self.hide()

    def showEvent(self, event):
        super().showEvent(event)
        exclude_from_capture(int(self.winId()))

    def set_values(self, screenshot: str, audio: str, system: str):
        self.ss.setPlainText(screenshot or "")
        self.au.setPlainText(audio or "")
        self.sy.setPlainText(system or "")

    def _save(self):
        payload = {
            "screenshot": self.ss.toPlainText().strip(),
            "audio": self.au.toPlainText().strip(),
            "system": self.sy.toPlainText().strip(),
        }
        self.saved.emit(payload)
        self.hide()

    def move_center(self):
        screen = QtGui.QGuiApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + (geo.height() - self.height()) // 2
        self.move(x, y)


# =========================
# UI: SettingsOverlay (modelos)
# =========================
class SettingsOverlay(QtWidgets.QWidget):
    saved = QtCore.Signal(dict)  # {"vision":..., "text":..., "transcribe":...}

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)

        self.box = QtWidgets.QWidget()
        self.box.setStyleSheet("""
            QWidget {
                background: rgba(0,0,0,170);
                color: white;
                border-radius: 12px;
            }
            QLabel { color: white; font-size: 13px; }
            QComboBox {
                background: rgba(20,20,20,220);
                color: white;
                border-radius: 8px;
                padding: 6px;
                font-size: 13px;
            }
            QPushButton {
                background: rgba(40,40,40,220);
                color: white;
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QPushButton:hover { background: rgba(60,60,60,220); }
        """)

        self.vision_combo = QtWidgets.QComboBox()
        self.text_combo = QtWidgets.QComboBox()
        self.transcribe_combo = QtWidgets.QComboBox()

        lbl1 = QtWidgets.QLabel("Modelo para Screenshot (visão):")
        lbl2 = QtWidgets.QLabel("Modelo para Texto/Chat:")
        lbl3 = QtWidgets.QLabel("Modelo para Transcrição de Áudio:")

        self.btn_save = QtWidgets.QPushButton("Salvar")
        self.btn_cancel = QtWidgets.QPushButton("Cancelar")

        self.btn_save.clicked.connect(self._save)
        self.btn_cancel.clicked.connect(self.hide)

        form = QtWidgets.QVBoxLayout(self.box)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(10)
        form.addWidget(lbl1)
        form.addWidget(self.vision_combo)
        form.addWidget(lbl2)
        form.addWidget(self.text_combo)
        form.addWidget(lbl3)
        form.addWidget(self.transcribe_combo)

        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_save)
        form.addLayout(row)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.addWidget(self.box)

        self.resize(640, 380)
        self.hide()

    def showEvent(self, event):
        super().showEvent(event)
        exclude_from_capture(int(self.winId()))

    def _set_combo_value(self, combo: QtWidgets.QComboBox, value: str):
        idx = combo.findText(value)
        if idx < 0 and value:
            combo.addItem(value)
            idx = combo.findText(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def set_models(self, models: list[str], vision: str, text: str, transcribe: str):
        self.vision_combo.clear()
        self.text_combo.clear()
        self.transcribe_combo.clear()
        for model in models:
            self.vision_combo.addItem(model)
            self.text_combo.addItem(model)
            self.transcribe_combo.addItem(model)
        self._set_combo_value(self.vision_combo, vision)
        self._set_combo_value(self.text_combo, text)
        self._set_combo_value(self.transcribe_combo, transcribe)

    def _save(self):
        payload = {
            "vision": self.vision_combo.currentText().strip(),
            "text": self.text_combo.currentText().strip(),
            "transcribe": self.transcribe_combo.currentText().strip(),
        }
        self.saved.emit(payload)
        self.hide()

    def move_center(self):
        screen = QtGui.QGuiApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + (geo.height() - self.height()) // 2
        self.move(x, y)


# =========================
# UI: ShortcutOverlay (atalhos)
# =========================
class ShortcutOverlay(QtWidgets.QWidget):
    saved = QtCore.Signal(dict)  # {"screenshot":..., "audio_toggle":..., ...}

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)

        self.box = QtWidgets.QWidget()
        self.box.setStyleSheet("""
            QWidget {
                background: rgba(0,0,0,170);
                color: white;
                border-radius: 12px;
            }
            QLabel { color: white; font-size: 13px; }
            QLineEdit {
                background: rgba(20,20,20,220);
                color: white;
                border-radius: 8px;
                padding: 6px;
                font-size: 13px;
            }
            QPushButton {
                background: rgba(40,40,40,220);
                color: white;
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QPushButton:hover { background: rgba(60,60,60,220); }
        """)

        self.fields = {}

        form = QtWidgets.QFormLayout()
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(10)

        for key, label in SHORTCUT_LABELS.items():
            line = QtWidgets.QLineEdit()
            if key in SHORTCUT_FIXED_KEYS:
                line.setReadOnly(True)
                line.setStyleSheet("color: rgba(200,200,200,180);")
            self.fields[key] = line
            form.addRow(QtWidgets.QLabel(label + ":"), line)

        note = QtWidgets.QLabel("F1 e ESC são fixos e não podem ser alterados.")
        note.setStyleSheet("color: rgba(200,200,200,180); font-size: 12px;")

        self.btn_save = QtWidgets.QPushButton("Salvar")
        self.btn_cancel = QtWidgets.QPushButton("Cancelar")
        self.btn_save.clicked.connect(self._save)
        self.btn_cancel.clicked.connect(self.hide)

        form.addRow(note)

        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_save)

        wrapper = QtWidgets.QVBoxLayout(self.box)
        wrapper.setContentsMargins(16, 16, 16, 16)
        wrapper.addLayout(form)
        wrapper.addLayout(row)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.addWidget(self.box)

        self.resize(640, 520)
        self.hide()

    def showEvent(self, event):
        super().showEvent(event)
        exclude_from_capture(int(self.winId()))

    def set_shortcuts(self, values: dict):
        for key, field in self.fields.items():
            field.setText(values.get(key, ""))

    def _save(self):
        payload = {}
        reserved = {shortcuts["show_help"].lower(), shortcuts["hide"].lower()}
        for key, field in self.fields.items():
            value = field.text().strip()
            if key in SHORTCUT_FIXED_KEYS:
                payload[key] = shortcuts[key]
                continue
            if not value:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Atalhos",
                    f"O atalho '{SHORTCUT_LABELS[key]}' não pode ficar vazio.",
                )
                return
            if value.lower() in reserved:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Atalhos",
                    f"O atalho '{SHORTCUT_LABELS[key]}' não pode usar {value} (reservado).",
                )
                return
            payload[key] = value

        self.saved.emit(payload)
        self.hide()

    def move_center(self):
        screen = QtGui.QGuiApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + (geo.height() - self.height()) // 2
        self.move(x, y)


# =========================
# Audio Recorder
# =========================
class AudioRecorder:
    def __init__(self, device_index: int, rate=16000, channels=1, sample_width=2):
        self.device_index = device_index
        self.rate = rate
        self.channels = channels
        self.sample_width = sample_width

        self._pa = pyaudio.PyAudio()
        self._stream = None
        self._frames = []
        self._lock = threading.Lock()
        self._recording = False
        self._start_ts = None

    @property
    def recording(self) -> bool:
        return self._recording

    def bytes_per_second(self) -> int:
        return self.rate * self.channels * self.sample_width

    def elapsed_seconds(self) -> float:
        if not self._start_ts:
            return 0.0
        return time.time() - self._start_ts

    def estimated_wav_size_bytes(self) -> int:
        return int(self.elapsed_seconds() * self.bytes_per_second()) + 44

    def start(self):
        if self._recording:
            return

        self._frames = []
        self._recording = True
        self._start_ts = time.time()

        fmt = self._pa.get_format_from_width(self.sample_width)

        self._stream = self._pa.open(
            format=fmt,
            channels=self.channels,
            rate=self.rate,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=1024,
            stream_callback=self._callback,
        )
        self._stream.start_stream()

    def _callback(self, in_data, frame_count, time_info, status):
        if self._recording:
            with self._lock:
                self._frames.append(in_data)
        return (None, pyaudio.paContinue)

    def stop_and_get_wav_bytes(self) -> bytes:
        if not self._recording:
            return b""

        self._recording = False
        try:
            if self._stream is not None:
                self._stream.stop_stream()
                self._stream.close()
        finally:
            self._stream = None

        with self._lock:
            pcm = b"".join(self._frames)
            self._frames = []

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.sample_width)
            wf.setframerate(self.rate)
            wf.writeframes(pcm)

        return buf.getvalue()

    def close(self):
        if self._recording:
            self.stop_and_get_wav_bytes()
        if self._pa is not None:
            self._pa.terminate()
            self._pa = None


# =========================
# Workers
# =========================
class ScreenshotWorker(QtCore.QObject):
    status = QtCore.Signal(str)
    result = QtCore.Signal(str)

    def __init__(self, prompt: str):
        super().__init__()
        self.prompt = prompt

    @QtCore.Slot()
    def run(self):
        try:
            self.status.emit("Capturando tela...")
            png = capture_screen()

            self.status.emit("Consultando LLM (imagem)...")
            answer = ask_llm(self.prompt, png, VISION_MODEL)

            self.status.emit("Transcrevendo imagem para histórico...")
            img_transcription = describe_image_textually_from_answer(answer)

            memory_add(f"[IMAGEM]\n{img_transcription}", answer)
            self.result.emit(answer)
        except Exception as e:
            self.result.emit(f"Erro (screenshot/LLM):\n{e!r}")


class AudioProcessWorker(QtCore.QObject):
    status = QtCore.Signal(str)
    result = QtCore.Signal(str)

    def __init__(self, wav_bytes: bytes, prompt: str):
        super().__init__()
        self.wav_bytes = wav_bytes
        self.prompt = prompt

    @QtCore.Slot()
    def run(self):
        try:
            self.status.emit("📝 Transcrevendo áudio...")
            transcript = transcribe_wav_bytes(self.wav_bytes)

            self.status.emit("💬 Gerando resposta (com memória)...")
            user_text = f"{self.prompt}\n\nTRANSCRIÇÃO:\n{transcript}"
            answer = ask_text_with_memory(user_text)

            out = f"{answer}\n\n---\nTRANSCRIÇÃO (debug):\n{transcript}"
            self.result.emit(out)
        except Exception as e:
            self.result.emit(f"Erro (áudio):\n{e!r}")


class TextAskWorker(QtCore.QObject):
    status = QtCore.Signal(str)
    result = QtCore.Signal(str)

    def __init__(self, user_text: str):
        super().__init__()
        self.user_text = user_text

    @QtCore.Slot()
    def run(self):
        try:
            self.status.emit("💬 Perguntando ao LLM (com memória)...")
            answer = ask_text_with_memory(self.user_text)
            self.result.emit(answer)
        except Exception as e:
            self.result.emit(f"Erro (texto):\n{e!r}")


# =========================
# Bridge: hotkeys -> Qt main thread
# =========================
class HotkeyBridge(QtCore.QObject):
    screenshot = QtCore.Signal()
    audio_toggle = QtCore.Signal()
    hide = QtCore.Signal()
    quit = QtCore.Signal()
    clear_memory = QtCore.Signal()
    focus_input = QtCore.Signal()
    send_input = QtCore.Signal()
    show_help = QtCore.Signal()
    edit_prompts = QtCore.Signal()
    edit_settings = QtCore.Signal()


def list_openai_models() -> list[str]:
    try:
        models = client.models.list()
        names = sorted({m.id for m in models.data if getattr(m, "id", None)})
        return names
    except Exception:
        return []


# =========================
# Device selection
# =========================
def list_input_devices(pa: pyaudio.PyAudio, only_hostapis=None):
    host_api_names = {
        i: pa.get_host_api_info_by_index(i)["name"]
        for i in range(pa.get_host_api_count())
    }
    devs = []
    for i in range(pa.get_device_count()):
        d = pa.get_device_info_by_index(i)
        if d.get("maxInputChannels", 0) <= 0:
            continue
        host = host_api_names.get(d["hostApi"], "")
        if only_hostapis and host not in only_hostapis:
            continue
        devs.append((i, d["name"], host, d.get("maxInputChannels", 0)))
    return devs


def find_stereo_mix_device(pa: pyaudio.PyAudio) -> int | None:
    preferred_host_apis = {"MME", "Windows DirectSound"}
    devs = list_input_devices(pa, only_hostapis=preferred_host_apis)
    for idx, name, host, ch in devs:
        n = name.lower()
        if ("mixagem" in n) or ("stereo mix" in n) or ("stereo" in n and "mix" in n):
            print(f"🎧 Stereo Mix encontrado: [{idx}] {name} ({host})")
            return idx
    return None


def pick_microphone_device(pa: pyaudio.PyAudio) -> int | None:
    try:
        info = pa.get_default_input_device_info()
        idx = int(info["index"])
        print(f"🎤 Usando microfone padrão: [{idx}] {info.get('name', '')}")
        return idx
    except Exception:
        return None


def ask_user_to_choose_device(pa: pyaudio.PyAudio) -> int | None:
    preferred_host_apis = {"MME", "Windows DirectSound"}
    devs = list_input_devices(pa, only_hostapis=preferred_host_apis) or list_input_devices(pa, None)

    print("\n=== Selecione um dispositivo de entrada para gravar ===")
    for idx, name, host, ch in devs:
        print(f"[{idx}] {name} | host={host} | inputs={ch}")
    print("\nDigite o número do device (ou Enter para cancelar): ", end="")
    s = input().strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def main():
    global SYSTEM_PROMPT_TEXT

    app = QtWidgets.QApplication(sys.argv)

    overlay = Overlay()
    help_overlay = HelpOverlay()
    prompt_overlay = PromptOverlay()
    settings_overlay = SettingsOverlay()
    shortcut_overlay = ShortcutOverlay()
    bridge = HotkeyBridge()

    # Mostra HELP ao iniciar (overlay invisível à captura)
    help_overlay.set_text(shortcuts_text())
    help_overlay.move_center()
    help_overlay.show()
    help_overlay.raise_()

    # threads separadas
    state = {
        "shot_thread": None, "shot_worker": None,
        "audio_thread": None, "audio_worker": None,
        "text_thread": None, "text_worker": None,
    }

    # Audio device
    pa = pyaudio.PyAudio()
    chosen_device = find_stereo_mix_device(pa)
    if chosen_device is None:
        print("⚠️ Não achei Stereo Mix/Mixagem estéreo em MME/DirectSound.")
        chosen_device = pick_microphone_device(pa)
    if chosen_device is None:
        print("⚠️ Não consegui pegar microfone padrão automaticamente.")
        chosen_device = ask_user_to_choose_device(pa)

    recorder = None
    if chosen_device is None:
        print("❌ Sem dispositivo de captura escolhido. O atalho F8 não vai funcionar.")
    else:
        recorder = AudioRecorder(
            device_index=chosen_device,
            rate=AUDIO_RATE,
            channels=AUDIO_CHANNELS,
            sample_width=SAMPLE_WIDTH_BYTES,
        )
    pa.terminate()
    pa = None

    def clear_thread(thread_key: str, worker_key: str):
        state[thread_key] = None
        state[worker_key] = None

    def run_worker(worker_obj: QtCore.QObject, thread_key: str, worker_key: str):
        thr = state.get(thread_key)
        if thr is not None and thr.isRunning():
            return False

        thread = QtCore.QThread()
        worker_obj.moveToThread(thread)
        thread.started.connect(worker_obj.run)

        worker_obj.status.connect(overlay.set_text)
        worker_obj.result.connect(overlay.set_text)
        worker_obj.result.connect(thread.quit)

        thread.finished.connect(worker_obj.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: clear_thread(thread_key, worker_key))

        state[thread_key] = thread
        state[worker_key] = worker_obj
        thread.start()
        return True

    # -------- actions --------
    @QtCore.Slot()
    def do_screenshot():
        overlay.move_to_bottom_right()
        overlay.set_text("Iniciando (screenshot)...")
        overlay.show()
        overlay.raise_()
        worker = ScreenshotWorker(prompts["screenshot"])
        if not run_worker(worker, "shot_thread", "shot_worker"):
            overlay.set_text("Já estou processando um screenshot... (aguarde)")

    def schedule_audio_limit_check():
        if recorder is None or not recorder.recording:
            return
        if recorder.elapsed_seconds() >= MAX_AUDIO_SECONDS_HARD:
            bridge.audio_toggle.emit()
            return
        if recorder.estimated_wav_size_bytes() >= MAX_AUDIO_BYTES:
            bridge.audio_toggle.emit()
            return
        QtCore.QTimer.singleShot(250, schedule_audio_limit_check)

    @QtCore.Slot()
    def do_audio_toggle():
        overlay.move_to_bottom_right()
        overlay.show()
        overlay.raise_()

        if recorder is None:
            overlay.set_text("Áudio não configurado.\nVeja o terminal para escolher device.")
            return

        if not recorder.recording:
            try:
                recorder.start()
            except Exception as e:
                overlay.set_text(f"Erro ao iniciar captura de áudio:\n{e!r}")
                return
            overlay.set_text("🎙️ Gravando áudio... (F8 para parar e enviar)")
            schedule_audio_limit_check()
            return

        overlay.set_text("⏹️ Parando gravação...")
        wav_bytes = recorder.stop_and_get_wav_bytes()
        if not wav_bytes:
            overlay.set_text("Não capturei áudio (silêncio).")
            return
        if len(wav_bytes) >= MAX_AUDIO_BYTES:
            overlay.set_text(f"Áudio muito grande ({len(wav_bytes)/1024/1024:.1f} MB).")
            return

        worker = AudioProcessWorker(wav_bytes, prompts["audio"])
        if not run_worker(worker, "audio_thread", "audio_worker"):
            overlay.set_text("Já estou processando um áudio... (aguarde)")

    @QtCore.Slot(str)
    def do_text_question(user_text: str):
        overlay.move_to_bottom_right()
        overlay.show()
        overlay.raise_()
        worker = TextAskWorker(user_text)
        if not run_worker(worker, "text_thread", "text_worker"):
            overlay.set_text("Já estou processando uma pergunta... (aguarde)")

    @QtCore.Slot()
    def clear_memory_slot():
        with memory_lock:
            memory.clear()
        overlay.move_to_bottom_right()
        overlay.set_text("🧹 Memória limpa (histórico zerado).")
        overlay.show()
        overlay.raise_()

    @QtCore.Slot()
    def hide_all_overlays():
        overlay.hide()
        help_overlay.hide()
        prompt_overlay.hide()
        settings_overlay.hide()
        shortcut_overlay.hide()

    @QtCore.Slot()
    def quit_app():
        overlay.hide()
        help_overlay.hide()
        prompt_overlay.hide()
        settings_overlay.hide()
        shortcut_overlay.hide()
        if recorder is not None:
            try:
                recorder.close()
            except Exception:
                pass
        try:
            keyboard.clear_all_hotkeys()
        except Exception:
            pass
        QtCore.QCoreApplication.quit()

    @QtCore.Slot()
    def show_help_overlay():
        help_overlay.set_text(shortcuts_text())
        help_overlay.move_center()
        help_overlay.show()
        help_overlay.raise_()

    @QtCore.Slot()
    def show_prompt_overlay():
        prompt_overlay.set_values(
            prompts.get("screenshot", ""),
            prompts.get("audio", ""),
            SYSTEM_PROMPT_TEXT,
        )
        prompt_overlay.move_center()
        prompt_overlay.show()
        prompt_overlay.raise_()
        prompt_overlay.activateWindow()

    def show_settings_overlay():
        available = list_openai_models()
        if not available:
            available = [VISION_MODEL, TEXT_MODEL, TRANSCRIBE_MODEL]
        else:
            for model in (VISION_MODEL, TEXT_MODEL, TRANSCRIBE_MODEL):
                if model not in available:
                    available.append(model)
        available = sorted(dict.fromkeys(available))
        settings_overlay.set_models(available, VISION_MODEL, TEXT_MODEL, TRANSCRIBE_MODEL)
        settings_overlay.move_center()
        settings_overlay.show()
        settings_overlay.raise_()
        settings_overlay.activateWindow()

    def show_shortcut_overlay():
        shortcut_overlay.set_shortcuts(shortcuts)
        shortcut_overlay.move_center()
        shortcut_overlay.show()
        shortcut_overlay.raise_()
        shortcut_overlay.activateWindow()

    def on_prompts_saved(payload: dict):
        global SYSTEM_PROMPT_TEXT
        # Atualiza os 3 prompts
        prompts["screenshot"] = payload.get("screenshot", prompts["screenshot"])
        prompts["audio"] = payload.get("audio", prompts["audio"])

        # Atualiza system prompt (global)
        sp = payload.get("system", "").strip()
        if sp:
            globals()["SYSTEM_PROMPT_TEXT"] = sp

        persist_config()

        overlay.move_to_bottom_right()
        overlay.set_text("✅ Prompts atualizados (Screenshot/Áudio/System).")
        overlay.show()
        overlay.raise_()

    prompt_overlay.saved.connect(on_prompts_saved)

    def on_settings_saved(payload: dict):
        global VISION_MODEL, TEXT_MODEL, TRANSCRIBE_MODEL
        vision = payload.get("vision", "").strip()
        text = payload.get("text", "").strip()
        transcribe = payload.get("transcribe", "").strip()
        if vision:
            VISION_MODEL = vision
        if text:
            TEXT_MODEL = text
        if transcribe:
            TRANSCRIBE_MODEL = transcribe

        persist_config()

        overlay.move_to_bottom_right()
        overlay.set_text("✅ Modelos atualizados (Screenshot/Texto/Áudio).")
        overlay.show()
        overlay.raise_()

    settings_overlay.saved.connect(on_settings_saved)

    def register_hotkeys():
        keyboard.clear_all_hotkeys()
        keyboard.add_hotkey(shortcuts["screenshot"], lambda: bridge.screenshot.emit())
        keyboard.add_hotkey(shortcuts["audio_toggle"], lambda: bridge.audio_toggle.emit())
        keyboard.add_hotkey(shortcuts["clear_memory"], lambda: bridge.clear_memory.emit())
        keyboard.add_hotkey(shortcuts["focus_input"], lambda: bridge.focus_input.emit())
        keyboard.add_hotkey(shortcuts["send_input"], lambda: bridge.send_input.emit())
        keyboard.add_hotkey(shortcuts["show_help"], lambda: bridge.show_help.emit())
        keyboard.add_hotkey(shortcuts["edit_prompts"], lambda: bridge.edit_prompts.emit())
        keyboard.add_hotkey(shortcuts["edit_settings"], lambda: bridge.edit_settings.emit())
        keyboard.add_hotkey(shortcuts["hide"], lambda: bridge.hide.emit())
        keyboard.add_hotkey(shortcuts["quit"], lambda: bridge.quit.emit())

    def on_shortcuts_saved(payload: dict):
        for key, value in payload.items():
            shortcuts[key] = value
        persist_config()
        register_hotkeys()

        overlay.move_to_bottom_right()
        overlay.set_text("✅ Atalhos atualizados.")
        overlay.show()
        overlay.raise_()

    shortcut_overlay.saved.connect(on_shortcuts_saved)
    help_overlay.configure_shortcuts.connect(show_shortcut_overlay)

    # Overlay enter -> pergunta manual
    overlay.ask.connect(do_text_question)

    # Bridge wiring
    bridge.screenshot.connect(do_screenshot)
    bridge.audio_toggle.connect(do_audio_toggle)
    bridge.hide.connect(hide_all_overlays)
    bridge.quit.connect(quit_app)
    bridge.clear_memory.connect(clear_memory_slot)
    bridge.focus_input.connect(overlay.focus_input)
    bridge.send_input.connect(overlay.send_input)
    bridge.show_help.connect(show_help_overlay)
    bridge.edit_prompts.connect(show_prompt_overlay)
    bridge.edit_settings.connect(show_settings_overlay)

    # Hotkeys
    register_hotkeys()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
