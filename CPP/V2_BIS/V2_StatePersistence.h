// V2_StatePersistence.h — Atomic I/O + corruption recovery
// ==========================================================
// Design doc : DOCS/V2_BIS_DESIGN_P0.md section 4.6
// Statut : stub P0, implementation P1+
// LOC cible : ~120
// Port Python : V1CLEAN/risk/risk_manager.py equivalent atomic write
// (ref exacte a confirmer P1 — incident COMMENT_FALSE 22/04 : reference
// "risk_manager.py:545-564" du stub initial non verifiee empiriquement).

#pragma once
#include "V2_Interfaces.h"
#include <filesystem>
#include <string>

namespace v2bis {

class V2StatePersistence : public IPersistence {
public:
    explicit V2StatePersistence(ILogger& logger, IEventJournal& journal);

    // v1.4.3 (22/04 Plan D1+D2) : signature Result<T> + nlohmann::json.
    // Atomic write : tempfile + fsync + MoveFileEx REPLACE_EXISTING.
    Result<void>           write_json(const std::filesystem::path& target,
                                      const nlohmann::json& data) override;

    // Read avec fallback .bak si corruption JSON (retourne PersistenceError::BackupUsed).
    Result<nlohmann::json> read_json(const std::filesystem::path& target) override;

    // Backup explicite avant migration schema version (nomme .bak.v{N}).
    Result<void>           backup_before_migration(const std::filesystem::path& target) override;

    // v1.4.3 Plan R4 : schema version exposee (garantie design doc L44).
    Result<int>            read_schema_version(const std::filesystem::path& target) override;

private:
    ILogger&        logger_;
    IEventJournal&  journal_;

    Result<void>           atomic_rename(const std::filesystem::path& tmp,
                                         const std::filesystem::path& target);
    Result<nlohmann::json> parse_with_fallback(const std::filesystem::path& target);
    Result<nlohmann::json> restore_from_backup(const std::filesystem::path& target);

    // v1.4.3 Plan suggestion : cleanup *.tmp orphelins au boot (scenario B crash mid-write).
    void                   cleanup_orphan_temps();
};

} // namespace v2bis

// ─── Garanties ──────────────────────────────────────────────────────
// - Jamais de fichier partiel apres crash (atomic rename MoveFileEx)
// - Corruption JSON detectee → fallback .bak (PersistenceError::BackupUsed)
// - Schema version check via read_schema_version() (API exposee v1.4.3)
// - Compatible Windows (MoveFileEx + MOVEFILE_REPLACE_EXISTING + retry si locked)
// - Cleanup .tmp orphelins au constructeur (crash recovery automatic)
//
// ─── THREAD-SAFETY (v1.4.3 Plan R3) ─────────────────────────────────
// NOT thread-safe by design. Caller responsable serialization :
//   Mutex Windows Named Kernel cross-process ES vs NQ (section 7.9).
//   Atomic rename garantit SEULEMENT absence fichier partiel,
//   pas last-writer-wins ordering sur concurrent writes.
// Test concurrent_write_es_nq = verifier 2 writes sans mutex ne corrompent pas
// le fichier (atomic rename), PAS ordering garanti.
//
// ─── Tests cibles (8) ──────────────────────────────────────────────
//   atomic_ok, crash_mid_write_simulated, corruption_detected,
//   backup_restored, windows_rename_edge, concurrent_write_es_nq,
//   disk_full_handled, permissions_denied
//   (tests distincts IoError/Corrupted/SchemaMismatch possibles avec
//    Result<T> granulaire v1.4.3)
