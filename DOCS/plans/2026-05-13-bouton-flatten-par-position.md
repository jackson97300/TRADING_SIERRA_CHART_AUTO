# Plan : Bouton FLATTEN par position ouverte (dashboard)

**Date** : 2026-05-12 (à exécuter 13/05)
**Demandé par** : Jackson 12/05 03:55 UTC + précision 04:00 "par position ouverte seulement"
**Objectif** : permettre fermer manuellement un trade depuis le dashboard sans accéder Sierra Chart

## Spec UI/UX

- **Visibilité** : bouton FLATTEN **uniquement** dans la card d'une position ouverte
- **Localisation** : section "TRADES EN COURS" du dashboard, dans chaque card de trade
- **Apparence** : bouton rouge, texte "🔴 FLATTEN", taille discrète (top-right de la card)
- **Confirmation** : modale "Êtes-vous sûr de fermer ce trade {sym} {direction} entry={entry} ?"
- **État** : disabled si déjà en cours de fermeture (anti double-click)
- **Réservé à OWNER tier** : `user.tier === "owner"` (vérification frontend + backend)

## Architecture technique

### Backend — Nouveau endpoint FastAPI

**Fichier** : `DASHBOARD/api/admin_routes.py` (déjà existant, ajout)

```python
@router.post("/api/bot/{bot_name}/flatten/{symbol}")
async def flatten_bot_position(
    bot_name: str,
    symbol: str,
    current_user: dict = Depends(require_owner)
):
    """Flatten une position ouverte d'un bot specifique.

    Args:
        bot_name : 'bot1' | 'bot2_v6' | 'bot3'
        symbol   : 'ES' | 'NQ' | 'MGC'

    Returns:
        {success: bool, message: str, qty_closed: int}
    """
    # 1. Lire state JSON du bot pour identifier la position
    state_files = {
        "bot1": ROOT / "DATA" / "PAPER_TRADES" / "state.json",
        "bot2_v6": ROOT / "DATA" / "PAPER_TRADES" / "state_v6.json",
        "bot3": ROOT / "DATA" / "PAPER_TRADES" / "databento_paper_v3_state.json",
    }
    if bot_name not in state_files:
        raise HTTPException(400, f"Unknown bot: {bot_name}")

    with open(state_files[bot_name]) as f:
        state = json.load(f)

    # 2. Trouver la position du symbole
    positions = state.get("positions", {}) or state.get("active_positions", {})
    pos = positions.get(symbol)
    if not pos:
        raise HTTPException(404, f"No open position for {bot_name}/{symbol}")

    # 3. Envoyer ordre FLATTEN via DTC connector
    # ATTENTION : il faut un DTC connector partagé OU un mécanisme de signal
    # cross-process (flag file dans DATA/BOT_CONTROL/) que le bot consume.

    # OPTION A (recommandée) : flag file que le bot consume
    flag_path = ROOT / "DATA" / "BOT_CONTROL" / f"FLATTEN_{bot_name}_{symbol}.flag"
    flag_path.parent.mkdir(parents=True, exist_ok=True)
    flag_data = {
        "requested_by": current_user.get("email"),
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "bot": bot_name,
        "symbol": symbol,
        "entry_price": pos.get("entry_price"),
        "n_contracts": pos.get("n_contracts", 1),
    }
    with open(flag_path, "w") as f:
        json.dump(flag_data, f)

    # 4. Log audit
    audit_log = ROOT / "LOGS" / "events" / "manual_flatten_audit.jsonl"
    audit_log.parent.mkdir(parents=True, exist_ok=True)
    with open(audit_log, "a") as f:
        f.write(json.dumps(flag_data) + "\n")

    return {
        "success": True,
        "message": f"FLATTEN requested {bot_name}/{symbol}",
        "qty_to_close": pos.get("n_contracts", 1),
    }
```

### Backend — Bot consume flag file

Dans chaque bot (`mia_paper_trader.py`, `mia2_brain_v6_databento.py`, `databento_paper_trader_v2.py`), dans la boucle principale (poll cycle), ajouter check :

```python
def _check_flatten_flag(self, symbol: str) -> bool:
    """Verifie si un flag FLATTEN manuel a ete pose pour ce bot/symbol."""
    flag_path = ROOT / "DATA" / "BOT_CONTROL" / f"FLATTEN_{self.bot_name}_{symbol}.flag"
    if not flag_path.exists():
        return False
    try:
        with open(flag_path) as f:
            flag_data = json.load(f)
        # Execute FLATTEN
        self._close_trade(symbol, price=None, reason="MANUAL_FLATTEN", flag_data=flag_data)
        # Cleanup flag
        flag_path.rename(flag_path.with_suffix(".processed"))
        _v2log.emit("MANUAL_FLATTEN_EXECUTED", sym=symbol, requested_by=flag_data.get("requested_by"))
        return True
    except Exception as e:
        _v2log.emit("MANUAL_FLATTEN_ERROR", sym=symbol, err=str(e))
        return False
```

### Frontend — Bouton dans card

**Fichier** : `DASHBOARD/static/js/dashboard.js`

