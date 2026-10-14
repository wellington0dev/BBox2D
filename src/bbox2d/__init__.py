"""bbox2d — motor de jogos 2D sobre Pygame.

API pública inicial da Fase M2. Ela é **pequena e intencional**: exporta o
que um desenvolvedor precisa para criar um jogo, e nada mais. Tudo o que não
está listado aqui continua importável pelo caminho completo
(`bbox2d.physics.PhysicsWorld`), mas esse caminho é detalhe de implementação
e pode mudar.

A API pública poderá evoluir depois que a extração estiver validada; por
isso nada aqui foi renomeado ou reorganizado em relação ao código original.

Exemplo mínimo
--------------

    import pygame
    from bbox2d import Game, PhysicsWorld, Platform, Scene, SceneManager

    class MinhaCena(Scene):
        def on_enter(self):
            self.world = PhysicsWorld(bounds=(0, 0, 640, 480))
            self.world.add_platform(Platform((0, 460), (640, 20)))

        def update(self, dt):
            self.world.update(dt)

        def render(self, surface):
            surface.fill((18, 18, 24))
            for plataforma in self.world.platforms:
                pygame.draw.rect(surface, plataforma.color, plataforma.rect)

    jogo = Game(width=640, height=480, title="Meu jogo")
    jogo.scene_manager.register("nivel", MinhaCena)
    jogo.run("nivel")

Importar este módulo **não** inicializa o Pygame nem abre janela: `pygame.init()`
e `pygame.display.set_mode()` acontecem em `Game.__init__`, e só lá. É por isso
que a física pode ser importada e usada em teste, script e servidor sem display.
"""

# --------------------------------------------------------------------------
# Aplicação
# --------------------------------------------------------------------------
from .core.Game import Game
from .core.SceneManager import SceneManager
from .core.scenes.Scene import Scene

# --------------------------------------------------------------------------
# Física
# --------------------------------------------------------------------------
from .physics.Collision import Collision, ContactState, Direction
from .physics.PhysicsWorld import PhysicsWorld

# --------------------------------------------------------------------------
# Corpos
# --------------------------------------------------------------------------
from .objects.Enemy import Enemy
from .objects.GameObject import GameObject
from .objects.InteractiveObject import InteractiveObject
from .objects.Player import Player

# --------------------------------------------------------------------------
# Superfícies
# --------------------------------------------------------------------------
from .platforms.Platform import Platform

# --------------------------------------------------------------------------
# Interface
# --------------------------------------------------------------------------
from .ui.Button import Button
from .ui.Text import Text

__version__ = "0.1.0"

__all__ = [
    # Aplicação
    "Game",
    "Scene",
    "SceneManager",
    # Física
    "PhysicsWorld",
    "Collision",
    "ContactState",
    "Direction",
    # Corpos
    "GameObject",
    "Player",
    "Enemy",
    "InteractiveObject",
    # Superfícies
    "Platform",
    # Interface
    "Text",
    "Button",
    # Metadados
    "__version__",
]