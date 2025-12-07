# Fermenter Manager
**Fermenter Manager** is a desktop application built with Python and Tkinter designed for home brewers, vintners, and fermenters to easily track, log, and manage multiple active fermentation batches. It provides a clean, local interface for monitoring metrics, logging events, and archiving completed brews.

## ✨ Key Features
* **Multi-Slot Tracking:** Manage multiple fermentation slots with easy slot-to-slot navigation and transfers.
* **Visual Charts:** View Gravity and Temperature trends over time with automatic attenuation and ABV calculations.
* **Persistent Data:** All active brew data, history, and configuration are saved automatically to local JSON files with atomic writes to prevent corruption.
* **Customizable Configuration:** Easily define your own `CATEGORIES`, `STAGES`, and `EVENT_TYPES` via the `config.json` file.
* **Automatic Logging:** Changes to key metrics (OG, FG, Volume, pH, Temp) are automatically logged as time-stamped events when details are saved.
* **Advanced ABV Calculation:** Uses an improved formula that accounts for alcohol presence in final gravity for greater accuracy.
* **Archive Management:** Full search and edit capabilities for historical brew records.

---

## 🚀 What's New in v3.4 (Latest Update: Dec 7, 2025)
The v3.4 release introduces visual analytics, enhanced data validation, and improved archive management:

| Area | Feature | Description |
| :--- | :--- | :--- |
| **Charting** | **View Charts Button** | New button opens a dedicated window displaying **Gravity and Temperature charts** with trend lines, attenuation percentages, and statistical summaries. |
| **Calculations** | **Advanced ABV Formula** | Upgraded to a more accurate calculation: `ABV = [76.08 * (OG - FG) / (1.775 - OG)] * (FG / 0.794)` that accounts for alcohol in final gravity. |
| **Archive Management** | **Edit Archive Records** | Archive entries can now be **fully edited** (name, metrics, recipe, notes) with validation checks to ensure data integrity. |
| **Archive Management** | **History Search Bar** | Added **real-time search** to quickly filter and find archived brews by name. |
| **Data Validation** | **Input Validation** | Gravity inputs (0.980-1.200), volume loss, and all numeric fields now have **validation checks** with clear error messages. |
| **Data Reliability** | **Autosave & Atomic Writes** | **Autosave on window close** prevents data loss, and **atomic file writing** for history prevents corruption during saves. |
| **Chart Accuracy** | **Improved Parsing** | Gravity parsing now handles **2+ decimal places** (e.g., 1.03, 1.050) for accurate chart plotting. |
| **UI Polish** | **History Tab Redesign** | Improved styling and layout for better readability and navigation. |
| **Fermenter Handling** | **Removal Process Flow Redesign** | Users now select which empty slot to delete instead of forced last-slot removal. |
---

## ⚙️ Installation & Setup

### Requirements
Fermenter Manager requires **Python 3.x** and the following libraries:
- `tkinter` (usually included with Python)
- `matplotlib` (for charting functionality)

Install matplotlib if needed:
```bash
pip install matplotlib
```

### Initial Configuration ⚠️
Before running the application, you **must** update the timezone settings in `config.json` to ensure accurate time logging:

1.  Open the `config.json` file in a text editor.
2.  Locate the `"LOCAL_TIMEZONE"` entry.
3.  Change the value `"America/New_York"` to your **local timezone string** (e.g., `"Europe/London"`, `"America/Los_Angeles"`, etc.). You can find a full list of valid timezone strings online (e.g., Wikipedia TZ database list).

### Running the Application
1.  Clone this repository or download the `FermenterManager.py` and `config.json` files.
2.  Open your terminal or command prompt in the directory where the files are located.
3.  Run the application:
```bash
python FermenterManager.py
```
