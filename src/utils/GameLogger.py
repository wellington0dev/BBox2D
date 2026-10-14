"""GameLogger: registro da execução e relatório final em .txt.

O objetivo é depurar o ciclo do jogo em tempo de execução sem `print()`
espalhado pelo código. O logger começa junto com o `Game`, acumula eventos
enquanto o jogo roda e, ao encerrar, grava um arquivo `.txt` com tudo o que
ocorreu: cenas visitadas, trocas, eventos relevantes, colisões e erros.

Uso normal (automático):

    game = Game(log_to_file=True)     # já registra e salva ao sair

Para acompanhar no terminal enquanto joga:

    import src.utils.GameLogger as gl
    gl.LOGGER.console = True

O arquivo é gravado em `logs/bbox_AAAAMMDD_HHMMSS.txt`, relativo à raiz do
projeto (calculada a partir deste arquivo, e não do diretório atual).
"""

import os
import time
import traceback
from pathlib import Path

# Raus do projeto: src/utils/GameLogger.py -> src/utils -> src -> projeto
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = PROJECT_ROOT / "logs"

# Nível mínimo gravado. "DEBUG" grava tudo; "INFO" esconde o ruído por quadro.
LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}
DEFAULT_LEVEL = "INFO"


class GameLogger:
    """Acumula eventos da execução e escreve um relatório ao encerrar."""

    def __init__(self, level=DEFAULT_LEVEL, console=False, log_dir=LOG_DIR):
        self.level = level
        self.console = console
        self.log_dir = Path(log_dir)

        self.entries = []          # tuplas (timestamp, nível, categoria, mensagem)
        self.started_at = None
        self.ended_at = None
        self.file_path = None

        # Mensagens repetidas em sequência são agrupadas em vez de repetidas.
        self._repeat_count = 0

        # Contadores, úteis para o resumo final.
        self.counters = {}

        # Estado do jogo, preenchido pelos-released módulos para o relatório.
        self.snapshot = {}

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------
    def start(self):
        """Marca o início da execução e prepara o arquivo."""
        self.started_at = time.time()
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            # Sem permissão para criar a pasta: seguimos sem arquivo e
            # registramos a falha quando houver logs.
            self.log_dir = None
            self._console_print_line(f"[Logger] não foi possível criar '{LOG_DIR}': {exc}")
        return self

    def stop(self):
        """Grava o relatório final em .txt e devolve o caminho usado."""
        self.ended_at = time.time()
        if self.log_dir is None:
            return None

        self.file_path = self.log_dir / f"bbox_{self._timestamp()}.txt"
        try:
            self.file_path.write_text(self.build_report(), encoding="utf-8")
        except OSError as exc:
            self._console_print_line(f"[Logger] falha ao gravar o log: {exc}")
            return None
        return self.file_path

    def _timestamp(self):
        return time.strftime("%Y%m%d_%H%M%S", time.localtime(self.started_at))

    # ------------------------------------------------------------------
    # Registro
    # ------------------------------------------------------------------
    def log(self, level, category, message):
        """Registra uma entrada, respeitando o nível mínimo."""
        if LEVELS.get(level, 20) < LEVELS.get(self.level, 20):
            return

        entry = (time.time(), level, category, message)

        # Repetir a mesma mensagem várias vezes seguidas (um erro que persiste
        # a cada quadro) contaria uma entrada só, com a contagem anexada.
        if self.entries and self.entries[-1][1:] == entry[1:]:
            self._repeat_count += 1
            if self.console:
                print(f"[{level:5}] {category:16} {message} (x{self._repeat_count})")
            return

        if self._repeat_count > 1:
            # Fecha o bloco anterior antes de começar um novo.
            last_time, last_level, last_category, last_message = self.entries[-1]
            self.entries[-1] = (
                last_time,
                last_level,
                last_category,
                f"{last_message} (repetido {self._repeat_count}x)",
            )
        self._repeat_count = 1

        self.entries.append(entry)
        self.counters[category] = self.counters.get(category, 0) + 1
        self._console_print_line(f"[{level:5}] {category:16} {message}")

    def debug(self, category, message):
        self.log("DEBUG", category, message)

    def info(self, category, message):
        self.log("INFO", category, message)

    def warn(self, category, message):
        self.log("WARN", category, message)

    def error(self, category, message):
        self.log("ERROR", category, message)

    def _console_print_line(self, text):
        """Escreve no terminal, se o modo console estiver ligado."""
        if self.console:
            print(text)

    # ------------------------------------------------------------------
    # Relatório
    # ------------------------------------------------------------------
    def build_report(self):
        """Monta o texto completo do relatório."""
        duration = (self.ended_at or time.time()) - (self.started_at or time.time())
        lines = [
            "=" * 72,
            "BBox - relatorio de execucao",
            "=" * 72,
            f"Inicio : {_format_time(self.started_at)}",
            f"Fim    : {_format_time(self.ended_at)}",
            f"Duracao: {duration:.2f} s",
            f"Python : {_python_version()}",
            f"Pygame : {_pygame_version()}",
            f"Registros: {len(self.entries)}",
            "",
        ]

        lines.append("-" * 72)
        lines.append("RESUMO POR CATEGORIA")
        lines.append("-" * 72)
        if self.counters:
            for category, total in sorted(
                self.counters.items(), key=lambda item: -item[1]
            ):
                lines.append(f"{category:<18} {total:>6}")
        else:
            lines.append("(nenhum registro)")
        lines.append("")

        if self.snapshot:
            lines.append("-" * 72)
            lines.append("ESTADO FINAL")
            lines.append("-" * 72)
            for key, value in self.snapshot.items():
                lines.append(f"{key:<18} {value}")
            lines.append("")

        lines.append("-" * 72)
        lines.append("CRONOLOGIA")
        lines.append("-" * 72)

        if not self.entries:
            lines.append("(sem eventos)")
        else:
            base = self.started_at or 0
            for entry in self.entries:
                _append_entry(lines, entry, base)

        lines.append("")
        lines.append("=" * 72)
        lines.append("Fim do relatorio")
        lines.append("=" * 72)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def mark(self):
        """Instante atual, usado para marcar eventos com tempo relativo."""
        return time.time()

    def exception(self, category, exc):
        """Registra uma exceção com o traceback completo."""
        detail = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ).strip()
        self.error(category, f"{type(exc).__name__}: {exc}")
        for line in detail.splitlines():
            self.debug(category, line)

    def summary(self, key, value):
        """Guarda um valor para a seção ESTADO FINAL do relatório."""
        self.snapshot[key] = value


def _append_entry(lines, entry, base):
    """Escreve uma entrada no relatório."""
    timestamp, level, category, message = entry
    lines.append(_format_clock(timestamp, base))
    lines.append(f"    {level:<5} {category:<18} {message}")


def _format_time(epoch):
    if not epoch:
        return "-"
    return time.strftime("%H:%M:%S", time.localtime(epoch))


def _format_clock(epoch, base):
    if not epoch or not base:
        return "        "
    return f"[{epoch - base:8.3f}s]"


def _python_version():
    import sys

    return sys.version.split()[0]


def _pygame_version():
    try:
        import pygame

        return pygame.version.ver
    except Exception:  # pragma: no cover
        return "indisponivel"


#: Instância única usada pelo jogo. Importar este módulo dá acesso ao mesmo
#: logger de qualquer lugar, sem precisar passar o objeto adiante.
LOGGER = GameLogger()