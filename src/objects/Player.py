"""Player: entidade controlada pelo teclado.

O `Player` NÃO aplica deslocamento. Ele lê as teclas e declara a velocidade
desejada; quem aplica o movimento e resolve as colisões é o `PhysicsWorld`.
Assim a mesma física serve para o jogador, para inimigos e para objetos sem
gravidade.

Convenção de Y do Pygame: positivo é para BAIXO. Então o pulo começa com uma
velocidade vertical NEGATIVA, e a gravidade (positiva) desacelera a subida
até o ponto mais alto e acelera a queda.
"""

import pygame

from .GameObject import DEFAULT_WEIGHT, GameObject

DEFAULT_SIZE = (32, 40)
DEFAULT_COLOR = (240, 200, 120)

#: Velocidades padrão, em pixels por SEGUNDO.
DEFAULT_MOVE_SPEED = 260.0
DEFAULT_JUMP_SPEED = 620.0


class Player(GameObject):
    """Personagem jogável, afetado pela gravidade."""

    def __init__(
        self,
        position=(0, 0),
        size=DEFAULT_SIZE,
        color=DEFAULT_COLOR,
        move_speed=DEFAULT_MOVE_SPEED,
        jump_speed=DEFAULT_JUMP_SPEED,
        gravity_scale=1.0,
        weight=DEFAULT_WEIGHT,
    ):
        super().__init__(
            position=position,
            size=size,
            color=color,
            gravity_enabled=True,
            gravity_scale=gravity_scale,
            movement_enabled=True,
            solid=True,
            weight=weight,
            jump_strength=jump_speed,
        )

        self.move_speed = move_speed
        # `jump_speed` é o nome histórico deste projeto; o atributo oficial do
        # sistema de pesos é `jump_strength` (na classe-base). A propriedade
        # abaixo mantém os dois apontando para o mesmo valor.
        self.jump_speed = jump_speed

        # Peso próprio: com carga igual a ele, o salto é bloqueado.
        self.weight = weight

        # Controlos configuráveis: a física não conhece nenhuma tecla.
        # {"esquerda": pygame.K_a, "direita": pygame.K_d, "pular": pygame.K_SPACE}
        self.controls = {
            "esquerda": pygame.K_LEFT,
            "direita": pygame.K_RIGHT,
            "pular": pygame.K_SPACE,
        }

        self._jump_requested = False

    @property
    def jump_speed(self):
        """Alias de `jump_strength`, mantido por compatibilidade."""
        return self.jump_strength

    @jump_speed.setter
    def jump_speed(self, value):
        self.jump_strength = value

    # ------------------------------------------------------------------
    # Entrada
    # ------------------------------------------------------------------
    def handle_event(self, event):
        """Registra a intenção de pular.

        O pulo acontece no `update()` e só se o jogador estiver apoiado, o
        que impede pulo duplo no ar.
        """
        if event.type == pygame.KEYDOWN:
            if event.key == self.controls["pular"]:
                self._jump_requested = True
                return True
        return False

    # ------------------------------------------------------------------
    # Comportamento
    # ------------------------------------------------------------------
    def update(self, dt=0.0):
        """Define a velocidade horizontal e executa o pulo, se permitido.

        Roda ANTES do `PhysicsWorld.update()`, então aqui só mudamos a
        velocidade; o deslocamento é aplicado uma única vez pela física.
        """
        super().update(dt)

        keys = pygame.key.get_pressed()
        axis = 0.0
        if keys[self.controls["esquerda"]]:
            axis -= 1.0
        if keys[self.controls["direita"]]:
            axis += 1.0

        # No eixo X não usamos a gravidade, então podemos definir a velocidade
        # diretamente.
        self.velocity.x = axis * self.move_speed

        # Pular: só com os pés no chão e carga abaixo do próprio peso.
        #
        # `can_jump()` e `get_effective_jump_strength()` já aplicam a fórmula
        # de carga; aqui só pedimos o valor e deixamos a física aplicar o
        # movimento. `_jump_requested` é limpo ao usar, e como só o ar da para
        # saltar de novo, não há pulo duplo no ar.
        if self._jump_requested:
            if self.can_jump():
                strength = self.get_effective_jump_strength()
                # para cima é negativo em Y
                self.velocity.y = -strength
            self._jump_requested = False

    # ------------------------------------------------------------------
    # Reações a colisões
    # ------------------------------------------------------------------
    def on_landed(self, collision):
        print(f"[Player] aterrissou em {collision.other!r}")

    def on_hit_ceiling(self, collision):
        print("[Player] bateu no teto")

    def on_hit_wall(self, collision):
        pass