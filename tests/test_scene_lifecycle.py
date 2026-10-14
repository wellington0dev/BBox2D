"""Testes de ciclo de vida de cenas e gerenciamento de sprites.

Executar a partir da pasta do projeto:

    python3 -m unittest tests.test_scene_lifecycle -v

Ou todos os testes:

    python3 -m unittest discover -s tests -t . -v

Os testes rodam com o display virtual (`SDL_VIDEODRIVER=dummy`), definido
aqui antes de qualquer import do Pygame, para não exigir uma janela.

Por que este arquivo existe
---------------------------
A suíte anterior cobria física e pesos, e nada mais: `Scene`, `SceneManager`
e o contrato de sprites tinham **zero** cobertura. Isso é grave na hora de
extrair um framework, porque é justamente a parte que todo jogo consome
primeiro — abrir uma cena, trocar de cena, receber um clique.

Sem display, sem loop principal
-------------------------------
Nenhum teste aqui instancia `Game`, que exige janela real (`set_mode`) e
eventos de teclado. Tudo o que é testado roda em `SceneManager` e `Scene`
diretamente, com `game=None`. É por isso que `Game.run` fica fora: testá-lo
exigiria abrir uma janela, e abrir uma janela em CI é frágil e lento.

O contrato testado aqui é o mesmo que `Game.run` usa, só que dirigido à mão.
"""


import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from bbox2d.core.SceneManager import SceneManager
from bbox2d.core.scenes.Scene import Scene

#: passo fixo de simulação, em segundos.
DT = 1 / 60


class TracingScene(Scene):
    """Cena que registra a ordem em que os ganchos de ciclo de vida disparam.

    A ordem importa tanto quanto a ocorrência: uma cena que receba `on_enter`
    antes de a anterior receber `on_exit` compartilha estado entre as duas.
    Por isso o registro é uma lista só, e não um conjunto.
    """

    def __init__(self, game=None, trace=None, name="scene"):
        super().__init__(game)
        self.trace = trace if trace is not None else []
        self.name = name

    def on_enter(self):
        self.trace.append(f"{self.name}.enter")

    def on_exit(self):
        self.trace.append(f"{self.name}.exit")


class RecordingSprite(pygame.sprite.Sprite):
    """Sprite que registra os eventos que recebe.

    `handle_event` devolve `consumes`, como a interface exige: devolvendo
    `True`, o sprite "consumiu" o evento e a cena para nele.
    """

    def __init__(self, consumes=True, tag="sprite", visited=None):
        super().__init__()
        self.consumes = consumes
        self.tag = tag
        self.visited = visited if visited is not None else []
        self.image = pygame.Surface((4, 4))
        self.image.fill((200, 200, 200))
        self.rect = self.image.get_rect()

    def handle_event(self, event):
        self.visited.append(self.tag)
        return self.consumes

    def update(self, dt):
        self.visited.append(("update", dt))

    def draw(self, surface):
        # Desenha um único pixel deslocado, para que o teste differentiate o
        # fundo da cena do sprite sem precisar de imagem real.
        surface.set_at((6, 6), (10, 20, 30))


