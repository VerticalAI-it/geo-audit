# -*- coding: utf-8 -*-
"""6.1 · Chi vede cosa: il piano di un progetto e cosa sblocca.

Fino a qui nel prodotto non esisteva nessun concetto di piano: tutto era
visibile a tutti. Le decisioni su *quali* funzioni stanno di qua e di là erano
però già prese nel documento, e sono quelle riportate in `FUNZIONI`.

⚠️ **I prezzi non stanno qui e non stanno da nessuna parte nel codice.** Sono
vuoti apposta (`LISTINO`): il modello commerciale è una decisione di Vertical
AI, e un numero scritto «per ora» in un file diventa il numero vero il giorno
che qualcuno lo legge senza sapere che era un segnaposto.

⚠️ Il piano sta sul **progetto**, non sul cliente: un'agenzia può avere un
sito in prova e tre a pagamento, ed è il caso normale, non l'eccezione.
"""
from __future__ import annotations

FREE = "free"
PAID = "paid"
PIANI = (FREE, PAID)

NOME_PIANO = {FREE: "Base", PAID: "Completo"}


# Cosa sblocca ogni piano. `True` = incluso; `"teaser"` = si vede che esiste
# ma non si apre; `False` = non compare proprio.
#
# ⚠️ La differenza fra `teaser` e `False` è una scelta commerciale esplicita
# del documento: «si mostra che la funzione esiste anche quando non la si
# calcola». Nascondere del tutto una funzione non vende niente; mostrarla
# spenta dice al cliente cosa si sta perdendo. Ma va fatto senza ingannare —
# il pannello bloccato dichiara che è bloccato, non finge di caricare.
FUNZIONI = {
    "punteggio":        {FREE: True,     PAID: True},
    "report_completo":  {FREE: True,     PAID: True},
    "criticita":        {FREE: True,     PAID: True},
    "traffico_ai":      {FREE: True,     PAID: True},
    "roadmap_90":       {FREE: "teaser", PAID: True},
    "punteggio_motore": {FREE: "teaser", PAID: True},
    "citazioni":        {FREE: "teaser", PAID: True},
    "competitors":      {FREE: "teaser", PAID: True},
}

ETICHETTA = {
    "roadmap_90": "Piano a 90 giorni",
    "punteggio_motore": "Punteggio per assistente",
    "citazioni": "Citazioni negli assistenti AI",
    "competitors": "Confronto coi concorrenti",
}

# ⚠️ Vuoto di proposito: i prezzi li decide Vertical AI. Quando ci saranno,
# vanno qui e in nessun altro posto — un prezzo scritto in due file diverge
# al primo aggiornamento.
LISTINO: dict = {
    FREE: {"prezzo": None, "periodo": None},
    PAID: {"prezzo": None, "periodo": None},
}


def piano_del_progetto(project: dict | None) -> str:
    """Il piano di un progetto.

    ⚠️ Chi non ha un piano scritto è `paid`, non `free`. I progetti che
    esistono oggi sono stati creati quando i piani non c'erano e i loro
    proprietari vedono tutto: farli diventare `free` da un giorno all'altro
    toglierebbe loro funzioni che usano. Il `free` si assegna, non si eredita.
    """
    if not project:
        return PAID
    piano = (project.get("plan") or "").strip().lower()
    return piano if piano in PIANI else PAID


def stato(project: dict | None, funzione: str) -> bool | str:
    """`True`, `"teaser"` o `False` per questa funzione su questo progetto."""
    riga = FUNZIONI.get(funzione)
    if riga is None:
        return True                    # funzione non governata: visibile
    return riga[piano_del_progetto(project)]


def incluso(project: dict | None, funzione: str) -> bool:
    return stato(project, funzione) is True


def solo_assaggio(project: dict | None, funzione: str) -> bool:
    return stato(project, funzione) == "teaser"
