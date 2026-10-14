"""Suíte de testes do BBox / bbox2d.

Por que este arquivo não está vazio
-----------------------------------
O pacote usa **layout src**: o código vive em `src/bbox2d/`, e `src/` não
é um pacote importável a partir da raiz do repositório. Isso é deliberado —
é o layout que impede que um `import bbox2d` acerte por acidente o código do
projeto em vez do código instalado.

A consequência é que, num checkout limpo **sem** `pip install -e .`, rodar a
suíte a partir da raiz do repositório não encontraria `bbox2d`. Este arquivo
resolve isso colocando `src/` no `sys.path`, de forma condicional:

- se `bbox2d` já estiver importável (porque o pacote foi instalado, como
  acontece na CI depois de `pip install -e .`), nada é feito e a versão
  **instalada** é a que os testes exercitam;
- se não estiver, `src/` é acrescentado ao caminho e a suíte funciona
  direto do repositório.

O teste nessa ordem importa: exercitar o código instalado quando ele
existe vale mais do que exercitar a cópia da árvore de trabalho, porque é o
que o consumidor da biblioteca vai encontrar.
"""

import os
import sys

try:  # pragma: no cover - depende do ambiente, não do código testado
    import bbox2d as _bbox2d  # noqa: F401
except ImportError:
    _SRC = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"
    )
    if os.path.isdir(_SRC) and _SRC not in sys.path:
        sys.path.insert(0, _SRC)