class SceneRegistrationTest(unittest.TestCase):
    """Registro de cenas pelo nome, sem conhecimento da classe concreta."""

    def setUp(self):
        self.trace = []
        self.manager = SceneManager(game=None)
        self.manager.register(
            "alpha", lambda game=None: TracingScene(game, self.trace, "alpha")
        )
        self.manager.register(
            "beta", lambda game=None: TracingScene(game, self.trace, "beta")
        )

    def test_start_activates_the_scene_and_calls_on_enter(self):
        """`start` instancia a cena e dispara `on_enter` uma vez."""
        self.manager.start("alpha")

        self.assertEqual(self.trace, ["alpha.enter"])
        self.assertIsInstance(self.manager.current_scene, TracingScene)

    def test_request_scene_does_not_switch_immediately(self):
        """Pedir a troca não troca: a troca é adiada.

        Trocar durante o laço de eventos invalidaria a iteração sobre os
        sprites, que é exatamente o que a lista de eventos do Pygame faz.
        """
        self.manager.start("alpha")
        self.trace.clear()

        self.manager.request_scene("beta")

        self.assertEqual(self.trace, [])
        self.assertEqual(type(self.manager.current_scene).__name__, "TracingScene")
        self.assertEqual(self.manager.current_scene.name, "alpha")

    def test_pending_switch_is_applied_on_next_update_in_order(self):
        """O `update` seguinte aplica a troca pendente, na ordem correta.

        Este teste cobre DOIS contratos de uma vez, porque são o mesmo
        percurso observado de dois jeitos:

        1. a troca pendente é aplicada — `current_scene` passa a ser a nova;
        2. a ordem é `on_exit` da antiga e só depois `on_enter` da nova.

        A ordem é o que a lista de trace comprova: se fosse invertida, a nova
        cena entraria enquanto a antiga ainda estivesse viva, e qualquer
        recurso compartilhado entre as duas seria destruído tarde demais.
        """
        self.manager.start("alpha")
        self.trace.clear()
        self.manager.request_scene("beta")

        self.manager.update(DT)

        self.assertEqual(self.trace, ["alpha.exit", "beta.enter"])
        self.assertEqual(self.manager.current_scene.name, "beta")

        # A pendência foi consumida: um update a mais não reaplica nada.
        self.manager.update(DT)
        self.assertEqual(self.trace, ["alpha.exit", "beta.enter"])

    def test_requesting_an_unregistered_scene_raises_key_error(self):
        """Nome desconhecido é erro de programador, não silêncio.

        Falhar aqui é melhor do que a troca simplesmente não acontecer e o
        jogo ficar travado na cena errada sem nenhuma pista.
        """
        with self.assertRaises(KeyError):
            self.manager.request_scene("inexistente")

    def test_shutdown_exits_the_active_scene(self):
        """Encerrar o gerenciador dispara `on_exit` e limpa a cena ativa."""
        self.manager.start("alpha")
        self.trace.clear()

        self.manager.shutdown()

        self.assertEqual(self.trace, ["alpha.exit"])
        self.assertIsNone(self.manager.current_scene)

    def test_manager_without_scene_survives_update_and_event(self):
        """Antes de `start`, nada acontece e nada quebra."""
        self.manager.update(DT)
        self.manager.handle_event(None)

        self.assertIsNone(self.manager.current_scene)

    def test_render_without_scene_fills_the_surface_black(self):
        """Sem cena ativa, a tela fica preta em vez de ficar suja.

        Ocorre na troca de cena: `_apply_pending_scene` zera `current_scene`
        entre um passo e outro, e `render` pode ser chamado nesse intervalo.
        """
        surface = pygame.Surface((8, 8))
        surface.fill((255, 255, 255))

        self.manager.render(surface)

        self.assertEqual(surface.get_at((0, 0))[:3], (0, 0, 0))


