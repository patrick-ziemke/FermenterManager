# FermenterManager
Tkinter-based fermentation management software for home winemakers and brewers. Tracks multiple fermenters, logs events with timestamps, stores gravity/ABV, manages batch transfers, archives completed brews, and persists data locally via JSON.

## Features
- Dashboard with dynamically addable fermenter slots (default: 5)
- Create brews with OG/FG, category, notes & recipe
- Timestamped event logging (gravity, nutrients, pH, temperature, etc.)
- Track fermentation stages and vessel transfers with volume loss
- Archive finished batches with full log history
- Export/backup JSON state
- Offline - no network required

## Roadmap
- Charting for gravity/temp curves
- CSV export + import
- Encryption option for logs
- Web dashboard interface
** Contributions welcome! Fork, modify, and open a PR. **

## Files
________________________________________________________________________________
| File                   | Purpose                                             |
--------------------------------------------------------------------------------
| 'FermenterManager.py'  | Main Tkinter app + data model + history/state logic |
| 'brews.json'           | Active fermenters (auto-generated)                  |
| 'brew_history.json'    | Archived batches (auto-generated)                   |
--------------------------------------------------------------------------------

## Requirements
- Python 3.10+ (3.9+ should also work)
- Tkinter (bundled with most Python installs)
- zoneinfo (standard in 3.9+)

## Run
'''bash
python3 FermenterManager.py
