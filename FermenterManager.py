"""
Fermenter Manager v3.4
======================
Tkinter-based fermentation tracking suite for home winemakers/brewers.

Changes in v3.4:
----------------
- Bug fixes
- Fermentation Tracking: Added Gravity and Temperature charts accessible via a new 
"View Charts" button. ABV calculation was upgraded to a more advanced and accurate formula.
- Archive Management: History tab styling was changed. Added a search bar to the history
list. Archive records can now be edited.
- Data Reliability: Implemented autosave on window close to prevent data loss. Upgraded
history saving to an atomic process to prevent file corruption. Validation checks were
introduced for gravity inputs and archive edits (OG/FG). Transfer volume validation was
added to ensure logical volume loss. Gravity parsing logic was improved for better chart
accuracy data.

Persistence:
------------
* Active slots -> brews.json
* Archive history -> brew_history.json
* Configuration -> config.json
"""

import json
import os
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from datetime import datetime, timezone
from typing import Optional, Union, List, Tuple, Dict, Any, TYPE_CHECKING
from zoneinfo import ZoneInfo
import re

import matplotlib
matplotlib.use('TkAgg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import matplotlib.dates as mdates
from matplotlib.lines import Line2D

# ==============================================================================
# CONFIGURATION
# ==============================================================================

# Persistent file names
CONFIG_FILE = "config.json"
STATE_FILE = "brews.json"
HISTORY_FILE = "brew_history.json"

# Global Configuration Variables (Loaded from config.json)
CONFIG = {}
DEFAULT_SLOT_COUNT = 5
CATEGORIES = []
STAGES = []
EVENT_TYPES = []
LOCAL_ZONE = ZoneInfo("America/New_York")
DATE_DISPLAY_FMT = "%Y-%m-%d %H:%M"

def load_config():
    """Loads configuration settings from the config.json file."""
    global CONFIG, DEFAULT_SLOT_COUNT, CATEGORIES, STAGES, EVENT_TYPES, LOCAL_ZONE, DATE_DISPLAY_FMT
    if not os.path.exists(CONFIG_FILE):
        print(f"Warning: {CONFIG_FILE} not found. Using hardcoded defaults.")
        # Fallback to defaults if file is missing
        CATEGORIES.extend(["Beer", "Wine"]) 
        return
        
    try:
        with open(CONFIG_FILE, 'r') as f:
            CONFIG = json.load(f)

            # Load constants from the CONFIG dictionary
            DEFAULT_SLOT_COUNT = CONFIG.get("DEFAULT_SLOT_COUNT", 5)
            CATEGORIES.extend(CONFIG.get("CATEGORIES", ["Beer", "Wine"]))
            STAGES.extend(CONFIG.get("STAGES", ["Primary", "Secondary"]))
            EVENT_TYPES.extend(CONFIG.get("EVENT_TYPES", ["General Note", "Gravity Reading"]))
            
            tz_name = CONFIG.get("LOCAL_TIMEZONE", "America/New_York")
            try:
                LOCAL_ZONE = ZoneInfo(tz_name)
            except Exception:
                print(f"Warning: Invalid timezone '{tz_name}'. Defaulting to UTC.")
                LOCAL_ZONE = timezone.utc

            DATE_DISPLAY_FMT = CONFIG.get("DATE_DISPLAY_FMT", "%Y-%m-%d %H:%M")

    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {CONFIG_FILE}. Check file integrity.")
    except Exception as e:
        print(f"An unexpected error occurred loading config: {e}")

load_config()

# ==============================================================================
# UTILITIES
# ==============================================================================

def now_utc() -> datetime:
    """Return current time as timezone-aware UTC datetime object."""
    return datetime.now(timezone.utc)

def iso_now() -> str:
    """Returns the current UTC time in ISO-8601 string format."""
    return now_utc().isoformat()

def parse_iso(s: str) -> Optional[datetime]:
    """
    Parse ISO-8601 datetime string into a UTC-aware datetime object.

    Args:
        s: The ISO-8601 formatted datetime string
    
    Returns:
        The timezone-aware datetime object, or None if the string is invalid.
    """
    if not s: return None
    try:
        dt = datetime.fromisoformat(s)
        # Ensure naive datetimes are treated as UTC for consistency
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError: return None

def fmt(dt) -> str:
    """
    Convert UTC datetime (or ISO string) into formatted LOCAL display time.
    The datetime is converted to the local zone defined in config.json.

    Args:
        dt (datetime|str): The starting time (UTC aware datetime object or ISO string).

    Returns:
        str formatted using DATE_DISPLAY_FMT or '-' on failure.
    """
    if not dt: return "-"
    if isinstance(dt, str): dt = parse_iso(dt)
    if dt is None: return "-"
    return dt.astimezone(LOCAL_ZONE).strftime(DATE_DISPLAY_FMT)

def human_delta(dt) -> str:
    """
    Return time elapsed since dt in 'Xd, Xh, Xm' format.
    
    Args:
        dt (datetime|str): The starting time (UTC aware datetime object or ISO string).

    Returns:
        Formatted string showing time elapsed, or '-' on failure.
    """
    if not dt: return "-"

    delta = now_utc() - dt
    total_seconds = int(delta.total_seconds())

    days = total_seconds // 86400; total_seconds %= 86400
    hours = total_seconds // 3600; total_seconds %= 3600
    minutes = total_seconds // 60

    return f"{days}d, {hours}h, {minutes}m"

def calc_abv(og, fg) -> float:
    """
    Calculates Alcohol by Volume (ABV) using the advanced, non-conditional formula that
    accounts for the presence of alcohol in the final gravity reading, providing greater
    accuracy, especially for high-gravity brews.

    Formula (advanced): ABV = [76.08 * (OG - FG) / (1.775 - OG)] * (FG / 0.794)

    Args:
        og (float|str): Original gravity
        fg (float|str): Final gravity

    Returns:
        float: %ABV rounded to 2 decimal places. Returns 0.0 on invalid input.
    """
    try:
        og_f, fg_f = float(og), float(fg)

        # Sanity check: OG must be greater than FG
        if og_f <= fg_f:
            return 0.0
        
        # Alcohol by Weight (ABW) Calculation (Numerator/Denominator)
        abw_numerator = 76.08 * (og_f - fg_f)
        abw_denominator = 1.775 - og_f

        # Factor to convert ABW to ABV (using final gravity)
        abv_conversion_factor = fg_f / 0.794

        # Combine to get final ABV
        final_abv = (abw_numerator / abw_denominator) * abv_conversion_factor
        return round(final_abv, 2)
    except ValueError:
        return 0.0
    except ZeroDivisionError:
        return 0.0

def validate_float(value_str, default=0.0) -> Optional[float]:
    """
    Safely convert a string or float input to a float, returning a default on failure.
    
    Args:
        value_str: The input value (string or float).
        default: The value to return if conversion fails.

    Return:
        The converted float, or the default value.
    """
    try:
        return float(value_str)
    except ValueError:
        return default


# --------------------------------------------------------------------------
# Data Model
# --------------------------------------------------------------------------


class Brew:
    """
    A single tracked fermentation batch.

    Attributes:
        id (str)                    Unique ID (ms timestamp)
        name (str)                  User-assigned brew name
        category (str)              Beer/Wine/Mead/etc.
        recipe (str)                Freeform text recipe field
        notes (str)                 Observations + misc notes
        start_date (str)            ISO timestamp of creation
        stage (str)                 Current fermentation stage
        volume (float)              Current volume (liters)
        original_volume (float)     Volume at creation for ABV yield reporting
        og (float)                  Original gravity
        fg (float)                  Final gravity
        ph (float)                  Last recorded pH
        temp (float)                Last recorded temperature
        log (list[dict])            Event records [{time,type,text},...]

    Behavior:
        add_event()     Append timestamped log entry
        get_abv()       Calculate ABV if OG+FG exist
        to_dict()       Serialize for JSON persistence
        from_dict()     Construct from saved data
    """
    def __init__(self, **kwargs):
        """
        Initializes a Brew object, setting defaults or loading from keyword arguments.

        Args:
            **kwargs: Dictionary containing existing brew attributes for loading.
        """
        self.id = kwargs.get("id") or f"brew_{int(now_utc().timestamp()*1000)}"
        self.name = kwargs.get("name", "Untitled")
        self.category = kwargs.get("category", CATEGORIES[0] if CATEGORIES else "Beer")
        self.recipe = kwargs.get("recipe", "")
        self.notes = kwargs.get("notes", "")
        
        self.start_date = kwargs.get("start_date") or iso_now()
        self.stage = kwargs.get("stage", STAGES[0] if STAGES else "Primary")
        
        self.volume = kwargs.get("volume", 0.0) 
        self.original_volume = kwargs.get("original_volume", self.volume)
        
        self.og = kwargs.get("og", 0.0)
        self.fg = kwargs.get("fg", 0.0)
        self.ph = kwargs.get("ph", 0.0)
        self.temp = kwargs.get("temp", 0.0)

        self.log = kwargs.get("log", [])
        if not self.log:
            self.add_event("Lifecycle", f"Created: {self.name}. Start Vol: {self.volume}L")

    def add_event(self, e_type, text) -> None:
        """
        Appends a time-stamped entry to the brew log.

        Args:
            e_type: The type of event (e.g., "Gravity Reading")
            text: The description or content of the event
        """
        entry = {
            "time": iso_now(),
            "type": e_type,
            "text": text
        }
        self.log.append(entry)

    def get_abv(self) -> Optional[float]:
        """
        Calculates the Alcohol by Volume (ABV) based on OG and FG.

        Returns:
            The calculated ABV (float) rounded to two decimal places, or None if OG and FG are missing.
        """
        if self.og and self.fg:
            return calc_abv(self.og, self.fg)
        return None

    def to_dict(self):
        """
        Serializes the Brew object to a dictionary for JSON saving.

        Returns:
            A dictionary representation of the brew's attributes.
        """
        return self.__dict__

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> Optional['Brew']:
        """
        Creates a Brew object from a dictionary (used for JSON loading).
        
        Args:
            d: The dictionary containing brew attributes.

        Returns:
            A new Brew instance, or None if the input dictionary is empty.
        """
        if not d: return None
        return cls(**d)


# --------------------------------------------------------------------------
# Matplotlib Chart Window
# --------------------------------------------------------------------------


class ChartWindow(tk.Toplevel):
    """
    Dedicated window for displaying matplotlib charts of brew metrics.
    
    Displays two subplots: Specific Gravity over Time and Temperature over Time.
    """
    
    def __init__(self, parent: tk.Tk, brew: 'Brew') -> None:
        """
        Initializes the ChartWindow, sets up the UI, and generates initial plots.

        Args:
            parent: The root Tkinter window
            brewL The Brew object containing log data to plot
        """
        super().__init__(parent)
        self.title(f"Charts: {brew.name}")
        self.geometry("1000x700")
        self.brew = brew
        
        # 1. Prepare data
        self.gravity_data = self._extract_gravity_data()
        self.temp_data = self._extract_temp_data()
        
        # 2. Create the matplotlib figure
        self.fig = Figure(figsize=(10, 8), dpi=100)
        self._sep_line = None
        
        # Add subplots (2 rows, 1 column: ax1=Gravity, ax2=Temperature)
        self.ax1 = self.fig.add_subplot(211)
        self.ax2 = self.fig.add_subplot(212)
        
        # 3. Plot the data
        self._plot_gravity()
        self._plot_temperature()
        
        self.fig.tight_layout()
        
        # 4. Embed in tkinter
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        # 5. Add toolbar and buttons
        toolbar = NavigationToolbar2Tk(self.canvas, self)
        toolbar.update()
        
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(btn_frame, text="Refresh Charts", command=self.refresh).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Close", command=self.destroy).pack(side=tk.RIGHT)
    
    def _extract_gravity_data(self):
        """
        Extract gravity readings from brew log with timestamps.

        The gravity value is extracted using regex matching common gravity formats
        (X.XXX or XXX/XXXX) and validated against realistic bounds (0.990 to 1.200).

        Returns:
            A list of tuples: (datetime_object, gravity_float, label_string)
        """
        data: List[Tuple[datetime, float, str]] = []
        
        # Add OG as first point (at start date)
        if self.brew.og and self.brew.og > 0:
            start_dt = parse_iso(self.brew.start_date)
            if start_dt:
                data.append((start_dt, self.brew.og, "OG"))
        
        # Regex to capture X.XXX+ format (Group 1) OR XXX/XXXX format (Group 2)
        gravity_regex = re.compile(r'(\d\.\d{2,})|\b([01]?\d{3})\b')

        # Parse log entries for gravity readings
        for i, entry in enumerate(self.brew.log):
            text = entry['text']
            entry_type = entry['type']
            
            # Check if entry is explicitly a reading or contains gravity keywords
            if (entry_type == 'Gravity Reading' or any(keyword in text.lower() for keyword in ['gravity', 'og', 'fg'])):
                dt = parse_iso(entry['time'])
                if not dt:
                    continue
                
                gravity_match = gravity_regex.search(text)

                gravity: Optional[float] = None
                if gravity_match:
                    if gravity_match.group(1):      # Matched X.XXX+ format
                        gravity = float(gravity_match.group(1))
                    elif gravity_match.group(2):    # Matched XXX or XXXX format
                        g_str = gravity_match.group(2)
                        gravity = float(g_str) / 1000

                if gravity is None:
                    continue
                
                # Sanity Check: Only accept realistic gravity values
                if 0.990 <= gravity <= 1.200:
                    text_upper = text.upper()
                    if 'OG' in text_upper and 'FG' not in text_upper:
                        label = "OG"
                    elif 'FG' in text_upper:
                        label = "FG"
                    else:
                        label = "Reading"
                    
                    data.append((dt, gravity, label))
                
                # else: gravity outside bounds, ignore it
        
        data.sort(key=lambda x: x[0])
        return data
    
    def _extract_temp_data(self) -> List[Tuple[datetime, float]]:
        """
        Extracts temperature readings from brew log with timestamps.

        Looks for numeric values followed by C or F units.

        Returns:
            A list of tuples: (datetime_object, temperature_float)
        """
        data: List[Tuple[datetime, float]] = []

        # Regex to capture number + optional decimal, optional degree sign, and unit C or F
        temp_regex = re.compile(r'(\d+(?:\.\d+)?)\s*(?:°\s*)?([CFcf])\b')
        
        for entry in self.brew.log:
            text = entry.get('text', '')
            entry_type = entry.get('type', '')
            
            # Proceed if entry type explicitly marks a temp check OR the text contains "temp"
            if entry_type == 'Temp Check' or 'temp' in text.lower():
                dt = parse_iso(entry.get('time'))
                if not dt:
                    continue

                m = temp_regex.search(text)
                if not m:
                    continue
                
                temp_val = float(m.group(1))

                # Sanity Check: Only accept realistic fermentation temps (-5C to 100C)
                if -5 <= temp_val <= 100:
                    data.append((dt, round(temp_val, 2)))

        data.sort(key=lambda x: x[0])
        return data
        
    def _plot_gravity(self):
        """Plots the gravity vs time chart in the top subplot (ax1)."""
        self.ax1.clear()
        
        if not self.gravity_data:
            self.ax1.text(0.5, 0.5, 'No gravity data available', 
                        ha='center', va='center', transform=self.ax1.transAxes,
                        fontsize=12, color='gray')
            self.ax1.set_title('Specific Gravity Over Time')
            return
        
        times, gravities, labels = zip(*self.gravity_data)
        
        # Plot line connecting all points
        self.ax1.plot(times, gravities, '-', linewidth=2, color='#1f77b4', zorder=1)

        # Format x-axis
        self.ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
        self.ax1.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=6))
            
        # Plot points with appropriate colors and labels
        og_plotted = False
        fg_plotted = False
        reading_plotted = False
        
        for t, g, lbl in self.gravity_data:
            color = 'red'
            size = 6
            legend_label = None
            zorder = 2
            
            if lbl == "OG":
                size = 8
                if not og_plotted:
                    color = 'green'
                    legend_label = 'Original Gravity'
                    og_plotted = True
            elif lbl == "FG":
                if not fg_plotted:
                    legend_label = 'Final Gravity'
                    fg_plotted = True
            else:
                if not reading_plotted:
                    legend_label = 'Gravity Reading'
                    reading_plotted = True

            self.ax1.plot(t, g, 'o', markersize=size, color=color, label=legend_label, zorder=zorder)
        
        # Labels and styling
        self.ax1.set_xlabel('Date/Time', fontsize=10)
        self.ax1.set_ylabel('Specific Gravity', fontsize=10)
        self.ax1.set_title(f'Specific Gravity Over Time - {self.brew.name}', fontsize=12, fontweight='bold')
        self.ax1.grid(True, alpha=0.3)
        self.ax1.legend(loc='best')
        
        # Calculate and display attenuation if we have both OG and FG
        if self.brew.og > 0 and self.brew.fg > 0:
            attenuation = ((self.brew.og - self.brew.fg) / (self.brew.og - 1.0)) * 100
            abv = self.brew.get_abv()
            info_text = f'Attenuation: {attenuation:.1f}%\nCurrent ABV: {abv:.2f}%'
            self.ax1.text(0.02, 0.05, info_text, transform=self.ax1.transAxes,
                        fontsize=10, verticalalignment='bottom', horizontalalignment='left',
                        bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
                
    def _plot_temperature(self) -> None:
        """Plots the temperature vs time chart in the bottom subplot (ax2)."""
        self.ax2.clear()
        
        if not self.temp_data:
            self.ax2.text(0.5, 0.5, 'No temperature data available', 
                         ha='center', va='center', transform=self.ax2.transAxes,
                         fontsize=12, color='gray')
            self.ax2.set_title('Temperature Over Time')
            return
        
        times, temps = zip(*self.temp_data)
        
        # Plot temperature data
        self.ax2.plot(times, temps, 'o-', linewidth=2, markersize=6, 
                     color='#ff7f0e', label='Temperature')
        
        # Format x-axis
        self.ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
        self.ax2.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=6))
        
        # Labels and styling
        self.ax2.set_xlabel('Date/Time', fontsize=10)
        self.ax2.set_ylabel('Temperature (°C)', fontsize=10)
        self.ax2.set_title(f'Temperature Over Time - {self.brew.name}', fontsize=12, fontweight='bold')
        self.ax2.grid(True, alpha=0.3)
        self.ax2.legend(loc='upper right')
        
        # Show current temp range info box
        if temps:
            avg_temp = sum(temps) / len(temps)
            min_temp = min(temps)
            max_temp = max(temps)
            info_text = f'Avg: {avg_temp:.1f}°C\nMin: {min_temp:.1f}°C\nMax: {max_temp:.1f}°C'
            self.ax2.text(0.02, 0.95, info_text, transform=self.ax2.transAxes,
                         fontsize=10, verticalalignment='top',
                         bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.5))
    
    def refresh(self) -> None:
        """Refreshes the charts by re-extracting data and replotting."""
        self.gravity_data = self._extract_gravity_data()
        self.temp_data = self._extract_temp_data()
        self._plot_gravity()
        self._plot_temperature()
        self.fig.tight_layout()
        self.canvas.draw()


