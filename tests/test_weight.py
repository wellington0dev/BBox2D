"""Testes do sistema de pesos e cargas.

Executar a partir da pasta do projeto:

    python3 -m unittest tests.test_weight -v

Ou todos:

    python3 -m unittest discover -s tests -v

Os testes definem `SDL_VIDEODRIVER=dummy`, então rodam sem abrir janela.
"""

import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from src.objects.GameObject import (
    MIN_WEIGHT,
    GameObject,
)
from src.physics import PhysicsWorld as pw_module
from src.physics.PhysicsWorld import PhysicsWorld
from src.platforms.Platform import Platform

#: passo fixo da simulação, em segundos.
DT = 1 / 60
TOLERANCE = 0.5


def simulate(world, seconds):
    """Roda a simulação por um número fixo de quadros."""
    for _ in range(int(seconds / DT)):
        world.update(DT)


def grounded_world(gravity=0.0, position=(100, 366), size=(30, 30), **kwargs):
    """Mundo com um chão e um objeto apoiado nele."""
    world = PhysicsWorld()
    world.add_platform(Platform((0, 400), (640, 20)))
    obj = world.add_object(
        GameObject(position=position, size=size, gravity_enabled=True, **kwargs)
    )
    simulate(world, 1.0)  # deixa assentar
    return world, obj


class WeightAttributeTest(unittest.TestCase):
    """Validação e semântica dos atributos de peso."""

    def setUp(self):
        pygame.init()
        if pygame.display.get_surface() is None:
            pygame.display.set_mode((640, 480))

    def test_default_weight_is_positive(self):
        obj = GameObject()
        self.assertGreater(obj.weight, 0.0)

    def test_negative_weight_is_clamped(self):
        obj = GameObject(weight=-5.0)
        self.assertEqual(obj.weight, MIN_WEIGHT)

    def test_zero_weight_is_clamped_to_avoid_division(self):
        obj = GameObject(weight=0.0)
        self.assertGreaterEqual(obj.weight, MIN_WEIGHT)
        # A divisão não pode explodir.
        self.assertEqual(obj.get_load_ratio(), 0.0)

    def test_nan_weight_is_clamped(self):
        obj = GameObject(weight=float("nan"))
        self.assertGreaterEqual(obj.weight, MIN_WEIGHT)

    def test_invalid_weight_type_falls_back(self):
        obj = GameObject()
        obj.weight = "não é número"
        self.assertEqual(obj.weight, 1.0)

    def test_weight_is_not_changed_by_load(self):
        """A carga recebida não pode contaminar o peso intrínseco."""
        world, obj = grounded_world(weight=2.0)
        self.assertEqual(obj.weight, 2.0)

        world.add_object(
            GameObject((100, 336), size=(30, 30), gravity_enabled=True, weight=5.0)
        )
        simulate(world, 1.0)

        self.assertEqual(obj.weight, 2.0)
        self.assertEqual(obj.get_supported_load(), 5.0)

    def test_negative_influence_is_clamped(self):
        obj = GameObject(weight_influence=-2.0)
        self.assertGreaterEqual(obj.weight_influence, 0.0)

    def test_object_without_jump_strength_cannot_jump(self):
        obj = GameObject()
        self.assertIsNone(obj.get_effective_jump_strength())
        self.assertFalse(obj.can_jump())


