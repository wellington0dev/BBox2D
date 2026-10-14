"""Ponto de entrada do jogo.

Aqui ficam apenas as decisões de inicialização: criar o `Game`, registrar
quais cenas existem e dizer qual cena começa. Nenhuma cena concreta é
importada pelo SceneManager, o que evita dependências circulares.
"""

import sys
from pathlib import Path

try:
    # Executado como módulo: `python3 -m src.main` (a partir da pasta do projeto)
    from .core.Game import Game
    from .core.scenes.MenuScene import MenuScene
    from .core.scenes.GameScene import GameScene
except ImportError:
    # Executado como script: `python3 src/main.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.core.Game import Game
    from src.core.scenes.MenuScene import MenuScene
    from src.core.scenes.GameScene import GameScene

WIDTH = 640
HEIGHT = 480
TITLE = "BBox"
FPS = 60

START_SCENE = "menu"


def main():
    game = Game(width=WIDTH, height=HEIGHT, title=TITLE, fps=FPS)

    # Registro de cenas: o SceneManager só conhece estes nomes.
    game.scene_manager.register("menu", MenuScene)
    game.scene_manager.register("game", GameScene)

    game.run(START_SCENE)


if __name__ == "__main__":
    main()