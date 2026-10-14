"""Cena de demonstração da física.

Contém um cenário para exercitar o sistema de objetos, gravidade e colisões:
chão, plataformas suspensas, paredes e teto, um jogador controlável, um inimigo
que patrulha e um objeto sem gravidade que anda em linha reta até bater em algo.

Ordem de atualização (importante para o movimento não ser aplicado duas vezes):

    1. `handle_event` (no Game) chega aqui e o Player registra a intenção de pular;
    2. `self.physics.update(dt)`:
         a. o Player.update() lê o teclado e DEFINE a velocidade;
         b. a gravidade é aplicada;
         c. o movimento é aplicado e as colisões resolvidas;
    3. a cena desenha tudo.

O Player nunca move o próprio `rect`: ele só declara velocidade.
"""

import pygame

from .Scene import Scene
from ...objects.Enemy import Enemy
from ...objects.GameObject import GameObject
from ...objects.InteractiveObject import InteractiveObject
from ...objects.Player import Player
from ...physics.PhysicsWorld import PhysicsWorld
from ...platforms.Platform import Platform
from ...ui.Button import Button
from ...ui.Text import Text

MESSAGE = "Setor de teste da fisica"
BUTTON_LABEL = "Menu"
HELP_LINES = (
    "Setas / A D: andar     ESPACO: pular (as caixas amarelas pesam)",
    "R: reiniciar",
)

# Cores do cenário.
COLOR_GROUND = (86, 68, 46)
COLOR_PLATFORM = (120, 96, 64)
COLOR_WALL = (58, 48, 38)
COLOR_MOVING_PLATFORM = (168, 92, 140)
CARGO_COLOR = (226, 168, 74)
COLOR_TEXT = (238, 236, 220)

WALL_THICKNESS = 32
FLOOR_HEIGHT = 32
CEILING_HEIGHT = 24


