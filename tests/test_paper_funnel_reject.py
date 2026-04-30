"""Tests regression bug _funnel_reject() got multiple values for argument 'reason'.

Bug observé 30/04/2026 dans paper_trader.err :
  File "CORE/mia_paper_trader.py", line 843, in check_entry
    self._funnel_reject("3_conseil", "sell_auto_disabled",
TypeError: PaperTrader._funnel_reject() got multiple values for argument 'reason'

Cause : signature `def _funnel_reject(self, step_key, reason, symbol=None, **ctx)`.
L'appel passait `reason=` en kwarg alors que `reason` est positional → conflit
avec l'argument positionnel "sell_auto_disabled".

Fix : renomme `reason=` en `disable_reason=` dans le kwarg.

Ce test pin le contrat de _funnel_reject : kwargs ne peuvent PAS contenir
les noms de parametres positionnels (step_key, reason, symbol).
"""
from __future__ import annotations

import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from CORE.mia_paper_trader import PaperTrader  # noqa: E402


# ── Test contrat signature ──────────────────────────────────────────


class TestFunnelRejectSignature:
    """Pin le contrat de _funnel_reject : positional args ne doivent pas
    apparaitre dans **kwargs des appels."""

    def test_funnel_reject_signature_has_positional_reason(self):
        sig = inspect.signature(PaperTrader._funnel_reject)
        params = sig.parameters
        # reason DOIT etre POSITIONAL_OR_KEYWORD (pas VAR_KEYWORD)
        assert "reason" in params
        assert params["reason"].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD


# ── Test regression bug 30/04 ───────────────────────────────────────


class TestSellAutoDisabledRejectNoConflict:
    """Reproduction du bug : appel _funnel_reject avec reason= kwarg + reason
    positional → TypeError."""

    def _build_mock_trader(self):
        """Mock minimal pour tester _funnel_reject sans __init__ complet."""
        trader = PaperTrader.__new__(PaperTrader)
        trader._funnel = {
            "steps": {"3_conseil": {"rejected": 0}},
            "reject_detail": {},
        }
        trader._reject_log_last_ts = {}
        # date_str requis par _log_rejection_detailed (chemin fichier rotatif)
        trader.date_str = "20260430"
        return trader

    def test_reject_with_disable_reason_kwarg_works(self, tmp_path, monkeypatch):
        """Apres fix : disable_reason= kwarg n'entre pas en conflit avec
        reason positional."""
        # Redirige le repertoire de logs vers tmp_path pour ne pas polluer
        from CORE import mia_paper_trader as mpt
        monkeypatch.setattr(mpt, "REJECTIONS_LOG_DIR", str(tmp_path))

        trader = self._build_mock_trader()

        # Appel exact qui plantait avant fix
        try:
            trader._funnel_reject(
                "3_conseil", "sell_auto_disabled",
                symbol="ES",
                action="ACHAT_PRUDENT",
                disable_reason="3 SL consecutifs",
                signal_id="abc123",
            )
        except TypeError as e:
            pytest.fail(
                f"_funnel_reject ne doit plus lever TypeError, got: {e}"
            )

        assert trader._funnel["steps"]["3_conseil"]["rejected"] == 1
        assert trader._funnel["reject_detail"]["sell_auto_disabled"] == 1

    def test_reject_with_reason_kwarg_still_raises(self):
        """Garde anti-regression : si quelqu'un re-introduit reason= kwarg
        en plus du positional, le test capture le bug."""
        trader = self._build_mock_trader()

        # Tentative d'usage incorrect (deux fois reason)
        with pytest.raises(TypeError, match="reason"):
            trader._funnel_reject(
                "3_conseil", "sell_auto_disabled",
                symbol="ES",
                reason="Should NOT be a kwarg",  # CONFLIT volontaire
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
