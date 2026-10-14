# -*- coding: utf-8 -*-
"""L'archiviazione dei progetti (richiesta di Silvio del 07/10).

Il testo della richiesta: «archiviare, forse meglio che eliminare del tutto, i
progetti in maniera tale che non si vedano più nella home page e che tutto
quello che è attivo sul progetto stesso (cronjob, check, email, ecc.) venga
stoppato».

Quindi due cose, e la seconda è quella che si dimentica: non basta nascondere
la card. Un progetto archiviato che continua a mandare email al cliente e a
interrogare gli assistenti AI è peggio di uno non archiviato, perché nessuno
sta più guardando.
"""
import inspect
import unittest

from tests import conftest_env  # noqa: F401

import db
import server
import views


class LeFunzioniDiArchivio(unittest.TestCase):

    def test_esistono(self):
        for nome in ("_sb_project_archivia", "_sb_project_ripristina",
                     "_sb_progetti_archiviati", "_archivio_c_e", "_filtro_attivi"):
            self.assertTrue(callable(getattr(db, nome)), nome)

    def test_senza_la_colonna_non_fingono_di_aver_fatto(self):
        """⚠️ Doppio binario come per le fasi G, H e I: il codice esce prima
        della migrazione. Finche' la colonna non c'e', archiviare deve dire NO,
        non rispondere ok e non archiviare niente."""
        vero = db._archivio_c_e
        db._archivio_c_e = lambda: False
        try:
            self.assertIs(db._sb_project_archivia("x", "a@b.it"), False)
            self.assertIs(db._sb_project_ripristina("x"), False)
            self.assertEqual(db._sb_progetti_archiviati(), [])
            self.assertEqual(db._filtro_attivi(), {})
        finally:
            db._archivio_c_e = vero

    def test_con_la_colonna_il_filtro_c_e(self):
        vero = db._archivio_c_e
        db._archivio_c_e = lambda: True
        try:
            self.assertEqual(db._filtro_attivi(), {"archived_at": "is.null"})
        finally:
            db._archivio_c_e = vero

    def test_il_ripristino_rimette_a_posto_il_prossimo_audit(self):
        """⚠️ Senza azzerare `next_scan_at`, il progetto torna in home con una
        data vecchia di mesi: il cron lo rivendica al primo giro e passa davanti
        a tutti gli altri in coda."""
        self.assertIn("next_scan_at", inspect.getsource(db._sb_project_ripristina))

    def test_si_sa_chi_ha_archiviato(self):
        """Mesi dopo, nessuno ricorda perche' quel progetto e' sparito."""
        self.assertIn("archived_by", inspect.getsource(db._sb_project_archivia))


class TuttoQuelloCheGiraSiFerma(unittest.TestCase):
    """La metà della richiesta che si dimentica."""

    def test_non_compare_piu_in_home(self):
        self.assertIn("_filtro_attivi", inspect.getsource(db._sb_projects_by_user))

    def test_l_audit_periodico_non_lo_prende_piu(self):
        self.assertIn("_filtro_attivi", inspect.getsource(db._sb_project_claim_due))

    def test_le_email_non_partono_piu(self):
        """I riepiloghi e gli avvisi di traffico girano su `_sb_progetti_tutti`:
        l'esclusione sta nel suo default, non in chi la chiama."""
        sorgente = inspect.getsource(db._sb_progetti_tutti)
        self.assertIn("includi_archiviati: bool = False", sorgente)
        self.assertIn("_filtro_attivi", sorgente)
        # e il giro dei digest la chiama senza chiedere gli archiviati
        self.assertIn("_sb_progetti_tutti()",
                      inspect.getsource(server._manda_i_digest_scaduti))

    def test_il_monitoraggio_ai_si_ferma(self):
        """⚠️ Qui il progetto si legge per id, quindi il filtro degli elenchi
        non protegge: senza un controllo esplicito un progetto archiviato
        continuerebbe a interrogare gli assistenti, cioe' a costare soldi."""
        self.assertIn('project.get("archived_at")',
                      inspect.getsource(server.api_cron_ai))


class _ColonnaPresente(unittest.TestCase):
    """Le schede si guardano come appariranno a migrazione eseguita."""

    def setUp(self):
        self._vero = views._archivio_c_e
        views._archivio_c_e = lambda: True

    def tearDown(self):
        views._archivio_c_e = self._vero


class SiRientraDallArchivio(_ColonnaPresente):
    """⚠️ Un archivio da cui non si rientra e' una cancellazione con un altro
    nome, e la richiesta diceva l'opposto («forse meglio che eliminare»)."""

    ARCHIVIATO = {"id": "11111111-1111-1111-1111-111111111111", "domain": "x.it",
                  "archived_at": "2026-10-01T10:00:00+00:00",
                  "archived_by": "silvio@verticalai.it"}
    ATTIVO = {"id": "22222222-2222-2222-2222-222222222222", "domain": "y.it"}

    def test_la_rotta_di_ripristino_esiste(self):
        percorsi = [r.path for r in server.app.routes if hasattr(r, "path")]
        self.assertIn("/project/{project_id}/ripristina", percorsi)
        self.assertIn("/project/{project_id}/archivia", percorsi)

    def test_il_progetto_archiviato_mostra_il_pulsante_di_ripristino(self):
        h = views._card_archivio(self.ARCHIVIATO)
        self.assertIn("/ripristina", h)
        self.assertIn("Ripristina progetto", h)

    def test_e_dice_quando_e_da_chi(self):
        h = views._card_archivio(self.ARCHIVIATO)
        self.assertIn("silvio@verticalai.it", h)

    def test_e_rassicura_che_i_dati_sono_la(self):
        h = views._card_archivio(self.ARCHIVIATO)
        self.assertIn("al loro posto", h)

    def test_un_progetto_attivo_mostra_invece_archivia(self):
        h = views._card_archivio(self.ATTIVO)
        self.assertIn("/archivia", h)
        self.assertNotIn("/ripristina", h)