class GameScene(Scene):
    """Cenário de testes da física."""

    def __init__(self, game=None):
        super().__init__(game)
        self.background_color = (24, 28, 38)

        width = self.game.width if self.game else 640
        height = self.game.height if self.game else 480

        # Cada cena tem o seu próprio mundo físico: nada de uma cena interfere
        # nos objetos de outra.
        self.world = PhysicsWorld(bounds=pygame.Rect(0, 0, width, height))

        self._build_level(width, height)

        self.message = Text(MESSAGE, font_size=28, color=COLOR_TEXT)
        self.message.center = (width // 2, 28)
        self.message.rect.center = self.message.center

        self.help_texts = []
        for index, line in enumerate(HELP_LINES):
            text = Text(line, font_size=16, color=(190, 190, 180))
            text.center = (width // 2, height - 34 + index * 18)
            text.rect.center = text.center
            self.help_texts.append(text)

        self.back_button = self.add_sprite(Button(BUTTON_LABEL, 110, 42, font_size=20))
        self.back_button.rect.topleft = (16, height - 150)

    # ------------------------------------------------------------------
    # Cenário
    # ------------------------------------------------------------------
    def _build_level(self, width, height):
        """Cria as plataformas e os objetos do cenário."""
        # `R` reconstrói o cenário: sem esta limpeza as plataformas antigas
        # continuariam no mundo e os objetos nasceriam sobre elas.
        self.world.platforms.clear()

        # Superfícies: chão, teto, paredes e plataformas suspensas.
        self._add_platform(
            (0, height - FLOOR_HEIGHT), (width, FLOOR_HEIGHT), COLOR_GROUND
        )
        self._add_platform((0, 0), (width, CEILING_HEIGHT), COLOR_WALL)
        self._add_platform((0, 0), (WALL_THICKNESS, height), COLOR_WALL)
        self._add_platform(
            (width - WALL_THICKNESS, 0), (WALL_THICKNESS, height), COLOR_WALL
        )

        # Duas plataformas suspensas, para pular nelas.
        self._add_platform((120, height - 150), (140, 20), COLOR_PLATFORM)
        self._add_platform((420, height - 300), (150, 20), COLOR_PLATFORM)

        # Elevador: sobe e desce levando quem estiver em cima. Fica na coluna
        # esquerda, livre de outras plataformas, e o percurso termina longe do
        # teto: se o encostasse, pararia de subir e o passageiro ficaria
        # para trás.
        self.lift = Platform(
            position=(60, height - 300),
            size=(100, 18),
            color=COLOR_MOVING_PLATFORM,
            moving=True,
            speed=70,
            travel=80,
            axis="y",
        )
        self.world.add_platform(self.lift)

        # Shuttle: plataforma horizontal que leva quem está em cima de um
        # lado para o outro.
        self.shuttle = Platform(
            position=(180, height - 90),
            size=(110, 18),
            color=(110, 150, 180),
            moving=True,
            speed=80,
            travel=140,
            axis="x",
        )
        self.world.add_platform(self.shuttle)

        # Jogador: começa em cima da primeira plataforma suspensa. O peso é
        # maior que o das caixas, para que ele consiga saltar carregando uma
        # delas, mas não duas.
        self.player = self._spawn(Player((160, height - 220), weight=4.0))

        # Caixas de peso: caem sobre o jogador e reduzem a altura do pulo. As duas
        # nascem já apoiadas nele, uma sobre a outra. As posições são exatas
        # (30px de altura cada) para que nenhuma caixa nasça penetrada, o que
        # causaria um reposicionamento de colisão no primeiro quadro.
        self.boxes = []
        for index in range(2):
            box = GameObject(
                (166, height - 220 - 30 - index * 30),
                size=(30, 30),
                color=CARGO_COLOR,
                gravity_enabled=True,
                solid=True,
                weight=1.5,
            )
            self.boxes.append(self._spawn(box))

        # Passageiro: nasce EM CIMA do elevador e é arrastado por ele durante todo o
        # percurso, exercitando o arrasto vertical.
        self.ride = self._spawn(
            GameObject(
                (98, height - 324),
                size=(24, 24),
                color=(240, 140, 200),
                gravity_enabled=True,
                solid=True,
            )
        )

        # Inimigo: patrulha a plataforma mais alta, longe do elevador para não
        # disputar o espaço com o passageiro.
        self.enemy = self._spawn(Enemy((440, height - 370)))

        # Objeto sem gravidade: anda na horizontal até bater numa parede.
        self.mover = self._spawn(
            InteractiveObject(
                (260, height - 200),
                size=(24, 24),
                color=(120, 200, 255),
                gravity_enabled=False,
                solid=True,
                speed=150,
            )
        )
        self.mover.activate()

    def _add_platform(self, position, size, color):
        platform = Platform(position=position, size=size, color=color)
        self.world.add_platform(platform)
        return platform

    def _spawn(self, game_object):
        """Registra um objeto no mundo físico e no grupo de sprites da cena."""
        self.world.add_object(game_object)
        self.add_sprite(game_object)
        return game_object

    # ------------------------------------------------------------------
    # Ciclo da cena
    # ------------------------------------------------------------------
    def on_enter(self):
        print(f"[{type(self).__name__}] entrou")

    def on_exit(self):
        print(f"[{type(self).__name__}] saiu")

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.request_scene("menu")
                return
            if event.key == pygame.K_q:
                self.game.running = False
                return
            if event.key == pygame.K_r:
                self._restart()
                return

        # O Player registra a intenção de pular e consome o evento de tecla.
        if self.player.handle_event(event):
            return self.player

        clicked = super().handle_event(event)
        if clicked is self.back_button:
            self.request_scene("menu")
        return clicked

    def update(self, dt):
        # A cena não move nada: a física é dona do deslocamento. Ela também
        # chama `obj.update(dt)`, onde o Player lê o teclado.
        self.world.update(dt)

    def render(self, surface):
        surface.fill(self.background_color)

        # Cenário atrás dos objetos.
        for platform in self.world.platforms:
            platform.draw(surface)

        for sprite in self.sprites:
            sprite.draw(surface)

        self.message.draw(surface)
        for text in self.help_texts:
            text.draw(surface)

        self._draw_debug(surface)

    # ------------------------------------------------------------------
    # Apoio à verificação
    # ------------------------------------------------------------------
    def _draw_debug(self, surface):
        """Descreve o estado físico e a carga do jogador."""
        grounded = "CHAO" if self.player.grounded else "AR"
        player = self.player
        load = player.get_supported_load()
        info = (
            f"vy={player.velocity.y:7.1f}  vx={player.velocity.x:6.1f}  {grounded}"
            f"  |  carga={load:4.1f}/{player.weight:.0f}"
            f"  pulo={player.get_jump_factor() * 100:3.0f}%"
        )
        debug = Text(info, font_size=16, color=(150, 220, 160))
        debug.center = (self.game.width // 2 if self.game else 320, 56)
        debug.rect.center = debug.center
        debug.draw(surface)

    def _restart(self):
        """Recria os objetos do cenário, útil para testar a queda de novo."""
        for obj in (self.player, self.enemy, self.mover, self.ride, *self.boxes):
            self.world.remove_object(obj)
            self.remove_sprite(obj)

        self._build_level(self.game.width, self.game.height)
        print("[GameScene] cenario reiniciado")