"""Testes de contrato público do `PhysicsWorld`.

Executar a partir da pasta do projeto:

    python3 -m unittest tests.test_world_contract -v

Ou todos os testes:

    python3 -m unittest discover -s tests -v

Os testes rodam com o display virtual (`SDL_VIDEODRIVER=dummy`), definido
aqui antes de qualquer import do Pygame, para não exigir uma janela.

Por que este arquivo existe
---------------------------
`tests/test_physics.py` cobre muito bem o *comportamento observável* da
simulação (queda, colisão, eventos, transporte em plataformas móveis). O que
não cobria eram os **contratos de API** que a extração para framework vai
expor publicamente: idempotência de registro, remoção, os parâmetros de
construtor (`bounds`, `max_fall_speed`), `get_surfaces`, `Platform.one_way`
e `Platform.solid=False`.

Esses contratos são a superfície que o jogo de demonstração ainda não usa,
mas que qualquer consumidor do framework vai usar. Um deles quebrar deve
aparecer aqui, e não três meses depois na extração.

Escopo desta suíte
------------------
Todos os testes usam **apenas API pública**. Nenhum toca em `_shift_axis`,
`_push_out`, `_apply_carry` ou `_contacts`. Onde seria natural recorrer a
uma API privada, o teste foi reformulado para observar o efeito pelo estado
público do objeto (`position`, `velocity`, `grounded`) ou pela API pública
de consulta (`get_surfaces`, `has_floor_ahead`).

Uma exceção deliberada: `_sync_rect()` NÃO é usada. Nos testes existentes
ela aparece porque o teste teleporta o objeto na mão. Aqui nenhum objeto é
movido manualmente — todos partem de uma posição e são movidos pela própria
simulação, que é o caminho que um jogo real percorre.


Defeitos conhecidos (NÃO cobertos aqui de propósito)
----------------------------------------------------
Esta suíte passa inteira. Os defeitos abaixo **não** são fixados por teste,
porque um teste que passa fixando um comportamento errado é pior do que
nenhum teste: ele transforma defeito em requisito. A documentação e a
correção ficam a cargo da Fase M6 (correção do carry).

1. `test_stack_of_objects_is_carried_upwards`
   (`tests/test_physics.py:601`)
   Três objetos empilhados sobre plataforma vertical que sobe.
   Observado: `start - obj.position.y == -470.0`, esperado `rise == 60`
   (diferença de 530.0). A pilha não sobe: o objeto de baixo fica parado no
   ar enquanto a plataforma sai por baixo, e depois a pilha se desmonta.
   Já cubierto pelo teste original, que continua vermelho.

2. `test_object_moving_up_carries_object_above`
   (`tests/test_physics.py:705`)
   Objeto de baixo sobe 3 px por quadro durante 10 quadros.
   Observado: `top_rise == 3.0`, esperado `base_rise == 30.0`.
   O objeto de cima acompanha o primeiro movimento e depois trava.

3. `Platform(can_carry=False)` não impede o arraste  (ACHADO NESTA FASE)
   `can_carry` é verificado em `_apply_platform_carry` (passo 1 do quadro),
   mas NÃO em `_apply_carry` (passo 4). Como `Platform.get_ride_offset()`
   devolve `frame_motion` sem olhar `can_carry`, o passo 4 arrasta o objeto
   do mesmo jeito — verificado empiricamente: com `can_carry=False` e
   `can_carry=True` o objeto chega à mesma posição final (x=220.0 partindo
   de 140.0 com a plataforma indo de x=100 para x=180).
   Não há teste cobrindo isso de propósito: o único jeito de escrevê-lo hoje
   seria ou fixar o defeito como esperado, ou acrescentar uma terceira
   falha à suíte. Fica registrado aqui para a Fase M6.

4. `Platform(one_way=True)` não deixa atravessar por baixo  (ACHADO NESTA FASE)
   O `one_way` é implementado em `_contact_direction` (linha 1642), que
   devolve `None` quando `obj.velocity.y <= 0` — isto é, não gera contato ao
   subir. Mas a resolução que de fato impede a passagem é
   `_resolve_axis_contacts`, que classifica o lado por `_side_on_axis`
   (linha 1453) e NÃO consulta `one_way`. Resultado verificado: um objeto
   subindo a 300 px/s de baixo para cima para com o topo encostado na base da
   plataforma (`rect.top == 220`, velocidade zerada), quando deveria
   atravessar e seguir até y=150.
   Ou seja, `one_way` funciona na direção pretendida (bloquear descida pelo
   topo, coberto por `test_one_way_blocks_falling_from_above`) e NÃO funciona
   na direção oposta.
   O teste que expressa o contrato desejado
   (`assertLess(body.rect.top, 200)`) está descrito em
   `PlatformFlagTest`, e não roda: ver o comentário naquele ponto do arquivo.
   Os defeitos 3 e 4 são a mesma classe: uma flag de superfície honrada em um
   caminho do motor e ignorada no outro.
"""