# --------------------------------------------------------------------------
# Business Logic (The Manager)
# --------------------------------------------------------------------------


class FermenterManager:
    """
    State and business logic layer for managing fermenter slots and brew history.
    Handles persistence (loading and saving state/history) but has no UI components.
    """
    def __init__(self) -> None:
        """Initializes the manager and loads persistent data."""
        self.slots: List[Dict[str, Optional['Brew']]] = [] 
        self.history: List[Dict[str, Any]] = []
        self.load_state()
        self.load_history()

    def add_slot(self) -> None:
        """Adds a new, empty fermenter slot with a default name."""
        new_idx = len(self.slots) + 1
        self.slots.append({'name': f"Fermenter {new_idx}", 'brew': None})
        self.save_state()

    def remove_last_slot(self) -> None:
        """
        Removes the last fermenter slot.
        
        Returns:
            True if the slot was removed, False if the slot was occupied or the list was empty.
        """
        if not self.slots: return False
        if self.slots[-1]['brew'] is not None: return False # Cannot remove occupied slot
        self.slots.pop()
        self.save_state()
        return True
        
    def rename_slot(self, idx: int, new_name: str) -> None:
        """
        Renames a specific fermenter slot.
        
        Args:
            idx: The index of the slot to rename
            new_name: The new name for the slot
        """
        self.slots[idx]['name'] = new_name
        self.save_state()

    def create_brew(self, idx: int, brew: 'Brew') -> None:
        """
        Places a new Brew object into the specified fermenter slot.
        
        Args:
            idx: The index of the slot where the brew will be placed
            brew: The new Brew object
        """
        self.slots[idx]['brew'] = brew
        self.save_state()

    def archive_brew(self, idx: int) -> None:
        """
        Moves the Brew from an active slot to the history list, saving it's final
        metrics, and clears the active slot.
        
        Args:
            idx: The index of the slot containing the brew to archive
        """
        slot = self.slots[idx]
        b = slot['brew']
        if b:
            b.add_event("Lifecycle", "Archived to History")
            b_dict = b.to_dict()
            b_dict['archived_from'] = slot['name']
            self.history.insert(0, b_dict)
            self.save_history()
        slot['brew'] = None
        self.save_state()

    def transfer(self, src_idx: int, dest_idx: int, vol_loss: Union[float, int] = 0) -> bool:
        """
        Moves a brew from one slot to another and logs any volume loss.

        Performs validation to ensure volume loss is non-negative and realistic.

        Args:
            src_idx: The index of the source fermenter slot
            dest_idx: The index of the destination fermenter slot
            vol_loss: The volume lost during the transfer (in Liters)

        Returns:
            True if the transfer was successful, False otherwise (due to validation errors)
        """
        src_slot = self.slots[src_idx]
        dest_slot = self.slots[dest_idx]
        brew = src_slot['brew']
        old_vol = brew.volume
        
        # Validation logic
        if vol_loss < 0:
            messagebox.showerror("Error", "Volume loss cannot be a negative number (implying volume gain).")
            return False
        
        if vol_loss > old_vol:
            messagebox.showerror("Error",
                                 f"Volume loss ({vol_loss:.2f}L) cannot be greater than the current volume ({old_vol:.2f}L).")
            return False

        # Calculate loss and update volume
        new_vol = old_vol - vol_loss
        loss_pct = (vol_loss / old_vol * 100) if old_vol > 0 else 0
        brew.volume = round(new_vol, 2)
        
        # Log transfer in brew log
        log_msg = (f"Transferred {src_slot['name']} -> {dest_slot['name']}. "
                   f"Loss: {vol_loss}L ({loss_pct:.1f}%). New Vol: {brew.volume}L")
        brew.add_event("Transfer", log_msg)
        
        # Move object and clear source
        dest_slot['brew'] = brew
        src_slot['brew'] = None
        self.save_state()

        return True

    # ==========================================================================
    # Persistence
    # ==========================================================================

    def load_state(self) -> None:
        """
        Loads active fermenter slot data from the state file.
        
        Handles migration fro older save formats (list of Brews) to the current format
        (list of dictionaries containing 'name' and 'brew').
        """
        if not os.path.exists(STATE_FILE):
            self.slots = [{'name': f"Fermenter {i+1}", 'brew': None} for i in range(DEFAULT_SLOT_COUNT)]
            return
        try:
            with open(STATE_FILE, 'r') as f:
                data = json.load(f)
                cleaned_slots = []
                
                if isinstance(data, list):
                    for i, item in enumerate(data):
                        if isinstance(item, dict) and 'name' in item and 'brew' in item:
                             cleaned_slots.append({
                                 'name': item['name'],
                                 'brew': Brew.from_dict(item['brew']) if item['brew'] else None
                             })
                        else:
                            # Old format detected: auto-assign default name
                            cleaned_slots.append({
                                'name': f"Fermenter {i+1}",
                                'brew': Brew.from_dict(item) if item else None
                            })
                    self.slots = cleaned_slots
                else:
                    self.slots = [{'name': f"Fermenter {i+1}", 'brew': None} for i in range(DEFAULT_SLOT_COUNT)]
        except Exception as e:
            print(f"Load State Error: {e}")
            self.slots = [{'name': f"Fermenter {i+1}", 'brew': None} for i in range(DEFAULT_SLOT_COUNT)]

    def save_state(self) -> None:
        """Saves the active fermenter slots to the state file."""
        out = []
        for s in self.slots:
            out.append({
                'name': s['name'],
                'brew': s['brew'].to_dict() if s['brew'] else None
            })
        with open(STATE_FILE, 'w') as f:
            json.dump(out, f, indent=2)

    def load_history(self) -> None:
        """Loads archived brew data from the history file."""
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, 'r') as f:
                    self.history = json.load(f)
            except: self.history = []

    def save_history(self) -> None:
        """
        Saves the archive history to the history file using an atomic write pattern.
        
        This process writes to a temporary file fiest, forces a disk write, and then
        atomically replaces the final history file. This prevents corruption in case of crashes.
        """
        temp_file = HISTORY_FILE + ".tmp"
        
        try:
            with open(temp_file, 'w') as f:
                json.dump(self.history, f, indent=4)
                f.flush()
                os.fsync(f.fileno())
            
            # Atomically swap temp -> final
            os.replace(temp_file, HISTORY_FILE)
        
        except Exception as e:
            print(f"Error saving history: {e}")
            if os.path.exists(temp_file):
                os.remove(temp_file)

    def delete_log_entry(self, slot_idx: int, log_idx: int) -> None:
        """
        Removes a specific log entry from the brew in the given slot.

        Args:
            slot_idx: The index of the fermenter slot containing the brew
            log_idx: The index of the log entry within the brew.log list to be deleted
        """
        brew = self.slots[slot_idx]['brew']
        if brew and 0 <= log_idx < len(brew.log):
            del brew.log[log_idx]
            self.save_state()


