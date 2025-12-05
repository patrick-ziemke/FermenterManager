# Fermenter Manager

**Fermenter Manager** is a desktop application built with Python and Tkinter designed for home brewers, vintners, and fermenters to easily track, log, and manage multiple active fermentation batches. It provides a clean, local interface for monitoring metrics, logging events, and archiving completed brews.

## ✨ Key Features

* **Multi-Slot Tracking:** Manage a fixed number of fermentation slots with easy slot-to-slot navigation.
* **Persistent Data:** All active brew data, history, and configuration are saved automatically to local JSON files.
* **Customizable Configuration:** Easily define your own `CATEGORIES`, `STAGES`, and `EVENT_TYPES` via the `config.json` file.
* **Automatic Logging:** Changes to key metrics (OG, FG, Volume, pH, Temp) are automatically logged as time-stamped events when details are saved.
* **Calculated Metrics:** Automatically calculates **Approximate ABV** based on Original and Final Gravity readings.

---

## 🚀 What's New in v3.3 (Latest Update: Dec 5, 2025)

The v3.3 release focuses heavily on user experience, data integrity, and clearer tracking:

| Area | Feature | Description |
| :--- | :--- | :--- |
| **Data Integrity** | **Log Entry Deletion** | Added a **"Delete Entry"** feature to the Live Log for correcting accidental or erroneous data reports (with confirmation). |
| **UI/UX** | **Split Recipe & Notes** | The Recipe and Notes sections are now **separated into two distinct, enlarged panels** with white backgrounds for clearer data entry and visibility. |
| **Safety UX** | **Destructive Action Styling** | The **"Archive Brew & Clear Fermenter"** button is restyled in red to clearly signal its function as a destructive action, preventing accidental slot clearing. |
| **Tracking** | **Enhanced Time & Volume** | Brew duration tracking now includes **hours and minutes** for higher precision, and transfer logging is updated to accurately record **volume loss**. |

---

## ⚙️ Installation & Setup

### Requirements

Fermenter Manager requires **Python 3.x** and only uses standard libraries for its core functionality (including `tkinter` for the GUI). No external dependencies (like Matplotlib) are required to run the program.

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
