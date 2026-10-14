"""Componente de texto reutilizável.

Responsável apenas por: conteúdo textual, fonte, tamanho, cor e renderização.
Não conhece o loop principal, cenas ou eventos do Pygame.

DEBUG
-----
O carregamento de fonte é um ponto comum de falha silenciosa (caminho errado,
fonte que não existe, módulo `pygame.font` não inicializado). Para tornar
esses casos visíveis em log, defina:

    from ui.Text import DEBUG
    DEBUG = True

Os logs usam o prefixo [Text] e vão para stdout.
"""

from pathlib import Path

import pygame

# Liga/desliga os logs de depuração deste módulo.
DEBUG = True


def _log(*args):
    if DEBUG:
        print("[Text]", *args)


# src/ui/Text.py -> src/ui -> src
ASSETS_PATH = Path(__file__).resolve().parents[1] / "assets"
DEFAULT_FONT_PATH = ASSETS_PATH / "font" / "upheavtt.ttf"


def load_font(font_path=None, font_size=24):
    """Carrega a fonte pedida e cai para a fonte padrão do projeto.

    Ordem de tentativa:
      1. `font_path`, se informado;
      2. a fonte padrão do projeto (`assets/font/upheavtt.ttf`);
      3. a fonte embutida do Pygame (`pygame.font.Font(None, ...)`).

    Se nenhum arquivo existir, a última opção sempre funciona.
    """
    # `pygame.font.Font` exige o módulo de fonte inicializado. O `pygame.init()`
    # do Game já faz isso, mas o Text pode ser usado de forma isolada
    # (testes, uso direto do componente) e nesse caso quebraria sem isto.
    if not pygame.font.get_init():
        _log("pygame.font não estava inicializado, chamando pygame.font.init()")
        pygame.font.init()

    candidates = []
    if font_path is not None:
        candidates.append(("informada", Path(font_path)))
    # Só tenta a fonte padrão se ela ainda não foi tentada acima.
    if font_path is None or Path(font_path) != DEFAULT_FONT_PATH:
        candidates.append(("padrão do projeto", DEFAULT_FONT_PATH))

    _log(f"carregando fonte, tamanho={font_size}, tentativas={[str(p) for _, p in candidates]}")

    for origem, candidate in candidates:
        if candidate.is_file():
            try:
                font = pygame.font.Font(str(candidate), font_size)
            except (pygame.error, OSError) as exc:
                # Arquivo existe mas o Pygame não conseguiu abrir: segue tentando.
                _log(f"FALHA ao abrir {candidate} (origem: {origem}): {exc}")
                continue
            _log(f"OK fonte carregada de {candidate} (origem: {origem})")
            return font

        _log(f"NÃO EXISTE {candidate} (origem: {origem}), tentando próxima")

    _log("AVISO: nenhuma fonte em disco funcionou, usando a fonte embutida do Pygame")
    return pygame.font.Font(None, font_size)


class Text:
    """Um texto renderizável.

    A superfície de texto só é re-renderizada quando alguma propriedade
    relevante muda (conteúdo, fonte ou cor), e não a cada quadro.
    """

    def __init__(
        self,
        content="",
        font_path=None,
        font_size=24,
        color=(255, 255, 255),
    ):
        self.content = content
        self.font_size = font_size
        self.font_path = font_path
        self.color = color

        _log(f"criando Text: conteudo={content!r} tamanho={font_size} cor={color}")

        if not content:
            _log("AVISO: texto criado com conteúdo vazio, nada será visível")

        self.font = load_font(font_path, font_size)

        # A superfície real só é criada no primeiro desenho (lazy rendering).
        self._surface = None

        # `rect` existe desde o início para poder posicionar o texto
        # antes do primeiro desenho.
        self.rect = pygame.Rect(0, 0, 0, 0)

        # Âncora opcional: se definida, o texto é recentrado nela sempre que
        # for renderizado de novo. Sem isso, mudar o conteúdo mudaria o tamanho
        # do rect e o texto "pularia" de lugar.
        self.center = None

    @property
    def surface(self):
        """Superfície renderizada, criada/atualizada só quando necessário."""
        if self._surface is None:
            self._surface = self._render()
            self.rect.size = self._surface.get_size()
            if self.center is not None:
                self.rect.center = self.center
            _log(
                f"render: conteudo={self.content!r} "
                f"tamanho_render={self._surface.get_size()} rect={tuple(self.rect)}"
            )
        return self._surface

    def _render(self):
        """Renderiza o texto, com fallback se a fonte falhar na hora de desenhar.

        Uma fonte corrompida pode ser carregada sem erro pelo SDL e só falhar
        aqui com `Passed a NULL pointer`. Nesse caso usamos a fonte embutida
        do Pygame para o texto continuar visível.
        """
        try:
            return self.font.render(self.content, True, self.color)
        except pygame.error as exc:
            _log(f"FALHA no render com a fonte {self.font_path}: {exc}")
            fallback = pygame.font.Font(None, self.font_size)
            self.font = fallback
            return fallback.render(self.content, True, self.color)

    def set_text(self, content):
        if content != self.content:
            _log(f"set_text: {self.content!r} -> {content!r}")
            self.content = content
            self._surface = None  # força um novo render no próximo desenho

    def set_color(self, color):
        if color != self.color:
            _log(f"set_color: {self.color} -> {color}")
            self.color = color
            self._surface = None

    def set_font_size(self, font_size):
        if font_size != self.font_size:
            _log(f"set_font_size: {self.font_size} -> {font_size}")
            self.font_size = font_size
            self.font = load_font(self.font_path, font_size)
            self._surface = None

    def set_font_path(self, font_path):
        _log(f"set_font_path: {self.font_path} -> {font_path}")
        self.font_path = font_path
        self.font = load_font(font_path, self.font_size)
        self._surface = None

    def draw(self, surface):
        if DEBUG and self._surface is None:
            _log(f"primeiro draw do texto {self.content!r}, renderizando agora")
        surface.blit(self.surface, self.rect)