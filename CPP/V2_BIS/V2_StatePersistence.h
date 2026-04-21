// V2_StatePersistence.h — Atomic I/O + corruption recovery
// ==========================================================
// Design doc : DOCS/V2_BIS_DESIGN_P0.md section 4.6
// Statut : stub P0, implementation P1+
// LOC cible : ~120
// Port Python : risk_manager.py:545-564 (_write_snapshot_atomic, 20 LOC)
//              + logique restore + backup

#pragma once
#include "V2_Interfaces.h"
#include <filesystem>
#include <string>

namespace v2bis {

class V2StatePersistence : public IPersistence {
public:
    explicit V2StatePersistence(ILogger& logger, IEventJournal& journal);

    // Atomic write : tempfile + fsync + rename
    bool write_json(const std::filesystem::path& target, const void* data_ptr) override;

    // Read avec fallback backup (.bak) si corruption JSON
    bool read_json(const std::filesystem::path& target, void* out_ptr) override;

    // Backup explicite avant migration schema version
    bool backup_before_migration(const std::filesystem::path& target) override;

private:
    ILogger&        logger_;
    IEventJournal&  journal_;

    bool atomic_rename(const std::filesystem::path& tmp,
                       const std::filesystem::path& target);
    bool parse_with_fallback(const std::filesystem::path& target, void* out_ptr);
    bool restore_from_backup(const std::filesystem::path& target);
};

} // namespace v2bis

// ─── Garanties ──────────────────────────────────────────────────────
// - Jamais de fichier partiel apres crash (atomic rename)
// - Corruption JSON detectee → fallback .bak
// - Schema version check avant parse
// - Compatible Windows (MoveFileEx + MOVEFILE_REPLACE_EXISTING)
//
// Tests cibles (8) :
//   atomic_ok, crash_mid_write_simulated, corruption_detected,
//   backup_restored, windows_rename_edge, concurrent_write_es_nq,
//   disk_full_handled, permissions_denied
