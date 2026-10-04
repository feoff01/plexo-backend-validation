"""Seeds construídos em Python, para o que a forma de arquivo SQL não serve bem.

`seeds/*.sql` continua sendo a forma padrão — é declarativa, revisável linha a linha e roda
por `plexo seed dev|persona`. Este pacote existe para um caso específico: quando o mesmo
esqueleto se repete N vezes e só os números mudam. Seis personas em SQL seriam ~1.400 linhas
das quais 90% seria a mesma coisa, e a sétima custaria mais 230 — o oposto de escalável.
"""
from __future__ import annotations
