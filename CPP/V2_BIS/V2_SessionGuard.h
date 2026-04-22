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

// v1.4.3 (22/04 Plan V2_SessionGuard) : implemente ISessionWindow pour
// injection dans V2_HealthCheck (zombie RTH detection sans couplage concret).
class V2SessionGuard : public ISessionWindow {
public:
    V2SessionGuard(IConfigProvider& cfg, ITimeProvider& clock);

    // Principal check : fenetre trading autorisee ?
    bool is_trading_window() const;

    // Phase actuelle pour logging/snapshot.
    // v1.4.3 (Plan Q4) : is_flatten_required() SUPPRIME (redondance).
    // Utiliser helper libre is_flatten(SessionPhase) de V2_Types.h :
    //   if (is_flatten(session.current_phase())) order_exec.flatten_all(...);
    SessionPhase current_phase() const;

    // ISessionWindow impl : v1.4.3 pour injection V2_HealthCheck
    bool is_rth_active() const override;

private:
    IConfigProvider& cfg_;
    ITimeProvider&   clock_;
    // PAS DE : IMarketDataProvider, pas de membres "regime", "vix", "atr"

    // v1.4.3 (Plan Q2) : weekend/holiday via std::chrono C++20 INTERNE.
    // PAS d'ajout day_of_week_et() a ITimeProvider (ISP : orderflow ne l'utilise pas).
    // Calcul weekday depuis clock_.now_ms() + std::chrono::zoned_time("America/New_York").
    // Holidays CBOE 2026 hardcoded dans .cpp : static constexpr array<date, 10>
    //   (New Year, MLK, Presidents, Good Friday 2026-04-03, Memorial, Juneteenth,
    //    July 4, Labor, Thanksgiving, Christmas).
    // IMarketCalendar dedie = over-engineering pour 10 dates/an.
    bool is_market_day() const;  // !weekend && !holiday

    // Fenetres autorisees (v1.4.3 : US RTH ONLY, cf project_v2clean_multi_session.md) :
    //   US RTH       : 09:30-15:55 ET (5 min avant close = flatten)
    //   Flatten      : 15:55-16:00 ET → close positions
    //   London/Asia/overnight : SKIP (edge negatif, spreads x3 — dead code retire)
};

} // namespace v2bis

// ─── Tests cibles (v1.4.3 : 7 total, retire 2 London) ──────────────
//   transitions_closed_to_us_rth         (09:29 → 09:30 ET)
//   transitions_us_rth_to_flatten_window (15:54 → 15:55 ET)
//   transitions_flatten_to_closed        (15:59 → 16:00 ET)
//   weekend_always_closed                (std::chrono::weekday samedi/dimanche)
//   holiday_no_trading                   (2026-04-03 Good Friday)
//   dst_transition_handled               (2026-03-08 spring forward)
//   STATIC: no_MarketDataProvider_injected  ← grep CI
//
// Retirés v1.4.3 (Plan Q1, London supprime) :
//   transitions_asia_to_london, transitions_london_to_opr_pause