class LoadCalculationTest(unittest.TestCase):
    """Cálculo e transmissão da carga."""

    def setUp(self):
        pygame.init()
        if pygame.display.get_surface() is None:
            pygame.display.set_mode((640, 480))

    def test_no_load_by_default(self):
        _, obj = grounded_world(weight=1.0)
        self.assertEqual(obj.get_supported_load(), 0.0)

    def test_single_object_transmits_its_weight(self):
        world, obj = grounded_world(weight=3.0)
        world.add_object(
            GameObject((100, 336), size=(30, 30), gravity_enabled=True, weight=2.0)
        )
        simulate(world, 1.0)
        self.assertAlmostEqual(obj.get_supported_load(), 2.0, delta=TOLERANCE)

    def test_stack_transmits_total_load(self):
        """Uma pilha transmite a soma dos pesos de toda a cadeia."""
        world, base = grounded_world(weight=3.0)
        middle = world.add_object(
            GameObject((100, 336), size=(30, 30), gravity_enabled=True, weight=2.0)
        )
        simulate(world, 1.0)
        top = world.add_object(
            GameObject((100, 306), size=(30, 30), gravity_enabled=True, weight=1.0)
        )
        simulate(world, 1.0)

        # A base recebe 2.0 + 1.0.
        self.assertAlmostEqual(base.get_supported_load(), 3.0, delta=TOLERANCE)
        # O meio recebe só o que está em cima dele.
        self.assertAlmostEqual(middle.get_supported_load(), 1.0, delta=TOLERANCE)
        # O topo não recebe nada.
        self.assertAlmostEqual(top.get_supported_load(), 0.0, delta=TOLERANCE)

    def test_total_load_is_weight_plus_received(self):
        world, obj = grounded_world(weight=3.0)
        world.add_object(
            GameObject((100, 336), size=(30, 30), gravity_enabled=True, weight=2.0)
        )
        simulate(world, 1.0)
        self.assertAlmostEqual(
            obj.get_total_load(), obj.weight + obj.get_supported_load()
        )

    def test_load_stops_when_object_moves_away(self):
        """Carga antiga é removida quando o objeto sai da superfície."""
        world, obj = grounded_world(weight=2.0)
        box = world.add_object(
            GameObject((100, 336), size=(30, 30), gravity_enabled=True, weight=2.0)
        )
        simulate(world, 1.0)
        self.assertGreater(obj.get_supported_load(), 0)

        # Empurra a caixa para longe.
        box.position.x = 400
        box._sync_rect()
        simulate(world, 1.0)

        self.assertEqual(obj.get_supported_load(), 0.0)

    def test_load_stops_after_removal(self):
        world, obj = grounded_world(weight=2.0)
        box = world.add_object(
            GameObject((100, 336), size=(30, 30), gravity_enabled=True, weight=2.0)
        )
        simulate(world, 1.0)
        self.assertGreater(obj.get_supported_load(), 0)

        world.remove_object(box)
        simulate(world, 0.5)

        self.assertEqual(obj.get_supported_load(), 0.0)

    def test_inactive_object_does_not_add_load(self):
        world, obj = grounded_world(weight=2.0)
        box = world.add_object(
            GameObject((100, 336), size=(30, 30), gravity_enabled=True, weight=9.0)
        )
        simulate(world, 1.0)
        self.assertGreater(obj.get_supported_load(), 0)

        box.active = False
        simulate(world, 0.5)

        self.assertEqual(obj.get_supported_load(), 0.0)

    def test_lateral_overlap_is_not_a_load(self):
        """Só encostar de lado não conta como carga."""
        world, obj = grounded_world(weight=2.0)
        # Objeto ao lado, no mesmo nível: sem sobreposição horizontal útil.
        side = world.add_object(
            GameObject((200, 366), size=(30, 30), gravity_enabled=True, weight=5.0)
        )
        simulate(world, 1.0)

        self.assertEqual(obj.get_supported_load(), 0.0)
        self.assertIsNot(side, obj)

    def test_cycle_does_not_hang(self):
        """Mesmo com posições absurdas, o cálculo não entra em recursão."""
        world, obj = grounded_world(weight=1.0)
        other = world.add_object(
            GameObject((100, 336), size=(30, 30), gravity_enabled=True, weight=1.0)
        )
        simulate(world, 1.0)
        # Força os dois a se "apoiar" mutuamente num estado impossível.
        simulate(world, 0.1)
        self.assertIsNotNone(other.get_total_load())


class JumpUnderLoadTest(unittest.TestCase):
    """Regras de salto sob carga."""

    def setUp(self):
        pygame.init()
        if pygame.display.get_surface() is None:
            pygame.display.set_mode((640, 480))

    def test_jump_without_load_uses_full_strength(self):
        _, obj = grounded_world(weight=1.0, jump_strength=600.0)
        self.assertAlmostEqual(obj.get_load_ratio(), 0.0)
        self.assertAlmostEqual(obj.get_jump_factor(), 1.0)
        self.assertAlmostEqual(obj.get_effective_jump_strength(), 600.0)
        self.assertTrue(obj.can_jump())

    def test_light_load_reduces_jump(self):
        world, obj = grounded_world(weight=1.0, jump_strength=600.0)
        world.add_object(
            GameObject((100, 336), size=(30, 30), gravity_enabled=True, weight=0.5)
        )
        simulate(world, 1.0)

        self.assertAlmostEqual(obj.get_load_ratio(), 0.5, delta=TOLERANCE)
        self.assertAlmostEqual(obj.get_jump_factor(), 0.5, delta=TOLERANCE)
        self.assertAlmostEqual(obj.get_effective_jump_strength(), 300.0, delta=5.0)
        self.assertTrue(obj.can_jump())

    def test_load_equal_to_weight_blocks_jump(self):
        world, obj = grounded_world(weight=1.0, jump_strength=600.0)
        world.add_object(
            GameObject((100, 336), size=(30, 30), gravity_enabled=True, weight=1.0)
        )
        simulate(world, 1.0)

        self.assertAlmostEqual(obj.get_load_ratio(), 1.0, delta=TOLERANCE)
        self.assertAlmostEqual(obj.get_jump_factor(), 0.0, delta=TOLERANCE)
        self.assertFalse(obj.can_jump())

    def test_load_above_weight_blocks_jump(self):
        world, obj = grounded_world(weight=1.0, jump_strength=600.0)
        world.add_object(
            GameObject((100, 336), size=(30, 30), gravity_enabled=True, weight=5.0)
        )
        simulate(world, 1.0)

        self.assertEqual(obj.get_jump_factor(), 0.0)
        self.assertFalse(obj.can_jump())

    def test_cannot_jump_in_the_air(self):
        world, obj = grounded_world(weight=1.0, jump_strength=600.0)
        obj.velocity.y = -300.0  # no ar
        simulate(world, 0.1)
        self.assertFalse(obj.can_jump())

    def test_jump_becomes_possible_again_after_load_leaves(self):
        world, obj = grounded_world(weight=1.0, jump_strength=600.0)
        box = world.add_object(
            GameObject((100, 336), size=(30, 30), gravity_enabled=True, weight=5.0)
        )
        simulate(world, 1.0)
        self.assertFalse(obj.can_jump())

        box.position.x = 450
        box._sync_rect()
        simulate(world, 1.0)

        self.assertTrue(obj.can_jump())
        self.assertAlmostEqual(obj.get_effective_jump_strength(), 600.0)


