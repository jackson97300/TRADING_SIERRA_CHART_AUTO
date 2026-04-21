// V2_SessionGuard.h — Filter trades par session (PURE TIME-BASED)
// =================================================================
// Design doc : DOCS/V2_BIS_DESIGN_P0.md section 4.10 + 8.3
// Statut : stub P0, implementation P1+
// LOC cible : ~120
//
// GARDE-FOU PATTERN 11 (CRITIQUE v1.1) :
// ═══════════════════════════════════════
// Ce module est PURE time-based. AUCUN MarketDataProvider injecte.
// AUCUNE reference a vix_level, atr_ticks, regime, spread, volume, orderflow.
// Test statique CI verifie absence IMarketDataProvider dans ce fichier.
// Si tentation d'ajouter "skip si VIX > 25" → retour V2CLEAN Python.

#pragma once
#include "V2_Interfaces.h"

namespace v2bis {

class V2SessionGuard {
public:
    V2SessionGuard(IConfigProvider& cfg, ITimeProvider& clock);

    // Principal check : fenetre trading autorisee ?
    bool is_trading_window() const;

    // Fenetre flatten forcee (15:55-16:00 ET) : ferme positions ouvertes
    bool is_flatten_required() const;

    // Phase actuelle pour logging/snapshot
    SessionPhase current_phase() const;

private:
    IConfigProvider& cfg_;
    ITimeProvider&   clock_;
    // PAS DE : IMarketDataProvider, pas de membres "regime", "vix", "atr"

    // Fenetres autorisees (config) :
    //   London early : 08:00-09:15 ET (MenthorQ publish levels 08:00)
    //   Pause OPR    : 09:15-10:00 ET (Opening Range Pause) → SKIP
    //   US RTH       : 10:00-15:55 ET (5 min avant close = flatten)
    //   Flatten      : 15:55-16:00 ET → close positions
    //   Asia/overnight : SKIP (edge negatif, spreads x3)
};

} // namespace v2bis

// ─── Tests cibles (9 total : 8 scenarios + 1 statique) ──────────────
//   transitions_asia_to_london,
//   transitions_london_to_opr_pause,
//   transitions_opr_to_us_rth,
//   transitions_us_rth_to_flatten_window,
//   transitions_flatten_to_closed,
//   weekend_always_closed,
//   holiday_no_trading,
//   dst_transition_handled,
//   STATIC: no_MarketDataProvider_injected  ← grep CI
