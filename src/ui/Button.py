"""Componente de botão reutilizável.

Responsável apenas por: imagem, retângulo de posicionamento, texto interno
e detecção de clique. Não executa nenhuma ação do jogo: quem decide o que
acontece no clique é a cena, que chama `request_scene`, `running = False`, etc.

DEBUG
-----
Para ligar os logs, troque `DEBUG = False` por `DEBUG = True` abaixo, ou em
tempo de execução: `import src.ui.Button as ui_button; ui_button.DEBUG = True`.
"""

from pathlib import Path

import pygame

from .Text import Text

# Liga/desliga os logs de depuração deste módulo.
DEBUG = False


def _log(*args):
    if DEBUG:
        print("[Button]", *args)


# src/ui/Button.py -> src/ui -> src
ASSETS_PATH = Path(__file__).resolve().parents[1] / "assets"
DEFAULT_IMAGE_PATH = ASSETS_PATH / "button.png"


class Button(pygame.sprite.Sprite):
    def __init__(
        self,
        label="",
        width=180,
        height=70,
        font_size=28,
        color=(255, 255, 255),
        image_path=None,
    ):
        # Sprite dá ao botão `image` e `rect`, que o Group usa para
        # atualizar e organizar o objeto.
        super().__init__()

        if image_path is None:
            image_path = DEFAULT_IMAGE_PATH
        image_path = Path(image_path)
        if not image_path.is_file():
            raise FileNotFoundError(f"Imagem do botão não encontrada: {image_path}")

        image = pygame.image.load(str(image_path)).convert_alpha()
        original_size = image.get_size()
        self.image = pygame.transform.scale(image, (width, height))
        self.rect = self.image.get_rect()

        # O botão cuida do próprio texto: basta passar a string do rótulo.
        self.text = Text(label, font_size=font_size, color=color)

        _log(
            f"criado: rotulo={label!r} tamanho={font_size} cor={color} "
            f"imagem={image_path.name} {original_size} -> {self.image.get_size()} "
            f"rect={tuple(self.rect)}"
        )

        if self.image.get_alpha() is None:
            _log("AVISO: a imagem do botão não tem canal alfa")

    def handle_event(self, event):
        """Devolve True se este evento foi um clique esquerdo sobre o botão."""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                _log(f"clicado em {event.pos} (rect={tuple(self.rect)})")
                return True
            _log(f"clique em {event.pos} fora do botão (rect={tuple(self.rect)})")
        return False

    def update(self, dt=0.0):
        """O botão é estático, mas precisa existir para o Group.update()."""
        pass

    def draw(self, surface):
        surface.blit(self.image, self.rect)

        # `center` mantém o texto no meio do botão mesmo depois de
        # mudar o conteúdo (o que altera o tamanho do texto).
        self.text.center = self.rect.center
        self.text.rect.center = self.rect.center
        self.text.draw(surface)

        _log(
            f"desenhado em {tuple(self.rect)} "
            f"texto={self.text.content!r} em {tuple(self.text.rect)}"
        )