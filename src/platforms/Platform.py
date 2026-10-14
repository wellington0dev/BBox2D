"""Plataforma: superfície sólida, opcionalmente móvel.

Uma plataforma NÃO é um `GameObject`: ela não tem gravidade nem processa
entradas. É um retângulo sólido que o `PhysicsWorld` usa para resolver
contatos e, opcionalmente, desloca a cada quadro.

Movimento
---------
Com `moving=True` a plataforma percorre ida e volta entre dois pontos, no eixo
escolhido (`axis`):

- `axis="x"`: começa indo para a DIREITA;
- `axis="y"`: começa SUBINDO. No Pygame Y positivo é para baixo, então a
  direção inicial é -1.

O percurso tem `travel` pixels de extensão a partir da posição inicial. A cada
quadro a plataforma registra quanto andou em `frame_motion`, que é o que o
`PhysicsWorld` usa para arrastar quem está em cima dela.
"""

import pygame

#: Tolerância para considerar que a plataforma já chegou a uma das pontas.
#: Absorve o resíduo de ponto flutuante da divisão do passo.
_ARRIVED_EPSILON = 1e-6


def to_alpha(surface):
    """Converte a superfície para alpha, tolerando ausência de display.

    `convert_alpha()` exige uma superfície de display criada (`set_mode`).
    O jogo sempre tem uma, mas testes e scripts isolados podem não ter, e
    nesse caso a superfície original já funciona para blit.
    """
    if pygame.display.get_surface() is None:
        return surface
    return surface.convert_alpha()


class Platform:
    """Superfície sólida, estática por padrão e móvel se configurada."""

    def __init__(
        self,
        position=(0, 0),
        size=(64, 16),
        color=(120, 90, 60),
        image=None,
        solid=True,
        visible=True,
        one_way=False,
        moving=False,
        speed=60.0,
        travel=120.0,
        axis="x",
        can_carry=True,
    ):
        # `one_way=True` representa uma plataforma que só bloqueia quando o
        # objeto vem de cima (atravessa por baixo e por dentro ao subir).
        self.one_way = one_way

        self.size = size
        self.color = color
        self.solid = solid
        self.visible = visible

        # Movimento: desligado por padrão, como eram todas antes.
        self.moving = moving
        # `can_carry` permite que objetos sejam arrastados por ela. Uma
        # plataforma decorativa, por exemplo, pode ter `can_carry=False`.
        self.can_carry = can_carry

        self.rect = pygame.Rect(position, size)

        # Posição exata (com decimais). O retângulo é inteiro e não deve
        # acumular erro quando a velocidade não é múltipla de 60.
        self._exact = [float(self.rect.x), float(self.rect.y)]

        self.axis = axis if moving else None
        self.speed = abs(speed) if moving else 0.0
        self.travel = abs(travel) if moving else 0.0
        self.origin = pygame.Vector2(self.rect.topleft)
        # Sinal do eixo: +1 em x (direita) e -1 em y (cima), porque o Y do
        # Pygame cresce para baixo.
        self._axis_sign = 1 if axis == "x" else -1
        # Começa andando para o lado "natural" do eixo: direita em x, cima em y.
        self._direction = self._axis_sign
        # Deslocamento DESTE quadro, lido pelo PhysicsWorld no arrasto.
        self.frame_motion = pygame.Vector2(0, 0)

        if image is not None:
            self.image = to_alpha(pygame.transform.scale(image, size))
        elif visible:
            self.image = pygame.Surface(size)
            self.image.fill(color)
            self.image = to_alpha(self.image)
        else:
            self.image = None

    @property
    def position(self):
        return self.rect.topleft

    @property
    def bounds(self):
        """Retângulo da plataforma (mesmo que não seja visível)."""
        return self.rect

    # ------------------------------------------------------------------
    # Movimento
    # ------------------------------------------------------------------
    def update(self, dt):
        """Desloca a plataforma e registra o quanto andou NESTE quadro.

        `frame_motion` é o delta de um único quadro, e não o deslocamento
        acumulado desde o início: é esse valor que o arrasto soma à posição de
        quem está em cima, e somar o acumulado moveria o objeto em duplicidade
        a cada passo.
        """
        self.frame_motion.update(0, 0)

        if not self.moving or self.speed == 0:
            return

        before = (self._exact[0], self._exact[1])

        self._advance(self.speed * dt)

        self.frame_motion.x = self._exact[0] - before[0]
        self.frame_motion.y = self._exact[1] - before[1]

    def _advance(self, distance):
        """Anda `distance` na direção da marcha, invertindo ao chegar na ponta.

        O percurso é medido pelo CENTRO da plataforma, que começa em
        `center_start` (posição original). A outra ponta, `center_end`, fica a
        `travel` de distância seguindo o sinal do eixo:

        - em `x`, `travel` para a DIREITA (`+`), porque X cresce para a direita;
        - em `y`, `travel` para CIMA (`-`), porque no Pygame Y cresce para baixo.

        `_direction` vale sempre +1 ou -1 no espaço, e começa valendo o sinal
        do eixo, para que uma plataforma em `y` comece subindo.
        """
        # Vetores do Pygame são indexados por número: 0 = x, 1 = y.
        index = 0 if self.axis == "x" else 1

        half = self.size[index] / 2
        center_start = self.origin[index] + half
        # Em Y, "andar" é subir, então a ponta final fica MENOS que a inicial.
        center_end = center_start + self.travel * self._axis_sign

        center = self._exact[index] + half

        # A ponta que o sentido atual busca. `_direction` é o sentido no
        # ESPAÇO (+1 ou -1) e `center_start`/`center_end` são as pontas,
        # então o alvo depende dos dois: se a direção coincide com o lado da
        # ponta final, o alvo é `center_end`; senão, é `center_start`.
        going_to_end = (self._direction > 0) == (center_end > center_start)
        target = center_end if going_to_end else center_start

        # Distância que falta até a ponta, sempre positiva.
        remaining = abs(target - center)
        step = abs(distance)

        if remaining <= _ARRIVED_EPSILON:
            # Já está na ponta: inverte e gasta o passo inteiro na nova
            # direção. Sem isso, o quadro da inversão seria "perdido" e a
            # plataforma nunca voltaria exatamente à origem.
            self._direction *= -1
            new_center = center + step * self._direction
        elif step >= remaining:
            # Chegou na ponta neste quadro: anda só o que falta e inverte.
            new_center = target
            self._direction *= -1
        else:
            new_center = center + step * self._direction

        delta = new_center - center
        # `rect` guarda inteiros, então um delta fracionário seria truncado a
        # cada quadro e o erro se acumularia. A posição exata é guardada em
        # `_exact`, e o retângulo apenas reflete esse valor arredondado.
        self._exact[index] += delta
        if index == 0:
            self.rect.x = round(self._exact[0])
        else:
            self.rect.y = round(self._exact[1])

    def get_ride_offset(self):
        """Quanto esta plataforma andou neste quadro.

        É esse valor que o `PhysicsWorld` soma à posição de quem está em cima
        dela, produzindo o arrasto.
        """
        return self.frame_motion

    def colliderect(self, other_rect):
        """True se `other_rect` se sobrepõe à plataforma."""
        return self.rect.colliderect(other_rect)

    def draw(self, surface):
        """Desenha a plataforma, se for visível."""
        if self.visible and self.image is not None:
            surface.blit(self.image, self.rect)
        elif self.visible:
            pygame.draw.rect(surface, self.color, self.rect)

    def __repr__(self):
        return f"<Platform {tuple(self.rect)} sólido={self.solid} móvel={self.moving}>"