# --------------------------------------------------------------------------
# GUI (Tkinter Application)
# --------------------------------------------------------------------------


class App(tk.Tk):
    """
    Tkinter UI wrapper providing a dashboard for fermenter management.

    Features:
        - Dashboard of active fermenters.
        - Detailed view for logging, metric updates, and stage changes.
        - Brew transfer and archival functionality.
        - Chart visualization for gravity and temperature history.
        - JSON import/export.
        - Automatic dashboard refresh for time updates.
    """
    def __init__(self) -> None:
        """Initializes the main application window and loads the application state."""
        super().__init__()
        self.title("Fermenter Manager v3.2")
        self.geometry("1300x850")

        # Ensure state is saved when window is closed
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        
        self.manager = FermenterManager()
        self.selected_slot_idx = None
        self.transfer_source = None
        
        self._setup_styles()
        self._build_menu()
        self._build_ui()
        self._refresh_dashboard()
        
        # Schedule auto-refresh to update ages/times every 30 seconds
        self.after(30000, self._auto_refresh)

    # === Setup & Building ===

    def _setup_styles(self) -> None:
        """Defines ttk UI theme styles and fonts for card display."""
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("Card.TFrame", background="#f4f4f4", relief="raised")
        style.configure("Occupied.TLabel", foreground="#003366", font=("Segoe UI", 11, "bold"))
        style.configure("SlotTitle.TLabel", font=("Segoe UI", 12, "bold"))
        style.configure("Metric.TLabel", font=("Segoe UI", 10))
        style.configure("LiveLog.Treeview",
                        background="#f2f2f2",
                        fieldbackground="#f2f2f2",
                        foreground="black")
        style.configure("Destructive.TButton",
                        background="#FFCCCC",
                        foreground="#800000",
                        font=("Segoe UI", 12, "bold"),
                        padding=(10,6))

    def _build_menu(self) -> None:
        """Creates the top menu bar, currently only containing the 'Export JSON' option."""
        menubar = tk.Menu(self)
        fm = tk.Menu(menubar, tearoff=0)
        fm.add_command(label="Export JSON", command=self.export_json)
        menubar.add_cascade(label="File", menu=fm)
        self.config(menu=menubar)

    def _build_ui(self) -> None:
        """Constructs the full GUI layout, including the dashboard, detail notebook, and history panel."""
        main_paned = tk.PanedWindow(self, orient=tk.HORIZONTAL, sashwidth=4)
        main_paned.pack(fill=tk.BOTH, expand=True)

        # === Left: Dashboard (Fermenter List) ===
        self.dash_frame = ttk.Frame(main_paned)
        main_paned.add(self.dash_frame, width=380)
        ttk.Label(self.dash_frame, text="Active Fermenters", font=("Arial", 16, "bold")).pack(pady=(10,5))
        
        # Control Buttons
        ctrl_frame = ttk.Frame(self.dash_frame)
        ctrl_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=10, padx=10)
        ttk.Button(ctrl_frame, text="+ Add Fermenter", command=self.add_fermenter).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        ttk.Button(ctrl_frame, text="- Remove Fermenter", command=self.remove_fermenter).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        # Scrollable area for the list of fermenter cards
        self.canvas = tk.Canvas(self.dash_frame, bg="#e1e1e1")
        self.scrollbar = ttk.Scrollbar(self.dash_frame, orient="vertical", command=self.canvas.yview)
        self.scroll_frame = ttk.Frame(self.canvas)
        # Bind frame size changes to update the canvas scroll region
        self.scroll_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw", width=360) 
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # === Right: Details & History Notebook ===
        self.notebook = ttk.Notebook(main_paned)
        main_paned.add(self.notebook)

        # Tab 1: Active Brew Detail
        self.detail_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.detail_tab, text="Active Brew")
        self._build_detail_panel()

        # Tab 2: History Viewer
        self.history_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.history_tab, text="Brew History")
        self._build_history_panel()

    def _build_detail_panel(self) -> None:
        """Builds the UI for the 'Active Brew' tab, including input fields and the log viewer."""
        self.header_lbl = ttk.Label(self.detail_tab, text="Select a fermenter...", font=("Arial", 18, "bold"))
        self.header_lbl.pack(anchor="w", pady=(0, 10))
        data_container = ttk.Frame(self.detail_tab)
        data_container.pack(fill=tk.BOTH, expand=True)

        # Variables mapped to the input fields
        self.vars = {
            "name": tk.StringVar(), "category": tk.StringVar(), "stage": tk.StringVar(),
            "volume": tk.StringVar(), "og": tk.StringVar(), "fg": tk.StringVar(),
            "ph": tk.StringVar(), "temp": tk.StringVar(),
        }

        # Structure the detail inputs using grids
        top_frame = ttk.Frame(data_container); top_frame.pack(fill=tk.X)
        info_frame = ttk.LabelFrame(top_frame, text="Details", padding=10); info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        r=0
        ttk.Label(info_frame, text="Name:").grid(row=r, column=0, sticky="e"); ttk.Entry(info_frame, textvariable=self.vars["name"]).grid(row=r, column=1, sticky="ew"); r+=1
        ttk.Label(info_frame, text="Category:").grid(row=r, column=0, sticky="e"); ttk.Combobox(info_frame, textvariable=self.vars["category"], values=CATEGORIES).grid(row=r, column=1, sticky="ew"); r+=1
        ttk.Label(info_frame, text="Stage:").grid(row=r, column=0, sticky="e"); ttk.Combobox(info_frame, textvariable=self.vars["stage"], values=STAGES).grid(row=r, column=1, sticky="ew"); r+=1
        ttk.Label(info_frame, text="Current Vol (L):").grid(row=r, column=0, sticky="e"); ttk.Entry(info_frame, textvariable=self.vars["volume"]).grid(row=r, column=1, sticky="ew"); r+=1

        metric_frame = ttk.LabelFrame(top_frame, text="Metrics", padding=10); metric_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))
        r=0
        ttk.Label(metric_frame, text="Orig. Gravity:").grid(row=r, column=0, sticky="e"); ttk.Entry(metric_frame, textvariable=self.vars["og"]).grid(row=r, column=1, sticky="ew"); r+=1
        ttk.Label(metric_frame, text="Final Gravity:").grid(row=r, column=0, sticky="e"); ttk.Entry(metric_frame, textvariable=self.vars["fg"]).grid(row=r, column=1, sticky="ew"); r+=1
        ttk.Label(metric_frame, text="pH:").grid(row=r, column=0, sticky="e"); ttk.Entry(metric_frame, textvariable=self.vars["ph"]).grid(row=r, column=1, sticky="ew"); r+=1
        ttk.Label(metric_frame, text="Temp (°C):").grid(row=r, column=0, sticky="e"); ttk.Entry(metric_frame, textvariable=self.vars["temp"]).grid(row=r, column=1, sticky="ew"); r+=1
        
        self.calc_lbl = ttk.Label(metric_frame, text="ABV: -", font=("Arial", 12, "bold"), foreground="green")
        self.calc_lbl.grid(row=r, column=0, columnspan=2, pady=10)

        # === Recipe/Notes Text Area ===
        split_frame = ttk.Frame(data_container)
        split_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        txt_conf = {"height": 10, "width": 1, "font": ("Segoe UI", 14), "bg": "#f2f2f2", "fg": "black"}

        # Left Box: Recipe
        recipe_frame = ttk.LabelFrame(split_frame, text="Recipe", padding=5)
        recipe_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,5))
        self.txt_recipe = tk.Text(recipe_frame, **txt_conf)
        self.txt_recipe.pack(fill=tk.BOTH, expand=True)

        # Right Box: Notes
        note_frame = ttk.LabelFrame(split_frame, text="Notes", padding=5)
        note_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5,0))
        self.txt_notes = tk.Text(note_frame, **txt_conf)
        self.txt_notes.pack(fill=tk.BOTH, expand=True)

        # Action Buttons
        btn_frame = ttk.Frame(data_container); btn_frame.pack(fill=tk.X, pady=5)
        ttk.Button(btn_frame, text="Save Changes", command=self.save_details).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="Add Event / Log", command=self.add_event_dialog).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="View Charts", command=self.open_charts).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Delete Entry", command=self.delete_log_entry).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Archive Brew & Clear Fermenter", command=self.archive_brew, style="Destructive.TButton").pack(side=tk.RIGHT)

        # Log Treeview
        log_frame = ttk.LabelFrame(data_container, text="Live Log", padding=10); log_frame.pack(fill=tk.BOTH, expand=True)
        cols = ("Time", "Type", "Description")
        self.tree = ttk.Treeview(log_frame, columns=cols, show="headings", height=4, style="LiveLog.Treeview")
        self.tree.heading("Time", text="Time"); self.tree.heading("Type", text="Type"); self.tree.heading("Description", text="Details")
        self.tree.column("Time", width=120); self.tree.column("Type", width=120); self.tree.column("Description", width=400)
        vsb = ttk.Scrollbar(log_frame, orient="vertical", command=self.tree.yview); self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); vsb.pack(side=tk.RIGHT, fill=tk.Y)
        
    def _build_history_panel(self) -> None:
        """Builds the UI for the 'Brew History' tab, including the list view, search, and detail panel."""
        h_paned = tk.PanedWindow(self.history_tab, orient=tk.HORIZONTAL, sashwidth=4)
        h_paned.pack(fill=tk.BOTH, expand=True)

        # --- Left Pane: List of archived brews ---
        left_h = ttk.Frame(h_paned); h_paned.add(left_h, width=300)
        ttk.Label(left_h, text="Archived Brews", font=("Arial", 12, "bold")).pack(pady=5)
        
        # Search Bar
        search_frame = ttk.Frame(left_h)
        search_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(search_frame, text="Search:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        # Trigger filter function whenever search text changes
        self.search_var.trace_add('write', lambda *args: self._filter_history_list())
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        
        # Archived brews list
        ttk.Button(left_h, text="Refresh List", command=self._refresh_history_list).pack(fill=tk.X)
        self.hist_tree = ttk.Treeview(left_h, columns=("Date", "Name"), show="headings")
        self.hist_tree.heading("Date", text="Date"); self.hist_tree.heading("Name", text="Name")
        self.hist_tree.column("Date", width=100)
        self.hist_tree.pack(fill=tk.BOTH, expand=True)
        self.hist_tree.bind("<<TreeviewSelect>>", self._on_hist_select)

        # --- Right Pane: Details panel with edit button ---
        self.h_detail_frame = ttk.Frame(h_paned, padding=10)
        h_paned.add(self.h_detail_frame)
        
        # Edit Archive Record Button
        h_btn_frame = ttk.Frame(self.h_detail_frame)
        h_btn_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Button(h_btn_frame, text="Edit Archive Record", command=self.edit_archive_record).pack(side=tk.LEFT)
        
        # Archived brew (Brew Record) text section
        self.h_content = tk.Text(self.h_detail_frame, state='disabled', wrap='word',
                                font=("Segoe UI", 11), bg="#f2f2f2", fg="black",
                                relief="flat", padx=10, pady=10)
        self.h_content.pack(fill=tk.BOTH, expand=True)

    # === Dashboard & Slot Logic ===

    def _refresh_dashboard(self) -> None:
        """Rebuilds all fermenter cards in the scrollable dashboard and refreshes timestamps."""
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
        for i, slot in enumerate(self.manager.slots):
            self._create_slot_card(i, slot)
        # Refresh history list as well to ensure it reflects any recent archiving
        self._refresh_history_list(None)

    def _create_slot_card(self, i: int, slot: Dict[str, Any]) -> None:
        """
        Creates the visual card for a single fermenter slot.

        Args:
            i (int): The index of the fermenter slot.
            slot (dict): The slot dictinoary containing 'name' and 'brew'.
        """
        f = ttk.Frame(self.scroll_frame, style="Card.TFrame", padding=10)
        f.pack(fill=tk.X, pady=5, padx=5)
        head = ttk.Frame(f)
        head.pack(fill=tk.X)
        name_lbl = ttk.Label(head, text=slot['name'], style="SlotTitle.TLabel")
        name_lbl.pack(side=tk.LEFT)
        
        # Rename fermenter button
        ttk.Button(head, text="✎", width=3, command=lambda idx=i: self.rename_slot_dialog(idx)).pack(side=tk.RIGHT)

        brew = slot['brew']
        if brew:
            # Display active brew details
            ttk.Label(f, text=brew.name, style="Occupied.TLabel").pack(anchor="w", pady=(5,0))
            met = ttk.Frame(f)
            met.pack(fill=tk.X)
            # Calculate and display the brew's age
            age = human_delta(parse_iso(brew.start_date))
            ttk.Label(met, text=f"{brew.category} • {brew.stage} • {age}", style="Metric.TLabel").pack(anchor="w")
            abv = brew.get_abv()
            val_abv = f"{abv:.1f}%" if abv else "?"
            ttk.Label(met, text=f"{brew.volume}L • {val_abv} ABV", style="Metric.TLabel").pack(anchor="w")
            
            # Action buttons (Manager/Transfer)
            btns = ttk.Frame(f)
            btns.pack(fill=tk.X, pady=(10,0))
            ttk.Button(btns, text="Manage", command=lambda idx=i: self.select_slot(idx)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
            t_text = "Target" if self.transfer_source is not None else "Transfer"
            if self.transfer_source == i: t_text = "Cancel"
            ttk.Button(btns, text=t_text, command=lambda idx=i: self.handle_transfer(idx)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        else:
            # Display empty slot actions
            ttk.Label(f, text="Empty", foreground="gray").pack(anchor="w", pady=10)
            btns = ttk.Frame(f)
            btns.pack(fill=tk.X)
            ttk.Button(btns, text="New Brew", command=lambda idx=i: self.new_brew_dialog(idx)).pack(fill=tk.X, pady=2)
            if self.transfer_source is not None:
                ttk.Button(btns, text="Paste Here", command=lambda idx=i: self.handle_transfer(idx)).pack(fill=tk.X)

    def rename_slot_dialog(self, idx: int) -> None:
        """
        Opens a dialog to rename a fermenter slot, validating that the new name is not empty.

        Args:
            idx: The index of the slot to rename.
        """
        old_name = self.manager.slots[idx]['name']
        new = simpledialog.askstring("Rename", "Enter name for this fermenter:", initialvalue=old_name, parent=self)
        if new and new.strip():
            self.manager.rename_slot(idx, new.strip())
            self._refresh_dashboard()
        elif new == "":
            messagebox.showerror("Error", "Fermenter name cannot be empty.")

    def select_slot(self, idx: int) -> None:
        """
        Loads the details of the selected brew into the 'Active Brew' detail tab and populates input fields.

        Args:
            idx: The index of the slot to select.
        """
        self.selected_slot_idx = idx
        slot = self.manager.slots[idx]
        brew = slot['brew']
        
        # Handle empty slot selection
        if not brew:
            self.header_lbl.config(text=f"{slot['name']} is Empty")
            self.notebook.select(self.detail_tab)
            return

        self.header_lbl.config(text=f"{slot['name']}: {brew.name}")
        
        # Populate UI variables from the Brew object (casting floats to strings)
        self.vars["name"].set(brew.name)
        self.vars["category"].set(brew.category)
        self.vars["stage"].set(brew.stage)
        self.vars["volume"].set(f"{brew.volume:.2f}")
        self.vars["og"].set(f"{brew.og:.3f}")
        self.vars["fg"].set(f"{brew.fg:.3f}")
        self.vars["ph"].set(f"{brew.ph:.2f}")
        self.vars["temp"].set(f"{brew.temp:.1f}")
        
        self.txt_recipe.delete("1.0", tk.END)
        self.txt_recipe.insert(tk.END, brew.recipe)

        self.txt_notes.delete("1.0", tk.END)
        self.txt_notes.insert(tk.END, brew.notes)

        abv = brew.get_abv()
        self.calc_lbl.config(text=f"ABV: {abv:.2f}%" if abv else "ABV: -")

        # Populate the Log Treeview (displaying in reverse chronological order)
        for item in self.tree.get_children(): self.tree.delete(item)
        for entry in reversed(brew.log):
            self.tree.insert("", "end", values=(fmt(entry["time"]), entry["type"], entry["text"]))
        
        self.notebook.select(self.detail_tab)

    def save_details(self) -> None:
        """
        Saves the contents of the detail panel back to the active Brew object.

        Validates numeric inputs and automatically logs metric changes (volume, gravity, etc.)
        if the new value is significantly different from the old value.
        """
        idx = self.selected_slot_idx
        if idx is None: return
        brew = self.manager.slots[idx]['brew']
        if not brew: return

        # Store old metrics for comparison
        old_metrics = {k: getattr(brew, k) for k in ["volume", "og", "fg", "ph", "temp"]}
        
        # Update static fields
        brew.name = self.vars["name"].get()
        brew.category = self.vars["category"].get()
        new_stage = self.vars["stage"].get()
        
        brew.recipe = self.txt_recipe.get("1.0", tk.END).strip()
        brew.notes = self.txt_notes.get("1.0", tk.END).strip()
        
        # Validate and update numeric fields (with logging)
        errors = []
        updates = {}
        metric_map = {
            "volume": ("Volume Reading", "L"), "og": ("Gravity Reading", ""), 
            "fg": ("Gravity Reading", ""), "ph": ("pH Reading", ""), "temp": ("Temp Check", "°C")
        }

        for key in metric_map:
            new_val = validate_float(self.vars[key].get(), default=None)
            
            if new_val is None:
                errors.append(key)
                # Re-set the UI variable to the last saved value to visually correct the error
                self.vars[key].set(f"{old_metrics[key]:.2f}") 
                continue
            
            # Update the brew object
            setattr(brew, key, new_val)
            
            # Check for significant change to log it
            if abs(new_val - old_metrics[key]) > 0.001:
                updates[key] = new_val

        if errors:
            messagebox.showerror("Validation Error", 
                                 "Invalid input for: " + ", ".join(errors) + ". Please enter numbers only.")
            # Re-render to show correct calculated fields and log entries
            self.select_slot(idx)
            return

        # Log all metric changes that passed validation
        for key, new_val in updates.items():
            event_type, unit = metric_map[key]
            log_text = f"{key.upper()} updated to {new_val}{unit}"
            brew.add_event(event_type, log_text)

        # Log stage change if necessary
        if new_stage != brew.stage:
            brew.add_event("Brew Stage Change", f"Stage changed from {brew.stage} to {new_stage}")
            brew.stage = new_stage # Update after logging old stage

        # Save and refresh
        self.manager.save_state()
        self._refresh_dashboard()
        self.select_slot(idx) # Re-render to update calculated fields (like ABV) and log
        messagebox.showinfo("Saved", "Changes saved and metric updates logged.")

    def add_event_dialog(self) -> None:
        """Opens a model dialog to add a new event/log entry to the currently selected brew."""
        idx = self.selected_slot_idx
        if idx is None or not self.manager.slots[idx]['brew']: return
        
        d = tk.Toplevel(self)
        d.title("Add Event")
        d.geometry("350x300")
        
        ttk.Label(d, text="Event Type").pack(pady=5)
        cbox = ttk.Combobox(d, values=EVENT_TYPES, state="readonly")
        cbox.current(0)
        cbox.pack()
        
        ttk.Label(d, text="Details / Reading Value").pack(pady=5)
        entry = tk.Entry(d)
        entry.pack(fill=tk.X, padx=20)
        
        def commit():
            txt = entry.get()
            etype = cbox.get()
            if txt:
                self.manager.slots[idx]['brew'].add_event(etype, txt)
                self.manager.save_state()
                self.select_slot(idx)   # Refresh the log
                d.destroy()
        
        ttk.Button(d, text="Add to Log", command=commit).pack(pady=20)

    def delete_log_entry(self) -> None:
        """Deletes the selected entry from the Live Log Treeview after user confirmation."""
        if self.selected_slot_idx is None:
            return
        
        selected_item = self.tree.selection()
        if not selected_item:
            messagebox.showwarning("Selection Required", "Please select a log entry to delete.")
            return
        
        brew = self.manager.slots[self.selected_slot_idx]['brew']
        if not brew: return

        # Calculate the real log index from the Treeview's visual (reversed) index
        visual_index = self.tree.index(selected_item[0])
        total_logs = len(brew.log)
        real_log_index = total_logs - 1 - visual_index
        entry_text = brew.log[real_log_index]['text']
        display_text = (entry_text[:50] + '...') if len(entry_text) > 50 else entry_text

        confirm = messagebox.askyesno(
            "Confirm Deletion",
            f"Are you sure you want to delete this event?\n\n'{display_text}"
        )
        if confirm:
            self.manager.delete_log_entry(self.selected_slot_idx, real_log_index)
            self.select_slot(self.selected_slot_idx)
    
    def archive_brew(self) -> None:
        """Archives the current brew (moves it to history) and clears the slot after confirmation."""
        if self.selected_slot_idx is None: return
        if messagebox.askyesno("Archive", "Move this brew to history and empty this fermenter?"):
            self.manager.archive_brew(self.selected_slot_idx)
            self._refresh_dashboard()
            self.selected_slot_idx = None
            self.header_lbl.config(text="Select a fermenter...")

    def open_charts(self) -> None:
        """Opens the chart visualization window for the currently selected brew."""
        if self.selected_slot_idx is None:
            messagebox.showwarning("No Selection", "Please select a brew first.")
            return
        
        brew = self.manager.slots[self.selected_slot_idx]['brew']
        if not brew:
            messagebox.showwarning("Empty Slot", "This fermenter is empty.")
            return
        
        # Initiate and display the ChartWindow
        ChartWindow(self, brew)
    
    # === Slot Management & Transfer Logic ===
    
    def handle_transfer(self, idx: int) -> None:
        """
        Initiates the first phase of a transfer (picking a source) or completes the second phase (executing
        transfer to a target).

        Args:
            idx: The index of the slot clicked.
        """
        if self.transfer_source is None:
            # Phase 1: Pick Source
            if self.manager.slots[idx]['brew'] is None: return
            self.transfer_source = idx
            self._refresh_dashboard()
            messagebox.showinfo("Transfer", f"Source selected: {self.manager.slots[idx]['name']}.\nSelect a target fermenter.")
        elif self.transfer_source == idx:
            # Cancel current transfer operation
            self.transfer_source = None
            self._refresh_dashboard()
        else:
            # Phase 2: Execute Transfer to Target
            if self.manager.slots[idx]['brew'] is not None:
                messagebox.showerror("Error", "Target fermenter must be empty.")
                return
            
            src_brew = self.manager.slots[self.transfer_source]['brew']
            
            # Open dialog to capture volume loss/final volume
            d = tk.Toplevel(self)
            d.title("Transfer Loss")
            d.transient(self) # Keep dialog on top
            
            v_start = src_brew.volume
            v_loss_str = tk.StringVar(value="0.0")
            v_final_str = tk.StringVar(value=f"{v_start:.2f}")

            # Function to link the two input fields (loss vs final volume)
            def update_fields(source):
                try:
                    if source == "loss":
                        loss = float(v_loss_str.get())
                        final = v_start - loss
                        v_final_str.set(f"{max(0, final):.2f}")
                    elif source == "final":
                        final = float(v_final_str.get())
                        loss = v_start - final
                        v_loss_str.set(f"{max(0, loss):.2f}")
                except ValueError:
                    # Ignore invalid input during typing
                    pass

            # UI for transfer dialog
            ttk.Label(d, text=f"Source: {self.manager.slots[self.transfer_source]['name']} (Start Vol: {v_start}L)").pack(pady=5)
            
            ttk.Label(d, text="Volume Lost (Trub/Sediment) L:").pack(pady=(10, 0))
            e_loss = ttk.Entry(d, textvariable=v_loss_str)
            e_loss.pack(fill=tk.X, padx=20)
            e_loss.bind("<KeyRelease>", lambda e: update_fields("loss"))
            
            ttk.Label(d, text="Volume into Target (Final Volume) L:").pack(pady=(10, 0))
            e_final = ttk.Entry(d, textvariable=v_final_str)
            e_final.pack(fill=tk.X, padx=20)
            e_final.bind("<KeyRelease>", lambda e: update_fields("final"))
            
            def do_it():
                loss = validate_float(v_loss_str.get())
                if loss < 0 or loss > v_start:
                    messagebox.showerror("Error", "Loss must be between 0 and starting volume.")
                    return
                
                # Execute the transfer via the manager
                self.manager.transfer(self.transfer_source, idx, loss)
                self.transfer_source = None
                self._refresh_dashboard()
                d.destroy()
                
            ttk.Button(d, text=f"Confirm Transfer to {self.manager.slots[idx]['name']}", command=do_it).pack(pady=20)
            
            d.grab_set()
            self.wait_window(d)

    def add_fermenter(self) -> None:
        """Adds a new fermenter slot and refreshes the dashboard."""
        self.manager.add_slot()
        self._refresh_dashboard()
        
    def remove_fermenter(self) -> None:
        """Removes the last fermenter slot, checking if it's empty first."""
        if not self.manager.remove_last_slot():
            messagebox.showerror("Error", "Cannot remove. Ensure last slot is empty.")
        else:
            self._refresh_dashboard()

    # === History Viewer Logic ===

    def _refresh_history_list(self, event: Optional[Any]) -> None:
        """Populates the TreeView list in the 'Brew History' tab."""
        self.search_var.set("") # Clear search
        for item in self.hist_tree.get_children(): self.hist_tree.delete(item)
        for i, h in enumerate(self.manager.history):
            d_str = fmt(h.get('start_date'))
            self.hist_tree.insert("", "end", iid=str(i), values=(d_str, h.get('name')))

    def _filter_history_list(self) -> None:
        """Filters the history list based on search input from the search_var."""
        search_term = self.search_var.get().lower()

        # Clear current items
        for item in self.hist_tree.get_children():
            self.hist_tree.delete(item)

        # Add filtered items
        for i, h in enumerate(self.manager.history):
            brew_name = h.get('name', '').lower()
            if search_term in brew_name:
                d_str = fmt(h.get('start_date'))
                self.hist_tree.insert("", "end", iid=str(i), values=(d_str, h.get('name')))

    def _on_hist_select(self, event: Any) -> None:
        """
        Displays the detailed text report for the selected archived brew.

        Args:
            event: The Treeview selection event (unused).
        """
        sel = self.hist_tree.selection()
        if not sel: return
        self.selected_history_idx = int(sel[0])
        data = self.manager.history[self.selected_history_idx]
        
        # Build the formatted text report
        lines = []
        lines.append(f"BREW RECORD: {data.get('name', 'Untitled')}")
        lines.append(f"Category: {data.get('category')}")
        lines.append(f"Started:  {fmt(data.get('start_date'))}")
        lines.append(f"Archived From: {data.get('archived_from', '-')}")
        lines.append("-" * 40)
        lines.append("METRICS")
        
        og = data.get('og')
        fg = data.get('fg')
        abv = calc_abv(og, fg) if (og and fg) else 0
        
        lines.append(f"Original Gravity: {og:.3f}" if isinstance(og, (float, int)) else "Original Gravity: -")
        lines.append(f"Final Gravity:    {fg:.3f}" if isinstance(fg, (float, int)) else "Final Gravity: -")
        lines.append(f"ABV:              {abv:.1f}%")
        lines.append("")
        
        orig_vol = data.get('original_volume', data.get('volume'))
        final_vol = data.get('volume')
        
        lines.append(f"Original Volume:  {orig_vol} L" if orig_vol is not None else "Original Volume: -")
        lines.append(f"Final Volume:     {final_vol} L" if final_vol is not None else "Final Volume: -")
        lines.append("-" * 40)
        lines.append(f"Recipe:\n{data.get('recipe', '')}\n")
        lines.append(f"Notes:\n{data.get('notes', '')}\n")
        lines.append("-" * 40)
        lines.append("EVENT LOG")
        for log in data.get('log', []):
            lines.append(f"[{fmt(log['time'])}] {log['type']}: {log['text']}")
            
        # Update the read-only text widget
        self.h_content.config(state='normal')
        self.h_content.delete("1.0", tk.END)
        self.h_content.insert(tk.END, "\n".join(lines))
        self.h_content.config(state='disabled')

    def edit_archive_record(self) -> None:
        """Opens a modal dialog (EditArchiveDialog) to edit the selected archived brew record."""
        if not hasattr(self, 'selected_history_idx') or self.selected_history_idx is None:
            messagebox.showwarning("No Selection", "Please select a brew from the history first.")
            return
        
        data = self.manager.history[self.selected_history_idx]
        EditArchiveDialog(self, data, self.selected_history_idx)

    def export_json(self) -> None:
        """Opens a save dialog and exports all active fermenter slots and history records to a single JSON file."""
        f = filedialog.asksaveasfilename(defaultextension=".json")
        if f:
            with open(f, 'w') as file:
                serial_slots = []
                # Prepare active slot data for serialization
                for s in self.manager.slots:
                    serial_slots.append({
                        'name': s['name'],
                        'brew': s['brew'].to_dict() if s['brew'] else None
                    })
                out = {'active': serial_slots, 'history': self.manager.history}
                json.dump(out, file, indent=2)

    def new_brew_dialog(self, idx: int) -> None:
        """
        Opens the initial dialog (NewBrewDialog) for creating a new brew in a specific empty slot.

        Args:
            idx: The index of the slot to place the new brew.
        """
        NewBrewDialog(self, idx)
    
    def _auto_refresh(self) -> None:
        """Timer loop that refreshes every 30 seconds to update brew/age time displays."""
        self._refresh_dashboard()
        self.after(30000, self._auto_refresh)

    def on_close(self) -> None:
        """Saves the current state of active brews and history before closing the application window."""
        try:
            self.manager.save_state()
            self.manager.save_history()
        except Exception as e:
            print(f"Error while saving: {e}")
            messagebox.showwarning("Autosave Failed", f"Failed to autosave active brews state: {e}\nData may be lost. Proceeding to close.")

        self.destroy()


# --------------------------------------------------------------------------
# Dialogs
# --------------------------------------------------------------------------


class EditArchiveDialog(tk.Toplevel):
    """
    Modal dialog for editing the details (name, metrics, recipe, notes) of a previously
    archived brew record in the history list.
    """
    def __init__(self, parent: 'App', data: Dict[str, Any], history_idx: int):
        """
        Initializes the dialog window and populates fields with archive data.

        Args:
            parent: The main application instance (App).
            data: The archived brew dictionary to be edited.
            history_idx: The index of the record in the FermenterManager.history list.
        """
        super().__init__(parent)
        self.parent = parent
        self.data = data
        self.history_idx = history_idx
        self.title(f"Edit Archive: {data.get('name', 'Untitled')}")
        self.geometry("800x700")

        # Create scrollable frame
        canvas = tk.Canvas(self)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)

        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Build form layout
        form = ttk.Frame(scroll_frame, padding=15)
        form.pack(fill=tk.BOTH, expand=True)

        # Variables for input fields
        self.v_name = tk.StringVar(value=data.get('name', ''))
        self.v_category = tk.StringVar(value=data.get('category', ''))
        # Ensure initial values are formatted consistently
        self.v_og = tk.StringVar(value=f"{data.get('og', 0):.3f}")
        self.v_fg = tk.StringVar(value=f"{data.get('fg', 0):.3f}")
        self.v_orig_vol = tk.StringVar(value=f"{data.get('original_volume', 0):.2f}")
        self.v_final_vol = tk.StringVar(value=f"{data.get('volume', 0):.2f}")

        # Basic info fields
        ttk.Label(form, text="Brew Name:", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w", pady=5)
        ttk.Entry(form, textvariable=self.v_name, width=40).grid(row=0, column=1, sticky="ew", pady=5)

        ttk.Label(form, text="Category:", font=("Segoe UI", 10, "bold")).grid(row=1, column=0, sticky="w", pady=5)
        ttk.Combobox(form, textvariable=self.v_category, values=CATEGORIES, width=37).grid(row=1, column=1, sticky="ew", pady=5)

        # Metric fields
        ttk.Label(form, text="Original Gravity:", font=("Segoe UI", 10, "bold")).grid(row=2, column=0, sticky="w", pady=5)
        ttk.Entry(form, textvariable=self.v_og, width=40).grid(row=2, column=1, sticky="ew", pady=5)
        
        ttk.Label(form, text="Final Gravity:", font=("Segoe UI", 10, "bold")).grid(row=3, column=0, sticky="w", pady=5)
        ttk.Entry(form, textvariable=self.v_fg, width=40).grid(row=3, column=1, sticky="ew", pady=5)
        
        ttk.Label(form, text="Original Volume (L):", font=("Segoe UI", 10, "bold")).grid(row=4, column=0, sticky="w", pady=5)
        ttk.Entry(form, textvariable=self.v_orig_vol, width=40).grid(row=4, column=1, sticky="ew", pady=5)
        
        ttk.Label(form, text="Final Volume (L):", font=("Segoe UI", 10, "bold")).grid(row=5, column=0, sticky="w", pady=5)
        ttk.Entry(form, textvariable=self.v_final_vol, width=40).grid(row=5, column=1, sticky="ew", pady=5)
        
        # Recipe text area
        ttk.Label(form, text="Recipe:", font=("Segoe UI", 10, "bold")).grid(row=6, column=0, sticky="nw", pady=5)
        self.txt_recipe = tk.Text(form, height=8, width=60, font=("Segoe UI", 11), bg="#f2f2f2", fg="black")
        self.txt_recipe.grid(row=6, column=1, sticky="ew", pady=5)
        self.txt_recipe.insert("1.0", data.get('recipe', ''))
        
        # Notes text area
        ttk.Label(form, text="Notes:", font=("Segoe UI", 10, "bold")).grid(row=7, column=0, sticky="nw", pady=5)
        self.txt_notes = tk.Text(form, height=8, width=60, font=("Segoe UI", 11), bg="#f2f2f2", fg="black")
        self.txt_notes.grid(row=7, column=1, sticky="ew", pady=5)
        self.txt_notes.insert("1.0", data.get('notes', ''))
        
        # Event Log (read-only display)
        ttk.Label(form, text="Event Log (read-only):", font=("Segoe UI", 10, "bold")).grid(row=8, column=0, sticky="nw", pady=5)
        self.txt_log = tk.Text(form, height=10, width=60, font=("Segoe UI", 9), bg="#f9f9f9", fg="black", state='disabled')
        self.txt_log.grid(row=8, column=1, sticky="ew", pady=5)
        
        # Populate log text area
        log_lines = []
        for log in data.get('log', []):
            # Assumes fmt is an available utility function
            log_lines.append(f"[{fmt(log['time'])}] {log['type']}: {log['text']}")
        self.txt_log.config(state='normal')
        self.txt_log.insert("1.0", "\n".join(log_lines))
        self.txt_log.config(state='disabled')
        
        # Action buttons
        btn_frame = ttk.Frame(form)
        btn_frame.grid(row=9, column=0, columnspan=2, pady=20)
        ttk.Button(btn_frame, text="Save Changes", command=self.save).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.LEFT, padx=5)
        
        form.columnconfigure(1, weight=1)

    def save(self) -> None:
        """
        Saves the edited details from the dialog fields back to the archive history record and
        triggers a UI refresh on the parent window.

        Performs validation to ensure fields like Gravity and Volume are valid floats within
        acceptable ranges
        """
        # Extract and validate inputs
        name = self.v_name.get().strip()
        # Assumes validate_float is an available utility function
        volume = validate_float(self.v_final_vol.get(), default=None)
        og = validate_float(self.v_og.get(), default=None)
        fg = validate_float(self.v_fg.get(), default=None)
        
        # --- Sanity Checks ---
        
        if not name:
            messagebox.showerror("Error", "Brew name cannot be empty.")
            return

        if volume is None or volume <= 0:
            messagebox.showerror("Error", "Volume must be a valid number greater than 0 (e.g., 20.0).")
            return
            
        if og is None:
            messagebox.showerror("Error", "Original Gravity must be a valid number (e.g., 1.050).")
            return
        if og < 0.980 or og > 1.200:
            messagebox.showerror("Error", f"Original Gravity ({og:.3f}) must be between 0.980 and 1.200.")
            return

        if fg is None:
            messagebox.showerror("Error", "Final Gravity must be a valid number (e.g., 1.010).")
            return
        if fg < 0.980 or fg > 1.200:
            messagebox.showerror("Error", f"Final Gravity ({fg:.3f}) must be between 0.980 and 1.200.")
            return
        
        # --- END SANITY CHECKS ---

        # Update the archive entry dictionary (self.data)
        self.data['name'] = name
        self.data['category'] = self.v_category.get() 
        self.data['volume'] = volume
        self.data['og'] = og
        self.data['fg'] = fg
        
        # Update text areas
        self.data['recipe'] = self.txt_recipe.get("1.0", tk.END).strip()
        self.data['notes'] = self.txt_notes.get("1.0", tk.END).strip()

        # Save changes and refresh UI
        try:
            self.parent.manager.save_history()
            # Refresh history list (to clear search filter, if active) and re-select the item
            self.parent._filter_history_list()
            self.parent.hist_tree.selection_set(self.history_idx)
            self.parent._on_hist_select(None)
            self.destroy() 
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save history or refresh UI: {e}")
            return


class NewBrewDialog(tk.Toplevel):
    """
    Modal dialog box for capturing the essential details required to start a new brew
    in an empty fermenter slot.
    """
    def __init__(self, parent: 'App', idx: int) -> None:
        """
        Initializes the dialog and sets up the form layout.

        Args:
            parent: The main application instance (App).
            idx: The index of the empty slot where the new brew will be created.
        """
        super().__init__(parent)
        self.parent = parent
        self.idx = idx
        self.title(f"New Brew in {parent.manager.slots[idx]['name']}")
        
        # Variables for input fields
        self.v_name = tk.StringVar()
        # Set category default to the first in the list, or "Beer" as a fallback
        self.v_cat = tk.StringVar(value=CATEGORIES[0] if CATEGORIES else "Beer")
        # Use StringVars for numeric input to handle validation
        self.v_vol = tk.StringVar(value="20.0")
        self.v_og = tk.StringVar(value="1.050")
        
        # Form layout
        form = ttk.Frame(self, padding=15)
        form.pack()
        
        # Name
        ttk.Label(form, text="Name:").grid(row=0, column=0, pady=5)
        ttk.Entry(form, textvariable=self.v_name).grid(row=0, column=1)
        
        # Category
        ttk.Label(form, text="Category:").grid(row=1, column=0, pady=5)
        ttk.Combobox(form, textvariable=self.v_cat, values=CATEGORIES).grid(row=1, column=1)
        
        # Starting volume
        ttk.Label(form, text="Start Vol (L):").grid(row=2, column=0, pady=5)
        ttk.Entry(form, textvariable=self.v_vol).grid(row=2, column=1)
        
        # Estimated original gravity (OG)
        ttk.Label(form, text="Est. OG:").grid(row=3, column=0, pady=5)
        ttk.Entry(form, textvariable=self.v_og).grid(row=3, column=1)
        
        # Create button
        ttk.Button(form, text="Create", command=self.save).grid(row=4, columnspan=2, pady=15)
        
    def save(self) -> None:
        """
        Validates the user input, instantiates a new Brew object, assigns it to the fermenter
        slot, and closes the dialog.
        """
        name = self.v_name.get().strip()
        # Assume validate_float is available
        volume = validate_float(self.v_vol.get(), default=None)
        og = validate_float(self.v_og.get(), default=None)
        
        # Validation checks
        if not name:
            messagebox.showerror("Error", "Brew name cannot be empty.")
            return
        if volume is None or og is None:
            messagebox.showerror("Error", "Volume and OG must be valid numbers (e.g., 20.0 or 1.050).")
            return

        # Create the new Brew object
        b = Brew(
            name=name,
            category=self.v_cat.get(),
            volume=volume,
            original_volume=volume,
            og=og
        )
        
        # Pass the new Brew object to the manager
        self.parent.manager.create_brew(self.idx, b)
        
        # Refresh the parent UI
        self.parent._refresh_dashboard()
        self.parent.select_slot(self.idx)
        
        self.destroy()

if __name__ == "__main__":
    app = App()
    app.mainloop()