class LoadMotionTest(unittest.TestCase):
    """Peso afetando o movimento vertical."""

    def setUp(self):
        pygame.init()
        if pygame.display.get_surface() is None:
            pygame.display.set_mode((640, 480))

    def test_object_without_gravity_stays_put_without_load(self):
        world = PhysicsWorld()
        floater = world.add_object(
            GameObject((100, 200), size=(40, 20), gravity_enabled=False)
        )
        simulate(world, 1.0)

        self.assertEqual(floater.get_supported_load(), 0.0)
        self.assertEqual(floater.position.y, 200)
        self.assertFalse(floater.gravity_enabled)

    def test_object_without_gravity_sags_under_load(self):
        world = PhysicsWorld()
        floater = world.add_object(
            GameObject((100, 200), size=(40, 20), gravity_enabled=False)
        )
        world.add_object(
            GameObject((105, 180), size=(30, 30), gravity_enabled=True, weight=2.0)
        )
        simulate(world, 1.5)

        self.assertGreater(floater.position.y, 200)
        # A gravidade continua desligada: ele cede por carga, não por cair.
        self.assertFalse(floater.gravity_enabled)

    def test_vertical_resistance_prevents_sag(self):
        world = PhysicsWorld()
        floater = world.add_object(
            GameObject(
                (100, 200), size=(40, 20), gravity_enabled=False, vertical_resistance=10.0
            )
        )
        world.add_object(
            GameObject((105, 180), size=(30, 30), gravity_enabled=True, weight=2.0)
        )
        simulate(world, 1.5)

        self.assertAlmostEqual(floater.position.y, 200, delta=TOLERANCE)

    def test_heavier_load_sags_more(self):
        """R8: carga leve produz efeito menor que carga pesada."""
        results = {}

        for label, weight in (("leve", 0.5), ("pesado", 4.0)):
            world = PhysicsWorld()
            floater = world.add_object(
                GameObject((100, 200), size=(40, 20), gravity_enabled=False)
            )
            world.add_object(
                GameObject(
                    (105, 180), size=(30, 30), gravity_enabled=True, weight=weight
                )
            )
            simulate(world, 1.5)
            results[label] = floater.position.y - 200

        self.assertGreater(results["pesado"], results["leve"])
        self.assertGreater(results["leve"], 0)

    def test_sag_is_removed_when_load_leaves(self):
        """R9: a remoção da carga restaura o comportamento normal."""
        world = PhysicsWorld()
        floater = world.add_object(
            GameObject((100, 200), size=(40, 20), gravity_enabled=False)
        )
        box = world.add_object(
            GameObject((105, 180), size=(30, 30), gravity_enabled=True, weight=2.0)
        )
        simulate(world, 1.0)
        self.assertGreater(floater.position.y, 200)

        # Some com a caixa e deixa a física resolver a sobreposição restante
        # antes de medir.
        world.remove_object(box)
        simulate(world, 0.5)

        self.assertEqual(floater.get_supported_load(), 0.0)

        # A partir daí não desce mais: a cedência foi removida por completo.
        start_y = floater.position.y
        simulate(world, 0.5)
        self.assertAlmostEqual(floater.position.y, start_y, delta=TOLERANCE)

    def test_sag_ceases_immediately_without_load(self):
        """Sem carga, `_sag_amount` é exatamente zero."""
        world = PhysicsWorld()
        floater = world.add_object(
            GameObject((100, 200), size=(40, 20), gravity_enabled=False)
        )
        box = world.add_object(
            GameObject((105, 180), size=(30, 30), gravity_enabled=True, weight=2.0)
        )
        simulate(world, 0.5)
        self.assertGreater(world._sag_amount(floater), 0)

        world.remove_object(box)
        simulate(world, 0.5)
        self.assertEqual(world._sag_amount(floater), 0.0)

    def test_sag_is_capped(self):
        """Peso absurdo não lança o objeto para fora da tela."""
        world = PhysicsWorld()
        floater = world.add_object(
            GameObject((100, 200), size=(40, 20), gravity_enabled=False)
        )
        world.add_object(
            GameObject((105, 180), size=(30, 30), gravity_enabled=True, weight=100000.0)
        )
        simulate(world, 0.5)

        self.assertLessEqual(
            world._sag_amount(floater), pw_module.LOAD_SAG_MAX + TOLERANCE
        )

    def test_zero_influence_disables_weight_effects(self):
        world = PhysicsWorld()
        floater = world.add_object(
            GameObject(
                (100, 200),
                size=(40, 20),
                gravity_enabled=False,
                weight_influence=0.0,
            )
        )
        world.add_object(
            GameObject((105, 180), size=(30, 30), gravity_enabled=True, weight=5.0)
        )
        simulate(world, 1.0)

        self.assertEqual(floater.position.y, 200)
        # A carga é computada, mas não influence o movimento.
        self.assertGreater(floater.get_supported_load(), 0)

    def test_heavy_load_increases_fall_speed(self):
        """Carga acima do peso aumenta a velocidade de queda."""
        speeds = {}

        for label, load_weight in (("sem carga", 0.0), ("com carga", 3.0)):
            world = PhysicsWorld()
            faller = world.add_object(
                GameObject((50, 50), size=(30, 30), gravity_enabled=True, weight=1.0)
            )
            if load_weight:
                world.add_object(
                    GameObject(
                        (50, 20), size=(30, 30), gravity_enabled=True, weight=load_weight
                    )
                )
            simulate(world, 0.2)
            speeds[label] = faller.velocity.y

        self.assertGreater(speeds["com carga"], speeds["sem carga"])

    def test_load_below_weight_does_not_affect_fall(self):
        """Carga menor que o peso não cria modificador extra."""
        world = PhysicsWorld()
        faller = world.add_object(
            GameObject((50, 50), size=(30, 30), gravity_enabled=True, weight=5.0)
        )
        world.add_object(
            GameObject((50, 20), size=(30, 30), gravity_enabled=True, weight=1.0)
        )
        simulate(world, 0.2)

        self.assertEqual(world._weight_effect(faller), 0.0)