class LaCardDiceCosaSuccede(_ColonnaPresente):

    def test_elenca_cosa_si_ferma_invece_di_chiedere_sei_sicuro(self):
        """⚠️ Chi archivia non sta chiedendosi se e' sicuro: sta chiedendosi
        cosa succede. Quattro voci, una per cosa che si ferma."""
        h = views._card_archivio({"id": "1", "domain": "x.it"})
        self.assertEqual(h.count("<li>"), 4)
        for pezzo in ("home", "audit", "monitoraggio", "avvisi"):
            self.assertIn(pezzo, h, pezzo)

    def test_dice_a_chiare_lettere_che_non_cancella(self):
        h = views._card_archivio({"id": "1", "domain": "x.it"})
        self.assertIn("Niente viene cancellato", h)

    def test_chiede_conferma(self):
        h = views._card_archivio({"id": "1", "domain": "x.it"})
        self.assertIn("confirm(", h)

    def test_la_conferma_non_spezza_l_attributo_html(self):
        """⚠️ Un apostrofo dentro l'onsubmit chiuderebbe l'attributo e il
        pulsante archivierebbe senza chiedere niente: il caso peggiore, perche'
        la pagina sembra giusta."""
        h = views._card_archivio({"id": "1", "domain": "x.it"})
        inizio = h.index('onsubmit="')
        fine = h.index('"', inizio + len('onsubmit="'))
        self.assertIn("confirm(", h[inizio:fine])
        self.assertIn("ripristinare", h[inizio:fine])

    def test_accenti_veri_non_apostrofi(self):
        """Regola di casa: «più», non «piu'»."""
        h = views._card_archivio({"id": "1", "domain": "x.it"})
        self.assertIn("più", h)
        self.assertNotIn("piu'", h)

    def test_e_agganciata_alle_impostazioni(self):
        self.assertIn("_card_archivio", inspect.getsource(views._tab_settings))


class PrimaDellaMigrazione(unittest.TestCase):
    """⚠️ Il codice esce prima che Silvio esegua lo script SQL. In quella
    finestra il pulsante non puo' funzionare, e un pulsante che non funziona e'
    peggio di un pulsante assente: chi lo preme crede di aver archiviato."""

    def setUp(self):
        self._vero = views._archivio_c_e
        views._archivio_c_e = lambda: False

    def tearDown(self):
        views._archivio_c_e = self._vero

    def test_non_mostra_un_pulsante_che_non_puo_funzionare(self):
        h = views._card_archivio({"id": "1", "domain": "x.it"})
        self.assertNotIn("/archivia", h)
        self.assertNotIn("<button", h)

    def test_dice_perche(self):
        h = views._card_archivio({"id": "1", "domain": "x.it"})
        self.assertIn("migrazione", h)


class LaMigrazione(unittest.TestCase):

    def _sql(self):
        import os
        qui = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(qui, "migrazioni-fase-m-archivio-progetti.sql"),
                  encoding="utf-8") as f:
            return f.read()

    def test_esiste(self):
        self.assertIn("archived_at", self._sql())

    def test_aggiunge_le_colonne_e_non_crea_la_tabella(self):
        """⚠️ `CREATE TABLE IF NOT EXISTS` su una tabella che esiste gia' non
        aggiunge le colonne nuove e non dice niente: sembrerebbe riuscito."""
        sql = self._sql()
        self.assertIn("ADD COLUMN IF NOT EXISTS", sql)
        # solo le righe eseguibili: «CREATE TABLE» compare nel commento che
        # spiega perche' NON si usa, e non va contato
        righe = [r for r in sql.splitlines() if not r.strip().startswith("--")]
        codice = chr(10).join(righe)
        self.assertNotIn("CREATE TABLE", codice)

    def test_si_puo_rilanciare(self):
        sql = self._sql()
        self.assertIn("CREATE INDEX IF NOT EXISTS", sql)

    def test_porta_la_sua_controprova(self):
        """Il pannello di Supabase dice «Success» anche quando non ha fatto
        niente: lo script deve stampare cosa ha creato."""
        self.assertIn("information_schema.columns", self._sql())


class LaDataNellaCardEInItaliano(unittest.TestCase):
    """⚠️ Difetto trovato guardando l'HTML che esce davvero, non ipotizzato:
    la card stampava «01 Oct 2026». `_fmt_date` usava `%b`, che dipende dalla
    locale del processo — sul server non e' impostata, quindi inglese — mentre
    la sua funzione sorella `_fmt_datetime` usava gia' `_MESI` in italiano. La
    stessa data, due lingue, diciassette punti dell'interfaccia cliente.
    """

    def test_il_mese_e_italiano(self):
        self.assertEqual(views._fmt_date("2026-10-01T10:00:00+00:00"), "1 ott 2026")

    def test_nessun_mese_inglese(self):
        inglesi = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
        for mese in range(1, 13):
            testo = views._fmt_date("2026-%02d-15T10:00:00+00:00" % mese)
            for ing in inglesi:
                self.assertNotIn(ing, testo, testo)

    def test_una_data_assente_resta_un_trattino(self):
        self.assertEqual(views._fmt_date(None), chr(0x2014))

    def test_una_data_illeggibile_non_fa_esplodere_la_pagina(self):
        self.assertEqual(views._fmt_date("ieri"), "ieri")


if __name__ == "__main__":
    unittest.main()
