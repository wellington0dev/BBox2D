"""Classe-base das entidades móveis e interativas do jogo.

Um `GameObject` guarda o estado físico (posição, velocidade, gravidade,
colisões) e oferece pontos de extensão para as subclasses reagirem a
eventos. Ele NÃO aplica o próprio deslocamento: quem move o objeto na tela é
o `PhysicsWorld`, que é o único dono da simulação.

Isso evita o problema clássico de "controle e física aplicando o mesmo
movimento duas vezes no mesmo quadro": o objeto apenas declara intenção
(`set_velocity`, `move`), e a física executa.

Eixos do Pygame: X cresce para a DIREITA e Y cresce para BAIXO. Por isso
"para cima" é um valor negativo de Y.

Peso e carga
------------
`weight` é o peso INTRÍNSEO do objeto, e nunca muda em tempo de execução.
A carga que o objeto RECEBE é calculada pelo `PhysicsWorld` a cada quadro e
fica em `supported_load`; as duas coisas são propositalmente separadas, para
que apoio temporário não "contamine" o peso próprio.

O peso influencia três coisas, e só três:

- a velocidade inicial do salto, via `get_effective_jump_strength`;
- a cedência vertical de objetos sem gravidade, via `vertical_resistance`;
- pequenos modificadores de velocidade vertical, via `weight_influence`.

Ele não substitui colisões, gravidade nem o arraste: um objeto pesado continua
obedecendo paredes, tetos e plataformas.
"""

import pygame

from ..physics.Collision import Direction
from ..platforms.Platform import to_alpha

#: Menor peso aceito. Evita divisão por zero em `load / weight`.
MIN_WEIGHT = 1e-6

#: Peso padrão de um objeto. Serve como unidade de comparação: a carga que
#: iguala o próprio peso já impede o salto (`load_ratio >= 1`).
DEFAULT_WEIGHT = 1.0

#: Quanto o objeto reage ao peso que recebe. `0.0` ignora a carga por
#: completo; `1.0` é a resposta padrão.
DEFAULT_WEIGHT_INFLUENCE = 1.0

#: Carga que um objeto sem gravidade aguenta antes de ceder, nas mesmas
#: unidades de `weight`. `0.0` significa que ele cede a qualquer carga acima
#: de zero, o que faz uma plataforma flutuante afundar quando alguém sobe
#: nela. Use `math.inf` para uma plataforma rígida que nunca cede.
DEFAULT_VERTICAL_RESISTANCE = 0.0

#: Tolerância para considerar que a carga "mudou". Evita disparar
#: `on_load_changed` por causa de ruído de ponto flutuante.
LOAD_EPSILON = 1e-6

#: Razão mínima de peso para um objeto conseguir empurrar outro. Com 1.2, um
#: objeto precisa ser pelo menos 20% mais pesado que o alvo; abaixo disso
#: (inclusive no empate) ele não o move.
PUSH_WEIGHT_RATIO = 1.2

#: Razão máxima que ainda é possível empurrar. Passar disso é pesado demais:
#: `can_push()` devolve False e o objeto mais leve simplesmente barra o outro,
#: como acontece com qualquer corpo sólido encostado.
PUSH_WEIGHT_FULL = 3.0

#: Força do empurrão contra um alvo exatamente em `PUSH_WEIGHT_FULL`. O
#: empurrão começa em `PUSH_LIGHT_FORCE` (1.0) contra um alvo quase igual e
#: decresce até este valor contra o alvo no limite: empurrar algo 3x mais
#: pesado é possível, mas devagar.
PUSH_LIGHT_FORCE = 0.3