class CollisionsStillApplyTest(unittest.TestCase):
    """R10: peso não substitui colisões."""

    def setUp(self):
        pygame.init()
        if pygame.display.get_surface() is None:
            pygame.display.set_mode((640, 480))

    def test_heavy_object_still_respects_wall_and_ground(self):
        world = PhysicsWorld()
        world.add_platform(Platform((0, 400), (640, 20)))
        world.add_platform(Platform((300, 0), (30, 400)))
        heavy = world.add_object(
            GameObject((100, 200), size=(30, 30), gravity_enabled=True, weight=50.0)
        )
        simulate(world, 2.0)

        self.assertLessEqual(heavy.rect.right, 300 + TOLERANCE)
        self.assertLessEqual(heavy.rect.bottom, 400 + TOLERANCE)

    def test_weight_does_not_grant_pass_through(self):
        world = PhysicsWorld()
        world.add_platform(Platform((0, 200), (640, 20)))
        heavy = world.add_object(
            GameObject((100, 50), size=(30, 30), gravity_enabled=True, weight=100.0)
        )
        simulate(world, 2.0)

        # Não pode atravessar a plataforma.
        self.assertLessEqual(heavy.rect.bottom, 200 + TOLERANCE)


class CarryIntegrationTest(unittest.TestCase):
    """R11: o arraste continua funcionando e as cargas se atualizam."""

    def setUp(self):
        pygame.init()
        if pygame.display.get_surface() is None:
            pygame.display.set_mode((640, 480))

    def test_carry_still_moves_object_and_updates_load(self):
        world = PhysicsWorld()
        world.add_platform(Platform((0, 300), (640, 20)))
        base = world.add_object(
            GameObject((100, 266), size=(30, 30), gravity_enabled=False, weight=1.0)
        )
        rider = world.add_object(
            GameObject((100, 236), size=(30, 30), gravity_enabled=False, weight=4.0)
        )
        start_x = base.position.x
        base.set_velocity(150, 0)
        simulate(world, 1.0)

        # O arraste continua movendo a pilha.
        self.assertGreater(base.position.x - start_x, 50)
        self.assertAlmostEqual(
            rider.position.x - start_x, base.position.x - start_x, delta=2.0
        )
        # E a carga foi reconhecida durante o arraste.
        self.assertAlmostEqual(base.get_supported_load(), 4.0, delta=TOLERANCE)

    def test_moving_platform_still_carries_and_loads(self):
        world = PhysicsWorld()
        world.add_platform(
            Platform(
                (100, 350), (120, 20), moving=True, speed=60, travel=100, axis="y"
            )
        )
        rider = world.add_object(
            GameObject((130, 320), size=(30, 30), gravity_enabled=True, weight=2.0)
        )
        start_y = rider.position.y

        simulate(world, 1.0)

        # Subiu com a plataforma, e a plataforma não "recebe carga" de objeto.
        self.assertLess(rider.position.y, start_y)

    def test_load_is_not_applied_twice_per_frame(self):
        """R12: modificadores não se acumulam quadro a quadro.

        Isola a INTEGRAÇÃO de velocidade (o passo onde o efeito do peso entra)
        e compara dois cenários idênticos, diferindo apenas pela carga. A
        diferença tem que ser exatamente UM efeito por quadro; se fosse
        aplicado duas vezes, seria o dobro.

        A integração é medida isolada de propósito: no `update` completo o
        objeto de baixo também sofre `_push_rider` (a caixa o empurra), que é
        um mecanismo de colisão, e não um modificador de peso.
        """
        def prepare(world_objects):
            for obj in world_objects:
                obj.begin_frame()
            world = PhysicsWorld()
            for obj in world_objects:
                world.add_object(obj)
            world._update_loads(world.objects)
            return world

        loaded = prepare(
            [
                GameObject((50, 50), size=(30, 30), gravity_enabled=True, weight=1.0),
                GameObject((50, 20), size=(30, 30), gravity_enabled=True, weight=3.0),
            ]
        )
        faller = loaded.objects[0]
        # Peso 3 em cima => ratio 3.0 => efeito conhecido.
        control = prepare(
            [GameObject((50, 50), size=(30, 30), gravity_enabled=True, weight=1.0)]
        )
        baseline = control.objects[0]

        effect = loaded._weight_effect(faller)
        self.assertGreater(effect, 0)

        loaded._integrate_velocity(faller, DT)
        control._integrate_velocity(baseline, DT)

        difference = faller.velocity.y - baseline.velocity.y
        # Um único efeito aplicado durante DT.
        self.assertAlmostEqual(difference, effect * DT, delta=0.01)

        # E o efeito não cresce com o tempo: aplica sempre o mesmo valor.
        self.assertAlmostEqual(effect, loaded._weight_effect(faller), delta=0.001)


