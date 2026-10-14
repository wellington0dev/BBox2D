"""Cena do menu inicial.

Responsável por mostrar o título e o botão "Jogar", e por decidir o que
acontece quando o botão é clicado: apenas pedir a troca de cena.
"""

import pygame

from bbox2d.core.scenes.Scene import Scene
from bbox2d.ui.Button import Button
from bbox2d.ui.Text import Text

TITLE_TEXT = "BBox"
BUTTON_LABEL = "Jogar"


class MenuScene(Scene):
    def __init__(self, game=None):
        super().__init__(game)
        self.background_color = (30, 30, 46)

        # Título: só é desenhado, não é um sprite (não se move nem recebe eventos).
        self.title = Text(TITLE_TEXT, font_size=48, color=(240, 240, 255))
        self.title.center = (self.game.width // 2 if self.game else 320, 120)
        self.title.rect.center = self.title.center

        # Botão: vira sprite da cena e responde ao clique sozinho.
        self.play_button = self.add_sprite(Button(BUTTON_LABEL, 180, 70))
        self.play_button.rect.center = (
            self.game.width // 2 if self.game else 320,
            self.game.height // 2 if self.game else 240,
        )

    def on_enter(self):
        print(f"[{type(self).__name__}] entrou")

    def on_exit(self):
        print(f"[{type(self).__name__}] saiu")

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.game.running = False
            return

        # `Scene.handle_event` entrega o evento aos sprites da cena uma
        # única vez e devolve o objeto que tratou o evento.
        clicked = super().handle_event(event)
        if clicked is self.play_button:
            # A cena pede a troca; quem executa é o SceneManager.
            self.request_scene("game")

    def render(self, surface):
        super().render(surface)
        self.title.draw(surface)