class SceneSpriteTest(unittest.TestCase):
    """Contrato do grupo de sprites próprio de cada cena."""

    def test_sprites_are_updated_with_dt_in_seconds(self):
        """`Scene.update` repassa `dt`, em segundos, para cada sprite."""
        scene = Scene()
        visited = []
        scene.add_sprite(RecordingSprite(visited=visited))

        scene.update(0.25)

        self.assertEqual(visited, [("update", 0.25)])

    def test_handle_event_stops_at_the_first_consumer(self):
        """Um clique não aciona dois sprites.

        Com dois botões na tela, o do segundo não pode reagir ao mesmo
        evento que o do primeiro já consumiu.
        """
        scene = Scene()
        visited = []
        first = scene.add_sprite(RecordingSprite(True, "a", visited))
        scene.add_sprite(RecordingSprite(True, "b", visited))

        consumed_by = scene.handle_event(None)

        self.assertIs(consumed_by, first)
        self.assertEqual(visited, ["a"])

    def test_handle_event_continues_past_non_consumers(self):
        """Quem devolve `False` não consome: o evento segue adiante."""
        scene = Scene()
        visited = []
        scene.add_sprite(RecordingSprite(False, "a", visited))
        second = scene.add_sprite(RecordingSprite(True, "b", visited))

        consumed_by = scene.handle_event(None)

        self.assertIs(consumed_by, second)
        self.assertEqual(visited, ["a", "b"])

    def test_handle_event_returns_none_when_nothing_consumes(self):
        scene = Scene()
        scene.add_sprite(RecordingSprite(False, "a"))

        self.assertIsNone(scene.handle_event(None))

    def test_adding_the_same_sprite_twice_registers_it_once(self):
        """`Group` ignora duplicata: um sprite não é atualizado duas vezes."""
        scene = Scene()
        visited = []
        sprite = scene.add_sprite(RecordingSprite(visited=visited))

        scene.add_sprite(sprite)

        self.assertEqual(len(scene.sprites), 1)

    def test_remove_and_clear_sprites(self):
        """A cena consegue esvaziar seus sprites ao sair."""
        scene = Scene()
        keep = scene.add_sprite(RecordingSprite())
        drop = scene.add_sprite(RecordingSprite())

        scene.remove_sprite(drop)
        self.assertEqual(len(scene.sprites), 1)

        scene.clear_sprites()
        self.assertEqual(len(scene.sprites), 0)
        self.assertNotIn(keep, scene.sprites)

    def test_render_paints_background_then_sprites(self):
        """O fundo vem primeiro e o sprite é desenhado por cima.

        `Scene.render` não usa `Group.draw()` de propósito: ele blitaria
        `sprite.image` direto e ignoraria o método `draw()` do sprite, que é
        onde o `Button` escreve o próprio rótulo.
        """
        scene = Scene()
        scene.background_color = (60, 60, 60)
        scene.add_sprite(RecordingSprite())
        surface = pygame.Surface((16, 16))

        scene.render(surface)

        # Canto sem sprite: fundo da cena.
        self.assertEqual(surface.get_at((15, 15))[:3], (60, 60, 60))
        # Pixel desenhado pelo sprite.
        self.assertEqual(surface.get_at((6, 6))[:3], (10, 20, 30))

    def test_scene_without_game_can_still_request_a_scene(self):
        """`request_scene` sem `game` não quebra — e não inventa um destino.

        Permite montar e testar uma cena isolada, sem `Game` por trás.

        Além de não levantar exceção, a cena precisa continuar sem `game` e
        sem sprites: um `request_scene` que fabricasse um destino seria tão
        defeituoso quanto um que estourasse.
        """
        scene = Scene()

        scene.request_scene("qualquer")

        self.assertIsNone(scene.game)
        self.assertEqual(len(scene.sprites), 0)

    def test_scene_without_game_still_updates_and_renders(self):
        """Uma cena sem `Game` atualiza e desenha normalmente.

        Renderiza sobre uma superfície já pintada de branco: o fundo da cena
        tem de cobrir por completo, senão sobraria pixel do teste anterior.
        """
        scene = Scene()
        scene.background_color = (7, 8, 9)
        surface = pygame.Surface((8, 8))
        surface.fill((255, 255, 255))

        scene.update(DT)
        scene.render(surface)

        self.assertEqual(surface.get_at((0, 0))[:3], (7, 8, 9))

    def test_clear_sprites_is_safe_on_an_empty_scene(self):
        """Esvaziar uma cena que já está vazia é seguro e idempotente."""
        scene = Scene()

        scene.clear_sprites()
        scene.clear_sprites()

        self.assertEqual(len(scene.sprites), 0)