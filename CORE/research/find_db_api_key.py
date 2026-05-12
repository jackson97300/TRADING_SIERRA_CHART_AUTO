"""Find Databento API key in running process env."""
import psutil

# Find databento_live_stream process
for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        cmd = proc.info.get('cmdline') or []
        cmd_str = ' '.join(cmd)
        if 'databento_live_stream' in cmd_str or 'databento_download' in cmd_str:
            print(f"PID {proc.info['pid']}: {cmd_str[:100]}")
            env = proc.environ()
            for k, v in env.items():
                if 'DATABENTO' in k.upper() or 'API_KEY' in k.upper():
                    print(f"  {k}={v[:8]}...{v[-4:]}" if len(v) > 12 else f"  {k}={v}")
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        continue

# Check .env files
from pathlib import Path
for fp in [
    Path("C:/TRADING_SIERRA_CHART_AUTO/.env"),
    Path("C:/TRADING_SIERRA_CHART_AUTO/CORE/.env"),
    Path("C:/Users/Administrator/.databento/api_key"),
]:
    if fp.exists():
        content = fp.read_text()[:500]
        if 'DATABENTO' in content or len(content) < 100:
            print(f"\n{fp}:")
            for line in content.split('\n')[:5]:
                if 'DATABENTO' in line.upper() or 'API' in line.upper():
                    print(f"  {line[:80]}")
