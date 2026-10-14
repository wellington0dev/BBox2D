"""PhysicsWorld: simulação, gravidade e resolução de colisões.

A física é a única dona do deslocamento dos objetos. Ela não conhece regras
de jogador, inimigo ou mecanismo: apenas integra movimento, aplica gravidade
a quem pediu e resolve contatos, informando o que houve por meio de eventos.

Convenção de eixos (Pygame): X para a direita, Y para BAIXO. Então "pular" é
uma velocidade vertical NEGATIVA, e o peso soma um valor POSITIVO em Y.

Resolução por eixos: o movimento é aplicado em X, depois em Y, e cada eixo é
testado contra as superfícies logo em seguida. É isso que permite distinguir
"caiu no chão" de "bateu no teto" e "encostou na parede", coisa que
`rect.colliderect()` sozinho não diz.

Sobreposição e ordem de atualização, para o movimento não ser aplicado duas
vezes no mesmo quadro:

    1. o objeto declara a INTENÇÃO (controles/teclado definem a velocidade);
    2. o mundo aplica gravidade e acceleration;
    3. o mundo move em X e resolve contatos horizontais;
    4. o mundo move em Y e resolve contatos verticais;
    5. os estados (`grounded`, velocidades) são atualizados;
    6. os objetos são notificados.

A cena cuida apenas do passo 1, chamando `update()` antes do `world.update()`.
"""

import math

import pygame

from ..objects.GameObject import GameObject
from ..platforms.Platform import Platform
from ..utils.GameLogger import LOGGER
from .Collision import Collision, ContactState, Direction

#: Gravidade padrão, em pixels por SEGUNDO ao quadrado.
DEFAULT_GRAVITY = 1800.0

#: Velocidade máxima de queda, em pixels por segundo. Evita que o objeto
#: atravesse uma plataforma fina quando cai rápido.
DEFAULT_MAX_FALL_SPEED = 900.0

#: Deslocamento, em pixels, acima do qual uma resolução de colisão é
#: considerada um salto suspeito e vira aviso no log. Uma aterrissagem normal
#: move poucos pixels; valores grandes indicam atravessamento ou ejeção.
TELEPORT_THRESHOLD = 8.0

#: Folga, em pixels, para considerar que um objeto está APOIADO sobre uma
#: superfície. Absorve o arredondamento entre a posição em ponto flutuante e
#: o retângulo inteiro usado na colisão.
RIDE_TOLERANCE = 2.0

#: Folga MAIOR usada só para manter a "pegada" no arrasto. Uma plataforma que
#: desce mais rápido do que a gravidade consegue colar o objeto deixa uma
#: separação de poucos pixels; sem esta tolerância maior, o objeto perderia o
#: apoio quadro a quadro e ficaria para trás.
RIDE_HOLD_TOLERANCE = 6.0

#: Liga/desliga o sistema de pesos. Desligado, a simulação volta exatamente ao
#: comportamento anterior, o que serve para comparar e para depurar.
LOAD_ENABLED = True

#: Aceleração de cedência por unidade de "déficit de carga", em px/s².
LOAD_YIELD_ACCEL = 240.0

#: Teto da aceleração de cedência, para que um peso absurdo não lance o
#: objeto para fora da tela. Em px/s².
LOAD_YIELD_MAX = 1400.0

#: Velocidade de cedência por unidade de excesso de carga, para objetos SEM
#: gravidade. Em px/s.
LOAD_SAG_RATE = 90.0

#: Teto da velocidade de cedência, em px/s, pelo mesmo motivo do teto acima.
LOAD_SAG_MAX = 420.0

#: Liga/desliga o empurrão por peso.
PUSH_ENABLED = True

#: Velocidade máxima do empurrão, em px/s, contra um alvo quase do mesmo peso.
#: Contra um alvo mais pesado a velocidade cai (ver `push_force_against`), até
#: `PUSH_SPEED_HEAVY`.
PUSH_SPEED = 260.0

#: Velocidade do empurrão contra o alvo no limite de peso (3x mais pesado).
#: Bem menor que `PUSH_SPEED`: mover algo pesado exige tempo.
PUSH_SPEED_HEAVY = 70.0

#: Quanto o objeto que empurra também é empurrado para trás, como fração da
#: força aplicada ao alvo, e apenas quando ele não tem movimento próprio.
#: `0.0` deixa o pesado parado; valores altos transformam o encontro num choque.
PUSH_RECOIL = 0.25

#: Quantas vezes a resolução de contatos de um eixo repete antes de desistir.
#: Resolver uma superfície pode empurrar o objeto contra outra que já foi
#: tratada no mesmo passe, e vice-versa; um segundo passe desfaz isso. O teto
#: existe para o caso patológico de duas superfícies disputando o mesmo pixel.
CONTACT_PASSES = 3

#: Folga, em pixels, para considerar que dois objetos "se tocam" de lado. Precisa
#: ser maior que o deslocamento de um quadro de empurrão (≈4px a 260px/s), ou o
#: contato se perderia no quadro seguinte e o empurrão pararia sozinho.
PUSH_TOUCH_TOLERANCE = 6.0

#: Tempo, em segundos, que o empurrão leva para perder toda a força depois que os
#: dois se separam. Um alvo solto ainda escorrega um pouco e depois para: o
#: empurrão é um impulso com inércia própria, não uma velocidade permanente.
PUSH_COAST_TIME = 0.15