Dans la fonction qui render les cards de trades en cours (chercher "TRADES EN COURS" / "trades_en_cours") :

```javascript
function renderActivePositionCard(bot, sym, pos) {
    const isOwner = window.currentUser?.tier === "owner";
    const flattenBtn = isOwner ? `
        <button class="flatten-btn" onclick="confirmFlatten('${bot}', '${sym}', '${pos.direction}', ${pos.entry_price})">
            🔴 FLATTEN
        </button>
    ` : '';

    return `
        <div class="position-card ${pos.unrealized_pnl_usd > 0 ? 'green' : 'red'}">
            <div class="position-header">
                <span>${sym} ${pos.direction}</span>
                ${flattenBtn}
                <span class="pnl">${formatUsd(pos.unrealized_pnl_usd)}</span>
            </div>
            <!-- ... reste de la card ... -->
        </div>
    `;
}

async function confirmFlatten(bot, sym, direction, entry) {
    const ok = confirm(`Fermer ce trade ${sym} ${direction} entry=${entry} ?`);
    if (!ok) return;
    const btn = event.target;
    btn.disabled = true;
    btn.textContent = "⏳ Closing...";
    try {
        const r = await fetch(`/api/bot/${bot}/flatten/${sym}`, {
            method: "POST",
            headers: { "Authorization": `Bearer ${getToken()}` }
        });
        const j = await r.json();
        if (j.success) {
            alert(`✅ FLATTEN requested. Bot will close within 30s.`);
        } else {
            alert(`❌ FLATTEN failed: ${j.message}`);
            btn.disabled = false;
            btn.textContent = "🔴 FLATTEN";
        }
    } catch (e) {
        alert(`❌ Error: ${e.message}`);
        btn.disabled = false;
        btn.textContent = "🔴 FLATTEN";
    }
}
```

### Frontend — CSS

**Fichier** : `DASHBOARD/static/css/dashboard.css`

```css
.flatten-btn {
    background: #c0392b;
    color: white;
    border: none;
    padding: 4px 12px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: bold;
    cursor: pointer;
    margin-left: auto;
    transition: background 0.15s;
}
.flatten-btn:hover {
    background: #e74c3c;
}
.flatten-btn:disabled {
    background: #555;
    cursor: not-allowed;
}
```

## Nouveaux codes log (à ajouter à `log_catalog.py`)

```python
"MANUAL_FLATTEN_REQUESTED": (LogLevel.MAJEUR, "execution", "FLATTEN manuel demande : {bot} {sym} par {user}"),
"MANUAL_FLATTEN_EXECUTED":  (LogLevel.MAJEUR, "execution", "FLATTEN manuel execute : {bot} {sym} qty={qty}"),
"MANUAL_FLATTEN_ERROR":     (LogLevel.CRITIQUE, "execution", "FLATTEN manuel ECHEC : {bot} {sym} err={err}"),
```

## Sécurité

1. **Owner only** : `require_owner` dependency FastAPI
2. **Audit trail** : `manual_flatten_audit.jsonl` avec `requested_by`, `requested_at`
3. **Anti double-click** : bouton disabled pendant l'attente
4. **Confirmation modale** : pas d'action sans confirmation explicite
5. **Logs MAJEUR** : visible immédiatement dans dashboard "Erreurs récentes"

## Tests requis avant deploy

1. Test unitaire endpoint API (mock state file)
2. Test consume flag file dans 1 bot (Bot 3 en priorité Sim1)
3. Test E2E : bouton click → flag créé → bot lit flag → ordre DTC FLATTEN → position fermée → flag.processed
4. Test sécurité : non-owner peut pas POST `/api/bot/.../flatten/...`

## Review agent obligatoire

- **code-reviewer** : architecture flag file vs API direct, race conditions, error handling
- **market-analyst** : impact sur la stratégie, cas où FLATTEN serait dangereux (pendant un setup en formation ?)

## ETA développement

| Tâche | ETA |
|---|---|
| Backend endpoint FastAPI | 1h |
| Backend bot consume flag (×3 bots) | 1.5h |
| Frontend bouton + CSS | 1h |
| Tests unitaires + E2E | 1h |
| Review agents | 1h |
| Deploy + validation | 30 min |
| **TOTAL** | **~6h** |

## Quand le faire

**Post-validation fix entry_price** (13/05 matin Jackson valide BOT_ENTRY_FILL_RECORDED OK sur N>=5 trades nouveaux).

Pas avant car :
- Si fix entry_price casse, on doit pouvoir rollback proprement
- Le bouton FLATTEN est un ajout, pas un fix critique
- Le risque trading-critical impose review agent

## Notes

- Le pattern **flag file** est choisi (vs API DTC direct) car :
  - Pas de coupling Dashboard ↔ DTC (DTC déjà busy avec bot)
  - Le bot consume le flag dans son poll cycle (déjà à 30s)
  - Audit trail explicite via file system
  - Rollback simple (delete flag file)

- Alternative API direct : plus rapide mais nécessite que Dashboard ait son propre DTC connector (overhead, race conditions avec bot)
