"""Gerenciador de cenas.

Guarda a cena ativa e sabe ativar, trocar e encaminhar eventos/atualização/
desenho para ela. Não conhece nenhuma cena concreta: as cenas são registradas
pelo código de inicialização (src/main.py), o que evita imports circulares.
"""

import pygame

from ..utils.GameLogger import LOGGER


class SceneManager:
    def __init__(self, game=None):
        self.game = game
        self.logger = LOGGER
        self.registry = {}        # nome -> classe da cena
        self.current_scene = None
        self.start_scene_name = None
        self._pending_name = None  # troca pedida, aplicada em momento seguro

    # ------------------------------------------------------------------
    # Registro e ativação
    # ------------------------------------------------------------------
    def register(self, name, scene_class):
        """Registra uma cena pelo nome (ex.: "menu" -> MenuScene)."""
        self.registry[name] = scene_class
        self.logger.debug("cena", f"registrada: {name} -> {scene_class.__name__}")

    def start(self, scene_name):
        """Ativa a primeira cena e chama seu on_enter()."""
        self.start_scene_name = scene_name
        self._activate(scene_name)

    def request_scene(self, scene_name):
        """Solicita a troca de cena.

        Guardamos só o nome: a troca real acontece no próximo `update()`,
        ou seja, fora do laço de eventos, evitando trocar a cena enquanto
        seus objetos estão sendo percorridos.
        """
        if scene_name not in self.registry:
            raise KeyError(f"Cena não registrada: {scene_name!r}")
        self._pending_name = scene_name

    def _activate(self, scene_name):
        self.current_scene = self.registry[scene_name](self.game)
        self.logger.info("cena", f"ativada: {scene_name}")
        self.current_scene.on_enter()

    def _apply_pending_scene(self):
        if self._pending_name is None:
            return

        name, self._pending_name = self._pending_name, None
        self.logger.info("cena", f"troca solicitada: {name}")

        # A cena antiga só é destruída depois de on_exit() e da leitura do nome.
        old_scene = self.current_scene
        self.current_scene = None
        if old_scene is not None:
            self.logger.info("cena", f"saindo de: {type(old_scene).__name__}")
            old_scene.on_exit()

        self._activate(name)

    # ------------------------------------------------------------------
    # Encaminhamento para a cena ativa
    # ------------------------------------------------------------------
    def handle_event(self, event):
        if self.current_scene is not None:
            self.current_scene.handle_event(event)

    def update(self, dt):
        self._apply_pending_scene()
        if self.current_scene is not None:
            self.current_scene.update(dt)

    def render(self, surface):
        if self.current_scene is not None:
            self.current_scene.render(surface)
        else:
            surface.fill((0, 0, 0))

    def shutdown(self):
        """Chama on_exit() da cena ativa ao encerrar a aplicação."""
        if self.current_scene is not None:
            self.logger.info("cena", f"saindo de: {type(self.current_scene).__name__}")
            self.current_scene.on_exit()
            self.current_scene = None