class GameObject(pygame.sprite.Sprite):
    """Entidade do jogo com estado físico."""

    def __init__(
        self,
        position=(0, 0),
        size=(32, 32),
        velocity=(0.0, 0.0),
        image=None,
        color=(200, 200, 200),
        gravity_enabled=False,
        gravity_scale=1.0,
        movement_enabled=True,
        solid=True,
        active=True,
        weight=DEFAULT_WEIGHT,
        weight_influence=DEFAULT_WEIGHT_INFLUENCE,
        vertical_resistance=DEFAULT_VERTICAL_RESISTANCE,
        jump_strength=None,
        pushable=True,
    ):
        super().__init__()

        # Vetor contínuo de posição. `rect` é derivado dele, nunca o contrário.
        self.position = pygame.Vector2(position)
        self.velocity = pygame.Vector2(velocity)
        self.acceleration = pygame.Vector2(0, 0)

        self.size = size

        if image is not None:
            self.image = pygame.transform.scale(image, size)
        else:
            # Sem imagem: um retângulo simples para testes e protótipos.
            self.image = pygame.Surface(size)
            self.image.fill(color)
        self.image = to_alpha(self.image)

        # `rect` fica sempre sincronizado com `position`.
        self.rect = self.image.get_rect()
        self.rect.topleft = (round(self.position.x), round(self.position.y))

        # Flags de comportamento.
        self.gravity_enabled = gravity_enabled
        self.gravity_scale = gravity_scale
        self.movement_enabled = movement_enabled
        self.solid = solid
        self.active = active

        # Preenchido pelo PhysicsWorld ao registrar o objeto. Permite que a
        # subclasse consulte superfícies sem conhecer a implementação da
        # física (ex.: `Enemy` checando se há chão à sua frente).
        self.world = None

        # Estado físico derivado das colisões, atualizado pelo PhysicsWorld.
        self.grounded = False
        self.current_collisions = []       # contatos neste quadro
        self._previous_contacts = {}       # pares já em contato no quadro anterior
        self._event_handlers = {}

        # Superfície em que este objeto está apoiado neste quadro. É preenchido
        # pelo PhysicsWorld e é o que permite arrastar quem está em cima de uma
        # plataforma ou de um objeto que se move.
        self.riding = None

        # Deslocamento aplicado por outra superfície neste quadro (arrasto).
        # Mantido por introspecção e para diagnóstico.
        self.carry_offset = pygame.Vector2(0, 0)

        # Posição no início do quadro. O PhysicsWorld a atualiza com
        # `begin_frame()`, e a diferença para a posição atual é o quanto o
        # objeto andou — inclusive por arrasto, que é o que faz ele carregar
        # quem está em cima.
        self._frame_start = self.position.copy()

        # ---- Peso e carga -------------------------------------------
        # `weight` é o peso próprio e é imutável em tempo de execução.
        # Passa pela property para já nascer validado (peso negativo, zero ou
        # NaN viram o mínimo seguro).
        self.weight = weight
        self.weight_influence = max(0.0, float(weight_influence))
        self.vertical_resistance = float(vertical_resistance)

        # Força/velocidade inicial de salto. `None` significa "não se aplica",
        # e a subclasses (como o Player) define a sua.
        self._jump_strength = None if jump_strength is None else float(jump_strength)

        # Carga RECEBIDA, recalculada pelo PhysicsWorld a cada quadro. Não é
        # parte do peso próprio e zera sozinha quando o apoio acaba.
        self.supported_load = 0.0

        # Support para o valor anterior, para firing de eventos só na mudança.
        self._previous_load = 0.0
        self._previous_riding = None

        # Se pode empurrar outros objetos pelo peso. `False` desliga a
        # interação para objetos que não deveriam participar dela.
        self.pushable = bool(pushable)

        # Velocidade horizontal, em px/s, que o empurrão está aplicando NESTE
        # objeto neste quadro (positiva = para a direita).
        #
        # Não entra na `velocity` do objeto: `velocity` é o movimento próprio
        # dele e persiste entre quadros, então somar o empurrão a cada quadro
        # o faria acelerar sem limite (190 -> 570 -> 1140 -> ...). Aqui o valor
        # é substituído a cada quadro pelo empurrão atual e decai sozinho quando
        # o contato termina, o que dá inércia curta em vez de velocidade
        # permanente.
        self.push_speed = 0.0

    # ------------------------------------------------------------------
    # Movimento (intenção). A aplicação é do PhysicsWorld.
    # ------------------------------------------------------------------
    def move(self, x=0, y=0):
        """Soma um deslocamento à velocidade atual (intenção de movimento)."""
        self.velocity += pygame.Vector2(x, y)

    def set_velocity(self, x=0.0, y=0.0):
        """Substitui a velocidade pelos valores dados."""
        self.velocity.update(x, y)

    def stop(self, horizontal=None, vertical=None):
        """Zera a velocidade.

        Sem argumento, para os dois eixos: `stop()`.

        Informe `False` no eixo que deve PRESERVAR a velocidade, que é o caso
        comum ao encostar numa parede:

            obj.stop(vertical=False)   # para o X, continua caindo
            obj.stop(horizontal=False)  # para o Y, continua andando
        """
        if horizontal is None and vertical is None:
            horizontal = vertical = True

        if horizontal is None:
            horizontal = True
        if vertical is None:
            vertical = True

        if horizontal:
            self.velocity.x = 0.0
        if vertical:
            self.velocity.y = 0.0

    # ------------------------------------------------------------------
    # Ciclo do objeto
    # ------------------------------------------------------------------
    def update(self, dt=0.0):
        """Atualiza o estado temporal do objeto.

        A classe-base não move nada: apenas mantém o `rect` alinhado com a
        posição. O deslocamento real acontece em `PhysicsWorld.update()`.
        """
        self._sync_rect()

    def draw(self, surface):
        """Desenha o objeto na superfície recebida."""
        if self.image is not None:
            surface.blit(self.image, self.rect)

    def _sync_rect(self):
        """Mantém o retângulo de colisão alinhado com a posição do objeto."""
        self.rect.topleft = (round(self.position.x), round(self.position.y))

    # ------------------------------------------------------------------
    # Eventos de colisão
    # ------------------------------------------------------------------
    def on_collision(self, collision):
        """Chamado em todo quadro de colisão. Vazio na base."""
        pass

    def on_collision_start(self, collision):
        """Chamado apenas no PRIMEIRO quadro de um contato."""
        pass

    def on_collision_end(self, collision):
        """Chamado quando o contato termina (objeto se afastou)."""
        pass

    def on_landed(self, collision):
        """Reação específica a aterrissagem (contato pelo topo)."""
        pass

    def on_hit_ceiling(self, collision):
        """Reação ao bater no teto (contato pela base)."""
        pass

    def on_hit_wall(self, collision):
        """Reação ao encostar numa parede (contato lateral)."""
        pass

    def on_event(self, event):
        """Ponto de extensão para eventos genéricos do jogo. Vazio na base."""
        pass

    def handle_event(self, event):
        """Processa eventos externos do Pygame.

        Devolve True se o evento foi consumido. A base não consome nada.
        """
        return False

    # ------------------------------------------------------------------
    # Registro de callbacks
    # ------------------------------------------------------------------
    def add_event_handler(self, event_type, callback):
        """Registra `callback` para um tipo de evento.

        Os tipos gerados pela simulação são as chaves de
        `CollisionPhase` (ex.: "collision_start", "landed", "hit_wall").
        """
        self._event_handlers.setdefault(event_type, []).append(callback)
        return callback

    def _notify(self, event_type, *args):
        """Chama o método correspondente e os callbacks registrados."""
        handler = getattr(self, f"on_{event_type}", None)
        if callable(handler):
            handler(*args)

        for callback in self._event_handlers.get(event_type, []):
            callback(*args)

    # ------------------------------------------------------------------
    # Peso e carga
    # ------------------------------------------------------------------
    @property
    def weight(self):
        """Peso intrínseco do objeto. Nunca negativo e nunca zero."""
        return self._weight

    @weight.setter
    def weight(self, value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = DEFAULT_WEIGHT

        # Peso negativo não faz sentido físico, e peso zero quebraria a
        # divisão `load / weight`. Ambos viram o mínimo seguro.
        if value != value or value < MIN_WEIGHT:  # NaN ou negativo/zero
            value = MIN_WEIGHT

        self._weight = value

    @property
    def jump_strength(self):
        """Velocidade inicial do salto, ou None se este objeto não salta."""
        return self._jump_strength

    @jump_strength.setter
    def jump_strength(self, value):
        if value is None:
            self._jump_strength = None
        else:
            self._jump_strength = max(0.0, float(value))

    def push_force_against(self, other):
        """Proporção do empurrão de `self` sobre `other`, entre 0.0 e 1.0.

        Deriva de `can_push()`. Dentro da faixa válida a força é MÁXIMA contra
        um alvo quase do mesmo peso e decresce até `PUSH_LIGHT_FORCE` contra o
        alvo no limite de `PUSH_WEIGHT_FULL`. Ou seja: empurrar um objeto leve é
        rápido e bruto; empurrar algo quase 3x mais pesado é possível, mas
        lento — que é o que a inércia do alvo pesado impõe de verdade.

        Devolve `0.0` quando `can_push()` é falso.
        """
        if not self.can_push(other):
            return 0.0

        ratio = self.weight / max(other.weight, MIN_WEIGHT)
        span = PUSH_WEIGHT_FULL - PUSH_WEIGHT_RATIO
        if span <= 0.0:
            return PUSH_LIGHT_FORCE

        # `t` vai de 0 (no limite mínimo, alvo quase igual) a 1 (no limite
        # máximo, alvo bem mais pesado).
        t = min(1.0, (ratio - PUSH_WEIGHT_RATIO) / span)

        return max(PUSH_LIGHT_FORCE, 1.0 - (1.0 - PUSH_LIGHT_FORCE) * t)

    def push_speed_against(self, other, light_speed, heavy_speed):
        """Velocidade, em px/s, com que `self` empurra `other`.

        A velocidade depende da razao `heaviness = self.weight / other.weight`
        (quao mais pesado o empurrador e que o alvo):

        - heaviness = 1 (pesos iguais): nao empurra (can_push=False)
        - 1 < heaviness <= 3: velocidade decresce de light_speed até heavy_speed
        - heaviness > 3: nao empurra (can_push=False)
        - heaviness < 1 (empurrador mais leve): nao empurra (can_push=False)

        A velocidade varia linearmente:
        - heaviness = 1 (empate): light_speed (mas can_push=False)
        - heaviness = 3: heavy_speed
        """
        if not self.can_push(other):
            return 0.0

        heaviness = self.weight / max(other.weight, MIN_WEIGHT)

        # Interpola de light_speed (heaviness=1) ate heavy_speed (heaviness=3)
        span = PUSH_WEIGHT_FULL - 1.0
        if span <= 0.0:
            return heavy_speed

        t = min(1.0, max(0.0, (heaviness - 1.0) / span))
        return light_speed + (heavy_speed - light_speed) * t

    def can_push(self, other):
        """True se este objeto consegue empurrar `other` pelo peso.

        So o objeto MAIS PESADO consegue empurrar o mais leve, ate uma razao
        de 3.0. O mais leve nunca empurra o mais pesado.

            self.weight > other.weight  E  self.weight / other.weight <= 3.0

        - Pesos iguais: nao empurra (empate).
        - self mais leve que other: nao empurra.
        - self mais pesado mas razao > 3.0: nao empurra (pesado demais).
        """
        if not self.pushable or not other.pushable:
            return False

        if self.weight <= other.weight:
            return False

        ratio = self.weight / other.weight
        return ratio <= PUSH_WEIGHT_FULL

    def get_supported_load(self):
        """Carga direta que este objeto recebe de quem está em cima.

        Não inclui o peso próprio: é só o que veio de cima. É recalculada pelo
         e vale  quando nada está apoiado.
        """
        return self.supported_load

    def get_total_load(self):
        """Peso próprio somado à carga que ele recebe.

        É este total que um objeto abaixo recebe quando este está em cima dele.
        """
        return self.weight + self.supported_load

    def get_load_ratio(self):
        """`supported_load / weight`, a fração da capacidade que está ocupada.

        `0.0` sem carga, `1.0` quando a carga iguala o peso próprio. O peso é
        limitado por `MIN_WEIGHT`, então a divisão nunca explode.
        """
        return self.supported_load / max(self.weight, MIN_WEIGHT)

    def get_jump_factor(self):
        """Fator de `0.0` a `1.0` que reduz a força do salto conforme a carga.

            jump_factor = max(0.0, 1.0 - load_ratio)

        Sem carga vale `1.0` (salto normal); com carga igual ao peso vale `0.0`
        (não consegue saltar).
        """
        return max(0.0, 1.0 - self.get_load_ratio())

    def get_effective_jump_strength(self):
        """Velocidade inicial de salto depois de aplicar a carga.

            effective = jump_strength * max(0, 1 - load_ratio)

        Devolve `None` quando este objeto não tem força de salto definida, para
        que a chamada seja inofensiva em quem não salta.
        """
        if self._jump_strength is None:
            return None
        return self._jump_strength * self.get_jump_factor()

    def can_jump(self):
        """True se este objeto pode iniciar um salto agora.

        Exige estar apoiado numa superfície e ter carga abaixo do próprio peso.
        Objetos sem força de salto definida nunca podem saltar.
        """
        if self._jump_strength is None:
            return False
        if not self.grounded:
            return False
        return self.get_jump_factor() > 0.0

    def on_load_changed(self, supported_load):
        """Chamado quando a carga recebida muda. Vazio na base."""
        pass

    def on_support_changed(self, support):
        """Chamado quando muda o objeto/superfície de apoio. Vazio na base."""
        pass

    def on_lifted(self):
        """Chamado quando o objeto deixa de estar apoiado. Vazio na base."""
        pass

    def _apply_load(self, supported_load, support):
        """Chamada pelo PhysicsWorld: atualiza a carga e dispara as mudanças.

        Os eventos só disparam quando o valor MUDA de verdade, para não gerar
        notificação a cada quadro.
        """
        load_changed = abs(supported_load - self._previous_load) > LOAD_EPSILON
        support_changed = support is not self._previous_riding

        self.supported_load = supported_load

        if load_changed:
            self._previous_load = supported_load
            self._notify("load_changed", supported_load)

        if support_changed:
            previous = self._previous_riding
            self._previous_riding = support
            self._notify("support_changed", support)
            # Perdeu o apoio sem ganhar outro: foi "levantado".
            if support is None and previous is not None:
                self._notify("lifted")

    # ------------------------------------------------------------------
    # Consultas usadas pela física
    # ------------------------------------------------------------------
    def collides_with(self, other):
        """True se os retângulos se sobrepõem."""
        return self.rect.colliderect(other.rect)

    def get_surfaces(self):
        """Superfícies conhecidas, ou lista vazia se o objeto não está simulado."""
        if self.world is None:
            return []
        return self.world.get_surfaces()

    def begin_frame(self):
        """Marca a posição no início do quadro, para medir o deslocamento depois.

        Chamado pelo `PhysicsWorld` antes de qualquer movimento.
        """
        self._frame_start = self.position.copy()
        self._carried_this_frame = False

    def get_ride_offset(self):
        """Quanto esta superfície andou NESTE quadro, por qualquer motivo.

        Serve para arrastar quem está em cima, e vale tanto para plataformas
        quanto para outros objetos. Um objeto que anda por conta própria (por
        velocidade, por arrasto ou porque foi empurrado) carrega o que está
        apoiado nele exatamente como uma plataforma faria.

        A medição é pela posição real de início e fim do quadro, e não por
        accumulates: assim o arrasto recebido também conta, e uma pilha inteira
        se move junto sem que o valor seja contado duas vezes.
        """
        start = getattr(self, "_frame_start", None)
        if start is None:
            return pygame.Vector2(0, 0)
        return self.position - start

    def has_floor_ahead(self, direction, distance=8):
        """True se há superfície sólida logo à frente, na direção dada.

        Usado por inimigos que andam sobre plataformas e precisam virar ao
        chegar perto da borda.
        """
        if self.world is None:
            return False

        probe = self.rect.move(int(direction * distance), 0)
        probe.bottom += 2
        return any(
            surface.solid and surface.rect.colliderect(probe)
            for surface in self.world.get_surfaces()
        )

    def is_contacting(self, other):
        """True se há um contato do tipo indicado neste quadro."""
        return any(c.other is other for c in self.current_collisions)

    def get_contact(self, other):
        """Devolve o `Collision` com `other`, ou None."""
        for collision in self.current_collisions:
            if collision.other is other:
                return collision
        return None

    def collides_in_direction(self, other, direction):
        """True se o contato com `other` é na direção indicada."""
        collision = self.get_contact(other)
        return collision is not None and collision.direction is direction