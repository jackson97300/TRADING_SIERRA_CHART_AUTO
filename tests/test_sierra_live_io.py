"""Tests unitaires CORE/sierra_live_io.py — lecteur stream Sierra DMP.

Cree 06/06/2026 pour Phase 1.3 migration full Sierra Chart.
Couvre les 14 scenarios cles :

1. Validation symbole ES / NQ accepte
2. Validation symbole MGC raise ValueError (V1 not supported)
3. Validation symbole lowercase normalisation
4. Validation symbole avec suffixe ".c.0" stripped
5. Reader init etat vide
6. Reader strict=True + pas de fichier = FileNotFoundError
7. Reader strict=False + pas de fichier = None
8. Schema 3.7.14 detection
9. Schema 3.7.15 detection
10. Schema unknown raise ValueError
11. Dedup ts (idempotence)
12. Cast defensif numeric cols
13. get_last_bar_age_seconds empty
14. Buffer cap window_bars

Convention DMP Sierra utilisee dans les fixtures (cf inspection 06/06) :
- `ts` en millisecondes epoch UTC (PAS ts_event_ns nanosecondes)
- `delta_bar` saint (Ask - Bid volumes)
- 268 features 3.7.14 / 272 features 3.7.15
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from CORE.sierra_live_io import (
    SierraLiveReader,
    SUPPORTED_SYMBOLS,
    ACCEPTED_SCHEMAS,
    _validate_symbol,
    _detect_schema_version,
)


def _make_bar(ts_ms: int, **overrides) -> dict:
    """Fixture minimaliste : bar Sierra DMP avec champs critiques.

    Inclut ts (ms), delta_bar (signe critique), cvd_day, atr.
    """
    bar = {
        "ts": ts_ms,
        "delta_bar": -10.0,
        "delta_day": -150.0,
        "cvd_day": -2500.0,
        "delta_day_dir": -1,
        "cvd_day_dir": -1,
        "ask_bid_imbalance": -0.05,
        "atr": 450.0,
        "atr_14m": 50.0,
        "price": 30000.0,
        "bar_high": 30005.0,
        "bar_low": 29995.0,
        "vwap_d_side": -1,
        "vwap_slope_10_dir": -1,
    }
    bar.update(overrides)
    return bar


class TestValidateSymbol(unittest.TestCase):
    """Tests _validate_symbol — normalisation et rejet symboles non supportes."""

    def test_es_accepted(self):
        self.assertEqual(_validate_symbol("ES"), "ES")

    def test_nq_accepted(self):
        self.assertEqual(_validate_symbol("NQ"), "NQ")

    def test_lowercase_normalized(self):
        self.assertEqual(_validate_symbol("nq"), "NQ")

    def test_with_databento_suffix_stripped(self):
        """NQ.c.0 (Databento format) doit etre normalise en 'NQ'."""
        self.assertEqual(_validate_symbol("NQ.c.0"), "NQ")
        self.assertEqual(_validate_symbol("ES.c.0"), "ES")

    def test_mgc_rejected(self):
        """MGC pas supporte par DMP Sierra V1 (cf VPS check 06/06)."""
        with self.assertRaises(ValueError) as ctx:
            _validate_symbol("MGC")
        self.assertIn("MGC", str(ctx.exception))
        self.assertIn("Phase 8+", str(ctx.exception))

    def test_unknown_symbol_rejected(self):
        with self.assertRaises(ValueError):
            _validate_symbol("BTC")


class TestSchemaDetection(unittest.TestCase):
    """Tests _detect_schema_version — fail-loud sur schema inconnu."""

    def test_schema_3_7_14_in_root(self):
        bar = {"schema_version": "3.7.14", "ts": 1780437660000}
        self.assertEqual(_detect_schema_version(bar), "3.7.14")

    def test_schema_3_7_15_in_root(self):
        bar = {"schema_version": "3.7.15", "ts": 1780437660000}
        self.assertEqual(_detect_schema_version(bar), "3.7.15")

    def test_schema_in_meta(self):
        bar = {"meta": {"schema_version": "3.7.14"}, "ts": 1780437660000}
        self.assertEqual(_detect_schema_version(bar), "3.7.14")

    def test_schema_absent_returns_none(self):
        """Sierra DMP n'ecrit pas schema_version dans chaque bar - OK."""
        bar = {"ts": 1780437660000}
        self.assertIsNone(_detect_schema_version(bar))

    def test_schema_unknown_raises(self):
        """Schema non reconnu = abort migration plutot que silent desync."""
        bar = {"schema_version": "999.0.0", "ts": 1780437660000}
        with self.assertRaises(ValueError) as ctx:
            _detect_schema_version(bar)
        self.assertIn("999.0.0", str(ctx.exception))