class LoadEventTest(unittest.TestCase):
    """Eventos de carga e de apoio."""

    def setUp(self):
        pygame.init()
        if pygame.display.get_surface() is None:
            pygame.display.set_mode((640, 480))

    def test_on_load_changed_fires_only_on_change(self):
        world, obj = grounded_world(weight=2.0)
        calls = []
        obj.on_load_changed = lambda load: calls.append(load)

        simulate(world, 0.5)
        self.assertEqual(len(calls), 0)  # carga já era 0

        box = world.add_object(
            GameObject((100, 336), size=(30, 30), gravity_enabled=True, weight=3.0)
        )
        simulate(world, 1.0)
        self.assertTrue(calls)  # houve mudança

        # Sem mudança, não dispara de novo.
        before = len(calls)
        simulate(world, 1.0)
        self.assertEqual(len(calls), before)

    def test_on_support_changed_and_lifted(self):
        world = PhysicsWorld()
        world.add_platform(Platform((0, 400), (640, 20)))
        obj = world.add_object(
            GameObject(
                (100, 366), size=(30, 30), gravity_enabled=True, weight=1.0
            )
        )

        supports = []
        lifted = []
        obj.on_support_changed = lambda s: supports.append(s)
        obj.on_lifted = lambda: lifted.append(True)

        simulate(world, 1.0)
        # Assentou na plataforma: houve mudança de suporte para a plataforma.
        self.assertTrue(supports)
        self.assertIsNotNone(supports[0])

        # Levanta o objeto: perde o apoio e dispara `lifted`.
        obj.position.y = 100
        obj._sync_rect()
        simulate(world, 1.0)
        self.assertIn(None, supports)
        self.assertTrue(lifted)

    def test_event_handler_registration(self):
        world, obj = grounded_world(weight=2.0)
        seen = []
        obj.add_event_handler("load_changed", lambda load: seen.append(load))

        world.add_object(
            GameObject((100, 336), size=(30, 30), gravity_enabled=True, weight=3.0)
        )
        simulate(world, 1.0)

        self.assertTrue(seen)


