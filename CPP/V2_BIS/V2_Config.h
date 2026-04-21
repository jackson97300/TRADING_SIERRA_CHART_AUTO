// V2_Config.h — Configuration centralisee
// ==========================================
// Design doc : DOCS/V2_BIS_DESIGN_P0.md section 4.5
// Statut : stub P0, implementation P1+
// LOC cible : ~100

#pragma once
#include "V2_Interfaces.h"

namespace v2bis {

class V2Config : public IConfigProvider {
public:
    static V2Config& instance();

    // IConfigProvider
    const PathConfig&      paths() const override;
    const RiskConfig&      risk() const override;
    const SessionConfig&   sessions() const override;
    const ExecutionConfig& execution() const override;
    const HealthConfig&    health() const override;

    // Hot reload via Analysis → Reload Custom Studies DLL
    void reload_from_disk() override;

private:
    V2Config();                                  // singleton
    V2Config(const V2Config&) = delete;
    V2Config& operator=(const V2Config&) = delete;

    void load_defaults();                        // fallback si config.json absent
    bool load_from_file(const std::filesystem::path& path);

    PathConfig      paths_;
    RiskConfig      risk_;
    SessionConfig   sessions_;
    ExecutionConfig execution_;
    HealthConfig    health_;
};

} // namespace v2bis

// ─── Defaults hardcoded (fallback) ──────────────────────────────────
// Chemins : V2_BIS_STATE, V2_BIS_SNAPSHOTS, V2_BIS_JOURNAL
// Risk : catastrophe=$850 / daily=$500 / intraday=$300 / max_trades=5
// Sessions : London 08:00-09:15 ET / Pause OPR 09:15-10:00 / US 10:00-16:00
// Execution : smart_entry=3t / trailing=0.5*SL / BE=0.3*TP
// Health : heartbeat=1s / stale_warn=30s / stale_block=120s / zombie=15-30 min