import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from src.objects.GameObject import GameObject
from src.physics.PhysicsWorld import PhysicsWorld
from src.platforms.Platform import Platform

#: passo fixo da simulação, em segundos.
DT = 1 / 60

#: tolerância de comparação de posição, em pixels.
TOLERANCE = 0.5


def simulate(world, seconds):
    """Roda a simulação por um número fixo de quadros."""
    for _ in range(int(seconds / DT)):
        world.update(DT)


def ground_at(world, y=300):
    """Registra um chão horizontal largo na altura `y`."""
    return world.add_platform(Platform((0, y), (640, 20)))


class RecordingLogger:
    """Logger que guarda o que foi registrado, para o teste consultar.

    `PhysicsWorld(logger=...)` é ponto de injeção **público**: o mundo nunca
    chama `pygame.log` nem escreve em arquivo por conta própria. Usar a
    injeção oficial é melhor do que monkeypatchar `world.logger` depois,
    porque não depende de atributo interno.

    Só o nível `error` é guardado: é o que os testes de `bounds` precisam.
    Os níveis abaixo existem porque o mundo chama `debug` a cada registro.
    """

    def __init__(self):
        self.errors = []

    def debug(self, category, message):
        pass

    def info(self, category, message):
        pass

    def warn(self, category, message):
        pass

    def error(self, category, message):
        self.errors.append((category, message))


class WorldRegistrationTest(unittest.TestCase):
    """Contrato de registro e remoção de corpos e superfícies."""

    def test_add_object_is_idempotent(self):
        """Registrar o mesmo objeto duas vezes não duplica a simulação."""
        world = PhysicsWorld()
        body = GameObject((100, 100), size=(30, 30))

        world.add_object(body)
        world.add_object(body)
        world.add_object(body)

        # Com duas cópias, o objeto colidiria consigo mesmo e sairia da tela.
        self.assertEqual(len(world.objects), 1)

    def test_add_platform_is_idempotent(self):
        """Registrar a mesma plataforma duas vezes não duplica a superfície."""
        world = PhysicsWorld()
        platform = Platform((100, 100), (80, 20))

        world.add_platform(platform)
        world.add_platform(platform)

        self.assertEqual(len(world.platforms), 1)

    def test_add_returns_the_same_object(self):
        """`add_object`/`add_platform` devolvem o próprio item registrado.

        Permite encadear: `world.add_object(GameObject(...))`.
        """
        world = PhysicsWorld()
        body = GameObject((0, 0), size=(10, 10))
        platform = Platform((0, 0), (10, 10))

        self.assertIs(world.add_object(body), body)
        self.assertIs(world.add_platform(platform), platform)

    def test_removed_object_stops_being_simulated(self):
        """Depois de `remove_object`, o objeto congela onde estava."""
        world = PhysicsWorld()
        ground_at(world)
        body = world.add_object(
            GameObject((100, 200), size=(30, 30), gravity_enabled=True)
        )

        simulate(world, 0.5)
        self.assertGreater(body.position.y, 200.0)

        world.remove_object(body)
        position_after_removal = body.position.y
        velocity_after_removal = body.velocity.y

        simulate(world, 1.0)

        self.assertEqual(body.position.y, position_after_removal)
        self.assertEqual(body.velocity.y, velocity_after_removal)
        self.assertNotIn(body, world.objects)

    def test_removed_platform_stops_blocking(self):
        """Depois de `remove_platform`, o chão some e o objeto atravessa."""
        world = PhysicsWorld()
        ground = ground_at(world)
        body = world.add_object(
            GameObject((100, 200), size=(30, 30), gravity_enabled=True)
        )

        simulate(world, 1.0)
        resting_y = body.position.y
        # O objeto descansa em cima do chão: base em y=300.
        self.assertAlmostEqual(body.rect.bottom, 300, delta=TOLERANCE)

        world.remove_platform(ground)
        simulate(world, 1.0)

        self.assertGreater(body.position.y, resting_y)
        self.assertNotIn(ground, world.platforms)

    def test_object_can_be_registered_again_after_removal(self):
        """Reinscrever um objeto removido o devolve à simulação."""
        world = PhysicsWorld()
        ground_at(world)
        body = world.add_object(
            GameObject((100, 200), size=(30, 30), gravity_enabled=True)
        )

        simulate(world, 0.5)
        world.remove_object(body)
        world.add_object(body)

        simulate(world, 1.0)

        self.assertEqual(len(world.objects), 1)
        self.assertAlmostEqual(body.rect.bottom, 300, delta=TOLERANCE)


