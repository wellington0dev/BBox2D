# BBox

Jogo em Python + Pygame organizado em **núcleo (loop/window), cenas e componentes de UI**.

## Executar

A partir da pasta do projeto:

```bash
python3 -m src.main
```

Ou, de qualquer diretório:

```bash
python3 /caminho/ate/o/projeto/src/main.py
```

## Estrutura

```text
bbox/
├── src/
│   ├── main.py                  # ponto de entrada: cria o Game e registra as cenas
│   ├── assets/                  # imagens e fontes (carregadas via __file__, não via cwd)
│   ├── core/
│   │   ├── Game.py              # janela, relógio e loop principal
│   │   ├── SceneManager.py      # cena ativa, troca de cena, encaminhamento
│   │   └── scenes/
│   │       ├── Scene.py         # classe-base das cenas
│   │       ├── MenuScene.py     # tela inicial + botão "Jogar"
│   │       └── GameScene.py     # cenário de testes da física
│   ├── physics/
│   │   ├── Collision.py         # Direction, Collision e ContactState
│   │   └── PhysicsWorld.py      # simulação, gravidade e resolução de colisões
│   ├── objects/
│   │   ├── GameObject.py        # entidade com estado físico e pontos de extensão
│   │   ├── Player.py            # controlado pelo teclado
│   │   ├── Enemy.py             # patrulha uma plataforma
│   │   └── InteractiveObject.py # ativável, com ou sem gravidade
│   ├── platforms/
│   │   └── Platform.py          # superfície sólida, estática ou móvel
│   ├── ui/
│   │   ├── Button.py            # imagem, rect, rótulo e clique
│   │   └── Text.py              # conteúdo, fonte, tamanho, cor e render
│   └── utils/
│       └── GameLogger.py        # log da execução e relatório .txt
├── tests/
│   ├── test_physics.py          # 46 testes de física, colisão e arrasto
│   └── test_weight.py           # 58 testes de peso, carga e empurrão
├── logs/                        # relatórios de execução (gerado ao rodar)
└── README.md
```

## Sistema de física

### Convenção de eixos

O Pygame usa Y crescendo para **BAIXO**. Então pular é uma velocidade vertical
**negativa**, e a gravidade soma um valor **positivo** em Y.

### Direção de colisão

`Direction` descreve sempre o **lado do objeto em movimento** que encostou,
nunca o lado da superfície:

| Direção  | Significado                                  | Normal   |
| -------- | -------------------------------------------- | -------- |
| `TOP`    | encostou pelo topo: está **apoiado** em cima  | `(0, -1)` |
| `BOTTOM` | encostou pela base: está **preso no teto**    | `(0, 1)` |
| `LEFT`   | encostou pela lateral esquerda                | `(1, 0)` |
| `RIGHT`  | encostou pela lateral direita                 | `(-1, 0)` |

`Collision.normal` aponta para fora da superfície, ou seja, é sempre a oposta
do lado que encostou.

### Como a colisão é resolvida

O movimento é aplicado **um eixo por vez**: primeiro X, depois Y. Cada eixo só
resolve contatos que são daquele eixo, o que permite distinguir cair no chão,
bater no teto e encostar na parede — coisa que `rect.colliderect()` sozinho não
explica.

O deslocamento é dividido em **subpassos** quando o objeto anda mais que o menor
objeto do cenário em um quadro. Sem isso um objeto rápido atravessa uma parede
fina sem que nenhum quadro detecte a sobreposição. O laço de subpassos é o ponto
onde uma detecção contínua (CCD) pode ser plugada depois.

Ao resolver, **apenas o eixo bloqueado** é zerado: encostar numa parede não
interrompe a queda.

A correção de posição é decidida pela **geometria** dos retângulos (qual
sobreposição é menor), nunca pelo sentido do movimento. Isso importa quando
dois objetos se espremem: o movimento já pode ter sido zerado no quadro
anterior e não diz mais nada sobre de que lado veio o contato. Decidir pela
direção do movimento fazia um objeto que batia por baixo ser empurrado para
**cima** da superfície, atravessando-a.

### Eventos

A classe-base informa o que aconteceu, e as subclasses decidem como reagir:

```python
on_collision(collision)          # todo quadro de contato
on_collision_start(collision)    # primeiro quadro do contato
on_collision_end(collision)      # quando o contato termina
on_landed(collision)             # só no início de um contato pelo topo
on_hit_ceiling(collision)        # só no início de um contato pela base
on_hit_wall(collision)           # só no início de um contato lateral
```

Os eventos específicos disparam **apenas no início** do contato, então um objeto
apoiado no chão não gera uma nova aterrissagem a cada quadro. Callbacks também
podem ser registrados:

