"""Classe-base das cenas.

Uma cena é uma tela completa da aplicação: ela tem uma cor de fundo e um
grupo de sprites próprios. O loop principal não conhece os detalhes de cada
cena: ele apenas pergunta ao SceneManager para atualizar/desenhar a cena ativa.

Fluxo de ciclo de vida:

    SceneManager.start()  -> on_enter()
    troca de cena         -> on_exit() da antiga, on_enter() da nova
    fim da aplicação      -> on_exit() da cena ativa
"""

import pygame

from ...utils.GameLogger import LOGGER


class Scene:
    def __init__(self, game=None):
        # `game` é opcional: permite que a cena peça trocas ao SceneManager
        # sem conhecer os detalhes de janela/loop.
        self.game = game

        # Objetos que pertencem a ESTA cena. Tudo que está aqui é atualizado
        # e desenhado automaticamente, e nada de outra cena aparece aqui.
        self.sprites = pygame.sprite.Group()

        self.background_color = (20, 20, 20)

        # Cada cena registra sua própria chave no relatório final.
        self.logger = LOGGER

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------
    def on_enter(self):
        """Chamada quando a cena se torna ativa (sobrescreva se precisar)."""
        pass

    def on_exit(self):
        """Chamada quando a cena deixa de ser ativa (sobrescreva se precisar)."""
        pass

    # ------------------------------------------------------------------
    # Eventos / atualização / desenho
    # ------------------------------------------------------------------
    def handle_event(self, event):
        """Encaminha o evento para os objetos da cena.

        Para no primeiro objeto que tratar o evento e devolve esse objeto
        (ou None). Assim um único evento não é processado duas vezes e um
        clique nunca aciona dois botões ao mesmo tempo.
        """
        for sprite in self.sprites:
            if hasattr(sprite, "handle_event") and sprite.handle_event(event):
                return sprite
        return None

    def update(self, dt):
        """Atualiza os objetos da cena. `dt` está em SEGUNDOS."""
        self.sprites.update(dt)

    def render(self, surface):
        """Desenha o fundo e os objetos da cena na superfície recebida.

        Não usamos `Group.draw()` aqui de propósito: ele faz blit direto de
        `sprite.image` e ignora o método `draw()` do sprite, o que esconderia
        partes desenhadas por conta própria (o texto de um Button, por exemplo).
        Aqui cada objeto desenha a si mesmo.
        """
        surface.fill(self.background_color)
        for sprite in self.sprites:
            sprite.draw(surface)

    # ------------------------------------------------------------------
    # Ajuda para as cenas
    # ------------------------------------------------------------------
    def add_sprite(self, sprite):
        self.sprites.add(sprite)
        return sprite

    def remove_sprite(self, sprite):
        self.sprites.remove(sprite)

    def clear_sprites(self):
        self.sprites.empty()

    def request_scene(self, name):
        """Pede a troca de cena sem controlar o loop principal.

        A troca só acontece depois que todos os eventos do quadro atual
        tiverem sido processados.
        """
        if self.game is not None:
            self.logger.info("cena", f"{type(self).__name__} pediu a cena '{name}'")
            self.game.scene_manager.request_scene(name)