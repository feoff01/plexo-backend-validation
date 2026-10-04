"""Hash canônico de payloads de tools — a base do cache content-addressed e da auditoria."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
from typing import Any


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def sha256_hex(dado: str | bytes) -> str:
    if isinstance(dado, str):
        dado = dado.encode("utf-8")
    return hashlib.sha256(dado).hexdigest()


def sha256_fonte(caminho: pathlib.Path | str) -> str:
    """Impressão digital de UM arquivo-fonte, independente de quebra de linha.

    O sha256 prova QUAL código produziu qual número; CRLF vs LF é artefato de checkout
    (`git core.autocrlf` no Windows), não mudança de código. Hashear os bytes crus dava sha
    diferente para o MESMO commit no dev Windows (CRLF) e no runner Linux (LF) — drift eterno
    no `tools sync --check` do CI, "resolvido" com bumps de semver falsos. Mesma normalização
    que o `read_text` faz nos prompts (`prompts check`).

    Para tools cuja implementação depende de helpers/engines em OUTROS arquivos, use
    `sha256_fontes`: hashear só o módulo da facade deixaria uma mudança de engine alterar
    números sem trocar a impressão digital da versão da tool.
    """
    return sha256_hex(_em_lf(pathlib.Path(caminho).read_bytes()))


def sha256_fontes(caminhos: list[pathlib.Path | str] | tuple[pathlib.Path | str, ...]) -> str:
    """Fingerprint composto de todos os arquivos que podem alterar o resultado de uma tool.

    - caminhos repetidos são deduplicados;
    - cada arquivo é normalizado para LF;
    - a ordem recebida não altera o hash;
    - caminhos ABSOLUTOS não entram no hash; o manifest usa caminhos relativos à raiz comum,
      preservando a identidade de cada arquivo entre checkouts em diretórios diferentes.

    Uma coleção de um único arquivo preserva exatamente o hash legado de `sha256_fonte`,
    evitando bump falso das tools atuais.
    """
    unicos = {pathlib.Path(c).resolve() for c in caminhos}
    if not unicos:
        raise ValueError("sha256_fontes exige ao menos um arquivo")
    if len(unicos) == 1:
        return sha256_fonte(next(iter(unicos)))

    # Liga CONTEÚDO à identidade relativa do arquivo. Hashear apenas o multiconjunto de
    # conteúdos deixaria um caso patológico: trocar o conteúdo de `risk.py` com `returns.py`
    # preservaria o mesmo conjunto de hashes apesar de mudar o comportamento dos imports.
    raiz = pathlib.Path(os.path.commonpath([str(c) for c in unicos]))
    manifest = sorted(
        ({"path": c.relative_to(raiz).as_posix(), "sha256": sha256_fonte(c)} for c in unicos),
        key=lambda item: item["path"],
    )
    return sha256_hex(canonical_json(manifest))


def sha256_fonte_crlf(caminho: pathlib.Path | str) -> str:
    """Como `sha256_fonte`, mas na forma CRLF. Serve a UM propósito: reconhecer impressões digitais
    gravadas até 2026-08-26 por um `tools sync` rodado em checkout Windows — ver `tools/sync.py`."""
    return sha256_hex(_em_lf(pathlib.Path(caminho).read_bytes()).replace(b"\n", b"\r\n"))


def _em_lf(bruto: bytes) -> bytes:
    return bruto.replace(b"\r\n", b"\n")


def arred2(x: float) -> float:
    """Dinheiro em saída de tool: arredonda uma única vez, na borda, a 2 casas.

    Evita que ruído binário de float (15000*0.9 = 13500.000000000002) vaze para o cliente
    e para os golden masters."""
    return float(round(x, 2))
