"""Classe Game: janela, relógio e loop principal.

Responsabilidades:
  - inicializar o Pygame uma única vez e criar a janela;
  - manter a superfície principal (`self.screen`) e o relógio (`self.clock`);
  - rodar o loop principal, delegando cenas ao SceneManager.

O loop segue sempre a mesma ordem, uma volta por quadro:
    1. processar eventos
    2. atualizar a cena ativa
    3. desenhar a cena ativa
    4. atualizar a tela
    5. limitar o FPS
"""

import pygame

from .SceneManager import SceneManager
from ..utils.GameLogger import LOGGER


class Game:
    def __init__(
        self,
        width=640,
        height=480,
        title="BBox",
        fps=60,
        log_level="INFO",
        log_to_file=True,
        log_console=False,
    ):
        # Inicialização do Pygame acontece UMA vez, aqui.
        pygame.init()

        self.width = width
        self.height = height
        self.fps = fps

        # O logger começa junto com o jogo e grava o .txt no encerramento.
        self.logger = LOGGER
        self.logger.level = log_level
        self.logger.console = log_console
        self.logger.start()
        self.logger.info(
            "jogo",
            f"iniciando '{title}' {width}x{height} a {fps} fps",
        )

        self.screen = pygame.display.set_mode((width, height))
        pygame.display.set_caption(title)
        self.clock = pygame.time.Clock()

        self.scene_manager = SceneManager(self)
        self.running = False
        self._frame_count = 0

    # ------------------------------------------------------------------
    # Loop principal
    # ------------------------------------------------------------------
    def run(self, start_scene_name):
        self.logger.info("jogo", f"cena inicial: {start_scene_name}")
        self.scene_manager.start(start_scene_name)
        self.running = True

        try:
            while self.running:
                # 1. Eventos
                self._process_events()

                # 2 e 3. Atualização e desenho ficam a cargo do SceneManager.
                # `dt` em SEGUNDOS (ex.: 0.016 = 16 ms). Depender do tempo e não
                # do número de quadros faz o movimento ficar igual em qualquer FPS.
                dt = self.clock.tick(self.fps) / 1000.0
                self.scene_manager.update(dt)
                self.scene_manager.render(self.screen)

                # 4. Mostra o que foi desenhado.
                pygame.display.flip()
                self._frame_count += 1
        except Exception as exc:  # noqa: BLE001 - registramos e re-lançamos
            # Um crash ainda precisa gerar o relatório com o traceback.
            self.logger.exception("erro", exc)
            raise
        finally:
            self.shutdown()

    def _process_events(self):
        """Lê cada evento uma única vez e o encaminha para a cena ativa."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                # Encerramento seguro: o `on_exit()` da cena roda no shutdown().
                self.logger.info("evento", "QUIT recebido, encerrando")
                self.running = False
                return

            self.scene_manager.handle_event(event)

    # ------------------------------------------------------------------
    # Encerramento
    # ------------------------------------------------------------------
    def shutdown(self):
        """Encerra a cena, fecha o Pygame e grava o relatório final."""
        if self.logger is not None:
            self.logger.summary("quadros", self._frame_count)
            self.logger.summary(
                "cena final",
                type(self.scene_manager.current_scene).__name__
                if self.scene_manager.current_scene
                else "(nenhuma)",
            )
            self.logger.info("jogo", "encerrando")
            self.logger.info("jogo", f"total de quadros: {self._frame_count}")

        self.scene_manager.shutdown()
        pygame.quit()

        if self.logger is not None:
            path = self.logger.stop()
            if path is not None:
                print(f"[Game] log da execucao gravado em: {path}")