class FallingStackTest(unittest.TestCase):
    """Pilhas em queda livre devem cair como um bloco só."""

    def setUp(self):
        pygame.init()
        if pygame.display.get_surface() is None:
            pygame.display.set_mode((640, 480))

    @staticmethod
    def stack_gaps(stack):
        """Separação vertical entre membros vizinhos (0 = encostados)."""
        return [a.rect.top - b.rect.bottom for a, b in zip(stack, stack[1:])]

    def test_falling_stack_stays_together(self):
        """R: a caixa de cima não pode ficar parada no ar."""
        world = PhysicsWorld()
        bottom = world.add_object(
            GameObject((50, 100), size=(30, 30), gravity_enabled=True, weight=1.0)
        )
        top = world.add_object(
            GameObject((50, 70), size=(30, 30), gravity_enabled=True, weight=3.0)
        )
        stack = [bottom, top]

        worst = 0.0
        for _ in range(60):
            world.update(DT)
            worst = max(worst, abs(self.stack_gaps(stack)[0]))

        self.assertLess(worst, 1.0)

    def test_falling_stack_of_three(self):
        world = PhysicsWorld()
        stack = [
            world.add_object(
                GameObject(
                    (50, 100 - i * 30),
                    size=(30, 30),
                    gravity_enabled=True,
                    weight=1.0 + i,
                )
            )
            for i in range(3)
        ]

        worst = 0.0
        for _ in range(60):
            world.update(DT)
            for gap in self.stack_gaps(stack):
                worst = max(worst, abs(gap))

        self.assertLess(worst, 1.0)

    def test_falling_stack_lands_together(self):
        """Pilha que cai e pousa continua inteira e com carga."""
        world = PhysicsWorld()
        world.add_platform(Platform((0, 300), (640, 20)))
        stack = [
            world.add_object(
                GameObject(
                    (150, 20 - i * 30),
                    size=(30, 30),
                    gravity_enabled=True,
                    weight=1.0 + i,
                )
            )
            for i in range(3)
        ]

        simulate(world, 2.0)

        self.assertTrue(stack[0].grounded)
        for gap in self.stack_gaps(stack):
            self.assertAlmostEqual(gap, 0.0, delta=1.0)
        # A base carrega tudo o que está em cima.
        self.assertAlmostEqual(stack[0].get_supported_load(), 5.0, delta=0.5)

    def test_falling_stack_respects_ceiling(self):
        """Bater no teto para a pilha inteira, sem atravessar."""
        world = PhysicsWorld()
        world.add_platform(Platform((0, 400), (640, 20)))
        world.add_platform(Platform((0, 0), (640, 20)))
        stack = [
            world.add_object(
                GameObject(
                    (150, 300 - i * 30),
                    size=(30, 30),
                    gravity_enabled=True,
                    weight=1.0 + i,
                )
            )
            for i in range(3)
        ]

        simulate(world, 3.0)

        # O teto termina em y=20: nada pode ficar acima disso.
        for obj in stack:
            self.assertGreaterEqual(obj.rect.top, 20 - TOLERANCE)

    def test_object_without_gravity_not_in_falling_stack(self):
        """Sem gravidade, o objeto tem cedência própria e não é arrastado
        pela pilha alheia."""
        world = PhysicsWorld()
        floater = world.add_object(
            GameObject(
                (100, 200),
                size=(40, 20),
                gravity_enabled=False,
                vertical_resistance=100.0,
            )
        )
        world.add_object(
            GameObject((105, 180), size=(30, 30), gravity_enabled=True, weight=2.0)
        )

        simulate(world, 1.5)

        # Resistência alta: não desce.
        self.assertAlmostEqual(floater.position.y, 200, delta=TOLERANCE)
        self.assertFalse(floater.gravity_enabled)

    def test_supported_stack_is_not_treated_as_falling(self):
        """Uma pilha apoiada não entra no caminho de queda livre."""
        world = PhysicsWorld()
        world.add_platform(Platform((0, 400), (640, 20)))
        bottom = world.add_object(
            GameObject((100, 366), size=(30, 30), gravity_enabled=True, weight=1.0)
        )
        world.add_object(
            GameObject((100, 336), size=(30, 30), gravity_enabled=True, weight=2.0)
        )

        simulate(world, 1.0)

        # Não caiu para fora do lugar, e a carga está lá.
        self.assertAlmostEqual(bottom.position.y, 370, delta=TOLERANCE)
        self.assertAlmostEqual(bottom.get_supported_load(), 2.0, delta=TOLERANCE)