class PhysicsWorld:
    """Simula movimento e colisões dos objetos registrados."""

    def __init__(
        self,
        bounds=None,
        gravity=DEFAULT_GRAVITY,
        max_fall_speed=DEFAULT_MAX_FALL_SPEED,
        logger=None,
    ):
        self.logger = logger or LOGGER

        # Limites da simulação (normalmente o tamanho da janela).
        # Paredes e teto do cenário também são plataformas registradas,
        # mas `bounds` garante que ninguém saia da tela.
        self.bounds = bounds

        self.gravity = gravity
        self.max_fall_speed = max_fall_speed

        self.objects = []
        self.platforms = []

        self._contacts = {}  # id(objeto) -> {id(superfície): ContactState}

        # Pares (base, rider) que JÁ foram elevados neste quadro, por
        # `_push_rider`. Existe porque elevar um rider resolve contatos, o que
        # pode chamar `_push_rider` de novo para o par vizinho: numa pilha de
        # três, A empurra B empurra C empurra A, e isso não termina.
        self._lifted_pairs = set()

    # ------------------------------------------------------------------
    # Registro
    # ------------------------------------------------------------------
    def add_object(self, obj):
        """Registra um GameObject na simulação."""
        if obj not in self.objects:
            self.objects.append(obj)
            # O objeto passa a poder consultar as superfícies do mundo.
            obj.world = self
            self.logger.debug(
                "fisica",
                f"objeto registrado: {type(obj).__name__} "
                f"em ({obj.position.x:.0f}, {obj.position.y:.0f}) "
                f"gravidade={obj.gravity_enabled}",
            )
        return obj

    def add_platform(self, platform):
        """Registra uma Platform como superfície de colisão."""
        if platform not in self.platforms:
            self.platforms.append(platform)
        return platform

    def remove_object(self, obj):
        """Remove um objeto da simulação e encerra seus contatos em aberto."""
        if obj in self.objects:
            self.objects.remove(obj)
            self._contacts.pop(id(obj), None)

    def remove_platform(self, platform):
        if platform in self.platforms:
            self.platforms.remove(platform)

    def get_surfaces(self, exclude=None):
        """Todas as superfícies: plataformas e objetos sólidos.

        `exclude` normalmente é o próprio objeto em simulação: um objeto
        sólido se sobrepõe a si mesmo, e tratá-lo como superfície o empurraria
        para fora da tela a cada quadro.
        """
        surfaces = list(self.platforms)
        surfaces.extend(
            obj for obj in self.objects if obj.solid and obj is not exclude
        )
        return surfaces

    # ------------------------------------------------------------------
    # Simulação
    # ------------------------------------------------------------------
    def update(self, dt):
        """Avança a simulação em `dt` segundos."""
        active = [obj for obj in self.objects if obj.active]

        # Cada par (base, rider) pode ser elevado uma vez so neste quadro.
        self._lifted_pairs = set()
        # Quanto o arrasto de plataforma entregou ate aqui neste quadro.
        self._delivered_at_frame_start = {}

        # Conjunto de superfícies que ja foram carregadas neste quadro,
        # para evitar recursão infinita no arraste.
        self._carried_this_frame = set()

        # 0. Marca onde cada objeto estava no início do quadro. A diferença para a
        #    posição final é o quanto ele andou, e é isso que faz um objeto
        #    carregar quem está em cima dele, do mesmo jeito que uma plataforma.
        for obj in active:
            obj.begin_frame()
            obj.carry_offset.update(0, 0)
            obj._pushing = set()
            obj._carried_this_frame = False
            # Flags do arrasto vertical: valem SÓ neste quadro. Sem limpá-las
            # aqui elas ficavam grudentas para sempre depois do primeiro toque
            # na plataforma: a gravidade parava de ser aplicada e a velocidade
            # da plataforma continuava empurrando o objeto para cima, fora do
            # elevador, quadro após quadro.
            obj._carried_by_platform = False
            obj._carried_up = False

        # 0b. Plataformas móveis andam ANTES dos objetos, mas antes salvamos
        #     suas posições antigas para poder carregar quem estava em cima.
        old_platform_positions = {}
        for platform in self.platforms:
            old_platform_positions[id(platform)] = platform.rect.copy()
            platform.update(dt)

        # 1. Arrasta quem está apoiado em plataformas móveis. Vem ANTES da
        #     integração de gravidade, para que objetos em plataformas que sobem
        #     não caiam antes de serem carregados.
        self._apply_platform_carry(active, dt, old_platform_positions)

        # 2. Empurrão por peso. Vem ANTES da integração porque desloca o alvo
        #     por `_shift_object`, e o passo seguinte já encontra a posição
        #     final do empurrão para resolver os contatos em cima dela.
        pushing = self._apply_weight_push(active, dt)

        # O `_pushing` so vale durante o proprio empurrao, mas guardamos quem
        # foi empurrado para que o movimento normal possa CARREGAR o alvo
        # junto (em vez de bater nele e ter a velocidade zerada).
        pushed_this_frame = {oid: set(targets) for oid, targets in pushing.items()}
        for obj in active:
            obj._pushing = set()
            obj._was_pushing = pushed_this_frame.get(id(obj), set())

        # 1b. Integracao da velocidade: gravidade e aceleracao propria.
        #     Passa old_platform_positions para que _integrate_velocity possa
        #     verificar se o objeto esta em uma plataforma que subiu neste quadro.
        for obj in active:
            self._integrate_velocity(obj, dt, old_platform_positions)

        # 2. Movimento por eixos, com resolução imediata de cada contato.
        #
        # A pilha que cede é processada de uma vez só (ver `_fall_with_stack`),
        # para que objetos empilhados caiam juntos. Se cada um caísse por
        # conta própria, o de baixo ganharia aceleração de peso e passaria à
        # frente do de cima, rompendo a pilha no ar.
        falling = self._fall_with_stack(active)

        for obj in active:
            if not obj.movement_enabled:
                continue
            if id(obj) in falling:
                continue
            # No eixo X o movimento normal SEMPRE vale: é o que faz o player
            # andar sobre uma plataforma móvel (o arraste é só deslocamento e
            # não pode engolir o input).
            self._move_x(obj, dt)

            # `_move_y` SEMPRE roda.
            #
            # Quem foi arrastado pela plataforma recebeu o deslocamento dela
            # como posição, não como velocidade. Pular o movimento vertical
            # inteiro impedia o player de pular de uma plataforma móvel — a
            # velocidade do pulo existia, mas nada a aplicava.
            #
            # A gravidade é que não se aplica nesse quadro (`_integrate_velocity`
            # vê `_carried_by_platform`), então o objeto não afunda enquanto
            # acompanha a plataforma, e quem tem velocidade própria (pulo,
            # peso sob carga) continua se movendo normalmente.
            self._move_y(obj, dt)

            # Reapoio: quem foi arrastado por uma plataforma pode ter ficado
            # PENETRADO nela (a plataforma subiu por baixo e o objeto ficou
            # dentro). `_move_y` só resolve contatos quando há movimento, e
            # aqui a velocidade é zero — o objeto ficava congelado dentro da
            # plataforma, invisível mas presente, atravessando o resto da cena.
            if getattr(obj, "_carried_by_platform", False):
                self._realign_to_support(obj)

        # Os que caem em pilha são movidos depois dos demais, em bloco.
        for group in falling.values():
            self._move_falling_stack(group, dt)

        # 3. Atualiza o estado de colisão e notifica os objetos.
        for obj in active:
            self._update_contacts(obj)

        # 3b. Calcula a carga que cada objeto recebe de quem está em cima.
        #     Vem depois dos contatos (as relações de apoio estão frescas) e
        #     ANTES do arrasto e do `update`, para que ambos vejam a carga do
        #     quadro. É feito uma única vez por quadro.
        self._update_loads(active)

        # 4. Arrasta a PILHA de objetos. Vem DEPOIS do movimento para não
        #     contar o mesmo deslocamento duas vezes.
        self._apply_carry(active, dt)

        # 4b. Quem foi arrastado AGORA (neste quadro) fica marcado para o
        #      próximo. Sem isto a pilha se desfaz: o objeto de baixo subia
        #      com a plataforma e o de cima, não sendo arrastado no mesmo
        #      instante, caía e os dois se separavam.

        # 5. Permite que objetos que precisam de tempo ajustem o próprio estado
        #    depois da física (a cena e os controles já atuam antes disto).
        for obj in active:
            obj.update(dt)

    def _update_loads(self, active):
        """Calcula a carga que cada objeto recebe e aplica os modificadores.

        Carga transmitida
        -----------------
        Um objeto carrega o próprio peso e, em cima disso, tudo o que está
        apoiado nele. A cadeia é resolvida de cima para baixo: um objeto com
        peso 2 em cima de um com peso 3 faz o de baixo receber carga 2.

        Só contam como apoio real as relações detectadas por `_find_support`,
        que exige sobreposição horizontal E a base encostada no topo da
        superfície. Uma sobreposição puramente lateral não cria carga.

        Plataformas não transmitem carga: elas são superfícies, não parte da
        pilha de objetos. E objetos inativos não pesam sobre ninguém.

        O cálculo é feito uma única vez por quadro, do topo para o chão, o que
        torna a soma consistente e evita contagem repetida.
        """
        if not LOAD_ENABLED:
            return

        # Mapa: id do objeto -> objeto que ele NÃO empurra, ou seja, quem ele
        # empurra. `dependents[id(surface)]` = objetos apoiados em `surface`.
        dependents = {}

        for obj in active:
            support = self._find_support(obj)

            # Só transmite carga quando o apoio é outro OBJETO.
            # Plataforma é superfície: nada é transmitido através dela.
            if (
                isinstance(support, GameObject)
                and support.active
                and support is not obj
            ):
                dependents.setdefault(id(support), []).append(obj)

            obj._load_support = support

        # Processa do mais ALTO para o mais baixo: quando se chega num objeto, todos
        # os que estão em cima dele já têm a carga total calculada.
        #
        # No Pygame, Y MENOR é mais alto. Quem sustenta está sempre com o topo
        # ABAIXO (`rect.top` maior) do objeto que apoia, então ordenar por
        # `rect.top` CRESCENTE processa primeiro o topo da pilha. É uma ordem
        # topológica válida e, por construction, não há como formar ciclo.
        order = sorted(active, key=lambda o: o.rect.top)

        total_loads = {}

        for obj in order:
            above = dependents.get(id(obj), ())
            received = sum(
                total_loads.get(id(other), 0.0)
                for other in above
                if other is not obj
            )
            total_loads[id(obj)] = obj.weight + received

        # Aplica a carga e dispara `on_load_changed` / `on_support_changed`.
        for obj in active:
            received = sum(
                total_loads.get(id(other), 0.0)
                for other in dependents.get(id(obj), ())
                if other is not obj
            )
            obj._apply_load(received, obj._load_support)

        # Guardado para o integrador de movimento e para consultas.
        self._total_loads = total_loads

    def _apply_load_motion(self, active, dt):
        """Aplica os efeitos do peso no movimento vertical.

        Chamado UMA vez por quadro, dentro de `_integrate_velocity`, para que
        a mesma carga não seja aplicada duas vezes (uma no movimento e outra no
        arrasto).
        """
        for obj in active:
            effect = self._weight_effect(obj)
            if effect == (0.0, 0.0):
                continue

            # Em Y do Pygame, positivo é para BAIXO: ceder é descer.
            obj.velocity.y += effect * dt

    def _weight_effect(self, obj):
        """Aceleração vertical extra caused pela carga, em px/s².

        A fórmula é a mesma da enunciada para o salto, aplicada à queda:

            load_ratio = supported_load / weight
            deficit    = max(0.0, load_ratio - 1.0)
            efeito     = deficit * influence * LOAD_YIELD_ACCEL

        Sem carga (`deficit == 0`) o efeito é zero e o objeto se comporta
        exatamente como antes do sistema de pesos.
        """
        if obj.weight_influence <= 0.0:
            return 0.0

        load_ratio = obj.get_load_ratio()
        if load_ratio <= 1.0:
            # Carga igual ou abaixo do peso: nenhuma cedência extra.
            return 0.0

        deficit = load_ratio - 1.0
        return min(deficit * obj.weight_influence * LOAD_YIELD_ACCEL, LOAD_YIELD_MAX)

    # 5. Permite que objetos que precisam de tempo ajustem o próprio estado
        #    depois da física (a cena e os controles já atuam antes disto).
        for obj in active:
            obj.update(dt)

    def _apply_platform_carry(self, active, dt, old_platform_positions):
        """Move objetos que estavam sobre plataformas móveis ANTES da gravidade.

        Isso evita que objetos em plataformas que sobem caiam antes de serem
        carregados. So plataformas com `can_carry=True` arrastam objetos.

        Usa as posicoes antigas das plataformas (antes do update) para
        determinar quem estava em cima, ja que as plataformas ja se moveram.
        """
        if not self.platforms:
            return

        # Quanto cada plataforma ja entregou neste quadro.
        delivered = {id(p): pygame.Vector2(0, 0) for p in self.platforms}
        self._delivered_at_frame_start = delivered

        # Processa do mais baixo para o mais alto (ordem topologica).
        # No Pygame, Y menor = mais alto.
        remaining = {id(obj): obj for obj in active}

        while remaining:
            # O mais baixo ainda nao processado.
            obj = min(remaining.values(), key=lambda o: o.rect.bottom)
            remaining.pop(id(obj))

            # So considera plataformas como apoio, usando posicoes ANTIGAS.
            support = self._find_platform_support(obj, old_platform_positions)
            if support is None or not support.can_carry:
                continue

            # O deslocamento da plataforma e a diferenca entre posicao atual e antiga.
            old_rect = old_platform_positions[id(support)]
            support_offset = pygame.Vector2(
                support.rect.x - old_rect.x,
                support.rect.y - old_rect.y
            )

            if support_offset == (0, 0):
                continue

            # Calcula o deslocamento que o objeto deve receber.
            offset = self._ride_offset_for(obj, support, support_offset)
            if offset == (0, 0):
                continue

            before = obj.position.copy()
            obj.riding = support
            # `grounded` NÃO é marcado aqui de propósito.
            #
            # Marcar fazia o objeto ficar "no chão" para sempre: assim que ele
            # deixava de encostar na plataforma, o carry continuava sustentando
            # um flag velho, a gravidade não era aplicada e a pilha ficava
            # congelada no ar. Quem decide se está no chão é o contato real,
            # em `_update_contacts`.
            #
            # `_carried_by_platform` é o flag deste quadro (a gravidade já foi
            #integrada), e `_carried_this_frame` evita o movimento vertical em
            # duplicata. Ambos são limpos no início de cada quadro.
            obj._carried_this_frame = True
            obj._carried_by_platform = True
            self._shift_object(obj, offset)
            delivered[id(support)] = delivered[id(support)] + support_offset

            if obj.position != before:
                for other in self._riders_of(obj):
                    remaining.setdefault(id(other), other)

    def _realign_to_support(self, obj):
        """Devolve o objeto para cima da superfície que o sustenta.

        Usado quando o objeto é arrastado por uma plataforma e pode ter ficado
        penetrado nela: sem velocidade não há movimento que dispare a
        resolução de contatos, então o ajuste é feito direto.
        """
        support = self._find_support(obj)
        if support is None:
            return

        gap = obj.rect.bottom - support.rect.top
        if gap >= 0:
            # Está apoiado (ou acima): nada a fazer.
            return

        # Só reposiciona se o objeto NÃO estiver subindo por conta própria.
        # Com pulo em curso (vy < 0), ele está deixando a plataforma; puxá-lo
        # de volta para baixo apagaria a velocidade do pulo e ele nunca sairia.
        if obj.velocity.y < 0.0:
            return

        # Penetrado: sobe só o necessário para encostar por cima, sem passar
        # do limite da tolerância de contato.
        correction = -min(gap, RIDE_HOLD_TOLERANCE)
        self._shift_axis(obj, "y", correction, ignore={support})

    def _find_platform_support(self, obj, old_platform_positions=None):
        """Encontra a plataforma (se houver) que apoia `obj` pela geometria atual.

        So considera plataformas, nao objetos. Se `old_platform_positions` for
        fornecido, usa as posicoes antigas das plataformas (antes do movimento
        deste quadro) para determinar o apoio.
        """
        best = None
        best_gap = RIDE_HOLD_TOLERANCE

        for surface in self.platforms:
            if not surface.solid:
                continue

            obj_rect = obj.rect
            if old_platform_positions is not None:
                surface_rect = old_platform_positions[id(surface)]
            else:
                surface_rect = surface.rect

            horizontal_overlap = min(obj_rect.right, surface_rect.right) - max(
                obj_rect.left, surface_rect.left
            )
            if horizontal_overlap <= 0:
                continue

            gap = obj_rect.bottom - surface_rect.top
            # Aceita `gap` NEGATIVO de leve: quando a plataforma sobe, o objeto
            # fica alguns pixels ACIMA dela. Exigir `gap >= 0` fazia o apoio se
            # perder no primeiro quadro de descasamento, e o objeto nunca mais
            # voltava a ser arrastado -- subia cada vez mais para longe.
            if -RIDE_HOLD_TOLERANCE <= gap <= best_gap:
                best = surface
                best_gap = gap

        return best if best_gap <= RIDE_HOLD_TOLERANCE else None

    def _apply_carry(self, active, dt=0.0):
        """Move junto quem está apoiado em uma superfície que se deslocou.

        A propagação é iterativa e vai do CHÃO PARA O TOPO da pilha: quando um
        objeto é arrastado, ele passa a carregar quem está em cima dele, no
        mesmo quadro.

        O quanto se propaga a cada passo é o que a superfície andou DESDE O
        ÚLTIMO PASSO, e não desde o início do quadro. Medir desde o início
        somaria a mesma distância várias vezes numa pilha: o de baixo andou
        1px, o do meio foi arrastado 1px (já 2px desde o início do quadro), e
        o de cima receberia 2px em vez de 1px.

        Cada deslocamento passa pela mesma resolução de colisões do resto da
        simulação: quem é arrastado para dentro de uma parede é barrado pela
        parede, em vez de atravessar.
        """
        # Quanto cada superfície JÁ entregou neste quadro, para propagar apenas
        # a diferença e nunca repetir a mesma distância.
        # Quanto cada superfície JÁ entregou. O arrasto de plataforma, no
        # início do quadro, consumiu parte disso: sem inicializar daqui, a
        # mesma distância seria aplicada duas vezes e o objeto subia rápido
        # demais, se soltando da plataforma.
        delivered = self._delivered_at_frame_start

        remaining = {id(obj): obj for obj in active}

        while remaining:
            # O mais baixo ainda não processado: a propagação sobe na ordem.
            obj = min(remaining.values(), key=lambda o: o.rect.bottom)
            remaining.pop(id(obj))

            support = self._find_support(obj)
            if support is None:
                continue

            total = support.get_ride_offset()
            already = delivered.get(id(support), pygame.Vector2(0, 0))
            support_offset = total - already

            if support_offset == (0, 0):
                continue

            offset = self._ride_offset_for(obj, support, support_offset)
            if offset == (0, 0):
                continue

            before = obj.position.copy()
            # Define riding ANTES do deslocamento, para que o pre-check
            # de colisao no _shift_axis saiba qual superficie ignorar.
            obj.riding = support
            # Mesmo contrato do arrasto de plataforma: a gravidade deste
            # quadro já foi integrada, então marcar aqui só vale para o
            # próximo quadro — e para propagar ao objeto que estiver em cima.
            obj._carried_by_platform = True
            self._shift_object(obj, offset)
            # O arraste é SÓ deslocamento. A velocidade do objeto não é tocada.
            #
            # Injetar aqui a velocidade da suporte era o que impedia o player de
            # andar numa plataforma móvel: o `Player.update` escreve a
            # velocidade a cada quadro, e o arrasto sobrescrevia logo depois.
            # Além disso a velocidade vazava ao soltar a plataforma, e o objeto
            # saía voando. Quem precisa de graça é a PLATAFORMA de apoio, e
            # isso é resolvido em `_carried_by_platform`, que suspende a
            # gravidade enquanto o arrasto está valendo.
            delivered[id(support)] = already + support_offset

            # Este objeto se moveu, então passa a carregar quem está em cima
            # dele. Reinsere esses na fila para a propagação subir pela pilha
            # dentro do mesmo quadro.
            if obj.position != before:
                for other in self._riders_of(obj):
                    remaining.setdefault(id(other), other)
    def _find_support(self, obj):
        """Superfície em que `obj` está apoiado, pela geometria do momento.

        Usado pelo arrasto porque os retângulos mudam durante a propagação: o
        `riding` gravado no início do quadro aponta para a posição antiga da
        superfície, e uma pilha se desfaria nesse meio-tempo.
        """
        best = None
        best_gap = RIDE_HOLD_TOLERANCE

        for surface in self.get_surfaces(exclude=obj):
            if not surface.solid:
                continue

            obj_rect = obj.rect
            surface_rect = surface.rect

            # Precisa de sobreposição horizontal para estar "em cima".
            horizontal_overlap = min(obj_rect.right, surface_rect.right) - max(
                obj_rect.left, surface_rect.left
            )
            if horizontal_overlap <= 0:
                continue

            # Distância entre a base do objeto e o topo da superfície. Perto de
            # zero significa que o objeto está apoiado; negativa, que penetrou.
            gap = abs(obj_rect.bottom - surface_rect.top)
            if gap <= best_gap:
                best_gap = gap
                best = surface

        return best

    def _ride_offset_for(self, obj, support, support_offset):
        """Filtra o deslocamento da superfície para o que vale para `obj`.

        Só é arrastado o eixo em que `obj` está de fato apoiado sobre a
        superfície:
          - apoiado em cima -> acompanha o eixo X e o Y da plataforma, porque
            tanto andar de lado quanto subir precisa ser acompanhado;
          - encostado na lateral -> acompanha apenas o X, para que uma
            plataforma que desce não empurre para baixo um objeto que apenas
            encostou de lado.

        A verificação usa os RETÂNGULOS diretamente, e não o estado de
        contato do quadro. Durante o arrasto as sobreposições mudam, e o
        estado de contato oscila entre `None` e a superfície, o que faria a
        pilha perder a ligação num quadro e se desfazer.
        """
        offset = pygame.Vector2(0, 0)

        obj_rect = obj.rect
        support_rect = support.rect

        # Precisa ter sobreposição horizontal para estar "em cima".
        horizontal_overlap = min(obj_rect.right, support_rect.right) - max(
            obj_rect.left, support_rect.left
        )
        if horizontal_overlap <= 0:
            return (0, 0)

        # Distância entre a base do objeto e o topo da superfície.
        # Negativo ou perto de zero significa apoiado; positivo é o objeto
        # acima da superfície (havendo colisão vertical).
        gap = obj_rect.bottom - support_rect.top

        if gap <= RIDE_HOLD_TOLERANCE:
            # APOIADO em cima (ou dentro dela, por poucos pixels): acompanha
            # os dois eixos.
            offset.update(support_offset.x, support_offset.y)
        else:
            # Só encostou de lado ou pelo teto: acompanha apenas o X.
            offset.x = support_offset.x

        return offset

    def _shift_object(self, obj, offset, ignore=None):
        """Desloca o objeto aplicando a mesma resolução de colisão do resto.

        O deslocamento vem por eixos, então um objeto arrastado contra uma
        parede para de ser arrastado no eixo X, mas continua no Y.

        `ignore` são superfícies que não devem travar este deslocamento. O
        empurrão usa isso para o alvo NÃO enxergar o próprio empurrador como
        parede: os dois estão encostados por definição, e sem a exceção o alvo
        seria barrado no primeiro pixel e o empurrão morria ali mesmo.

        Devolve True se o movimento no eixo X foi bloqueado por uma parede.
        """
        if offset.x:
            if self._shift_axis(obj, "x", offset.x, ignore=ignore):
                # Bloqueado no X: zera o restante e avisa para matar o push_speed.
                offset.x = 0
                return True
        if offset.y:
            self._shift_axis(obj, "y", offset.y, ignore=ignore)
        return False

    def _shift_axis(self, obj, axis, distance, ignore=None):
        """Desloca em um eixo com verificação de colisão, sem usar velocidade.

        A verificação ignora a superfície de apoio. Sem isso, um objeto que
        estava levemente penetrado nela (porque ela subiu em direção a ele)
        seria devolvido à posição anterior pela colisão, e o arrasto não
        aconteceria.

        Também ignora quem está apoiado NESTE objeto: essa pilha será arrastada
        logo em seguida, e tratá-la como obstáculo agora faria os dois se
        empurrarem em sentidos opostos, sem a pilha andar.

        `ignore` substitui esse conjunto quando é informado, e é usado pela
        pilha em queda livre, que se move como um bloco.
        """
        if distance == 0:
            return

        if ignore is None:
            ignore = {obj.riding} if obj.riding is not None else set()
            ignore.update(self._riders_of(obj))
        elif not isinstance(ignore, set):
            ignore = {ignore}

        steps = self._substeps_for(obj, axis, abs(distance))
        step = distance / steps
        forward = step > 0
        blocked = False

        # Sem pre-check geométrico: `_resolve_axis_contacts` (chamado logo
        # abaixo, já com o objeto movido) decide o que é bloqueio, e ele usa o
        # SENTIDO do deslocamento. Um teste "já está encostado?" feito antes de
        # mover via o apoio como obstáculo, e o objeto arrastado por uma
        # plataforma que sobe nunca saía do lugar.
        # Só no empurrão. O arrasto (plataforma/objeto carregando outro) NÃO
        # usa pre-check: o apoio é justamente a superfície contra a qual o
        # objeto está encostado, e testá-lo travava o arraste. Já no empurrão o
        # objeto se move por `push_speed` contra um alvo, e o pre-check evita
        # que ele entre na parede por mais um quadro antes de ser resolvido.
        # `_carried_by_platform` marca quem está sendo ARRASTADO por uma
        # plataforma; o empurrão não marca. Quem não é arrastado usa o
        # pre-check, que o segura antes de entrar na parede.
        usar_pre_check = not getattr(obj, "_carried_by_platform", False)

        for _ in range(steps):
            if usar_pre_check:
                test_rect = obj.rect.copy()
                setattr(test_rect, axis, getattr(test_rect, axis) + (1 if step > 0 else -1))
                for surface in self.get_surfaces(exclude=obj):
                    if surface is None or not surface.solid:
                        continue
                    if surface in ignore:
                        continue
                    if surface is getattr(obj, "riding", None):
                        continue
                    if self._is_touching_rect(test_rect, surface.rect):
                        blocked = True
                        break
            if blocked:
                break

            current = getattr(obj.position, axis)
            setattr(obj.position, axis, current + step)
            obj._sync_rect()

            before = getattr(obj.position, axis)
            self._resolve_axis_contacts(obj, axis, ignore=ignore, motion=step)

            after = getattr(obj.position, axis)
            moved = after - current
            if forward and moved < 0:
                blocked = True
                break
            if not forward and moved > 0:
                blocked = True
                break

        return blocked

    def _riders_of(self, obj):
        """Objetos apoiados direta ou indiretamente em `obj`.

        A detecção é geométrica (base encostando no topo com sobreposição
        horizontal) e não usa `riding`, que oscila durante o próprio arrasto.
        """
        riders = set()
        pending = [obj]

        while pending:
            current = pending.pop()

            for other in self.objects:
                if other is current or other in riders:
                    continue
                if not other.active:
                    continue

                rests_on_top = abs(other.rect.bottom - current.rect.top) <= RIDE_HOLD_TOLERANCE
                if not rests_on_top:
                    continue
                if self._horizontal_overlap(other.rect, current.rect) <= 0:
                    continue

                riders.add(other)
                pending.append(other)

        return riders

    @staticmethod
    def _horizontal_overlap(rect_a, rect_b):
        """Quanto dois retângulos se sobrepõem no eixo horizontal."""
        return min(rect_a.right, rect_b.right) - max(rect_a.left, rect_b.left)

    @staticmethod
    def _vertical_overlap(rect_a, rect_b):
        """Quanto dois retângulos se sobrepõem no eixo vertical."""
        return min(rect_a.bottom, rect_b.bottom) - max(rect_a.top, rect_b.top)

    def _fall_with_stack(self, active):
        """Agrupa as pilhas que estão caindo livres, sem apoio embaixo.

        O problema
        ----------
        Uma pilha em queda livre não pode ser simulada objeto por objeto. O de
        baixo recebe a carga de cima, ganha aceleração extra e passa à frente
        do de cima; a pilha se rompe e a caixa de cima fica parada no ar.

        A solução
        ----------
        Quando não há nada embaixo (a pilha está no ar), toda a pilha recebe a
        MESMA aceleração vertical: a do objeto mais carregado. É o que a física
        daria se eles estivessem presos, e evita que se separem.

        Pilhas com apoio embaixo (no chão ou numa plataforma) NÃO entram aqui:
        elas já são resolvidas pela gravidade normal e pelo arrasto, e mexer
        nelas seria duplicar movimento.

        Devolve `{id_do_objeto_base: [objetos_de_cima_para_baixo]}`.
        """
        groups = {}
        done = set()

        # Do mais baixo para o mais alto, para montar as pilhas de baixo para
        # cima. No Pygame, Y maior é mais baixo.
        for obj in sorted(active, key=lambda o: o.rect.top, reverse=True):
            if id(obj) in done:
                continue

            support = self._find_support(obj)
            if support is not None:
                # Tem apoio: não é queda livre.
                continue

            # Só objetos com gravidade formam pilha de queda livre. Um objeto
            # sem gravidade tem cedência própria (`vertical_resistance`) e não
            # deve receber a aceleração da pilha alheia.
            if not obj.gravity_enabled:
                continue

            # Sobe a pilha enquanto houver objeto encostado em cima.
            stack = [obj]
            done.add(id(obj))

            current = obj
            while True:
                riders = [
                    other
                    for other in active
                    if id(other) not in done
                    and other.active
                    and other.movement_enabled
                    # Só objetos COM gravidade entram na pilha de queda livre.
                    # Um objeto sem gravidade tem cedência própria, definida por
                    # `vertical_resistance`; colocá-lo aqui o faria receber
                    # gravidade e descer mesmo com resistência alta.
                    and other.gravity_enabled
                    and abs(other.rect.bottom - current.rect.top)
                    <= RIDE_HOLD_TOLERANCE
                    and self._horizontal_overlap(other.rect, current.rect) > 0
                ]
                if not riders:
                    break
                # O mais baixo entre os que se apoiam aqui vira o próximo elo.
                riders.sort(key=lambda o: o.rect.bottom, reverse=True)
                current = riders[0]
                stack.append(current)
                done.add(id(current))

            if len(stack) > 1:
                # `stack[0]` é a BASE (montada de baixo para cima), e é
                # ela que move o bloco em `_move_falling_stack`.
                groups[id(stack[0])] = stack

        return groups

    def _move_falling_stack(self, stack, dt):
        """Move uma pilha em queda livre como um bloco só.

        A aceleração vertical é a do objeto mais carregado da pilha (o de
        baixo recebe toda a carga). Todos os membros recebem o mesmo delta, e
        depois cada um passa pela resolução de colisões normal, então a pilha
        continua obedecendo tetos e paredes.
        """
        # Deslocamento vertical do bloco.
        #
        # A pilha é movida como um corpo rígido: primeiro a BASE se desloca,
        # e depois cada objeto acima é COLADO de volta nela, calcando o quanto
        # foi preciso. Assim o contato nunca se rompe, por mais rápido que o
        # bloco esteja caindo — o que uma detecção puramente geométrica não
        # conseguiria garantir, já que o deslocamento por quadro passa da
        # tolerância de contato em queda rápida.
        base = stack[0]

        # Aceleração do objeto mais carregado da pilha inteira.
        strongest = max(stack, key=lambda o: o.get_load_ratio())
        extra = self._weight_effect(strongest) if LOAD_ENABLED else 0.0

        total_vy = max(self.gravity * o.gravity_scale for o in stack) + extra
        delta = total_vy * dt

        if not base.movement_enabled:
            return

        # 1. A base desce o bloco inteiro.
        base_before = base.rect.top
        self._shift_axis(base, "y", delta, ignore=set(stack))
        moved = base.rect.top - base_before

        if moved == 0:
            return

        # 2. Cada objeto acima é reposicionado sobre quem sustenta, mantendo o
        #    deslocamento real da base (que pode ter sido bloqueado por um teto).
        for obj in stack[1:]:
            if not obj.movement_enabled:
                continue

            support = stack[stack.index(obj) - 1]
            target_top = support.rect.top - obj.rect.height

            correction = target_top - obj.rect.top
            if correction:
                self._shift_axis(obj, "y", correction, ignore=set(stack))

    def _apply_weight_push(self, active, dt):
        """Empurra objetos por peso: o mais pesado move o mais leve.

        Roda uma vez por quadro, antes do movimento. O resultado vira
        `push_speed` de cada objeto, uma velocidade **derivada**, e o
        deslocamento é feito por `_shift_object` -- o mesmo caminho de resolver
        colisao que o movimento normal usa. Por isso o objeto empurrado
        respeita paredes, tetos e plataformas: ele nunca atravessa nada.

        Inercia curta, nao velocidade permanente
        ---------------------------------------
        `push_speed` NAO entra na `velocity` do objeto. Isso e deliberado:

        - `velocity` e o movimento proprio e persiste entre quadros. Somar o
          empurrao nela a cada quadro faria acelerar sem limite
          (190 -> 570 -> 1140 -> 2850), e o objeto nunca mais pararia.
        - Em vez disso, `push_speed` e **substituida** a cada quadro pelo
          empurrao atual. Enquanto ha contato, vale a velocidade de empurrao.
          Quando o contato acaba, decai exponencialmente ate zero em
          `PUSH_COAST_TIME`: o alvo solto ainda escorrega um pouco e para.

        Regra
        -----
        Dois objetos solidos encostados lateralmente se empurram quando um e
        mais pesado que o outro, dentro da janela de `GameObject.can_push()`
        (1.2x a 3x). A velocidade cai conforme o alvo pesa mais: empurrar algo
        quase igual e rapido, empurrar algo 3x mais pesado e lento.

        Empates nao se empurram, e acima de 3x o alvo e pesado demais e barra o
        empurrador. `pushable=False` desliga a interacao.
        """
        if not PUSH_ENABLED:
            return

        # Velocidade de empurrao por objeto (o sinal e a direcao) e registro de
        # quem empurra quem, para a colisao saber quem nao bloqueia quem.
        speeds = {id(obj): 0.0 for obj in active}
        pushing = {id(obj): set() for obj in active}

        for pusher in active:
            if not pusher.pushable or not pusher.movement_enabled:
                continue
            if not pusher.solid:
                continue

            for target in active:
                if target is pusher:
                    continue
                if not target.pushable or not target.movement_enabled:
                    continue
                if not target.solid:
                    continue

                # So encostados DE LADO: empurrar para cima ou para baixo ja
                # e assunto da gravidade e do arraste.
                if not self._push_axis_touches(pusher, target):
                    continue

                speed = pusher.push_speed_against(
                    target, PUSH_SPEED, PUSH_SPEED_HEAVY
                )
                if speed <= 0.0:
                    continue

                direction = self._push_direction(pusher, target)
                if direction is None:
                    continue

                # Verifica se o empurrador esta bloqueado por uma parede (ou outro solido
                # que nao seja o alvo) no sentido do empurrao. Se estiver,
                # nao ha forca para transmitir: o empurrador esta encostado no
                # obstaculo e nao pode empurrar o alvo para dentro dele.
                push_dir = 1.0 if direction > 0 else -1.0
                blocked_by_wall = False

                if push_dir > 0:
                    # Empurrao para a direita: verifica se ha solido a direita do empurrador
                    for s in self.get_surfaces(exclude=pusher):
                        if s is target or not s.solid:
                            continue
                        # So considera se esta encostado no lado direito
                        if abs(s.rect.left - pusher.rect.right) <= PUSH_TOUCH_TOLERANCE:
                            # Sobreposicao VERTICAL (alinhamento em Y)?
                            if self._vertical_overlap(pusher.rect, s.rect) > 0:
                                blocked_by_wall = True
                                break
                else:
                    # Empurrao para a esquerda: verifica lado esquerdo
                    for s in self.get_surfaces(exclude=pusher):
                        if s is target or not s.solid:
                            continue
                        if abs(pusher.rect.left - s.rect.right) <= PUSH_TOUCH_TOLERANCE:
                            if self._vertical_overlap(pusher.rect, s.rect) > 0:
                                blocked_by_wall = True
                                break

                if blocked_by_wall:
                    # Empurrador bloqueado: nao transmite forca ao alvo.
                    continue

                pushing[id(pusher)].add(id(target))

                # Varios empurroes no mesmo sentido somam; em sentidos opostos
                # fica o maior, para que um objeto segurado por dois lados nao
                # fique tremendo entre eles.
                candidate = direction * speed

                if abs(candidate) > abs(speeds[id(target)]):
                    speeds[id(target)] = candidate

                # Recuo: so quando o empurrador nao tem movimento proprio NA DIRECAO
                # DO EMPURRAO. Se o empurrador ja esta se movendo para o mesmo
                # lado que o empurrao, ele so empurra o alvo adiante -- nao e
                # jogado para tras, porque a forca vem do proprio movimento.
                # Se o empurrador esta parado ou se movendo pro lado oposto,
                # ai sim ha recuo (reacao).
                if abs(pusher.velocity.x) < 0.01 or (pusher.velocity.x * push_dir < 0):
                    recoil = -candidate * PUSH_RECOIL
                    if abs(recoil) > abs(speeds[id(pusher)]):
                        speeds[id(pusher)] = recoil

        # Quem empurra quem, para que o alvo possa ignorar o empurrador quando
        # for deslocado (eles estao encostados por definicao).
        pushed_by = {}
        for pusher_id, targets in pushing.items():
            for target_id in targets:
                pushed_by.setdefault(target_id, pusher_id)
        by_id = {id(o): o for o in active}

        # Fator de decaimento por quadro: o empurrao perde-se em
        # `PUSH_COAST_TIME` depois de perder o contato.
        decay = 0.0 if dt <= 0.0 else math.exp(-dt / PUSH_COAST_TIME)

        for obj in active:
            obj._pushing = pushing[id(obj)]

            speed = speeds[id(obj)]
            if speed != 0.0:
                # Em contato: o empurrao vale a velocidade calculada agora.
                # Zera antes de inverter, para uma troca de direcao nao dar um
                # solavanco desnecessario.
                if obj.push_speed * speed < 0.0:
                    obj.push_speed = 0.0
                obj.push_speed = speed
            else:
                # Solto: decai ate zero e nunca vira velocidade permanente.
                obj.push_speed *= decay
                if abs(obj.push_speed) < 0.5:
                    obj.push_speed = 0.0

            if obj.push_speed == 0.0:
                continue

            # Desloca pela MESMA rotina de movimento, entao o objeto empurrado
            # respeita paredes, tetos e plataformas como qualquer outro.
            #
            # Quem e empurrado Tambem anda por aqui. Antes este objeto era
            # pulado, com a promessa de que o empurrador o carregaria junto
            # pelo movimento normal -- mas essa carga nunca existiu. O
            # resultado era o empurrador entrar no alvo enquanto o alvo
            # ficava parado, a sobreposicao crescer e o contato se perder
            # (`_push_axis_touches`), matando o empurrao. Por isso o empurrao
            # so funcionava com varios toques seguidos.
            pusher = by_id.get(pushed_by.get(id(obj)))
            ignore = {pusher} if pusher is not None else None
            blocked = self._shift_object(
                obj, pygame.Vector2(obj.push_speed * dt, 0), ignore=ignore
            )
            if blocked:
                # Bateu na parede: o empurrao para imediatamente.
                obj.push_speed = 0.0

        return pushing

    @staticmethod
    def _push_axis_touches(a, b):
        """True se os dois retângulos se encostam no eixo X.

        Exige sobreposição vertical real: duas caixas uma em cima da outra não
        estão se empurrando de lado.
        """
        rect_a = a.rect
        rect_b = b.rect

        overlap_y = min(rect_a.bottom, rect_b.bottom) - max(
            rect_a.top, rect_b.top
        )
        if overlap_y <= 0:
            return False

        # Encostadas de lado: a sobreposição horizontal é zero ou pequena.
        overlap_x = min(rect_a.right, rect_b.right) - max(
            rect_a.left, rect_b.left
        )
        return abs(overlap_x) <= PUSH_TOUCH_TOLERANCE

    @staticmethod
    def _push_direction(pusher, target):
        """Sinal da direção em que `pusher` empurra `target`.

        `1.0` para a direita, `-1.0` para a esquerda, `None` se estiverem
        exatamente na mesma coluna (não há lado definido).
        """
        delta = target.position.x - pusher.position.x
        if delta == 0:
            return None
        return 1.0 if delta > 0 else -1.0

    def _integrate_velocity(self, obj, dt, old_platform_positions=None):
        """Aplica gravidade, peso e aceleração à velocidade."""
        if obj.gravity_enabled:
            # Repouso: um objeto apoiado e sem deslizar não precisa continuar
            # acumulando gravidade, senão ele avança meio pixel, é reposicionado
            # e repete o ciclo indefinidamente (micro-vibração de repouso).
            # Se ele sair da borda da plataforma, `grounded` vira False no fim do
            # quadro seguinte e a gravidade volta a valer normalmente.
            # Excecao: se o objeto esta sendo carregado por uma plataforma
            # (flag _carried_by_platform) ou esta em uma plataforma que subiu neste quadro,
            # ele nao deve acumular gravidade (a plataforma o sustenta).
            carried_by_platform = getattr(obj, "_carried_by_platform", False)
            carried_up = getattr(obj, "_carried_up", False)

            # O arraste vertical e do apoio. Se o objeto tem movimento PROPRIO
            # para cima (pulo), ele nao esta mais apoiado: suspender a
            # gravidade prenderia o player na plataforma, com a velocidade do
            # pulo zerada a cada quadro pela resolucao de contato, e ele nunca
            # sairia do lugar.
            if carried_by_platform and obj.velocity.y < 0.0:
                carried_by_platform = False
            if not carried_by_platform and not getattr(obj, "_carried_up", False) and obj.grounded:
                # Verifica se o objeto esta em uma plataforma que subiu neste quadro,
                # usando as posicoes antigas das plataformas.
                support = None
                if old_platform_positions is not None:
                    # Procura plataforma nas posicoes antigas
                    for platform in self.platforms:
                        if not platform.solid:
                            continue
                        old_rect = old_platform_positions.get(id(platform))
                        if old_rect is None:
                            continue
                        obj_rect = obj.rect
                        surface_rect = old_rect
                        horizontal_overlap = min(obj_rect.right, surface_rect.right) - max(
                            obj_rect.left, surface_rect.left
                        )
                        if horizontal_overlap <= 0:
                            continue
                        gap = obj_rect.bottom - surface_rect.top
                        if 0 <= gap <= RIDE_HOLD_TOLERANCE:
                            support = platform
                            break

                if support is None:
                    support = self._find_support(obj)

                if hasattr(support, "frame_motion") and support.frame_motion.y < 0:
                    carried_up = True

            resting = obj.grounded and obj.velocity.y >= 0 and obj.velocity.x == 0
            if not resting and not carried_up and not carried_by_platform:
                # Y positivo = para baixo, então somamos o valor da gravidade.
                obj.velocity.y += self.gravity * obj.gravity_scale * dt

        obj.velocity += obj.acceleration * dt

        

        # Efeito do peso: assim que a carga é calculada (passo 3b), ela entra
        # aqui UMA vez por quadro, e SOMENTE para objetos com gravidade.
        #
        # Objetos sem gravidade têm o seu próprio caminho de cedência, em
        # `_move_y` (`_sag_amount`), baseado em `vertical_resistance`. Aplicar
        # os dois deixaria um resíduo de velocidade que continuaria descendo
        # mesmo depois de a carga desaparecer.
        if LOAD_ENABLED and obj.gravity_enabled and obj.supported_load > 0.0:
            resting = obj.grounded and obj.velocity.y >= 0
            if not resting:
                yield_accel = self._weight_effect(obj)
                if yield_accel:
                    # Positivo = para baixo: carregar pesa e faz ceder.
                    obj.velocity.y += yield_accel * dt

        # Limita a queda para não atravessar plataformas finas.
        if obj.velocity.y > self.max_fall_speed:
            obj.velocity.y = self.max_fall_speed

    def _move_x(self, obj, dt):
        """Move no eixo X e resolve contatos laterais.

        O deslocamento é dividido em subpassos quando o objeto anda mais do
        que a sua própria largura em um quadro. Sem isso, um objeto rápido
        atravessa uma parede fina sem que nenhum quadro detecte a sobreposição.
        Esse é o mesmo mecanismo que permite plugar detecção contínua (CCD)
        no futuro: basta trocar este laço.
        """
        self._move_axis(obj, dt, "x")

    def _move_y(self, obj, dt):
        """Move no eixo Y e resolve contatos de teto e de aterrissagem."""
        self._move_axis(obj, dt, "y")

        # Cedência vertical por carga, para objetos SEM gravidade.
        #
        # A gravidade normal é a responsável por fazer as coisas caírem; um
        # objeto sem gravidade não deve ser convertido em "com gravidade" só
        # porque alguém em cima dele pesa. Em vez disso, ele recebe um
        # deslocamento vertical extra e limitado, calculado a partir do
        # EXCESSO de carga sobre a sua resistência.
        if LOAD_ENABLED and not obj.gravity_enabled:
            sag = self._sag_amount(obj)
            if sag:
                # `_shift_axis` é o mesmo caminho do arrasto: respeita
                # colisões, então um objeto que cede continua barrado por
                # paredes, tetos e plataformas.
                self._shift_axis(obj, "y", sag * dt)

    def _sag_amount(self, obj):
        """Velocidade de cedência vertical, em px/s, para objeto sem gravidade.

            excesso = supported_load - vertical_resistance
            sag     = excesso * influence * LOAD_SAG_RATE

        Devolve `0.0` quando a carga está dentro da resistência, o que
        preserva exatamente o comportamento sem gravidade de antes.
        """
        if not LOAD_ENABLED or obj.weight_influence <= 0.0:
            return 0.0

        excess = obj.supported_load - obj.vertical_resistance
        if excess <= 0.0:
            return 0.0

        sag = excess * obj.weight_influence * LOAD_SAG_RATE
        return min(sag, LOAD_SAG_MAX)

    def _move_axis(self, obj, dt, axis):
        """Aplica o deslocamento em um eixo, subdividido em passos seguros.

        `axis` é "x" ou "y". Cada subpasso move um pouco, verifica contatos
        e resolve o que for preciso, o que impede que o objeto "pule" por
        cima de uma superfície.
        """
        # Se o objeto esta empurrando alvos, sua velocidade maxima e o
        # push_speed do alvo mais lento.
        #
        # O alvo e movido pelo PROPRIO empurrao (`_apply_weight_push`), e nao
        # pelo movimento do empurrador. Se o empurrador andasse mais rapido,
        # entraria dentro do alvo, a resolucao de contato o jogaria para
        # tras e o empurrao se desmancharia em varios toques. Por isso ele e
        # limitado AO push_speed: os dois andam juntos, na mesma velocidade,
        # e o contato se mantem.
        #
        # Vale sempre, e nao so contra parede: e o proprio empurrao que define
        # o ritmo, e um empurrador 3x mais pesado move o alvo devagar.
        if axis == "x" and getattr(obj, "_was_pushing", None):
            push_speed = min(
                (
                    t.push_speed
                    for t in self.objects
                    if id(t) in obj._was_pushing and t.push_speed > 0.0
                ),
                default=0.0,
            )
            if push_speed > 0.0:
                vel = getattr(obj.velocity, "x")
                if abs(vel) > push_speed:
                    setattr(
                        obj.velocity,
                        "x",
                        push_speed if vel > 0.0 else -push_speed,
                    )

        delta = getattr(obj.velocity, axis) * dt
        if delta == 0:
            return

        steps = self._substeps_for(obj, axis, abs(delta))

        for _ in range(steps):
            # Se a resolução anterior zerou este eixo (o objeto encostou),
            # não há mais deslocamento a aplicar.
            current_velocity = getattr(obj.velocity, axis)
            if current_velocity == 0:
                return

            step = current_velocity * dt / steps
            setattr(obj.position, axis, getattr(obj.position, axis) + step)
            obj._sync_rect()

            self._resolve_axis_contacts(obj, axis, motion=step)

    def _substeps_for(self, obj, axis, distance):
        """Quantos subpassos um deslocamento exige para não atravessar nada.

        Um passo nunca pode ser maior que o menor objeto do cenário no eixo,
        porque um deslocamento maior que isso pode passar inteiro por uma
        superfície sem gerar sobreposição em nenhum momento.
        """
        smallest = self.smallest_extent_on_axis(axis)
        if smallest <= 0:
            return 1

        # Um pouco de folga para não ficar exatamente na borda.
        limit = smallest * 0.5
        return max(1, int(distance // limit) + 1)

    def smallest_extent_on_axis(self, axis):
        """Menor largura (`x`) ou altura (`y`) entre objetos e plataformas."""
        sizes = [obj.rect.size[0 if axis == "x" else 1] for obj in self.objects]
        sizes += [p.rect.size[0 if axis == "x" else 1] for p in self.platforms]
        return min(sizes) if sizes else 0

    def _resolve_axis_contacts(self, obj, axis, ignore=None, motion=0.0):
        """Resolve os contatos do objeto no eixo informado.

        `ignore` é a superfície que está sendo arrastada junto com o objeto:
        ela é pulada de propósito, para que a colisão não desfaça o arrasto.

        `motion` é o deslocamento que está sendo aplicado agora, no mesmo eixo.
        Ele manda na hora de decidir de que lado veio o contato, porque
        `obj.velocity` pode estar zerado mesmo com o objeto sendo movido — é o
        caso do empurrão e do arraste, que deslocam sem passar por velocidade.
        Sem isso, um objeto empurrado contra uma parede seria classificado pelo
        centro e ejetado pelo LADO ERRADO, atravessando a parede.
        """
        # Superficies que ja foram carregadas neste quadro, para nao
        # carregar a mesma superficie multiplas vezes (uma por cada
        # passagem de CONTACT_PASSES e ate mesmo em chamadas recursivas).
        # Eixo perpendicular: um contato só pertence a este eixo se houver
        # sobreposição REAL no outro. Sem esta checagem, uma parede resolveria
        # também no eixo Y e o objeto "saltaria" para o topo dela.
        other_axis = "y" if axis == "x" else "x"

        # Várias passagens, e não uma só.
        #
        # Resolver a parede pode empurrar o objeto para dentro do objeto que
        # estava encostado nele, e resolver esse objeto pode jogá-lo de volta
        # na parede. Com uma passada só, o resultado final era o pior dos dois:
        # um objeto empurrado contra uma parede acabava do lado errado dela.
        # Cada passagem estabiliza um pouco mais; `CONTACT_PASSES` é o teto
        # para o caso patológico de duas superfícies disputando o mesmo pixel.
        for _ in range(CONTACT_PASSES):
            moved = False

            for surface in self.get_surfaces(exclude=obj):
                if surface is ignore:
                    continue
                # Quem este objeto está empurrando neste quadro não o bloqueia:
                # o objeto pesado precisa atravessar o alvo para empurrá-lo
                # adiante.
                if id(surface) in getattr(obj, "_pushing", ()):
                    continue
                # A superfície de APOIO não é ignorada aqui.
                #
                # Ignorá-la fazia o objeto afundar através do chão em que
                # estava apoiado: ao pousar, `riding` passa a ser o chão, e
                # daí em diante todo quadro pulava o chão na resolução de
                # contato. A recursão infinita que este check tentava evitar
                # já é barrada por `_lifted_pairs`, em `_push_rider`.
                if not surface.solid or not self._is_touching(obj, surface):
                    continue

                overlap_x, overlap_y = self._overlaps(obj.rect, surface.rect)
                overlap_other = overlap_y if other_axis == "y" else overlap_x

                # Só resolve neste eixo se realmente estiver sobreposto no
                # outro. Contato exatamente encostado (0) não conta, para não
                # prender o objeto numa aresta.
                if overlap_other <= 0:
                    continue

                before = getattr(obj.position, axis)
                direction = self._side_on_axis(obj, surface, axis, motion)

                # Se esta superficie foi empurrada por este objeto neste quadro,
                # nao o empurramos de volta: CARREGAMOS a superficie junto.
                # O 'motion' e o deslocamento pretendido neste subpasso.
                # Ja sabemos quanto o objeto tentou se mover, nao precisamos
                # recalcular a partir das posicoes (que ja foram atualizadas).
                # Porem, se o alvo tem push_speed menor que a velocidade do
                # empurrador, o empurrador nao consegue empurra-lo mais rapido
                # que push_speed: o alvo so se move ate esse limite.
                if isinstance(surface, GameObject) and id(surface) in getattr(obj, "_was_pushing", ()):
                    # So carrega uma vez por quadro.
                    if id(surface) in self._carried_this_frame:
                        continue
                    self._carried_this_frame.add(id(surface))

                    if motion != 0:
                        # Limita o deslocamento do alvo ao seu push_speed.
                        # motion = velocity * dt / steps
                        # max step for target = push_speed * dt / steps
                        # ratio = min(1, push_speed / |velocity|)
                        obj_vel = getattr(obj.velocity, axis)
                        if obj_vel != 0 and surface.push_speed > 0:
                            ratio = min(1.0, surface.push_speed / abs(obj_vel))
                            limited_motion = motion * ratio
                        else:
                            limited_motion = motion

                        # Antes de carregar, verifica se o alvo bateria numa parede
                        # ou solido na direcao do movimento. Se sim, nao carrega
                        # (ou limita para encostar na parede).
                        if limited_motion != 0:
                            # Cria retangulo temporario do alvo apos o movimento
                            future_rect = surface.rect.copy()
                            if axis == "x":
                                future_rect.x += limited_motion
                            else:
                                future_rect.y += limited_motion

                            # Verifica colisao com solidos (excluindo o empurrador e o proprio alvo)
                            for other in self.get_surfaces(exclude=surface):
                                if other is obj or not other.solid:
                                    continue
                                if self._is_touching_rect(future_rect, other.rect):
                                    # Ha solido no caminho: nao carrega alem desse ponto
                                    # Calcula o movimento maximo ate encostar
                                    if axis == "x":
                                        if limited_motion > 0:
                                            # Movendo para a direita: encosta na borda esquerda do obstaculo
                                            max_x = other.rect.left - surface.rect.width
                                            limited_motion = min(limited_motion, max_x - surface.rect.x)
                                        else:
                                            # Movendo para a esquerda: encosta na borda direita
                                            max_x = other.rect.right
                                            limited_motion = max(limited_motion, max_x - surface.rect.x)
                                    else:
                                        if limited_motion > 0:
                                            max_y = other.rect.top - surface.rect.height
                                            limited_motion = min(limited_motion, max_y - surface.rect.y)
                                        else:
                                            max_y = other.rect.bottom
                                            limited_motion = max(limited_motion, max_y - surface.rect.y)
                                    break

                            if limited_motion != 0:
                                self._shift_axis(surface, axis, limited_motion, ignore={obj, surface})
                    # Nao zeramos a velocidade do empurrador: ele continua
                    # empurrando.
                    # Ja resolvemos este contato (carregamos), pula para o proximo.
                    if motion != 0:
                        moved = True
                    continue
                else:
                    self._resolve(obj, surface, direction)

                if getattr(obj.position, axis) != before:
                    moved = True

            if not moved:
                break

    # ------------------------------------------------------------------
    # Detecção de direção
    # ------------------------------------------------------------------
    @staticmethod
    def _overlaps(obj_rect, surface_rect):
        """Sobreposição em X e em Y entre dois retângulos.

        Valores positivos significam sobreposição; zero significa encostado.
        """
        overlap_x = min(obj_rect.right, surface_rect.right) - max(
            obj_rect.left, surface_rect.left
        )
        overlap_y = min(obj_rect.bottom, surface_rect.bottom) - max(
            obj_rect.top, surface_rect.top
        )
        return overlap_x, overlap_y

    @classmethod
    def _side_on_axis(cls, obj, surface, axis, motion=0.0):
        """Lado do objeto que encostou, considerando APENAS um eixo.

        Como o movimento é resolvido por eixos, cada eixo já sabe em que
        sentido foi resolvido, e isso basta para saber de que lado veio o
        contato. `axis` é "x" (parede) ou "y" (chão ou teto).

        A decisão usa o SENTIDO DO DESLOCAMENTO no eixo, e não a comparação de
        centros. O centro engana: um objeto caindo rápido já tem o centro
        abaixo do centro da plataforma no momento do contato, e ele seria
        classificado como se tivesse vindo por baixo.

        `motion` é o deslocamento sendo aplicado agora. Ele tem prioridade
        sobre `obj.velocity` porque alguns movimentos (empurrão, arraste)
        deslocam sem declarar velocidade; se só a velocidade fosse usada, o
        objeto "parado" cairia no desempate por centro e poderia ser ejetado
        para o lado errado — é o que fazia um objeto empurrado atravessar a
        parede contra a qual estava encostado.

        Quando não há deslocamento nem velocidade (objeto encostado e parado),
        o movimento não informa nada, então cai para a comparação de centros.
        """
        obj_rect = obj.rect
        surface_rect = surface.rect
        displacement = motion if motion else getattr(obj.velocity, axis)

        if axis == "x":
            if displacement > 0:
                return Direction.RIGHT   # indo para a direita
            if displacement < 0:
                return Direction.LEFT    # indo para a esquerda

            # Parado no eixo: decide pelo centro.
            if obj_rect.centerx <= surface_rect.centerx:
                return Direction.RIGHT
            return Direction.LEFT

        # Eixo Y: positivo é para BAIXO no Pygame.
        if displacement > 0:
            return Direction.TOP     # caindo -> aterrissa pelo topo
        if displacement < 0:
            return Direction.BOTTOM  # subindo -> bate por baixo

        # Parado no eixo: decide pelo CENTRO, que é estável mesmo com o
        # objeto muito acima ou muito abaixo da superfície. Comparar as
        # bordas daria um resultado ambíguo quando um dos objetos é bem
        # maior que o outro.
        if obj_rect.centery <= surface_rect.centery:
            return Direction.TOP
        return Direction.BOTTOM

    @classmethod
    def _is_touching(cls, obj, surface):
        """True se os retângulos se sobrepõem ou estão encostados.

        `rect.colliderect()` exige sobreposição real, mas um objeto apoiado
        fica exatamente encostado (sobreposição 0), então aqui toleramos a
        adjacência.
        """
        overlap_x, overlap_y = cls._overlaps(obj.rect, surface.rect)
        return overlap_x >= 0 and overlap_y >= 0

    @classmethod
    def _is_touching_rect(cls, rect_a, rect_b):
        """True se dois retângulos se sobrepõem ou estão encostados.

        Versão que recebe retângulos diretamente, sem precisar de objetos.
        """
        overlap_x = min(rect_a.right, rect_b.right) - max(rect_a.left, rect_b.left)
        overlap_y = min(rect_a.bottom, rect_b.bottom) - max(rect_a.top, rect_b.top)
        return overlap_x >= 0 and overlap_y >= 0

    @classmethod
    def _contact_direction(cls, obj, surface):
        """Direção do contato entre `obj` e `surface`, ou None se não há contato.

        Decide pelo eixo de MENOR sobreposição: contato predominantemente
        horizontal é parede; predominantemente vertical é chão (`TOP`) ou
        teto (`BOTTOM`).

        Esta é a direção REPORTADA (usada em `grounded` e nos eventos). Ela
        funciona mesmo com o objeto parado, ao contrário do sentido do
        movimento, e por isso usa a sobreposição como critério.
        """
        overlap_x, overlap_y = cls._overlaps(obj.rect, surface.rect)

        # Folga de 1px: o contato já foi resolvido e o objeto está encostado.
        if overlap_x < 0 or overlap_y < 0:
            return None

        if getattr(surface, "one_way", False):
            # Plataforma de sentido único só bloqueia descidas pelo topo.
            if obj.velocity.y <= 0:
                return None
            return Direction.TOP

        if overlap_x < overlap_y:
            # Contato lateral: usa o sentido do movimento, ou os centros se
            # o objeto estiver parado no eixo.
            return cls._side_on_axis(obj, surface, "x")

        # Contato vertical: qual borda está mais perto da borda do objeto
        # decide se é apoio (`TOP`) ou teto (`BOTTOM`).
        to_top = obj.rect.bottom - surface.rect.top
        to_bottom = surface.rect.bottom - obj.rect.top
        if to_top <= to_bottom:
            return Direction.TOP
        return Direction.BOTTOM

    def _resolve(self, obj, surface, direction):
        """Corrige a posição e a velocidade do objeto após o contato.

        Antes de resolver, se `obj` estiver empurrando algo que está EM CIMA
        dele (contato pela base), esse algo sobe junto. Sem essa etapa, um
        objeto que sobe ficaria preso contra o objeto de cima, e nenhum dos
        dois se moveria.
        """
        if direction is Direction.BOTTOM and isinstance(surface, GameObject):
            if self._push_rider(surface, obj):
                # `obj` conseguiu erguer o que estava em cima, então segue
                # subindo em vez de ser barrado.
                obj.velocity.y = min(obj.velocity.y, 0.0)
                return

        penetration = self._penetration(obj, surface, direction)
        self._push_out(obj, surface, direction, penetration)

        # Zera SOMENTE o eixo bloqueado, como pede o enunciado: bater na
        # parede não pode parar a queda.
        # Excecao: se o objeto esta empurrando esta superficie lateralmente,
        # nao zera a velocidade (o objeto esta empurrando, nao batendo).
        if direction is Direction.TOP or direction is Direction.BOTTOM:
            # Não zera a velocidade de quem está SENDO ARRASTRADO para cima e
            # subindo por conta própria ao mesmo tempo.
            #
            # Quem sobe (pulo) contra uma plataforma que sobe junto tem os
            # retângulos cruzados por um instante, e o contato resolve como
            # `BOTTOM`. O `velocity.y = 0` seguinte apagava o pulo e prendia o
            # player na plataforma: ele estava indo embora, não batendo.
            #
            # Restrito a `_carried_by_platform` de propósito: bater num teto
            # comum tem de continuar parando quem sobe, senão o objeto atravessaria
            # o teto.
            arrastado_para_cima = (
                direction is Direction.BOTTOM
                and obj.velocity.y < 0.0
                and getattr(obj, "_carried_by_platform", False)
            )
            if not arrastado_para_cima:
                obj.velocity.y = 0.0
        else:
            if not (isinstance(surface, GameObject) and id(surface) in getattr(obj, "_was_pushing", ())):
                obj.velocity.x = 0.0

    def _push_rider(self, rider, base):
        """Sobe `rider` junto com `base` e propaga para quem está acima dele.

        `rider` está apoiado em `base` e `base` está subindo: em vez de ficar
        preso, o `rider` é elevado pela mesma distância. É o que faz um objeto
        carregar quem está em cima dele, do mesmo jeito que uma plataforma.

        O par é ignorado na resolução de contatos durante esse deslocamento.
        Sem isso, elevar o `rider` o faria penetrating `base` de novo, o que
        chamaria este mesmo método outra vez — uma pilha de três viraria
        recursão infinita.

        Devolve True se o `rider` foi movido.
        """
        if not rider.active or not rider.movement_enabled:
            return False

        # `rider` precisa estar MESMO EM CIMA de `base`. Só `penetration < 0`
        # não garante isso: os dois retângulos também "se sobrepõem" quando o
        # de cima é arrastado para cima e encontra o de baixo pelo lado de
        # baixo. Nesse caso elevar o de baixo o afundaria ainda mais.
        if rider.rect.top >= base.rect.bottom:
            return False

        # Se o rider já está montado no base (riding), não precisa empurrar.
        if getattr(rider, "riding", None) is base:
            return False

        # Cada par é elevado uma vez por quadro (ver `_lifted_pairs`).
        pair = (id(base), id(rider))
        if pair in self._lifted_pairs:
            return False

        # Distância que falta para a base de `rider` chegar ao topo de `base`.
        # Negativa significa que `rider` entrou dentro de `base`, e o próprio
        # valor já é o deslocamento a aplicar (negativo = para cima).
        penetration = base.rect.top - rider.rect.bottom
        if penetration >= 0:
            # Já estão separados (ou `rider` está acima). Nada a fazer.
            return False

        self._lifted_pairs.add(pair)
        self._shift_axis(rider, "y", penetration, ignore={base, rider})

        # Só o `rider` direto é movido aqui. Quem está em cima dele é levado
        # pelo `_apply_carry`, no fim do quadro: propagar agora também faria a
        # mesma distância ser aplicada duas vezes na pilha.
        #
        # Não se anota nada em `carry_offset`: o `PhysicsWorld` mede o
        # deslocamento pela posição de início e fim do quadro, e somar aqui
        # contaria a distância uma segunda vez.
        return True

    @staticmethod
    def _penetration(obj, surface, direction):
        """Profundidade da sobreposição no eixo do contato."""
        if direction is Direction.TOP:
            return obj.rect.bottom - surface.rect.top
        if direction is Direction.BOTTOM:
            return surface.rect.bottom - obj.rect.top
        if direction is Direction.LEFT:
            return surface.rect.right - obj.rect.left
        return obj.rect.right - surface.rect.left

    def _push_out(self, obj, surface, direction, penetration):
        """Afasta o objeto da superfície e realinha o retângulo.

        O lado é decidido pela GEOMETRIA (as posições reais dos retângulos),
        nunca pelo sentido do movimento. Isso é essencial: quando dois objetos
        se espremem, o movimento já pode ter sido zerado no quadro anterior e
        não diz mais nada sobre de que lado o contato aconteceu.

        Um objeto que colide pela base com o topo de uma plataforma tem
        sobreposição pequena para o lado de baixo (`below_overlap`) e grande
        para cima, então ele é reposicionado para baixo, como deve ser.
        """
        before_y = obj.position.y
        before_x = obj.position.x
        obj_rect = obj.rect
        surface_rect = surface.rect

        if direction is Direction.TOP or direction is Direction.BOTTOM:
            # Distâncias com sinal: uma delas é negativa quando o objeto está
            # do lado OPOSTO ao indicado, e é isso que decide.
            #   above: quanto o objeto está acima do topo da superfície.
            #   below: quanto o objeto está abaixo da base da superfície.
            above_overlap = obj_rect.bottom - surface_rect.top
            below_overlap = surface_rect.bottom - obj_rect.top

            # O objeto está mais alinhado ao topo => APOIADO em cima.
            # Caso contrário => está por baixo (teto) e volta para baixo.
            if above_overlap <= below_overlap:
                obj.position.y = surface_rect.top - obj_rect.height
            else:
                obj.position.y = surface_rect.bottom
        else:
            # Mesma lógica no eixo X: comparar a "penetração" relativa a cada
            # borda da superfície. O lado com MENOR distância absoluta é o
            # lado do contato, e o objeto é colocado FORA desse lado.
            #
            # Nota: `obj_rect.right - surface_rect.left` é a sobreposição
            # quando o objeto está VINDO DA ESQUERDA (entra pela esquerda da
            # superfície). `surface_rect.right - obj_rect.left` é a sobreposição
            # quando vindo da direita. O MENOR valor indica o lado real.
            left_pen = obj_rect.right - surface_rect.left     # entra pela esquerda
            right_pen = surface_rect.right - obj_rect.left    # entra pela direita

            if left_pen <= right_pen:
                # Contato veio da esquerda: empurra o objeto para A ESQUERDA
                # da superfície.
                obj.position.x = surface_rect.left - obj_rect.width
            else:
                # Contato veio da direita: empurra para A DIREITA.
                obj.position.x = surface_rect.right

        obj._sync_rect()

        # Só um reposicionamento MUITO grande é suspeito: uma aterrissagem normal
        # move o objeto poucos pixels, dentro do esperado. Um salto grande
        # significa que o objeto atravessou ou foi ejetado de uma superfície,
        # que é exatamente o tipo de bug que queremos ver no log.
        moved_x = abs(obj.position.x - before_x)
        moved_y = abs(obj.position.y - before_y)
        if max(moved_x, moved_y) > TELEPORT_THRESHOLD:
            self.logger.warn(
                "fisica",
                f"{type(obj).__name__} reposicionado ao resolver {direction.value}: "
                f"({before_x:.1f}, {before_y:.1f}) -> "
                f"({obj.position.x:.1f}, {obj.position.y:.1f}) "
                f"em {type(surface).__name__}",
            )

    # ------------------------------------------------------------------
    # Contatos e notificação
    # ------------------------------------------------------------------
    def _update_contacts(self, obj):
        """Atualiza o estado dos contatos de `obj` e dispara os eventos.

        Reaproveita o estado do quadro anterior para diferenciar início,
        continuidade e fim de colisão, evitando notificar a mesma aterrissagem
        a cada quadro em que o objeto fica apoiado.
        """
        current = {}
        grounded = False
        ride = None

        for surface in self.get_surfaces(exclude=obj):
            direction = self._contact_direction(obj, surface)
            if direction is None:
                continue

            penetration = self._penetration(obj, surface, direction)
            collision = Collision(
                other=surface,
                direction=direction,
                penetration=penetration,
            )

            if direction is Direction.TOP:
                grounded = True
                # Guarda a superfície de apoio para o arrasto. A geometria é
                # conferida de novo no fim do quadro, porque durante o
                # próprio arrasto os retângulos se movem.
                ride = surface

            # Sanidade: um contato `TOP` com o objeto bem abaixo do topo da
            # superfície é impossível. A tolerância absorve a penetração de
            # poucos pixels que é normal enquanto o objeto é arrastado por
            # uma plataforma, e só acima dela o contato é mesmo incoerente.
            if direction is Direction.TOP and obj.rect.bottom > surface.rect.top + RIDE_HOLD_TOLERANCE:
                self.logger.error(
                    "fisica",
                    f"contato incoerente: {type(obj).__name__} marcado como TOP "
                    f"com {type(surface).__name__}, mas obj.bottom="
                    f"{obj.rect.bottom} > surf.top={surface.rect.top}",
                )
                direction = Direction.BOTTOM
                collision = Collision(surface, direction, penetration)

            current[id(surface)] = (collision, surface)

        # Sanidade global: um objeto com gravidade não pode ficar acima do
        # teto do cenário nem abaixo do chão. Se ficar, ele atravessou uma
        # superfície e o log precisa apontar isso com o estado exato.
        self._check_bounds(obj)

        previous = self._contacts.get(id(obj), {})
        obj.current_collisions = [c for c, _ in current.values()]
        obj.grounded = grounded
        obj.riding = ride

        states = {}
        for surface_id, (collision, surface) in current.items():
            state = previous.get(surface_id)
            if state is None:
                # Primeiro quadro deste contato.
                self.logger.debug(
                    "colisao",
                    f"{type(obj).__name__} x {type(surface).__name__} "
                    f"direcao={collision.direction.value} "
                    f"penetracao={collision.penetration:.1f} "
                    f"pos=({obj.position.x:.0f}, {obj.position.y:.0f})",
                )
                self._emit(obj, collision, phase="start")
                states[surface_id] = ContactState(collision)
            else:
                # Contato contínuo: atualiza sem notificar de novo.
                states[surface_id] = state.refresh(collision)

        # Contatos que existiam e não existem mais.
        for surface_id, state in previous.items():
            if surface_id not in current:
                obj._notify("collision_end", state.collision)

        self._contacts[id(obj)] = states

    def _check_bounds(self, obj):
        """Avisa quando um objeto sai dos limites da simulação.

        Não corrige nada: apenas registra o estado exato do objeto, os limites
        e os contatos do quadro, que é o que permite encontrar a origem do
        problema depois.
        """
        if self.bounds is None:
            return

        rect = obj.rect
        bounds = self.bounds

        if rect.top < bounds.top or rect.bottom > bounds.bottom:
            self.logger.error(
                "limite",
                f"{type(obj).__name__} saiu do cenario: "
                f"pos=({obj.position.x:.1f}, {obj.position.y:.1f}) "
                f"rect={tuple(rect)} limites={tuple(bounds)} "
                f"contatos={[c.direction.value for c in obj.current_collisions]}",
            )
        elif rect.right < bounds.left or rect.left > bounds.right:
            self.logger.error(
                "limite",
                f"{type(obj).__name__} saiu do cenario na horizontal: "
                f"pos=({obj.position.x:.1f}, {obj.position.y:.1f}) "
                f"rect={tuple(rect)} limites={tuple(bounds)}",
            )

    def _emit(self, obj, collision, phase):
        """Dispara os eventos de colisão do objeto.

        `phase` é "start" ou "end". Só no início são disparados os eventos
        específicos (aterrissagem, teto, parede), para que um objeto apoiado
        no chão não gere uma nova aterrissagem a cada quadro.
        """
        direction = collision.direction

        if phase == "start":
            obj._notify("collision_start", collision)

        # Sempre notifica o contato, para permitir reação contínua.
        obj._notify("collision", collision)

        if phase == "start":
            # Reações específicas: só no início do contato, para não repetir
            # a aterrissagem enquanto o objeto permanece apoiado.
            if direction is Direction.TOP:
                obj._notify("landed", collision)
            elif direction is Direction.BOTTOM:
                obj._notify("hit_ceiling", collision)
            elif direction in (Direction.LEFT, Direction.RIGHT):
                obj._notify("hit_wall", collision)