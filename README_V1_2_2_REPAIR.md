# Rockstar Radar V1.2.2 - Cumulative Repair Patch

This repair addresses `ImportError: cannot import name 'ApiProviderError' from 'radar.fyers'` after applying the V1.2.2 restart patch without the prerequisite V1.2.1 safety patch.

Includes the combined V1.2.1 API-safety and V1.2.2 restart-recovery code, applied in that order. The archive has flat project-relative paths such as `radar/fyers.py` and `radar/service.py`. It contains NO `.env`, `config.json`, `data/`, `output/`, or credentials. Tested against the V1.2 base project: 52 offline unit tests passed.

## Install on macOS

1. Stop Radar (Ctrl+C). Back up the entire current project folder first.
2. Open Terminal and change directory to the project folder containing `launch.py` (e.g., `cd ~/Downloads/Rockstar_Radar_FYERS_Pilot_V1_1`).
3. Run:

```bash
unzip -o ~/Downloads/Rockstar_Radar_V1_2_2_Repair_Bundle.zip -d .
source .venv/bin/activate
python -c "from radar.fyers import ApiProviderError; from radar.service import SessionJournal; print('Imports OK')"
python -m unittest discover -s tests -q
```

4. If offline checks pass, use `python launch.py run` when API access is permitted. Stop before rerunning if FYERS is blocking your account/IP. By default, after the 11:30 signal cutoff plus retest window, V1.2.2 runs REVIEW-ONLY; an empty active Top 5 in that state is intentional.

Important: importing and running the unit tests does not authenticate to FYERS. The live FYERS WebSocket/reconnect behavior has not been independently tested with your credentials.