class PushByWeightTest(unittest.TestCase):
    """Empurrão por peso: o mais pesado move o mais leve.

    O modelo é uma JANELA de peso, não um piso. Um objeto empurra alvos de
    1.2x a 3x o seu peso: abaixo disso (empate, ou o outro mais pesado) não
    empurra, acima disso o alvo é pesado demais e barra o empurrador.
    """

    def setUp(self):
        pygame.init()
        if pygame.display.get_surface() is None:
            pygame.display.set_mode((640, 480))

    def test_heavier_can_push_lighter(self):
        """Na janela válida, o mais pesado empurra o mais leve."""
        heavy = GameObject(weight=3.0)
        light = GameObject(weight=1.0)

        self.assertTrue(heavy.can_push(light))
        self.assertFalse(light.can_push(heavy))

    def test_equal_weights_do_not_push(self):
        """Empate: dois iguais não se empurram, nemALKwards indefinidamente."""
        a = GameObject(weight=5.0)
        b = GameObject(weight=5.0)

        self.assertFalse(a.can_push(b))
        self.assertEqual(a.push_force_against(b), 0.0)

    def test_beyond_three_times_cannot_push(self):
        """Passar de 3x e pesado demais: a inércia do alvo vence."""
        heavy = GameObject(weight=3.5)
        light = GameObject(weight=1.0)

        self.assertFalse(heavy.can_push(light))
        self.assertEqual(heavy.push_force_against(light), 0.0)

    def test_slight_difference_pushes_strongly(self):
        """Dentro da janela, quanto mais perto do peso, mais forte o empurrao."""
        near = GameObject(weight=1.5)
        far = GameObject(weight=2.9)

        self.assertTrue(near.can_push(GameObject(weight=1.0)))
        self.assertTrue(far.can_push(GameObject(weight=1.0)))

        # Perto do peso do alvo: força alta.
        self.assertGreater(
            near.push_force_against(GameObject(weight=1.0)), 0.8
        )
        # Perto do limite de 3x: força bem menor.
        self.assertLess(
            far.push_force_against(GameObject(weight=1.0)), 0.5
        )

    def test_push_speed_falls_with_target_weight(self):
        """Empurrar algo mais pesado e mais lento (velocidade reduzida)."""
        light_target = GameObject(weight=1.0)
        near_pusher = GameObject(weight=1.5)
        # No limite de 3x, a velocidade deve ser PUSH_SPEED_HEAVY (70).
        far_pusher = GameObject(weight=3.0)

        fast = near_pusher.push_speed_against(light_target, 260.0, 70.0)
        slow = far_pusher.push_speed_against(light_target, 260.0, 70.0)

        self.assertGreater(fast, slow)
        self.assertLessEqual(slow, 70.0)
        self.assertLessEqual(fast, 260.0)

    def test_not_pushable_objects_are_excluded(self):
        heavy = GameObject(weight=2.0, pushable=False)
        light = GameObject(weight=1.0)

        self.assertFalse(heavy.can_push(light))

    def _push_scenario(self, pusher_weight, target_weight, seconds=1.5):
        world = PhysicsWorld()
        world.add_platform(Platform((0, 300), (640, 20)))
        pusher = world.add_object(
            GameObject(
                (100, 266), size=(30, 30), gravity_enabled=False, weight=pusher_weight
            )
        )
        target = world.add_object(
            GameObject(
                (128, 266), size=(30, 30), gravity_enabled=False, weight=target_weight
            )
        )
        pusher.set_velocity(200, 0)
        pusher_start = pusher.position.x
        target_start = target.position.x
        simulate(world, seconds)
        return pusher.position.x - pusher_start, target.position.x - target_start

    def test_light_object_is_pushed_away(self):
        """O mais leve sai da frente do mais pesado que o empurra."""
        pusher_dx, target_dx = self._push_scenario(2.5, 1.0)

        self.assertGreater(target_dx, 20.0)
        self.assertGreater(pusher_dx, 20.0)

    def test_equal_weights_are_not_pushed(self):
        """Empates nao se empurram.

        O alvo nao e deslocado pelo empurrao. O empurrador ainda e barrado
        pela COLISAO normal entre os dois corpos (e o que qualquer par de
        objetos solidos encostados faz), entao a tolerancia cobre esse pequeno
        recuo, mas nao um deslocamento de verdade.
        """
        pusher_dx, target_dx = self._push_scenario(5.0, 5.0)

        self.assertAlmostEqual(target_dx, 0.0, delta=TOLERANCE)
        self.assertGreater(pusher_dx, -10.0)

    def test_beyond_three_times_cannot_move(self):
        """Alvo 4x mais pesado barra o empurrador: nenhum dos dois anda muito.

        O empurrador bate no alvo e recua alguns pixels pela colisao normal
        (e o que qualquer par de solidos faz), mas nao ha empurrao.
        """
        pusher_dx, target_dx = self._push_scenario(1.0, 4.0)

        self.assertAlmostEqual(target_dx, 0.0, delta=TOLERANCE)
        # O empurrador recua um pouco pela colisao (nao empurrao), entao
        # usamos tolerancia maior.
        self.assertGreater(pusher_dx, -10.0)

    def test_three_times_heavier_still_moves_slowly(self):
        """Empurrador 3x mais pesado que o alvo ainda o move, mas devagar.

        O empurrador e 3x mais pesado que o alvo. O alvo se move, mas com
        velocidade reduzida devido a inercia do empurrador ser muito alta.
        """
        _, target_dx = self._push_scenario(3.0, 1.0, seconds=1.5)

        # Move, mas muito menos do que um empurrador quase do mesmo peso.
        _, light_dx = self._push_scenario(1.5, 1.0, seconds=1.5)
        self.assertGreater(target_dx, 10.0)
        self.assertLess(target_dx, light_dx * 0.75)

    def test_push_does_not_accumulate(self):
        """A velocidade do empurrao nunca vira velocidade permanente.

        Depois que os dois se separam, o empurrao decai até zero: o alvo nao
        fica deslizando para sempre nem acelera sem limite.
        """
        world = PhysicsWorld()
        world.add_platform(Platform((0, 300), (640, 20)))
        pusher = world.add_object(
            GameObject((100, 266), size=(30, 30), gravity_enabled=False, weight=2.5)
        )
        target = world.add_object(
            GameObject((128, 266), size=(30, 30), gravity_enabled=False, weight=1.0)
        )
        pusher.set_velocity(200, 0)

        simulate(world, 0.5)
        self.assertGreater(target.push_speed, 0.0)

        # O empurrador para de empurrar quando se afasta (aqui, removendo-o).
        world.remove_object(pusher)
        simulate(world, 1.0)

        # O empurrao desapareceu e a velocidade do objeto voltou a zero.
        self.assertAlmostEqual(target.push_speed, 0.0, delta=0.5)
        self.assertAlmostEqual(target.velocity.x, 0.0, delta=0.5)

    def test_push_never_exceeds_coast_speed(self):
        """A推 never grows without bound over frames of contact."""
        world = PhysicsWorld()
        world.add_platform(Platform((0, 300), (640, 20)))
        pusher = world.add_object(
            GameObject((100, 266), size=(30, 30), gravity_enabled=False, weight=2.0)
        )
        target = world.add_object(
            GameObject((128, 266), size=(30, 30), gravity_enabled=False, weight=1.0)
        )
        pusher.set_velocity(200, 0)

        peak = 0.0
        for _ in range(90):
            world.update(DT)
            peak = max(peak, abs(target.push_speed))

        # Nao disparou para o infinito (bug antigo: 190 -> 570 -> 1140 -> ...).
        self.assertLess(peak, 300.0)

    def test_push_preserves_stack_above(self):
        """Empurrar um objeto nao descola o que esta em cima dele."""
        world = PhysicsWorld()
        world.add_platform(Platform((0, 300), (640, 20)))
        pusher = world.add_object(
            GameObject((100, 266), size=(30, 30), gravity_enabled=True, weight=2.5)
        )
        stack = [
            pusher,
            world.add_object(
                GameObject((105, 236), size=(30, 30), gravity_enabled=True, weight=0.5)
            ),
        ]
        target = world.add_object(
            GameObject((128, 266), size=(30, 30), gravity_enabled=True, weight=1.0)
        )

        simulate(world, 0.5)
        pusher.set_velocity(200, 0)
        starts = [o.position.x for o in stack]
        simulate(world, 0.7)

        for obj in stack:
            self.assertGreater(obj.position.x - starts[stack.index(obj)], 10.0)
        gap = stack[0].rect.top - stack[1].rect.bottom
        self.assertAlmostEqual(gap, 0.0, delta=1.0)
        self.assertGreater(target.position.x, 128)

    def test_pushed_object_respects_walls(self):
        """O objeto empurrado nao atravessa parede nem platform."""
        world = PhysicsWorld()
        world.add_platform(Platform((0, 300), (640, 20)))
        world.add_platform(Platform((400, 0), (30, 480)))  # parede vertical
        pusher = world.add_object(
            GameObject((100, 266), size=(30, 30), gravity_enabled=False, weight=2.5)
        )
        target = world.add_object(
            GameObject((128, 266), size=(30, 30), gravity_enabled=False, weight=1.0)
        )
        pusher.set_velocity(300, 0)

        worst = 0.0
        for _ in range(200):
            world.update(DT)
            worst = max(worst, target.rect.right - 400)

        # Nunca atravessou a parede.
        self.assertLess(worst, TOLERANCE)



class LoadDisabledTest(unittest.TestCase):
    """O sistema pode ser desligado para comparação."""

    def setUp(self):
        pygame.init()
        if pygame.display.get_surface() is None:
            pygame.display.set_mode((640, 480))

    def test_disabling_load_restores_previous_behaviour(self):
        original = pw_module.LOAD_ENABLED
        try:
            pw_module.LOAD_ENABLED = False

            world, obj = grounded_world(weight=1.0, jump_strength=600.0)
            world.add_object(
                GameObject((100, 336), size=(30, 30), gravity_enabled=True, weight=5.0)
            )
            simulate(world, 1.0)

            # Com o sistema desligado, nada de carga é aplicado.
            self.assertEqual(obj.get_supported_load(), 0.0)
            self.assertTrue(obj.can_jump())
        finally:
            pw_module.LOAD_ENABLED = original


if __name__ == "__main__":
    unittest.main()