```python
obj.add_event_handler("landed", lambda collision: print("aterrissou"))
```

### Peso e carga

Todo objeto tem um **peso intrínseco** (`weight`) que nunca muda em tempo de
execução. A **carga que ele recebe** (`supported_load`) é recalculada pelo
`PhysicsWorld` a cada quadro e zera sozinha quando o apoio acaba — são coisas
deliberadamente separadas, para que apoio temporário não contamine o peso.

```python
GameObject(weight=2.0, weight_influence=1.0, vertical_resistance=0.0)
```

| Atributo | Significado |
| --- | --- |
| `weight` | peso próprio, usado para comparar com a carga recebida |
| `jump_strength` | velocidade inicial do salto (`None` = não salta) |
| `weight_influence` | quanto o objeto reage à carga; `0.0` ignora |
| `vertical_resistance` | carga que um objeto **sem gravidade** aguenta antes de ceder |

**Como a carga é transmitida.** Um objeto carrega o próprio peso e, em cima
disso, tudo o que está apoiado nele:

```text
caixa (1.0)  ─┐
              ├─▶  meio (2.0)  ──▶  base (3.0)
caixa (1.0)  ─┘        load=1.0       load=3.0   total=6.0
```

Só conta como apoio o que `_find_support` reconhece: sobreposição horizontal e
a base encostada no topo da superfície. Encostar de lado não cria carga, e
plataformas não transmitem carga (são superfícies, não parte da pilha). O
cálculo roda uma vez por quadro, do topo para o chão, o que torna a soma
consistente e impede ciclos por construção.

**Salto sob carga** (a fórmula pedida, com `load_ratio` = `carga / peso`):

```python
load_ratio = supported_load / weight
jump_factor = max(0.0, 1.0 - load_ratio)
effective_jump_strength = jump_strength * jump_factor
```

`Player.update()` só chama `can_jump()` e aplica o valor; o deslocamento
continua sendo feito pela física, sem movimento extra.

**Cedência vertical.** A mesma razão (`load_ratio`) vira modificador de
movimento:

```text
objeto COM gravidade:  deficit = max(0, load_ratio - 1)
                       efeito  = deficit * influence * 240   (teto 1400 px/s²)

objeto SEM gravidade:  excesso = supported_load - vertical_resistance
                       cedência = excesso * influence * 90    (teto 420 px/s)
```

Sem carga nenhum modificador fica ativo, e um objeto sem gravidade **não vira
"com gravidade"**: ele recebe um deslocamento vertical próprio, que respeita
paredes, tetos e plataformas como qualquer outro movimento. Carga igual ao peso
não produz efeito extra; só acima dela o objeto cede.

Para desligar o sistema e comparar: `physics.PhysicsWorld.LOAD_ENABLED = False`.

### Pilhas em queda livre

Uma pilha que cai no ar desce como um **bloco só**. Sem isso, o objeto de baixo
recebe a carga de cima, ganha aceleração extra, passa à frente e a pilha se
rompe — a caixa de cima ficaria parada no ar.

A pilha é detectada por `_find_support`, mas **não** volta a ser montada por
geometria a cada quadro: numa queda rápida o deslocamento por quadro passa da
tolerância de contato, e uma detecção puramente geométrica perderia o grupo
justamente quando ele é necessário. Por isso a base desce e cada objeto acima é
recolocado sobre quem o sustenta, preservando o contato por construção.

Pilhas **apoiadas** (no chão ou numa plataforma) não entram nesse caminho: já são
resolvidas pela gravidade e pelo arraste. E objetos **sem gravidade** ficam de
fora, porque têm cedência própria via `vertical_resistance`.

### Empurrar por peso

Dois objetos sólidos encostados **de lado** se empurram quando um é mais pesado
que o outro. O mais leve sai da frente:

```python
ratio  = self.weight / other.weight
força  = clamp((ratio - 1.2) / (2.5 - 1.2), 0, 1)
vx    += força * PUSH_SPEED
```

| Pesos | Empurrão |
| --- | --- |
| 10 × 1 | máximo (ratio 10 ≥ 2.5) |
| 2 × 1 | 62% |
| 1.3 × 1 | 8%, quase nada |
| 1 × 1 (empate) | **não se empurram** |

O empate não empurra de propósito: dois objetos do mesmo peso ficariam se
deslocando mutuamente para sempre. Quem se move por conta própria (controle,
script) não recua — a inércia manda. E quem é empurrado não bloqueia quem
empurra, senão o pesado travaria contra o leve em vez de movê-lo.

Use `pushable=False` para tirar um objeto dessa interação.

Para desligar: `physics.PhysicsWorld.PUSH_ENABLED = False`.

### Empurrar quem está em cima