class TestReaderInit(unittest.TestCase):
    """Tests SierraLiveReader.__init__ — etat initial."""

    def test_buffer_empty_at_init(self):
        r = SierraLiveReader(symbol="NQ", strict=False)
        self.assertEqual(r.get_buffer_size(), 0)
        self.assertIsNone(r.get_schema_version())

    def test_last_bar_age_empty_buffer(self):
        r = SierraLiveReader(symbol="NQ", strict=False)
        self.assertEqual(r.get_last_bar_age_seconds(), 999999.0)


class TestReaderStrictMode(unittest.TestCase):
    """Tests strict=True (fail-loud) vs strict=False (silent OK)."""

    def test_strict_raises_when_no_files(self):
        """strict=True doit raise FileNotFoundError si pas de fichier daily."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("CORE.sierra_live_io.DMP_BASE", Path(tmpdir)):
                r = SierraLiveReader(symbol="NQ", strict=True)
                with self.assertRaises(FileNotFoundError) as ctx:
                    r.load_rolling_window()
                self.assertIn("NQ", str(ctx.exception))

    def test_non_strict_returns_none_when_no_files(self):
        """strict=False doit retourner None silencieusement."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("CORE.sierra_live_io.DMP_BASE", Path(tmpdir)):
                r = SierraLiveReader(symbol="NQ", strict=False)
                self.assertIsNone(r.load_rolling_window())


