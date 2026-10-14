"""Utilitários compartilhados pelo pacote.

`utils/` era o único diretório sem `__init__.py` no projeto original: como
`Python` trata pasta sem `__init__.py` como *namespace package*, os imports
funcionavam em tempo de execução. O mesmo não vale para o empacotamento — a
descoberta de pacotes do setuptools não enxerga namespace packages por
padrão, e `bbox2d.utils` simplesmente não entraria no pacote instalado.

Este arquivo resolve isso sem mudar nenhum comportamento: o conteúdo de
`utils/GameLogger.py` é intocado.
"""