Um objeto que **sobe** contra o objeto que está em cima dele não fica preso:
`_push_rider` eleva quem está em cima pela mesma distância, e a propagação
continua pelo `_apply_carry`. É por isso que um pulo de um personagem carrega
o que estiver sobre ele.

### Quem aplica o movimento

`Player` e `Enemy` apenas **declaram velocidade**; quem move o objeto na tela é
o `PhysicsWorld`. Isso impede que controles e física apliquem o mesmo
deslocamento duas vezes no quadro.

Ordem dentro de `PhysicsWorld.update(dt)`:

```text
1. integra a velocidade (gravidade + aceleração)
2. move em X, subdividido, resolvendo contatos laterais
3. move em Y, subdividido, resolvendo chão e teto
4. atualiza grounded e dispara os eventos
5. obj.update(dt)  <- o Player lê o teclado aqui
6. arrasta quem está apoiado em algo que se moveu
```

Plataformas móveis andam **antes** dos objetos (passo 0), para que o arrasto
deste quadro use a posição nova da plataforma.

## Fluxo de execução

```text
Game.run()
  └─ loop por quadro:
       1. pygame.event.get()          -> eventos vão para a cena ativa
       2. dt = clock.tick(fps)/1000   -> dt em SEGUNDOS
       3. SceneManager.update(dt)     -> aplica troca pendente + atualiza a cena
       4. SceneManager.render(screen) -> fundo + sprites da cena
       5. pygame.display.flip()
       (clock.tick também limita o FPS)
```

### Troca de cena

1. A cena chama `self.request_scene("game")` durante o tratamento de um evento.
2. O `SceneManager` **guarda o nome** da cena pendente (não troca na hora).
3. No início do `update()` seguinte, a troca é aplicada:
   `on_exit()` da cena antiga -> cria a nova -> `on_enter()`.

Assim a cena nunca é trocada enquanto seus objetos estão sendo percorridos.

### Eventos

- `pygame.QUIT` é tratado apenas pelo `Game`, que encerra o loop e chama
  `on_exit()` da cena ativa.
- Todos os outros eventos seguem para a cena ativa.
- `Scene.handle_event` entrega o evento aos sprites **uma única vez** e para
  no primeiro objeto que o tratou (devolvendo o objeto), então um clique nunca
  aciona dois botões. Sprites removidos da cena não recebem mais eventos nem
  são desenhados.

## Como adicionar uma cena nova

```python
# src/core/scenes/PauseScene.py
from .Scene import Scene

class PauseScene(Scene):
    def __init__(self, game=None):
        super().__init__(game)
        self.background_color = (0, 0, 0)
```

Depois, registre em `src/main.py`:

```python
from .core.scenes.PauseScene import PauseScene
game.scene_manager.register("pause", PauseScene)
```

E chame `self.request_scene("pause")` de qualquer cena. Não é preciso alterar
`Game` nem `SceneManager`.

## Depuração de fonte e texto

Se um texto **ou um botão** não aparecer na tela, ligue os logs:

```python
import src.ui.Text as ui_text
import src.ui.Button as ui_button
ui_text.DEBUG = True
ui_button.DEBUG = True
```

Ou troque `DEBUG = False` por `DEBUG = True` no topo de `src/ui/Text.py` e de
`src/ui/Button.py`.

Os logs mostram, na ordem: o conteúdo pedido, cada caminho de fonte testado,
qual origem funcionou, o tamanho renderizado e o `rect` final. No botão também
saem a imagem carregada, o `rect` final e o resultado de cada clique testado.

Um detalhe importante: a cena **não** usa `Group.draw()`, porque ele faz blit
direto de `sprite.image` e ignora o método `draw()` do sprite — o texto de um
botão nunca apareceria. Cada objeto desenha a si mesmo em `Scene.render()`,
então todo sprite precisa ter um método `draw(surface)`.

Casos que costumam gerar texto invisível e agora aparecem em log:

- fonte não encontrada no caminho informado (cai para a do projeto);
- `pygame.font` não inicializado (o componente chama `pygame.font.init()` sozinho);
- texto criado com conteúdo vazio;
- fonte presente em disco mas ilegível pelo Pygame;
- fonte que carrega sem erro, mas falha ao renderizar (`Passed a NULL pointer`);
- sprite sem método `draw()`, que quebra o `Scene.render()`.

## Controles

| Cena | Ação |
| --- | --- |
| Menu | Clique esquerdo em **Jogar** ou `Esc` para sair |
| Jogo | Setas ou `A`/`D` para andar, `Espaço` para pular, `R` reinicia o cenário, `Esc` volta ao menu, `Q` sai |

