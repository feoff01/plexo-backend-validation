"""Hash de senha com scrypt (stdlib) em formato PHC: $scrypt$ln=15,r=8,p=3$<sal_b64>$<hash_b64>.

Parâmetros da OWASP (2024): N=2^15, r=8, p=3, 16 B de sal, 32 B de saída (~64 MiB de memória).
O prefixo identifica o algoritmo — trocar por argon2id no futuro é adicionar um verificador e
re-hashear no login (`precisa_rehash`), sem migration. Sem dependência nova.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_LN, _R, _P = 15, 8, 3
_SAL_BYTES, _DKLEN = 16, 32
_MAXMEM = 128 * 1024 * 1024


def _b64(dados: bytes) -> str:
    return base64.b64encode(dados).decode("ascii").rstrip("=")


def _unb64(texto: str) -> bytes:
    return base64.b64decode(texto + "=" * (-len(texto) % 4))


def _derivar(senha: str, sal: bytes, ln: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(senha.encode("utf-8"), salt=sal, n=2 ** ln, r=r, p=p, dklen=_DKLEN, maxmem=_MAXMEM)


def gerar(senha: str) -> str:
    sal = secrets.token_bytes(_SAL_BYTES)
    return f"$scrypt$ln={_LN},r={_R},p={_P}${_b64(sal)}${_b64(_derivar(senha, sal, _LN, _R, _P))}"


def _parse(hash_: str) -> tuple[int, int, int, bytes, bytes] | None:
    try:
        _, alg, params, sal, dk = hash_.split("$")
        if alg != "scrypt":
            return None
        p = dict(kv.split("=") for kv in params.split(","))
        return int(p["ln"]), int(p["r"]), int(p["p"]), _unb64(sal), _unb64(dk)
    except (ValueError, KeyError, AttributeError):
        return None


def verificar(senha: str, hash_: str | None) -> bool:
    """False para hash nulo, formato desconhecido ou senha errada — nunca levanta."""
    if not hash_:
        return False
    partes = _parse(hash_)
    if partes is None:
        return False
    ln, r, p, sal, dk = partes
    try:
        return hmac.compare_digest(_derivar(senha, sal, ln, r, p), dk)
    except ValueError:      # parâmetros fora do que a stdlib aceita
        return False


def precisa_rehash(hash_: str) -> bool:
    partes = _parse(hash_)
    return partes is None or (partes[0], partes[1], partes[2]) != (_LN, _R, _P)
