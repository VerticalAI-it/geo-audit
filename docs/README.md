# Documentazione — GEO Audit (Vertical AI)

Documentazione completa della piattaforma: cosa è stato costruito, come funziona,
com'è messa oggi e cosa manca. Pensata per essere letta da uno sviluppatore che
entra sul progetto e per essere la base su cui costruire la roadmap.

Ultimo allineamento al codice: **18 agosto 2026** (commit `b29a35d`).

---

## Da dove partire

**Se entri ora sul progetto**, in quest'ordine:

1. [01 · Il prodotto](01-prodotto.md) — cos'è, per chi, cosa fa oggi
2. [02 · Architettura](02-architettura.md) — stack, deploy, flussi, decisioni
3. [08 · Setup e deploy](08-setup-e-deploy.md) — far girare tutto in locale
4. [10 · Stato e debito tecnico](10-stato-e-debito-tecnico.md) — dove sono le mine

**Se devi pianificare**, in quest'ordine:

1. [09 · Storia e changelog](09-storia-e-changelog.md) — come ci siamo arrivati
2. [10 · Stato e debito tecnico](10-stato-e-debito-tecnico.md) — cosa va sanato
3. [11 · Next steps](11-next-steps.md) — backlog operativo, stimato e sequenziato
4. [roadmap.md](roadmap.md) — roadmap di prodotto per versione

---

## Indice completo

### Come funziona

| Doc | Contenuto |
|---|---|
| [01 · Il prodotto](01-prodotto.md) | Value proposition, utenti, cosa è disponibile oggi, cosa no |
| [02 · Architettura](02-architettura.md) | Stack, deploy Vercel, flussi runtime, decisioni architetturali e loro perché |
| [03 · Audit engine](03-audit-engine.md) | `geo_audit.py`: crawl, catalogo completo dei 28 check, scoring, report |
| [04 · Modello dati](04-data-model.md) | Schema Supabase, RLS, ciclo di vita delle issue, migrazioni |
| [05 · Applicazione web](05-applicazione-web.md) | Tutte le route, auth magic link, dashboard, 12 tab di progetto, tracking |
| [06 · Email](06-email.md) | Inventario delle 8 email transazionali, trigger, quali sono orfane |
| [07 · Design system](07-design-system.md) | Token, font, componenti, regole per non rompere la coerenza visiva |

### Come operarlo

| Doc | Contenuto |
|---|---|
| [08 · Setup e deploy](08-setup-e-deploy.md) | Variabili d'ambiente, dev locale, Docker, deploy Vercel, migrazioni, seed demo |

### Dove siamo e dove andiamo

| Doc | Contenuto |
|---|---|
| [09 · Storia e changelog](09-storia-e-changelog.md) | Fasi A→E, cronologia, cosa è stato provato e abbandonato |
| [10 · Stato e debito tecnico](10-stato-e-debito-tecnico.md) | Limiti noti, codice morto, rischi, incoerenze documentazione/codice |
| [11 · Next steps](11-next-steps.md) | Backlog operativo consolidato: cosa fare, in che ordine, con quali dipendenze |
| [roadmap.md](roadmap.md) | Roadmap di prodotto per versione (v1.x fatto, v2.x da fare) |
| [backlog/](backlog/) | Note grezze e gap analysis con decisioni di prodotto già prese |

---

## Altre fonti di verità nel repo

Questi file **non** sono in `docs/` ma sono normativi:

| File | Cosa contiene | Chi lo deve leggere |
|---|---|---|
| [`CLAUDE.md`](../CLAUDE.md) | Regole operative per chi modifica il codice (in particolare UX/UI e deploy) | Chiunque tocchi il repo |
| [`design_system/DESIGN_SYSTEM.md`](../design_system/DESIGN_SYSTEM.md) | Design system: token, font, componenti, email | Chiunque tocchi HTML/CSS/email |
| [`design_system/ds_components/ds.html`](../design_system/ds_components/ds.html) | Showcase visivo dei componenti | Frontend |
| [`supabase_setup.sql`](../supabase_setup.sql) | Migrazione completa dello schema (idempotente) | Chi mette in piedi un ambiente |
| [`.env.example`](../.env.example) | Variabili d'ambiente richieste | Chi mette in piedi un ambiente |

> ⚠️ Il [`README.md`](../README.md) alla radice è **obsoleto**: descrive la Fase A
> (audit anonimo, deploy su Railway/Render, endpoint PDF) che non è più com'è fatto
> il prodotto. Vedi [10 · Stato e debito tecnico](10-stato-e-debito-tecnico.md#documentazione-disallineata).

---

## Convenzioni di questa documentazione

- **Tutti i riferimenti a file e righe sono link cliccabili** e verificati contro
  il commit `b29a35d`. Se rinomini una funzione, cerca il suo nome qui dentro.
- Quando un comportamento è una **scelta deliberata**, è documentato il perché.
  Quando è un **limite noto**, è marcato come tale — non come feature.
- La documentazione **non ripete il codice**: descrive contratti, flussi e vincoli.
  Per il dettaglio implementativo il codice resta l'unica verità.