class TestReaderIncrementalLoad(unittest.TestCase):
    """Tests load_rolling_window — incremental, dedup, cast."""

    def _write_jsonl(self, path: Path, bars: list):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            for b in bars:
                fh.write(json.dumps(b) + "\n")

    def test_dedup_ts(self):
        """2 bars avec meme ts = 1 seule dans le buffer (defense profondeur)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            now_utc = datetime.now(timezone.utc)
            day_str = now_utc.strftime("%Y%m%d")
            fp = Path(tmpdir) / "NQ" / f"{day_str}_NQ.jsonl"
            ts_base = int(now_utc.timestamp() * 1000)

            bars = [
                _make_bar(ts_base + 60000),    # bar 1
                _make_bar(ts_base + 60000),    # bar dupliquee meme ts
                _make_bar(ts_base + 120000),   # bar 2
            ]
            self._write_jsonl(fp, bars)

            with patch("CORE.sierra_live_io.DMP_BASE", Path(tmpdir)):
                r = SierraLiveReader(symbol="NQ", strict=False)
                df = r.load_rolling_window()
                # Apres dedup : 2 bars uniques (pas 3)
                self.assertEqual(len(df), 2)

    def test_cast_defensif_numeric_cols(self):
        """Bar avec str au lieu de float pour delta_bar -> pd.to_numeric coerce."""
        with tempfile.TemporaryDirectory() as tmpdir:
            now_utc = datetime.now(timezone.utc)
            day_str = now_utc.strftime("%Y%m%d")
            fp = Path(tmpdir) / "NQ" / f"{day_str}_NQ.jsonl"
            ts_base = int(now_utc.timestamp() * 1000)

            bar_bad = _make_bar(ts_base + 60000, delta_bar="-50.5")    # str au lieu de float
            self._write_jsonl(fp, [bar_bad])

            with patch("CORE.sierra_live_io.DMP_BASE", Path(tmpdir)):
                r = SierraLiveReader(symbol="NQ", strict=False)
                df = r.load_rolling_window()
                self.assertEqual(df.delta_bar.dtype.kind, "f")    # float
                self.assertEqual(df.delta_bar.iloc[0], -50.5)

    def test_buffer_cap_window_bars(self):
        """Buffer doit etre cap a window_bars (drop oldest).

        Respecte assertion R4 code-reviewer 06/06 : window_bars >= 240.
        Test 250 bars cappes a 240 (10 bars droppes).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            now_utc = datetime.now(timezone.utc)
            day_str = now_utc.strftime("%Y%m%d")
            fp = Path(tmpdir) / "NQ" / f"{day_str}_NQ.jsonl"
            ts_base = int(now_utc.timestamp() * 1000)

            bars = [_make_bar(ts_base + i * 60000) for i in range(250)]
            self._write_jsonl(fp, bars)

            with patch("CORE.sierra_live_io.DMP_BASE", Path(tmpdir)):
                r = SierraLiveReader(symbol="NQ", window_bars=240, strict=False)
                df = r.load_rolling_window()
                self.assertEqual(len(df), 240)
                # Doit avoir garde les 240 plus recentes (offset 10-249)
                first_ts = df.ts.iloc[0]
                self.assertEqual(first_ts, ts_base + 10 * 60000)

    def test_window_bars_too_small_raises(self):
        """Fix R4 : window_bars < 240 doit raise (anti config bot accidente)."""
        with self.assertRaises(ValueError) as ctx:
            SierraLiveReader(symbol="NQ", window_bars=100, strict=False)
        self.assertIn("240", str(ctx.exception))

    def test_meta_schema_detection(self):
        """Fix B1 : schema_version doit etre lu depuis le .meta.json separe.

        Sierra DMP n'ecrit PAS schema_version dans les bars JSONL,
        UNIQUEMENT dans le `.meta.json` accompagnant.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            now_utc = datetime.now(timezone.utc)
            day_str = now_utc.strftime("%Y%m%d")
            jsonl_fp = Path(tmpdir) / "NQ" / f"{day_str}_NQ.jsonl"
            meta_fp = Path(tmpdir) / "NQ" / f"{day_str}_NQ.meta.json"
            ts_base = int(now_utc.timestamp() * 1000)

            # Bar SANS schema_version (comportement reel Sierra DMP)
            bars = [_make_bar(ts_base + i * 60000) for i in range(250)]
            self._write_jsonl(jsonl_fp, bars)

            # meta.json avec schema_version (la SEULE source en prod)
            meta_fp.parent.mkdir(parents=True, exist_ok=True)
            with open(meta_fp, "w", encoding="utf-8") as fh:
                json.dump({"schema_version": "3.7.15", "n_columns": 272}, fh)

            with patch("CORE.sierra_live_io.DMP_BASE", Path(tmpdir)):
                r = SierraLiveReader(symbol="NQ", window_bars=240, strict=False)
                _ = r.load_rolling_window()    # trigger meta read
                self.assertEqual(r.get_schema_version(), "3.7.15")

    def test_ts_out_of_ms_range_raises(self):
        """Fix B2 : ts en nanosecondes (ou autre unit) doit fail-loud.

        Anti silent fallback identique au bug delta_bar Databento qu'on fuit.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            now_utc = datetime.now(timezone.utc)
            day_str = now_utc.strftime("%Y%m%d")
            fp = Path(tmpdir) / "NQ" / f"{day_str}_NQ.jsonl"

            # Bar avec ts en nanosecondes (16 chiffres au lieu de 13)
            bar_bad = _make_bar(int(now_utc.timestamp() * 1e9))  # ns au lieu de ms
            self._write_jsonl(fp, [bar_bad])

            with patch("CORE.sierra_live_io.DMP_BASE", Path(tmpdir)):
                r = SierraLiveReader(symbol="NQ", window_bars=240, strict=False)
                with self.assertRaises(ValueError) as ctx:
                    r.load_rolling_window()
                self.assertIn("ms", str(ctx.exception).lower())

    def test_skip_truncated_lines(self):
        """Lignes JSON tronquees skipped silencieusement (DMP flush mid-bar)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            now_utc = datetime.now(timezone.utc)
            day_str = now_utc.strftime("%Y%m%d")
            fp = Path(tmpdir) / "NQ" / f"{day_str}_NQ.jsonl"
            ts_base = int(now_utc.timestamp() * 1000)

            fp.parent.mkdir(parents=True, exist_ok=True)
            with open(fp, "w", encoding="utf-8") as fh:
                # Bar valide
                fh.write(json.dumps(_make_bar(ts_base + 60000)) + "\n")
                # Ligne tronquee (pas de \n final, JSON incomplet)
                fh.write('{"ts": 99999, "delta_bar":')

            with patch("CORE.sierra_live_io.DMP_BASE", Path(tmpdir)):
                r = SierraLiveReader(symbol="NQ", strict=False)
                df = r.load_rolling_window()
                # Seule la bar valide dans buffer
                self.assertEqual(len(df), 1)
                self.assertEqual(df.delta_bar.iloc[0], -10.0)


class TestRolloverSessionDateLookahead(unittest.TestCase):
    """Tests fix 15/06/2026 : lookahead +1 jour pour rollover DMP session-date.

    Le DMP Sierra Chart rolle le fichier `YYYYMMDD_SYM.jsonl` a 18:00 ET
    (= 22:00 UTC) par convention CME Globex "session day". Sans lookahead,
    l'enricher tournant en UTC pure rate ~2h de bars/jour entre 22:00 UTC
    et 00:00 UTC suivant.
    """

    def test_lookahead_includes_tomorrow_file_if_exists(self):
        """Si DMP a roll vers `YYYYMMDD+1_SYM.jsonl` (UTC tomorrow), il est inclus."""
        from CORE.sierra_live_io import _list_recent_daily_paths

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            es_dir = base / "ES"
            es_dir.mkdir()
            now_utc = datetime.now(timezone.utc)
            today_str = now_utc.strftime("%Y%m%d")
            tomorrow_str = (now_utc + timedelta(days=1)).strftime("%Y%m%d")

            # Crée today + tomorrow (simule rollover DMP session-date à 22:00 UTC)
            (es_dir / f"{today_str}_ES.jsonl").write_text("{}\n", encoding="utf-8")
            (es_dir / f"{tomorrow_str}_ES.jsonl").write_text("{}\n", encoding="utf-8")

            with patch("CORE.sierra_live_io.DMP_BASE", base):
                paths = _list_recent_daily_paths("ES", n_days=2)

            names = [p.name for p in paths]
            self.assertIn(f"{today_str}_ES.jsonl", names)
            self.assertIn(
                f"{tomorrow_str}_ES.jsonl", names,
                msg=(
                    "Fix 15/06 manquant : tomorrow file existe sur disque mais pas "
                    "remonte. Cause bug enricher gele 22:01 UTC sur file ancien."
                ),
            )
            # Ordre chronologique : tomorrow en dernier
            self.assertEqual(names[-1], f"{tomorrow_str}_ES.jsonl")

    def test_lookahead_skips_tomorrow_file_if_absent(self):
        """Si pas de file tomorrow (cas normal weekday), pas d'ajout fantome."""
        from CORE.sierra_live_io import _list_recent_daily_paths

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            es_dir = base / "ES"
            es_dir.mkdir()
            now_utc = datetime.now(timezone.utc)
            today_str = now_utc.strftime("%Y%m%d")
            (es_dir / f"{today_str}_ES.jsonl").write_text("{}\n", encoding="utf-8")

            with patch("CORE.sierra_live_io.DMP_BASE", base):
                paths = _list_recent_daily_paths("ES", n_days=2)

            names = [p.name for p in paths]
            tomorrow_str = (now_utc + timedelta(days=1)).strftime("%Y%m%d")
            self.assertNotIn(f"{tomorrow_str}_ES.jsonl", names)
            self.assertEqual(len(paths), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
