"""Ponto de entrada do jogo.

Aqui ficam apenas as decisões de inicialização: criar o `Game`, registrar
quais cenas existem e dizer qual cena começa. Nenhuma cena concreta é
importada pelo SceneManager, o que evita dependências circulares.
"""

import sys
from pathlib import Path

# Permite executar o jogo direto do repositório, sem instalar o pacote:
#
#   python3 -m examples.bbox.main    (a partir da raiz do projeto)
#   python3 examples/bbox/main.py    (a partir de qualquer lugar)
#
# `bbox2d` fica em `src/`, o mesmo diretório que o pip usa em modo editável.
# As cenas deste jogo ficam em `examples/`, na raiz, fora do pacote instalado.
_RAIZ = Path(__file__).resolve().parent.parent.parent
for _caminho in (_RAIZ / "src", _RAIZ):
    if _caminho.is_dir() and str(_caminho) not in sys.path:
        sys.path.insert(0, str(_caminho))

from bbox2d.core.Game import Game
from examples.bbox.GameScene import GameScene
from examples.bbox.MenuScene import MenuScene

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