class SurfaceQueryTest(unittest.TestCase):
    """Contrato de `get_surfaces`: quem a física considera obstáculo."""

    def test_get_surfaces_includes_platforms_and_solid_objects(self):
        world = PhysicsWorld()
        platform = ground_at(world)
        solid = world.add_object(GameObject((0, 0), size=(10, 10), solid=True))

        surfaces = world.get_surfaces()

        self.assertIn(platform, surfaces)
        self.assertIn(solid, surfaces)

    def test_get_surfaces_excludes_non_solid_objects(self):
        """Objeto `solid=False` não é obstáculo, para ninguém."""
        world = PhysicsWorld()
        ghost = world.add_object(GameObject((0, 0), size=(10, 10), solid=False))

        self.assertNotIn(ghost, world.get_surfaces())

    def test_get_surfaces_exclude_removes_the_object_itself(self):
        """Um objeto sólido se sobrepõe a si mesmo.

        Tratá-lo como superfície própria o empurraria para fora da tela todo
        quadro, então `exclude` existe para isso.
        """
        world = PhysicsWorld()
        body = world.add_object(GameObject((100, 100), size=(30, 30), solid=True))

        self.assertIn(body, world.get_surfaces())
        self.assertNotIn(body, world.get_surfaces(exclude=body))

    def test_object_without_world_reports_no_surfaces(self):
        """Objeto nunca registrado responde sem quebrar.

        Permite construir um objeto e consultá-lo antes de existir um mundo,
        que é o caso de quem configura a cena antes de montar a simulação.
        """
        body = GameObject((0, 0), size=(10, 10))

        self.assertIsNone(body.world)
        self.assertEqual(body.get_surfaces(), [])
        self.assertFalse(body.has_floor_ahead(1))


class BoundsDiagnosticTest(unittest.TestCase):
    """Contrato de `PhysicsWorld(bounds=...)`.

    `bounds` NÃO é uma contenção: o docstring de `_check_bounds` diz
    explicitamente "não corrige nada". É um **diagnóstico** — registra no log
    o objeto que saiu do cenário, a posição, os limites e os contatos do
    quadro. Um teste que exigisse "o objeto nunca sai" estaria testando um
    mecanismo que não existe; o que se trava aqui é o registro.
    """

    def test_bounds_is_optional(self):
        """Sem `bounds`, nada é registrado mesmo com o objeto fora da tela."""
        logger = RecordingLogger()
        world = PhysicsWorld(logger=logger)
        # Não há chão: o objeto cai para sempre.
        world.add_object(GameObject((100, 50), size=(30, 30), gravity_enabled=True))

        simulate(world, 2.0)

        self.assertEqual(logger.errors, [])

    def test_object_leaving_bounds_is_reported(self):
        """Objeto que sai do cenário gera um erro de categoria `limite`."""
        logger = RecordingLogger()
        world = PhysicsWorld(bounds=pygame.Rect(0, 0, 640, 480), logger=logger)
        # Sem chão, o objeto atravessa o limite inferior e continua caindo.
        body = world.add_object(
            GameObject((100, 50), size=(30, 30), gravity_enabled=True)
        )

        simulate(world, 2.0)

        self.assertGreater(body.rect.bottom, 480)
        categories = {category for category, _ in logger.errors}
        self.assertIn("limite", categories)

    def test_object_inside_bounds_is_not_reported(self):
        """Objeto dentro dos limites não gera erro nenhum."""
        logger = RecordingLogger()
        world = PhysicsWorld(bounds=pygame.Rect(0, 0, 640, 480), logger=logger)
        ground_at(world, y=460)
        world.add_object(GameObject((100, 100), size=(30, 30), gravity_enabled=True))

        simulate(world, 1.0)

        self.assertEqual(logger.errors, [])

    def test_bounds_does_not_teleport_the_object_back(self):
        """`bounds` é diagnóstico: ele NÃO devolve o objeto para dentro.

        Este teste existe para impedir que alguém leia "bounds" como parede
        e escreva um teste que dependa desse comportamento inexistente.
        """
        world = PhysicsWorld(bounds=pygame.Rect(0, 0, 640, 480))
        body = world.add_object(
            GameObject((100, 100), size=(30, 30), gravity_enabled=True)
        )

        simulate(world, 2.0)

        # Caiu livremente, sem correção nenhuma.
        self.assertGreater(body.rect.bottom, 480)


