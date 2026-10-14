"""InteractiveObject: objeto que reage a gatilhos, não necessariamente à gravidade.

Serve para demonstrar a extensibilidade: pode ser tanto uma caixa affected
pela gravidade quanto uma plataforma flutuante sem gravidade, porque quem
aplica movimento e resolve colisões é sempre o `PhysicsWorld`.

O comportamento aqui é propositalmente genérico: métodos vazios para as
subclasses sobrescrevem. Nada de portas, enigmas ou baús fictícios.
"""

import pygame

from .GameObject import GameObject

DEFAULT_SIZE = (28, 28)
DEFAULT_COLOR = (150, 200, 240)


class InteractiveObject(GameObject):
    """Objeto genérico, ativável e reagindo a colisões."""

    def __init__(
        self,
        position=(0, 0),
        size=DEFAULT_SIZE,
        color=DEFAULT_COLOR,
        gravity_enabled=False,
        solid=False,
        active=True,
        speed=0.0,
    ):
        super().__init__(
            position=position,
            size=size,
            color=color,
            gravity_enabled=gravity_enabled,
            movement_enabled=True,
            solid=solid,
            active=active,
        )

        # Objetos interativos costumam ser movidos por script, não por
        # gravidade, então guardam a velocidade desejada e a aplicam no update.
        self.speed = speed
        self.activated = False
        self.direction = 1

    # ------------------------------------------------------------------
    # Controle externo
    # ------------------------------------------------------------------
    def activate(self):
        """Marca o objeto como ativado e dispara o evento correspondente."""
        if not self.activated:
            self.activated = True
            self.on_activate()
            self._notify("activate")

    def deactivate(self):
        """Desativa o objeto."""
        if self.activated:
            self.activated = False
            self.on_deactivate()
            self._notify("deactivate")

    def move(self, x=0, y=0):
        """Deslocamento direto, usado por script ou animação."""
        self.position += pygame.Vector2(x, y)
        self._sync_rect()

    def set_direction(self, direction):
        """Define a direção do movimento próprio (1 ou -1)."""
        self.direction = 1 if direction >= 0 else -1

    # ------------------------------------------------------------------
    # Comportamento
    # ------------------------------------------------------------------
    def update(self, dt=0.0):
        """Move o objeto na direção configurada, se ativado.

        Sem gravidade, o objeto não cai sozinho, mas continua respeitando
        as colisões: quem bloqueia o eixo é a física.
        """
        super().update(dt)

        if not self.activated:
            return

        self.velocity.x = self.speed * self.direction

    # ------------------------------------------------------------------
    # Pontos de extensão
    # ------------------------------------------------------------------
    def on_activate(self):
        """Chamado na ativação. Vazio na base."""
        pass

    def on_deactivate(self):
        """Chamado na desativação. Vazio na base."""
        pass

    def on_hit_wall(self, collision):
        """Inverte a direção ao encostar numa parede."""
        self.direction *= -1
        print(f"[InteractiveObject] invertendo direção: {self.direction}")