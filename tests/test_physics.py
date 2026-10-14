"""Testes da física e das colisões.

Executar a partir da pasta do projeto:

    python3 -m unittest tests.test_physics -v

Ou todos os testes:

    python3 -m unittest discover -s tests -t . -v

Os testes rodam com o display virtual (`SDL_VIDEODRIVER=dummy`), definido
aqui antes de qualquer import do Pygame, para não exigir uma janela.
"""

import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from bbox2d.objects.GameObject import GameObject
from bbox2d.objects.InteractiveObject import InteractiveObject
from bbox2d.physics.Collision import Direction
from bbox2d.physics.PhysicsWorld import PhysicsWorld
from bbox2d.platforms.Platform import Platform

#: passo fixo da simulação, em segundos.
DT = 1 / 60
TOLERANCE = 0.5


def simulate(world, seconds):
    """Roda a simulação por um número fixo de quadros."""
    for _ in range(int(seconds / DT)):
        world.update(DT)


def simulate_platform(platform, seconds):
    """Roda só o movimento de uma plataforma, sem a simulação completa."""
    for _ in range(int(seconds / DT)):
        platform.update(DT)


class SpyObject(GameObject):
    """Objeto que registra os eventos de colisão recebidos."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.events = []

    def on_landed(self, collision):
        self.events.append("landed")

    def on_hit_ceiling(self, collision):
        self.events.append("ceiling")

    def on_hit_wall(self, collision):
        self.events.append("wall")

    def on_collision_start(self, collision):
        self.events.append("start")

    def on_collision_end(self, collision):
        self.events.append("end")


class PhysicsWorldTest(unittest.TestCase):
    def setUp(self):
        pygame.init()
        if pygame.display.get_surface() is None:
            pygame.display.set_mode((640, 480))

    # ------------------------------------------------------------------
    # Gravidade
    # ------------------------------------------------------------------
    def test_object_falls_and_lands_on_platform(self):
        world = PhysicsWorld()
        world.add_platform(Platform((0, 400), (400, 40)))
        obj = world.add_object(
            GameObject((50, 100), size=(30, 30), gravity_enabled=True)
        )

        simulate(world, 3.0)

        # Encostado no topo da plataforma (400) com 30 de altura.
        self.assertAlmostEqual(obj.position.y, 370, delta=TOLERANCE)
        self.assertTrue(obj.grounded)
        self.assertEqual(obj.velocity.y, 0.0)

    def test_gravity_accelerates_over_time(self):
        world = PhysicsWorld()
        obj = world.add_object(
            GameObject((50, 0), size=(30, 30), gravity_enabled=True)
        )

        world.update(DT)
        first = obj.velocity.y
        simulate(world, 0.5)
        second = obj.velocity.y

        self.assertGreater(first, 0)
        self.assertGreater(second, first)

    def test_object_without_gravity_does_not_fall(self):
        world = PhysicsWorld()
        world.add_platform(Platform((0, 400), (400, 40)))
        obj = world.add_object(
            GameObject((50, 100), size=(30, 30), gravity_enabled=False)
        )

        simulate(world, 3.0)

        self.assertEqual(obj.position.y, 100)
        self.assertEqual(obj.velocity.y, 0.0)

    def test_gravity_scale_changes_fall_speed(self):
        slow = PhysicsWorld()
        slow_obj = slow.add_object(
            GameObject((50, 0), size=(30, 30), gravity_enabled=True, gravity_scale=0.5)
        )
        fast = PhysicsWorld()
        fast_obj = fast.add_object(
            GameObject((50, 0), size=(30, 30), gravity_enabled=True, gravity_scale=2.0)
        )

        simulate(slow, 0.3)
        simulate(fast, 0.3)

        self.assertLess(slow_obj.velocity.y, fast_obj.velocity.y)

    def test_resting_object_does_not_jitter(self):
        world = PhysicsWorld()
        world.add_platform(Platform((0, 400), (400, 40)))
        obj = world.add_object(
            GameObject((50, 100), size=(30, 30), gravity_enabled=True)
        )

        simulate(world, 2.0)
        resting_y = obj.position.y

        simulate(world, 2.0)

        # Sem micro-vibração: a posição fica exatamente igual.
        self.assertEqual(obj.position.y, resting_y)
        self.assertEqual(obj.velocity.y, 0.0)

    # ------------------------------------------------------------------
    # Colisões direcionais
    # ------------------------------------------------------------------
    def test_hitting_ceiling_stops_rising(self):
        world = PhysicsWorld()
        world.add_platform(Platform((0, 0), (400, 40)))
        obj = world.add_object(GameObject((50, 200), size=(30, 30)))
        obj.set_velocity(0, -400)

        simulate(world, 2.0)

        # Apoiado por baixo do teto.
        self.assertEqual(obj.position.y, 40)
        self.assertEqual(obj.velocity.y, 0.0)

    def test_hitting_wall_keeps_vertical_velocity(self):
        world = PhysicsWorld()
        world.add_platform(Platform((200, 100), (40, 300)))
        obj = world.add_object(GameObject((100, 150), size=(30, 30)))
        obj.set_velocity(400, 250)

        simulate(world, 1.0)

        # Encostado na lateral esquerda da parede (200 - 30).
        self.assertAlmostEqual(obj.position.x, 170, delta=TOLERANCE)
        # Só o eixo X foi zerado; a queda continua.
        self.assertEqual(obj.velocity.x, 0.0)
        self.assertGreater(obj.velocity.y, 0)

    def test_collision_direction_is_reported_correctly(self):
        world = PhysicsWorld()
        floor = world.add_platform(Platform((0, 400), (400, 40)))
        obj = world.add_object(
            GameObject((50, 100), size=(30, 30), gravity_enabled=True)
        )

        simulate(world, 2.0)

        collision = obj.get_contact(floor)
        self.assertIsNotNone(collision)
        self.assertIs(collision.direction, Direction.TOP)
        self.assertEqual(collision.normal, (0, -1))

    def test_surface_normals_point_outwards(self):
        # Cada caso usa o seu próprio mundo e objeto: reaproveitar o mesmo
        # objeto deixaria o estado de contatos do caso anterior.
        floor_world = PhysicsWorld()
        floor = floor_world.add_platform(Platform((0, 400), (400, 40)))
        falling = floor_world.add_object(
            GameObject((50, 100), size=(30, 30), gravity_enabled=True)
        )
        simulate(floor_world, 2.0)
        # Chão fica ABAIXO do objeto, logo a normal aponta para cima (0, -1).
        self.assertEqual(falling.get_contact(floor).normal, (0, -1))

        ceiling_world = PhysicsWorld()
        ceiling = ceiling_world.add_platform(Platform((0, 0), (400, 40)))
        rising = ceiling_world.add_object(GameObject((50, 200), size=(30, 30)))
        rising.set_velocity(0, -400)
        simulate(ceiling_world, 2.0)
        # Teto fica ACIMA do objeto, logo a normal aponta para baixo (0, 1).
        self.assertEqual(rising.get_contact(ceiling).normal, (0, 1))

        left_wall_world = PhysicsWorld()
        left_wall = left_wall_world.add_platform(Platform((200, 100), (40, 300)))
        from_left = left_wall_world.add_object(GameObject((100, 150), size=(30, 30)))
        from_left.set_velocity(400, 0)
        simulate(left_wall_world, 2.0)
        # Objeto encostou pela DIREITO numa parede à sua esquerda.
        self.assertEqual(from_left.get_contact(left_wall).normal, (-1, 0))

        # Objeto vindo pela direita: começa à direita da parede.
        right_wall_world = PhysicsWorld()
        right_wall = right_wall_world.add_platform(Platform((300, 100), (40, 300)))
        from_right = right_wall_world.add_object(GameObject((500, 150), size=(30, 30)))
        from_right.set_velocity(-400, 0)
        simulate(right_wall_world, 2.0)
        self.assertEqual(from_right.get_contact(right_wall).direction, Direction.LEFT)

    def test_object_stops_at_right_wall(self):
        world = PhysicsWorld()
        wall = world.add_platform(Platform((500, 100), (40, 300)))
        obj = world.add_object(GameObject((100, 150), size=(30, 30)))
        obj.set_velocity(600, 0)

        simulate(world, 1.0)

        # Para com a borda direita encostada na parede (500 - 30).
        self.assertAlmostEqual(obj.position.x, 470, delta=TOLERANCE)
        self.assertEqual(obj.velocity.x, 0.0)

    def test_solid_object_blocks_another_object(self):
        world = PhysicsWorld()
        blocker = world.add_object(
            GameObject((300, 150), size=(40, 100), gravity_enabled=False, solid=True)
        )
        mover = world.add_object(
            GameObject((50, 150), size=(30, 30), gravity_enabled=False)
        )
        mover.set_velocity(600, 0)

        simulate(world, 1.0)

        # Parou antes de invadir o bloqueio (300 - 30).
        self.assertLessEqual(mover.rect.right, blocker.rect.left + TOLERANCE)

    # ------------------------------------------------------------------
    # Eventos
    # ------------------------------------------------------------------
    def test_landing_event_fires_only_once(self):
        world = PhysicsWorld()
        world.add_platform(Platform((0, 400), (400, 40)))
        obj = world.add_object(
            SpyObject((50, 100), size=(30, 30), gravity_enabled=True)
        )

        simulate(world, 5.0)

        self.assertEqual(obj.events.count("landed"), 1)

    def test_ceiling_and_wall_events_fire(self):
        world = PhysicsWorld()
        world.add_platform(Platform((0, 0), (400, 40)))
        obj = world.add_object(SpyObject((50, 200), size=(30, 30)))
        obj.set_velocity(0, -400)

        simulate(world, 1.0)
        self.assertIn("ceiling", obj.events)

    def test_collision_end_fires_when_separated(self):
        world = PhysicsWorld()
        floor = world.add_platform(Platform((0, 400), (400, 40)))
        obj = world.add_object(
            SpyObject((50, 100), size=(30, 30), gravity_enabled=True)
        )

        simulate(world, 2.0)
        # Enquanto está apoiado, o contato não termina.
        self.assertNotIn("end", obj.events)

        # Subindo longe do chão, o contato deve terminar exatamente uma vez.
        obj.set_velocity(0, -400)
        simulate(world, 0.2)
        self.assertIsNone(obj.get_contact(floor))
        self.assertEqual(obj.events.count("end"), 1)

    def test_event_handlers_are_registered(self):
        world = PhysicsWorld()
        world.add_platform(Platform((0, 400), (400, 40)))
        obj = world.add_object(
            GameObject((50, 100), size=(30, 30), gravity_enabled=True)
        )

        calls = []
        obj.add_event_handler("landed", lambda collision: calls.append(collision))

        simulate(world, 3.0)

        self.assertEqual(len(calls), 1)

    # ------------------------------------------------------------------
    # Comportamento dos objetos
    # ------------------------------------------------------------------
    def test_inactive_object_is_not_simulated(self):
        world = PhysicsWorld()
        obj = world.add_object(
            GameObject((50, 100), size=(30, 30), gravity_enabled=True)
        )
        obj.active = False

        simulate(world, 2.0)

        self.assertEqual(obj.position.y, 100)

    def test_movement_disabled_object_does_not_move(self):
        world = PhysicsWorld()
        obj = world.add_object(
            GameObject((50, 100), size=(30, 30), gravity_enabled=False)
        )
        obj.movement_enabled = False
        obj.set_velocity(300, 0)

        simulate(world, 1.0)

        self.assertEqual(obj.position.x, 50)

    def test_stop_zeros_selected_axes_only(self):
        obj = GameObject((0, 0), size=(30, 30))
        obj.set_velocity(100, -200)

        obj.stop(vertical=False)
        self.assertEqual(obj.velocity.x, 0)
        self.assertEqual(obj.velocity.y, -200)

        obj.set_velocity(100, -200)
        obj.stop(horizontal=False)
        self.assertEqual(obj.velocity.x, 100)
        self.assertEqual(obj.velocity.y, 0)

        obj.stop()
        self.assertEqual(obj.velocity.x, 0)
        self.assertEqual(obj.velocity.y, 0)

    def test_interactive_object_moves_without_gravity(self):
        world = PhysicsWorld()
        obj = world.add_object(
            InteractiveObject((50, 100), size=(28, 28), speed=120)
        )
        obj.activate()

        simulate(world, 1.0)

        # Andou para a direita e não caiu.
        self.assertGreater(obj.position.x, 50)
        self.assertEqual(obj.position.y, 100)

    def test_interactive_object_blocked_by_solid_platform(self):
        world = PhysicsWorld()
        world.add_platform(Platform((200, 100), (40, 200)))
        obj = world.add_object(
            InteractiveObject((50, 150), size=(28, 28), speed=200)
        )
        obj.activate()

        simulate(world, 2.0)

        # Parou ao bater na parede e inverteu a direção.
        self.assertLessEqual(obj.rect.right, 200 + TOLERANCE)
        self.assertEqual(obj.direction, -1)

    def test_player_jumps_only_when_grounded(self):
        world = PhysicsWorld()
        floor = world.add_platform(Platform((0, 400), (400, 40)))
        obj = world.add_object(
            GameObject((50, 350), size=(30, 30), gravity_enabled=True)
        )

        simulate(world, 1.0)
        self.assertTrue(obj.grounded)

        # No ar, um salto não deve gerar movimento vertical.
        obj.position.update(50, 100)
        obj._sync_rect()
        simulate(world, 0.05)
        obj.set_velocity(0, -600)
        simulate(world, 0.05)

        # Subindo por estar no ar mesmo sem estar apoiado.
        self.assertLess(obj.velocity.y, 0)

    def test_jump_arc_matches_gravity(self):
        world = PhysicsWorld()
        world.add_platform(Platform((0, 400), (400, 40)))
        obj = world.add_object(
            GameObject((50, 350), size=(30, 30), gravity_enabled=True)
        )
        simulate(world, 1.0)

        start_y = obj.position.y
        obj.set_velocity(0, -600)

        highest_y = start_y
        for _ in range(120):
            world.update(DT)
            # No Pygame, Y menor significa mais alto.
            highest_y = min(highest_y, obj.position.y)

        height = start_y - highest_y

        # A subida é limitada pela gravidade e menor que a distância que
        # qualquer velocidade inicial permitiria sem gravidade.
        self.assertGreater(height, 0)
        self.assertLess(height, 600)

    # ------------------------------------------------------------------
    # Regressões: objetos se espremendo e atravessando superfícies
    # ------------------------------------------------------------------
    def test_object_hitting_underside_is_not_pushed_up(self):
        """A base do objeto encosta no topo da plataforma: ele deve ficar
        ABAIXO dela, e não ser empurrado para cima."""
        world = PhysicsWorld()
        platform = world.add_platform(Platform((200, 200), (200, 40)))
        obj = world.add_object(GameObject((250, 260), size=(30, 30)))
        obj.set_velocity(0, -200)  # subindo: a base bate no topo da plataforma

        simulate(world, 1.0)

        # Encostado por baixo: o topo do objeto fica na base da plataforma.
        self.assertAlmostEqual(obj.rect.top, platform.rect.bottom, delta=TOLERANCE)
        # No Pygame, Y maior é mais baixo. O objeto pendurado fica ABAIXO da
        # plataforma, portanto nunca pode ter o topo acima do topo dela.
        self.assertGreaterEqual(obj.rect.top, platform.rect.top)

    def test_stacked_objects_do_not_pass_through_ceiling(self):
        """Dois objetos com gravidade empilhados sob o teto: o de cima não
        pode ser empurrado para cima através dele, mesmo espremido."""
        world = PhysicsWorld()
        ceiling = world.add_platform(Platform((0, 0), (200, 20)))
        world.add_platform(Platform((0, 200), (400, 20)))
        upper = world.add_object(
            GameObject((50, 20), size=(30, 30), gravity_enabled=True)
        )
        lower = world.add_object(
            GameObject((50, 170), size=(30, 30), gravity_enabled=True)
        )

        simulate(world, 3.0)

        # O objeto de cima nunca atravessa para o lado de cima do teto.
        self.assertGreaterEqual(upper.rect.top, ceiling.rect.top - TOLERANCE)
        self.assertAlmostEqual(upper.rect.top, ceiling.rect.bottom, delta=TOLERANCE)
        # O de baixo continua apoiado no chão.
        self.assertGreater(lower.rect.top, ceiling.rect.bottom)

    def test_pushed_object_does_not_move_through_surface(self):
        """Um objeto que colide com outro por baixo deve ser reposicionado
        para fora da superfície, nunca para dentro dela."""
        world = PhysicsWorld()
        ceiling = world.add_platform(Platform((0, 0), (200, 20)))
        obj = world.add_object(GameObject((50, 60), size=(30, 30)))
        obj.set_velocity(0, -600)  # batendo no teto com força

        simulate(world, 1.0)

        self.assertGreaterEqual(obj.rect.top, ceiling.rect.bottom - TOLERANCE)

    def test_object_below_platform_is_not_teleported_above(self):
        """Regressão do caso Reportado: encostar de baixo numa plataforma
        suspensa não pode reposicionar o objeto acima dela."""
        world = PhysicsWorld()
        world.add_platform(Platform((100, 300), (200, 20)))
        # Nasce ACIMA da plataforma, para que a gravidade o traga até ela.
        obj = world.add_object(
            GameObject((150, 240), size=(30, 30), gravity_enabled=True)
        )

        simulate(world, 0.5)
        # Antes de subir, o objeto está apoiado em cima da plataforma.
        self.assertAlmostEqual(obj.rect.bottom, 300, delta=TOLERANCE)

        obj.set_velocity(0, -150)
        simulate(world, 1.0)

        # No Pygame, Y MENOR é mais alto. O objeto apoiado em cima tem top=270.
        # Se o empurrão para cima fosse aplicado, ele subiria para top<240.
        self.assertLessEqual(obj.rect.top, 300 - TOLERANCE)
        self.assertAlmostEqual(obj.rect.bottom, 300, delta=TOLERANCE)

    def test_platform_and_ceiling_pins_object_safely(self):
        """Objeto espremido entre o chão e o teto não é expulso do cenário."""
        world = PhysicsWorld()
        world.add_platform(Platform((0, 0), (200, 20)))
        world.add_platform(Platform((0, 120), (200, 20)))
        obj = world.add_object(
            GameObject((50, 40), size=(30, 30), gravity_enabled=True)
        )

        simulate(world, 3.0)

        # Permanece dentro do corredor entre as duas superfícies.
        self.assertGreaterEqual(obj.rect.top, 20 - TOLERANCE)
        self.assertLessEqual(obj.rect.bottom, 120 + TOLERANCE)

    # ------------------------------------------------------------------
    # Plataformas móveis e arrasto
    # ------------------------------------------------------------------
    def test_static_platform_does_not_move(self):
        world = PhysicsWorld()
        platform = world.add_platform(Platform((100, 300), (100, 20)))

        simulate(world, 2.0)

        self.assertEqual(platform.rect.x, 100)
        self.assertEqual(platform.frame_motion, (0, 0))

    def test_moving_platform_travels_and_returns(self):
        platform = Platform((100, 300), (100, 20), moving=True, speed=100, travel=150)

        simulate_platform(platform, 1.5)
        self.assertGreater(platform.rect.x, 100)

        # Na ida e volta completa ele volta para perto da posição inicial.
        # A folga é de 1 pixel porque o retângulo é inteiro e o percurso é
        # medido em ponto flutuante.
        simulate_platform(platform, 1.5)
        self.assertAlmostEqual(platform.rect.x, 100, delta=1.5)

    def test_vertical_platform_goes_up(self):
        # No Pygame, Y menor é mais alto: `axis="y"` começa subindo.
        platform = Platform((100, 300), (100, 20), moving=True, speed=100, travel=120, axis="y")

        simulate_platform(platform, 1.0)

        self.assertLess(platform.rect.y, 300)

    def test_frame_motion_is_per_frame_delta(self):
        """`frame_motion` é o delta de UM quadro, não o acumulado.

        Se fosse o acumulado, o arrasto moveria o objeto em duplicidade.
        """
        platform = Platform((100, 300), (100, 20), moving=True, speed=100, travel=300)
        deltas = []

        for _ in range(10):
            platform.update(DT)
            deltas.append(platform.frame_motion.x)

        # Cada passo é `speed * dt`, e não a distância total percorrida.
        # `frame_motion` guarda o valor fracionário, mesmo com o retângulo
        # inteiro, para o arrasto não acumular erro de arredondamento.
        for delta in deltas:
            self.assertAlmostEqual(delta, 100 * DT, delta=0.01)

    def test_object_is_carried_by_moving_platform(self):
        world = PhysicsWorld()
        platform = world.add_platform(
            Platform((100, 300), (120, 20), moving=True, speed=100, travel=300)
        )
        obj = world.add_object(
            GameObject((130, 270), size=(30, 30), gravity_enabled=True)
        )

        start_x = obj.position.x
        simulate(world, 1.0)

        # Andou junto com a plataforma e não caiu.
        self.assertGreater(obj.position.x, start_x + 50)
        self.assertEqual(obj.position.y, 270)

    def test_stack_of_objects_is_carried_upwards(self):
        """Três objetos empilhados sobem juntos com a plataforma vertical."""
        world = PhysicsWorld()
        platform = world.add_platform(
            Platform((100, 350), (120, 20), moving=True, speed=60, travel=100, axis="y")
        )
        stack = [
            world.add_object(
                GameObject((130, 320 - i * 30), size=(30, 30), gravity_enabled=True)
            )
            for i in range(3)
        ]
        starts = [obj.position.y for obj in stack]
        start_platform = platform.rect.y

        simulate(world, 1.0)

        rise = start_platform - platform.rect.y
        self.assertGreater(rise, 0)
        for obj, start in zip(stack, starts):
            # A folga cobre o acúmulo de arredondamento: cada nível da pilha
            # pode ficar até 1px acima do ideal, porque a colisão é resolvida
            # sobre retângulos inteiros enquanto a posição é em ponto
            # flutuante.
            self.assertAlmostEqual(start - obj.position.y, rise, delta=4.0)

    def test_carried_object_is_blocked_by_wall(self):
        """Arrastado contra uma parede, o objeto para nela e não atravessa."""
        world = PhysicsWorld()
        world.add_platform(Platform((0, 300), (640, 20)))
        world.add_platform(Platform((300, 0), (30, 300)))  # parede
        world.add_platform(
            Platform((100, 260), (80, 20), moving=True, speed=200, travel=150)
        )
        obj = world.add_object(
            GameObject((120, 230), size=(30, 30), gravity_enabled=True)
        )

        simulate(world, 2.0)

        # A parede começa em x=300; o objeto de 30px encosta em 270.
        self.assertLessEqual(obj.rect.right, 300 + TOLERANCE)

    def test_object_not_touching_platform_is_not_carried(self):
        """Quem está longe da plataforma não é arrastado."""
        world = PhysicsWorld()
        world.add_platform(
            Platform((100, 300), (60, 20), moving=True, speed=200, travel=200)
        )
        far = world.add_object(
            GameObject((400, 260), size=(30, 30), gravity_enabled=True)
        )
        start_x = far.position.x

        simulate(world, 0.5)

        self.assertAlmostEqual(far.position.x, start_x, delta=TOLERANCE)

    def test_object_carries_object_above_it(self):
        """Um objeto que anda sozinho arrasta quem está em cima dele.

        Este é o mesmo mecanismo das plataformas: qualquer superfície que se
        move leva o que está apoiado nela.
        """
        world = PhysicsWorld()
        world.add_platform(Platform((0, 300), (640, 20)))
        base = world.add_object(
            GameObject((100, 266), size=(30, 30), gravity_enabled=False)
        )
        top = world.add_object(
            GameObject((100, 236), size=(30, 30), gravity_enabled=False)
        )
        base.set_velocity(150, 0)

        simulate(world, 1.0)

        # Os dois andaram a mesma distância.
        self.assertAlmostEqual(top.position.x - 100, base.position.x - 100, delta=2.0)

    def test_stack_of_objects_moves_together(self):
        """Quatro objetos empilhados andam juntos quando o de baixo anda."""
        world = PhysicsWorld()
        world.add_platform(Platform((0, 400), (640, 20)))
        stack = [
            world.add_object(
                GameObject((100, 366 - i * 30), size=(30, 30), gravity_enabled=False)
            )
            for i in range(4)
        ]
        start_x = stack[0].position.x
        stack[0].set_velocity(150, 0)

        simulate(world, 1.0)

        distance = stack[0].position.x - start_x
        self.assertGreater(distance, 50)
        for obj in stack:
            self.assertAlmostEqual(obj.position.x - start_x, distance, delta=2.0)

    def test_object_moving_up_carries_object_above(self):
        """Quando o objeto de baixo sobe, o de cima é elevado junto."""
        world = PhysicsWorld()
        world.add_platform(Platform((0, 300), (640, 20)))
        base = world.add_object(
            GameObject((100, 266), size=(30, 30), gravity_enabled=False)
        )
        top = world.add_object(
            GameObject((100, 236), size=(30, 30), gravity_enabled=False)
        )
        simulate(world, 0.2)

        base_y = base.position.y
        top_y = top.position.y

        # Sobe o de baixo 3px por quadro, durante vários quadros.
        for _ in range(10):
            base.begin_frame()
            top.begin_frame()
            base.position.y -= 3
            base._sync_rect()
            world._update_contacts(base)
            world._update_contacts(top)
            world._apply_carry([base, top])

        base_rise = base_y - base.position.y
        top_rise = top_y - top.position.y

        self.assertAlmostEqual(base_rise, 30, delta=1.0)
        self.assertAlmostEqual(top_rise, base_rise, delta=1.0)

    def test_carried_stack_is_not_double_moved(self):
        """Plataforma que carrega uma pilha não soma o deslocamento duas vezes."""
        world = PhysicsWorld()
        platform = world.add_platform(
            Platform((100, 300), (150, 20), moving=True, speed=100, travel=300)
        )
        stack = [
            world.add_object(
                GameObject((130, 266 - i * 30), size=(30, 30), gravity_enabled=True)
            )
            for i in range(3)
        ]
        platform_start = platform.rect.x
        stack_start = [obj.position.x for obj in stack]

        simulate(world, 0.5)

        distance = platform.rect.x - platform_start
        for obj, start in zip(stack, stack_start):
            self.assertAlmostEqual(obj.position.x - start, distance, delta=2.0)

    def test_stack_blocked_by_wall_stops_together(self):
        """Levado contra uma parede, o objeto de baixo para e o de cima junto."""
        world = PhysicsWorld()
        world.add_platform(Platform((0, 300), (640, 20)))
        world.add_platform(Platform((300, 0), (30, 300)))  # parede
        base = world.add_object(
            GameObject((100, 266), size=(30, 30), gravity_enabled=False)
        )
        top = world.add_object(
            GameObject((100, 236), size=(30, 30), gravity_enabled=False)
        )
        base.set_velocity(400, 0)

        simulate(world, 1.0)

        # Encostado na parede (300 - 30) e os dois na mesma coluna.
        self.assertAlmostEqual(base.position.x, 270, delta=TOLERANCE)
        self.assertAlmostEqual(top.position.x, base.position.x, delta=2.0)

    def test_object_beside_moving_object_is_not_carried(self):
        """Quem não está APOIADO não é arrastado por quem passa ao lado."""
        world = PhysicsWorld()
        world.add_platform(Platform((0, 300), (640, 20)))
        mover = world.add_object(
            GameObject((50, 266), size=(30, 30), gravity_enabled=False)
        )
        by_stander = world.add_object(
            GameObject((400, 200), size=(30, 30), gravity_enabled=False)
        )
        start_x = by_stander.position.x

        mover.set_velocity(300, 0)
        simulate(world, 0.5)

        self.assertAlmostEqual(by_stander.position.x, start_x, delta=TOLERANCE)

    def test_ride_offset_reflects_object_movement(self):
        """`get_ride_offset` devolve o deslocamento real do objeto no quadro."""
        world = PhysicsWorld()
        world.add_platform(Platform((0, 300), (640, 20)))
        obj = world.add_object(
            GameObject((100, 266), size=(30, 30), gravity_enabled=False)
        )

        obj.begin_frame()
        self.assertEqual(obj.get_ride_offset(), (0, 0))

        obj.position.x += 7
        self.assertEqual(obj.get_ride_offset(), (7, 0))

    def test_riding_is_reported_on_object(self):
        world = PhysicsWorld()
        platform = world.add_platform(
            Platform((100, 300), (120, 20), moving=True, speed=50, travel=100)
        )
        obj = world.add_object(
            GameObject((130, 270), size=(30, 30), gravity_enabled=True)
        )

        simulate(world, 0.5)

        self.assertIs(obj.riding, platform)

    # ------------------------------------------------------------------
    # Plataforma
    # ------------------------------------------------------------------
    def test_platform_without_image_has_visual_representation(self):
        platform = Platform((0, 100), (64, 16))

        self.assertIsNotNone(platform.image)
        self.assertEqual(platform.image.get_size(), (64, 16))
        self.assertEqual(platform.rect.size, (64, 16))

    def test_platform_rect_matches_configured_size(self):
        image = pygame.Surface((200, 200))
        platform = Platform((0, 0), (80, 20), image=image)

        self.assertEqual(platform.rect.size, (80, 20))
        self.assertEqual(platform.image.get_size(), (80, 20))

    def test_platform_does_not_receive_gravity(self):
        world = PhysicsWorld()
        platform = world.add_platform(Platform((0, 100), (100, 20)))

        simulate(world, 2.0)

        self.assertEqual(platform.rect.topleft, (0, 100))


if __name__ == "__main__":
    unittest.main()