class PlatformFlagTest(unittest.TestCase):
    """Contrato das flags de superfície de `Platform`."""

    def test_one_way_blocks_falling_from_above(self):
        """Cair de cima para baixo: a plataforma uma via segura.

        Esta é a direção que `one_way` implementa de fato: `_contact_direction`
        devolve `None` quando o objeto sobe, de modo que só a descida gera
        contato.

        A direção oposta — atravessar por baixo — NÃO funciona hoje. Ver o
        defeito nº 4 na documentação do módulo.
        """
        world = PhysicsWorld()
        ground_at(world, y=400)
        platform = world.add_platform(Platform((100, 200), (120, 20), one_way=True))
        body = world.add_object(
            GameObject((130, 100), size=(30, 30), gravity_enabled=True)
        )

        simulate(world, 2.0)

        # Descansa sobre a plataforma, não no chão lá embaixo.
        self.assertAlmostEqual(body.rect.bottom, platform.rect.top, delta=TOLERANCE)

    # NÃO existe aqui um teste para a travessia de baixo para cima.
    #
    # O comportamento desejado seria `assertLess(body.rect.top, 200)`: um
    # objeto subindo a 300 px/s de `(130, 250)` deveria atravessar a plataforma
    # de `200..220` e continuar até y=150. Esse teste está escrito e verificado,
    # mas **falha hoje** (o objeto para em `rect.top == 220`, com a velocidade
    # zerada). Ver defeito nº 4 na documentação do módulo.
    #
    # Ele não entra nesta suíte por escolha, e a escolha é deliberada:
    #
    #   * escrevê-lo como está                  -> nova falha na suíte, que é
    #     exatamente o que a M1 prometeu não fazer;
    #   * escrevê-lo invertendo a asserção     -> afirmaria o defeito como
    #     contrato, congelando o bug na suíte de regressão.
    #
    # Ambos são ruins. O defeito fica registrado na documentação e a correção
    # acontece na Fase M6, junto com o carry. Quando `_side_on_axis` passar a
    # consultar `one_way`, o teste entra aqui com a asserção correta.

    def test_non_solid_platform_does_not_block(self):
        """`solid=False` torna a plataforma transparente para a física."""
        world = PhysicsWorld()
        ground = ground_at(world, y=300)
        world.add_platform(Platform((100, 200), (120, 20), solid=False))
        body = world.add_object(
            GameObject((130, 150), size=(30, 30), gravity_enabled=True)
        )

        simulate(world, 2.0)

        # Caiu direto até o chão, atravessando a plataforma invisível.
        self.assertAlmostEqual(body.rect.bottom, ground.rect.top, delta=TOLERANCE)

    def test_platform_without_moving_stays_in_place(self):
        """`moving=False` (o padrão) deixa a plataforma parada.

        Existe para fixar o padrão: qualquer teste de plataforma móvel em
        outro lugar precisa declarar `moving=True` com `axis` e `speed`, em vez
        de depender de algum valor herdado.
        """
        world = PhysicsWorld()
        platform = world.add_platform(Platform((100, 100), (80, 20)))

        simulate(world, 2.0)

        self.assertEqual(platform.rect.x, 100)
        self.assertEqual(platform.rect.y, 100)