No cenário há duas plataformas móveis (um **elevador** rosa que sobe e desce e um
**shuttle** azul horizontal) e duas **caixas amarelas** que caem sobre o jogador e
reduzem a altura do pulo (25% → 62% → 100% conforme as caixas saem). A linha de
depuração mostra a carga atual e quanto do pulo resta.

## Testes

```bash
python3 -m unittest discover -s tests -v
```

Os testes definem `SDL_VIDEODRIVER=dummy`, então rodam sem abrir janela. Cobrem
queda e aterrissagem, teto, paredes preservando a velocidade vertical, ausência
de gravidade, `gravity_scale`, bloqueio entre objetos sólidos, eventos de
aterrissagem sem repetição, normais das superfícies, objetos inativos,
plataformas e as regressões de objetos se espremendo (contato por baixo sem ser
empurrado para cima, e pilha de objetos com gravidade sob o teto).

O arrasto é verificado em três níveis: plataforma carregando objeto, objeto
carregando objeto, e pilha de vários objetos se movendo junta sem duplicar o
deslocamento.

```bash
python3 -m unittest tests.test_weight -v
```

Os testes de peso cobrem: salto sem carga, com carga leve e com carga bloqueante;
transmissão de carga em pilha; remoção da carga ao sair ou ser removido;
objeto sem gravidade parado, cedendo e com resistência; comparação entre carga
leve e pesada; objetos pesados ainda respeitando paredes e tetos; arraste
continuando a atualizar as cargas; e ausência de acumulação de modificadores.

Também cobrem a pilha em queda livre (mantém o contato ao cair e ao pousar, não
atravessa teto, objeto sem gravidade fica de fora) e o empurrão por peso (o mais
pesado move o mais leve, a força é proporcional, empate não empurra, pilha em
cima se mantém e o empurrão não se acumula).

## Plataformas móveis e arrasto

Uma plataforma pode se mover; o padrão continua sendo estática:

```python
Platform(
    position=(60, 180),
    size=(100, 18),
    moving=True,
    speed=70,        # pixels por segundo
    travel=80,       # extensão do percurso, em pixels
    axis="y",        # "x" começa indo para a direita; "y" começa subindo
)
```

A plataforma percorre o percurso de ida e volta e registra, a cada quadro, o
quanto andou em `frame_motion`.

### Arrasto

Quem está **apoiado** (`Direction.TOP`) numa superfície que se move é arrastado
junto, nos dois eixos.

Vale tanto para plataformas quanto para **objetos**: um objeto que anda, é
empurrado ou cai sobre outro carrega quem está em cima dele, exatamente como
uma plataforma faria. A propagação é encadeada e vai do chão para o topo, de
forma que uma pilha de objetos sobre uma plataforma móvel se move inteira.

Apenas o eixo de apoio é transmitido:

| Contato do objeto com a superfície | Eixos arrastados |
| --- | --- |
| `TOP` (apoiado em cima) | X e Y |
| `BOTTOM` (pendurado) | apenas X |
| `LEFT` / `RIGHT` (lateral) | apenas X |

Um objeto arrastado continua sujeito às colisões: levado contra uma parede,
ele para nela em vez de atravessar.

Para uma superfície não arrastar quem está em cima, use `can_carry=False`.

## Log da execução

Todo jogo grava um relatório em `logs/bbox_AAAAMMDD_HHMMSS.txt` ao encerrar, com
a linha do tempo completa: cenas visitadas, trocas de cena, eventos, colisões,
avisos de física e erros com traceback.

O nível padrão é `INFO`. Para ver mais:

```python
game = Game(log_level="DEBUG")   # inclui cada colisão e objeto registrado
```

Para acompanhar no terminal enquanto joga:

```python
import src.utils.GameLogger as gl
gl.LOGGER.console = True
```

Categorias registradas: `jogo`, `cena`, `evento`, `colisao`, `fisica`, `limite`
e `erro`. Registros repetidos em sequência são agrupados como `(repetido Nx)`,
então um erro que se repete a cada quadro não inunda o arquivo.

Dois avisos automático ajudam a achar problemas de física:

- `limite`: um objeto saiu dos limites do cenário, com posição e contatos exatos.
- `fisica`: um objeto foi reposicionado mais de 8px ao resolver uma colisão
  (um salto grande indica atravessamento ou ejeção de uma superfície).

## Como adicionar uma entidade nova

```python
from objects.GameObject import GameObject

class Coin(GameObject):
    def __init__(self, position):
        super().__init__(position=position, size=(16, 16), gravity_enabled=False)

    def on_collision(self, collision):
        self.active = False   # some ao ser tocada
```

Depois registre na cena com `self._spawn(Coin((100, 100)))`. Nada precisa ser
alterado em `Game`, `SceneManager` ou `PhysicsWorld`.