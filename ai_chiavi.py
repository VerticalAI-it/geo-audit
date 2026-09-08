# -*- coding: utf-8 -*-
"""Le chiavi API dei provider AI: cifrate a riposo, mai in chiaro.

Il documento lo mette fra i requisiti **non negoziabili**: chi legge la tabella
`llm_provider_config` non deve avere in mano niente di utilizzabile, e
l'interfaccia non deve mai mostrare più degli ultimi caratteri.

⚠️ La decifratura sta **in un punto solo** — questo file — apposta: se fosse
sparsa, prima o poi una chiave finirebbe in un log, in una risposta JSON o in
una pagina. Qui si può controllare che non succeda.

⚠️ La chiave di cifratura viene da `CHIAVE_CIFRATURA` nell'ambiente. Se manca,
il modulo **non inventa un ripiego**: dice che non è configurato e le chiavi non
si salvano. Cifrare con un segreto prevedibile darebbe l'impressione della
sicurezza senza averla, che è peggio del non cifrare — perché nessuno andrebbe
più a controllare.
"""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

_SEGRETO = os.environ.get("CHIAVE_CIFRATURA", "")


class CifraturaNonConfigurata(Exception):
    """Manca `CHIAVE_CIFRATURA`: senza, le chiavi API non si possono custodire."""


def _serratura() -> Fernet:
    if not _SEGRETO:
        raise CifraturaNonConfigurata(
            "manca CHIAVE_CIFRATURA nell'ambiente: le chiavi API non si salvano")
    # Fernet vuole 32 byte in base64: il segreto scritto a mano si porta a
    # quella forma con uno hash, così può essere una frase qualsiasi.
    materiale = hashlib.sha256(_SEGRETO.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(materiale))


def configurata() -> bool:
    """Se il prodotto è in grado di custodire una chiave. Da controllare PRIMA
    di offrire all'utente un campo dove scriverla."""
    return bool(_SEGRETO)


def cifra(chiave_in_chiaro: str) -> str:
    if not chiave_in_chiaro:
        return ""
    return _serratura().encrypt(chiave_in_chiaro.encode()).decode()


def decifra(chiave_cifrata: str) -> str:
    """Torna stringa vuota se non si riesce a decifrare.

    ⚠️ Succede se `CHIAVE_CIFRATURA` è cambiata: le chiavi salvate prima
    diventano illeggibili. Non è un errore da nascondere — chi chiama deve
    trattarlo come «chiave assente» e farla reinserire, non come un guasto
    momentaneo da riprovare.
    """
    if not chiave_cifrata:
        return ""
    try:
        return _serratura().decrypt(chiave_cifrata.encode()).decode()
    except (InvalidToken, CifraturaNonConfigurata, Exception):
        return ""


def mascherata(chiave_in_chiaro: str) -> str:
    """Come si mostra una chiave in pagina: `sk-…a83f`, mai per intero."""
    if not chiave_in_chiaro:
        return ""
    coda = chiave_in_chiaro[-4:]
    testa = chiave_in_chiaro[:3] if len(chiave_in_chiaro) > 10 else ""
    return f"{testa}…{coda}"