class MotionParameterTest(unittest.TestCase):
    """Contrato de `max_fall_speed` e de `acceleration`."""

    def test_max_fall_speed_caps_the_fall(self):
        """A queda não passa do teto configurado, mesmo após muitos quadros."""
        world = PhysicsWorld(max_fall_speed=100.0)
        # Chão muito abaixo: o objeto nunca pousa durante o teste.
        ground_at(world, y=5000)
        body = world.add_object(
            GameObject((100, 0), size=(30, 30), gravity_enabled=True)
        )

        simulate(world, 5.0)

        self.assertLessEqual(body.velocity.y, 100.0 + TOLERANCE)

    def test_default_max_fall_speed_is_faster(self):
        """O teto padrão é bem mais alto que um teto personalizado.

        Garante que o teste anterior não passa só porque `100.0` é o padrão.
        """
        world = PhysicsWorld()
        ground_at(world, y=5000)
        body = world.add_object(
            GameObject((100, 0), size=(30, 30), gravity_enabled=True)
        )

        simulate(world, 5.0)

        self.assertGreater(body.velocity.y, 100.0)

    def test_acceleration_integrates_into_velocity(self):
        """Aceleração constante vira velocidade após tempo conhecido."""
        world = PhysicsWorld()
        ground_at(world, y=5000)
        body = world.add_object(
            GameObject((100, 0), size=(30, 30), gravity_enabled=False)
        )
        body.acceleration.update(600, 0)

        simulate(world, 1.0)

        # v = a * t = 600 * 1
        self.assertAlmostEqual(body.velocity.x, 600.0, delta=TOLERANCE)

    def test_zero_acceleration_leaves_velocity_untouched(self):
        """Sem aceleração, a velocidade inicial é preservada."""
        world = PhysicsWorld()
        ground_at(world, y=5000)
        body = world.add_object(
            GameObject((100, 0), size=(30, 30), gravity_enabled=False)
        )
        body.set_velocity(123.0, 0)

        simulate(world, 1.0)

        self.assertAlmostEqual(body.velocity.x, 123.0, delta=TOLERANCE)


