# Regle TICK_SIZE — Policy long terme MGC (10/05/2026)

## Source unique de verite

**`CORE/constants.py`** est la SEULE source de verite pour `TICK_SIZE` et `TICK_VALUE`.
Tout autre fichier qui a besoin du tick d'un instrument DOIT :

```python
from CORE.constants import get_tick_size

tick = get_tick_size(symbol)  # 0.10 pour MGC, 0.25 pour ES/NQ
```

Ou recevoir `tick` en argument depuis un caller qui l'a calcule.

## Anti-patterns INTERDITS

### 1. Constante module hardcodee
```python
# ❌ INTERDIT en haut d'un module pipeline
TICK_SIZE = 0.25
```

**Pourquoi** : silent fallback. Si quelqu'un instancie pour MGC sans verifier, le
tick=0.25 est utilise au lieu de 0.10 → toutes les distances en ticks faussees
d'un facteur 2.5x. Bug detecte par audit code-reviewer 10/05/2026.

### 2. Variable locale hardcodee
```python
# ❌ INTERDIT dans une fonction
def compute_something(df):
    tick_size = 0.25  # NQ et ES — FAUX pour MGC
    return df['range'] / tick_size
```

**Correct** :
```python
def compute_something(df, tick: float):
    return df['range'] / tick
```

### 3. Fallback silencieux sans warning
```python
# ❌ INTERDIT
def my_helper(symbol="ES"):
    tick_dict = {"ES": 0.25, "NQ": 0.25}  # MGC manque
    return tick_dict.get(symbol, 0.25)  # silent fallback ES pour MGC
```

**Correct** : utiliser `get_tick_size()` qui log warning si symbole inconnu.

## Patterns ACCEPTES

### 1. Constante module commentee comme default
```python
# ✅ OK dans modules helpers tick-aware
TICK_SIZE = 0.25  # default ES/NQ. MGC=0.10 — caller passe tick explicitement
```

Le commentaire explicite signale que c'est un default et que le caller doit
passer `tick` pour MGC. Le lint guard whitelist ces lignes.

### 2. Import top-of-module avec fallback try/except
```python
# ✅ Pattern aligne sur mia_paper_trader.py:33-36
try:
    from CORE.constants import get_tick_size as _get_tick_size
except ImportError:
    from constants import get_tick_size as _get_tick_size
```

Necessaire car certains scripts sont lances depuis `D:\...\CORE\` (sys.path
inclut CORE/) tandis que d'autres sont lances depuis `D:\...` (sys.path inclut
ROOT/). 2 conventions a supporter.

### 3. Fonction tick-aware avec argument
```python
# ✅ OK
def add_session_high_low(df: pd.DataFrame, tick: float = TICK_SIZE) -> pd.DataFrame:
    return df.assign(dist_high_ticks=df['dist_high'] / tick)
```

Default = `TICK_SIZE` du module (= 0.25 ES/NQ), MAIS le caller passe explicitement
`tick=get_tick_size(symbol)` pour propager correctement MGC.

## Lint guard automatique

`tools/check_tick_hardcode.py` scan tout le projet et detecte les violations.

Usage :
```bash
python tools/check_tick_hardcode.py           # warning mode (info)
python tools/check_tick_hardcode.py --strict  # exit 1 si violation critique
```

**Modules pipeline V4 critiques** : violation = BLOCK commit.
**Modules legacy/research/audit** : warning seulement (cf IDEAS_BACKLOG dette R2).

## Pre-commit hook (auto-installable)

Pour activer la garde automatique :
```bash
python tools/install_precommit_hook.py
```

Cela cree `.git/hooks/pre-commit` qui execute le lint guard avant chaque commit.
Si une violation critique est trouvee, le commit est bloque.

Pour bypasser (urgences) : `git commit --no-verify`.

## Cross-reference

L'anti-pattern #3 (silent fallback) correspond exactement aux patterns documentes
dans `.claude/rules/lessons.md` (ex: "Gamma hardcode a 0.0 = gate MenthorQ jamais
actif → lire depuis features mq_*"). C'est la meme regle generale : **un default
silencieux qui devie de l'intention du caller = bug garanti** (decouvert tot ou
tard, souvent en prod). Le warning logger est la couche minimale de defense.

## Migration des modules legacy

Quand un module hors pipeline V4 doit etre etendu a MGC (live trading,
backtest MGC, etc.) :

1. Verifier qu'il est dans la dette R2 documentee `DOCS/IDEAS_BACKLOG.md`.
2. Remplacer `TICK_SIZE = 0.25` par import + helper :
   ```python
   try:
       from CORE.constants import get_tick_size
   except ImportError:
       from constants import get_tick_size
   ```
3. Identifier comment le module recoit/connait le `symbol`. Adapter signature.
4. Tester non-regression ES/NQ (math identique car tick=0.25 = 0.25).
5. Documenter migration dans `DOCS/BOT_CHANGELOG.md` si module bot live.

## Liens

- `CORE/constants.py` : source de verite
- `tools/check_tick_hardcode.py` : lint guard
- `DOCS/IDEAS_BACKLOG.md` : dette R2 modules residuels
- `.claude/rules/critical-tasks-review.md` : protocole agent review
