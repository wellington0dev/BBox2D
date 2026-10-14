"""Estruturas de dados de colisão.

Este módulo não tem dependência de nenhuma classe concreta: define apenas o
formato dos contatos entre um objeto e uma superfície. Assim tanto `Platform`
quanto `GameObject` podem ser usados sem conhecimento mútuo.
"""

from enum import Enum


class Direction(Enum):
    """Lado do objeto EM MOVIMENTO que encostou na superfície.

    Convenção do projeto (fixa, não misturar interpretações):

        TOP    -> o objeto encostou com o seu topo, ou seja, está APOIADO
                  em cima da superfície. Acontece ao aterrissar.
        BOTTOM -> o objeto encostou com a sua base, ou seja, está BATENDO
                  no teto, preso por baixo da superfície.
        LEFT   -> o objeto encostou com a sua lateral esquerda.
        RIGHT  -> o objeto encostou com a sua lateral direita.

    Ou seja: a direção descreve SEMPRE o lado do objeto que se move, nunca
    o lado da superfície. Para a superfície, use `Collision.normal`, que é o
    vetor que aponta PARA FORA dela.
    """

    TOP = "top"
    BOTTOM = "bottom"
    LEFT = "left"
    RIGHT = "right"


#: Normal da superfície para cada direção de contato, no sentido "empurra".
#: Aponta na direção em que a superfície empurra o objeto que encostou, e é
#: sempre a OPOSTA do lado do objeto que encostou.
#: Em pygame o eixo Y cresce para BAIXO, então o chão empurra para cima (0, -1).
SURFACE_NORMALS = {
    Direction.TOP: (0, -1),     # apoiado em cima -> empurra para cima
    Direction.BOTTOM: (0, 1),    # bateu por baixo -> empurra para baixo
    Direction.LEFT: (1, 0),      # encostou pela esquerda -> empurra para a direita
    Direction.RIGHT: (-1, 0),    # encostou pela direita -> empurra para a esquerda
}


class Collision:
    """Um contato entre um objeto e uma superfície (outro objeto ou plataforma).

    Atributos:
        other:       a superfície atingida (Platform ou GameObject).
        direction:   lado do objeto móvel que encostou (Direction).
        normal:      vetor unitário que aponta para fora da superfície.
        penetration: profundidade da sobreposição, em pixels.
        relative_position: diferença entre os centros, usada para desempate.
    """

    __slots__ = ("other", "direction", "normal", "penetration", "relative_position")

    def __init__(self, other, direction, penetration=0, relative_position=None):
        self.other = other
        self.direction = direction
        self.normal = SURFACE_NORMALS[direction]
        self.penetration = penetration
        self.relative_position = relative_position or (0, 0)

    @property
    def is_landing(self):
        """Contato com o topo: o objeto pode se dizer apoiado."""
        return self.direction is Direction.TOP

    @property
    def is_horizontal(self):
        """Contato lateral, que não deve mexer na velocidade vertical."""
        return self.direction in (Direction.LEFT, Direction.RIGHT)

    def __repr__(self):
        return (
            f"<Collision {self.direction.value} com "
            f"{type(self.other).__name__} penetração={self.penetration:.1f}>"
        )


class ContactState:
    """Estado de um par (objeto, superfície) entre dois quadros.

    Permite diferenciar início, continuidade e fim de colisão, evitando
    disparar uma nova aterrissagem a cada quadro em que o objeto permanece
    em cima da plataforma.
    """

    __slots__ = ("collision", "frames")

    def __init__(self, collision):
        self.collision = collision
        self.frames = 1

    def refresh(self, collision):
        self.collision = collision
        self.frames += 1
        return self