class WorldSteppingTest(unittest.TestCase):
    """Contrato do avanço temporal do mundo."""

    def test_update_with_zero_dt_does_nothing(self):
        """`update(0.0)` é seguro e não move nada.

        Acontece de verdade: um quadro perdido, um teste que chama update
        antes de fixar o passo, um loop que integrou o relógio errado.
        """
        world = PhysicsWorld()
        body = world.add_object(
            GameObject((100, 100), size=(30, 30), gravity_enabled=True)
        )

        for _ in range(10):
            world.update(0.0)

        self.assertEqual(body.position.y, 100.0)
        self.assertEqual(body.velocity.y, 0.0)

    def test_empty_world_updates_without_error(self):
        """Um mundo sem corpos e sem plataformas é um caso válido.

        Não basta não estourar: um mundo vazio também precisa continuar
        vazio depois do passo, senão a atualização estaria inventando
        objetos.
        """
        world = PhysicsWorld()

        simulate(world, 1.0)

        self.assertEqual(world.objects, [])
        self.assertEqual(world.platforms, [])

    def test_two_identical_runs_give_identical_results(self):
        """Mesma entrada, mesma saída: não há estado global escondido.

        Cobre o risco de o mundo guardar alguma informação entre quadros
        (uma lista de "quem já foi arrastado", um dicionário de entregas)
        que faça o resultado depender da história e não só do estado atual.
        """
        def build():
            world = PhysicsWorld()
            ground_at(world, y=300)
            world.add_platform(
                Platform(
                    (100, 200), (140, 18),
                    moving=True, speed=60, travel=200, axis="x",
                )
            )
            body = world.add_object(
                GameObject((140, 182), size=(30, 30), gravity_enabled=True)
            )
            return world, body

        first = build()
        simulate(first[0], 3.0)
        second = build()
        simulate(second[0], 3.0)

        self.assertEqual(first[1].position.x, second[1].position.x)
        self.assertEqual(first[1].position.y, second[1].position.y)
        # Compara o valor exato, não "quase": o ponto é provar que não há
        # estado acumulado entre quadros. Tolerância aqui esconderia
        # exatamente o tipo de deriva que o teste existe para detectar.
        self.assertNotEqual(first[1].position.y, 182.0)

    def test_result_does_not_depend_on_the_step_size(self):
        """Mesmo tempo total simulado dá o mesmo resultado — NESTE cenário.

        Contrato importante de um motor 2D: o jogo se comporta igual a 30, 60
        ou 120 fps, porque `dt` é tempo e não número de quadros.

        ESCOPO DELIMITADO DE PROPÓSITO. O que este teste cobre é queda livre
        até o chão com uma plataforma móvel horizontal embaixo. Ele NÃO
        afirma o contrato para toda a simulação, porque o contrato ainda não
        vale para todo o motor: em pilha sobre plataforma VERTICAL, 60 fps e
        120 fps divergem (verificado: após 1 s, os três objetos ficam em
        y=[790.0, 506.5, 260.0] a 60 fps e y=[776.75, 494.625, 260.0] a
        120 fps). Isso é consequência do defeito de carry que trava a pilha,
        e não uma propriedade aceita.

        Quando a Fase M6 corrigir o carry, este teste deve ser ampliado para
        incluir a pilha vertical, e só então a afirmação poderá ser feita sem
        ressalva.
        """
        def build():
            world = PhysicsWorld()
            ground_at(world, y=300)
            world.add_platform(
                Platform(
                    (100, 200), (140, 18),
                    moving=True, speed=60, travel=200, axis="x",
                )
            )
            body = world.add_object(
                GameObject((140, 182), size=(30, 30), gravity_enabled=True)
            )
            return world, body

        # 2 segundos de simulação, em três taxas de quadros diferentes.
        at_30 = build()
        for _ in range(60):
            at_30[0].update(1 / 30)

        at_60 = build()
        for _ in range(120):
            at_60[0].update(1 / 60)

        at_120 = build()
        for _ in range(240):
            at_120[0].update(1 / 120)

        for other in (at_30, at_120):
            self.assertAlmostEqual(
                other[1].position.x, at_60[1].position.x, delta=TOLERANCE
            )
            self.assertAlmostEqual(
                other[1].position.y, at_60[1].position.y, delta=TOLERANCE
            )


class DisplayIndependenceTest(unittest.TestCase):
    """A simulação não precisa de janela, superfície ou loop de eventos."""

    def test_simulation_runs_in_a_clean_interpreter_without_a_display(self):
        """Rodar a física em um processo limpo, sem `set_mode`.

        Roda em subprocesso de propósito. Um teste que só verificasse
        `pygame.display.get_surface() is None` no processo atual passaria ou
        falharia dependendo da ordem de execução dos testes: bastaria outro
        teste abrir uma janela em algum momento. O subprocesso garante que a
        afirmação vale para o mundo, e não para o histórico da suíte.
        """
        import subprocess
        import sys

        script = (
            "import pygame\n"
            "from src.physics.PhysicsWorld import PhysicsWorld\n"
            "from src.objects.GameObject import GameObject\n"
            "from src.platforms.Platform import Platform\n"
            "assert pygame.display.get_surface() is None, 'display aberto'\n"
            "world = PhysicsWorld(bounds=pygame.Rect(0, 0, 640, 480))\n"
            "world.add_platform(Platform((0, 460), (640, 20)))\n"
            "body = world.add_object(\n"
            "    GameObject((100, 100), size=(30, 30), gravity_enabled=True)\n"
            ")\n"
            "for _ in range(120):\n"
            "    world.update(1 / 60)\n"
            "assert pygame.display.get_surface() is None, 'display aberto'\n"
            "assert abs(body.rect.bottom - 460) <= 1, body.rect.bottom\n"
            "print('OK')\n"
        )

        environment = dict(os.environ, SDL_VIDEODRIVER="dummy")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )

        self.assertEqual(
            result.returncode, 0, msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        self.assertIn("OK", result.stdout)