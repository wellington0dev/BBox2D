"""Enemy: entidade afetada pela gravidade, com comportamento sobrescrevível.

Demonstra que a arquitetura é extensível: o inimigo usa exatamente a mesma
física do jogador, sem que a física saiba que ele existe. A "IA" aqui é
mínima de propósito (anda até uma borda e vira), para servir de base.
"""

from .GameObject import GameObject

DEFAULT_SIZE = (30, 30)
DEFAULT_COLOR = (200, 90, 90)


class Enemy(GameObject):
    """Inimigo simples que patrulha uma plataforma."""

    def __init__(
        self,
        position=(0, 0),
        size=DEFAULT_SIZE,
        color=DEFAULT_COLOR,
        patrol_speed=90.0,
        gravity_scale=1.0,
    ):
        super().__init__(
            position=position,
            size=size,
            color=color,
            gravity_enabled=True,
            gravity_scale=gravity_scale,
            movement_enabled=True,
            solid=True,
        )

        self.patrol_speed = patrol_speed
        self.direction = 1  # 1 = direita, -1 = esquerda

    def update(self, dt=0.0):
        """Patrulha horizontalmente e vira ao encontrar uma borda.

        Usa o estado `grounded` calculado pela física para não cair da
        plataforma, o que mostra os objetos reagindo aos contatos.
        """
        super().update(dt)

        if not self.grounded:
            return

        # Vira ao chegar perto da borda da plataforma, para não cair.
        if not self.has_floor_ahead(self.direction):
            self.direction *= -1

        self.velocity.x = self.direction * self.patrol_speed