"""
Fermenter Manager v3.3 (Latest Update: Dec 5, 2025)
===================================================
Tkinter-based fermentation tracking suite for home winemakers/brewers.

Changes in v3.3:
- Added a Log Entry Deletion feature for correcting mistakes in the Live Log.
- Split Recipe & Notes into two enlarged, distinct text panels for improved data entry and visibility.
- Restyled Archive Button for increased clarity.
- Enhanced time tracking to include hours and minutes, and updated transfer logging to track volume loss.

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
from zoneinfo import ZoneInfo

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
        # Fallback to defaults if file is missing (only for safety)
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

# Load configuration before defining the rest of the file
load_config()


# --------------------------------------------------------------------------
# Utilities
# --------------------------------------------------------------------------

def now_utc():
    """Return current time as timezone-aware UTC datetime object."""
    return datetime.now(timezone.utc)

def iso_now():
    """Returns the current UTC time in ISO-8601 string format."""
    return now_utc().isoformat()

def parse_iso(s: str):
    """
    Parse ISO-8601 datetime string -> UTC aware datetime.

    Returns:
        datetime or None if string is invalid.
    """
    if not s: return None
    try:
        dt = datetime.fromisoformat(s)
        # Ensure naive datetimes are treated as UTC for consistency
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except: return None

def fmt(dt):
    """
    Convert UTC datetime (or ISO string) into formatted LOCAL display time.

    Args:
        dt (datetime|str): The starting time (UTC aware datetime object).

    Returns:
        str formatted using DATE_DISPLAY_FMT or '-' on failure.
    """
    if not dt: return "-"
    if isinstance(dt, str): dt = parse_iso(dt)
    # The datetime is converted to the local zone defined in config
    return dt.astimezone(LOCAL_ZONE).strftime(DATE_DISPLAY_FMT)

def human_delta(dt):
    """
    Return time elapsed since dt in 'Xd, Xh, Xm' format.
    
    Args:
        dt (datetime|str): The starting time (UTC aware datetime object).

    Returns:
        str formatted time elapsed or '-' on failure.
    """
    if not dt: return "-"
    delta = now_utc() - dt
    total_seconds = int(delta.total_seconds())
    days = total_seconds // 86400; total_seconds %= 86400
    hours = total_seconds // 3600; total_seconds %= 3600
    minutes = total_seconds // 60
    return f"{days}d, {hours}h, {minutes}m"

def calc_abv(og, fg):
    """
    Calculate approximate ABV using a conditional coefficient based on the expected final
    alcohol content (common practice for high-gravity brews).
        Expected ABV <= 8%: ABV = (OG - FG) * 131.25
        Expected ABV > 8%:  ABV = (OG - FG) * 135.00

    Args:
        og (float|str): Original gravity.
        fg (float|str): Final gravity.

    Returns:
        float: %ABV. Returns 0.0 on invalid input.
    """
    try:
        og_f, fg_f = float(og), float(fg)
        gravity_diff = og_f - fg_f
        if gravity_diff <= 0.0:
            return 0.0
        provisional_abv = gravity_diff * 131.25 
        if provisional_abv > 8.0:   
            final_coefficient = 135.0
        else:
            final_coefficient = 131.25
        final_abv = gravity_diff * final_coefficient
        return final_abv
    except ValueError:
        # Catch errors if og or fg cannot be converted to float
        return 0.0

def validate_float(value_str, default=0.0):
    """Safely convert a string to a float, returning a default on failure."""
    try:
        # Tries to convert, handles both scientific notation and regular floats
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
        """Initializes a Brew object, setting defaults or loading from kwargs."""
        self.id = kwargs.get("id") or f"brew_{int(now_utc().timestamp()*1000)}"
        self.name = kwargs.get("name", "Untitled")
        self.category = kwargs.get("category", CATEGORIES[0] if CATEGORIES else "Beer")
        self.recipe = kwargs.get("recipe", "")
        self.notes = kwargs.get("notes", "")
        
        self.start_date = kwargs.get("start_date") or iso_now()
        self.stage = kwargs.get("stage", STAGES[0] if STAGES else "Primary")
        
        # Metrics
        self.volume = kwargs.get("volume", 0.0) 
        self.original_volume = kwargs.get("original_volume", self.volume)
        
        self.og = kwargs.get("og", 0.0)
        self.fg = kwargs.get("fg", 0.0)
        self.ph = kwargs.get("ph", 0.0)
        self.temp = kwargs.get("temp", 0.0)

        # Log: List of dicts {time, type, text}
        self.log = kwargs.get("log", [])
        if not self.log:
            # Add initial event automatically
            self.add_event("Lifecycle", f"Created: {self.name}. Start Vol: {self.volume}L")

    def add_event(self, e_type, text):
        """
        Append an entry to the brew log.
        """
        entry = {
            "time": iso_now(),
            "type": e_type,
            "text": text
        }
        self.log.append(entry)

    def get_abv(self):
        """Calculates and returns the ABV."""
        if self.og and self.fg:
            return calc_abv(self.og, self.fg)
        return None

    def to_dict(self):
        """Serializes the Brew object to a dictionary for JSON saving."""
        return self.__dict__

    @classmethod
    def from_dict(cls, d):
        """Creates a Brew object from a dictionary (used for JSON loading)."""
        if not d: return None
        return cls(**d)


# --------------------------------------------------------------------------
# Business Logic (The Manager)
# --------------------------------------------------------------------------


class FermenterManager:
    """
    State + business logic layer (no UI).
    """
    def __init__(self):
        self.slots = [] 
        self.history = []
        self.load_state()
        self.load_history()

    def add_slot(self):
        """Adds a new, empty fermenter slot with a default name."""
        new_idx = len(self.slots) + 1
        self.slots.append({'name': f"Fermenter {new_idx}", 'brew': None})
        self.save_state()

    def remove_last_slot(self):
        """Removes the last fermenter slot, but only if it is empty."""
        if not self.slots: return False
        if self.slots[-1]['brew'] is not None: return False # Cannot remove occupied slot
        self.slots.pop()
        self.save_state()
        return True
        
    def rename_slot(self, idx, new_name):
        """Renames a specific fermenter slot."""
        self.slots[idx]['name'] = new_name
        self.save_state()

    def create_brew(self, idx, brew):
        """Places a new Brew object into the specified fermenter slot."""
        self.slots[idx]['brew'] = brew
        self.save_state()

    def archive_brew(self, idx):
        """
        Moves the Brew from an active slot to the history list, saving it's final
        metrics, and clears the active slot.
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

    def transfer(self, src_idx, dest_idx, vol_loss=0):
        """
        Move brew from one slot to another and log volume loss.
        """
        src_slot = self.slots[src_idx]
        dest_slot = self.slots[dest_idx]
        brew = src_slot['brew']
        
        # Calculate loss and update volume
        old_vol = brew.volume
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

    # --- Persistence ---
    def load_state(self):
        """Loads active fermenter slot data from the state file."""
        if not os.path.exists(STATE_FILE):
            self.slots = [{'name': f"Fermenter {i+1}", 'brew': None} for i in range(DEFAULT_SLOT_COUNT)]
            return
        try:
            with open(STATE_FILE, 'r') as f:
                data = json.load(f)
                cleaned_slots = []
                
                # MIGRATION LOGIC: Handles transition from old format (list of Brews)
                # to new format (list of dictionaries containing 'name' and 'brew').
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

    def save_state(self):
        """Saves the active fermenter slots to the state file."""
        out = []
        for s in self.slots:
            out.append({
                'name': s['name'],
                'brew': s['brew'].to_dict() if s['brew'] else None
            })
        with open(STATE_FILE, 'w') as f:
            json.dump(out, f, indent=2)

    def load_history(self):
        """Loads archived brew data from the history file."""
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, 'r') as f:
                    self.history = json.load(f)
            except: self.history = []

    def save_history(self):
        """Saves the history list to the history file."""
        with open(HISTORY_FILE, 'w') as f:
            json.dump(self.history, f, indent=2)

    def delete_log_entry(self, slot_idx, log_idx):
        """
        Removes a specific log entry from the brew in the given slot.

        Args:
            slot_idx (int): The index of the fermenter slot containing the brew whose log is to be modified.
            log_idx:        The index of the log entry within the brew.log list to be deleted.
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
    Tkinter UI wrapper providing:
        * Dashboard of fermenters
        * Interaction for logging, stage, gravity, transfers, etc.
        * JSON import/export
        * Auto-refresh time updates
    """
    def __init__(self):
        super().__init__()
        self.title("Fermenter Manager v3.2")
        self.geometry("1300x850")
        
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

    def _setup_styles(self):
        """Define ttk UI theme + fonts for card display."""
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

    def _build_menu(self):
        """Create top menu: File -> Export JSON."""
        menubar = tk.Menu(self)
        fm = tk.Menu(menubar, tearoff=0)
        fm.add_command(label="Export JSON", command=self.export_json)
        menubar.add_cascade(label="File", menu=fm)
        self.config(menu=menubar)

    def _build_ui(self):
        """Construct full GUI (Sidebar list + detail panel)."""
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

    def _build_detail_panel(self):
        """Builds the UI for the 'Active Brew' tab, using StringVar for validation."""
        self.header_lbl = ttk.Label(self.detail_tab, text="Select a fermenter...", font=("Arial", 18, "bold"))
        self.header_lbl.pack(anchor="w", pady=(0, 10))
        data_container = ttk.Frame(self.detail_tab)
        data_container.pack(fill=tk.BOTH, expand=True)

        # Variables mapped to the input fields (using StringVar for all numeric inputs)
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

        txt_conf = {"height": 10, "width": 1, "font": ("Segoe UI", 10), "bg": "#f2f2f2", "fg": "black"}

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
        ttk.Button(btn_frame, text="Save Changes", command=self.save_details).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Add Event / Log", command=self.add_event_dialog).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="Delete Entry", command=self.delete_log_entry).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Archive Brew & Clear Fermenter", command=self.archive_brew, style="Destructive.TButton").pack(side=tk.RIGHT)

        # Log Treeview
        log_frame = ttk.LabelFrame(data_container, text="Live Log", padding=10); log_frame.pack(fill=tk.BOTH, expand=True)
        cols = ("Time", "Type", "Description")
        self.tree = ttk.Treeview(log_frame, columns=cols, show="headings", height=4, style="LiveLog.Treeview")
        self.tree.heading("Time", text="Time"); self.tree.heading("Type", text="Type"); self.tree.heading("Description", text="Details")
        self.tree.column("Time", width=120); self.tree.column("Type", width=120); self.tree.column("Description", width=400)
        vsb = ttk.Scrollbar(log_frame, orient="vertical", command=self.tree.yview); self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); vsb.pack(side=tk.RIGHT, fill=tk.Y)
        
    def _build_history_panel(self):
        """Builds the UI for the 'Brew History' tab (Master-Detail view)."""
        h_paned = tk.PanedWindow(self.history_tab, orient=tk.HORIZONTAL, sashwidth=4)
        h_paned.pack(fill=tk.BOTH, expand=True)

        # Left Pane: List of archived brews
        left_h = ttk.Frame(h_paned); h_paned.add(left_h, width=300)
        ttk.Label(left_h, text="Archived Brews", font=("Arial", 12, "bold")).pack(pady=5)
        ttk.Button(left_h, text="Refresh List", command=self._refresh_history_list).pack(fill=tk.X)
        self.hist_tree = ttk.Treeview(left_h, columns=("Date", "Name"), show="headings")
        self.hist_tree.heading("Date", text="Date"); self.hist_tree.heading("Name", text="Name")
        self.hist_tree.column("Date", width=100)
        self.hist_tree.pack(fill=tk.BOTH, expand=True)
        self.hist_tree.bind("<<TreeviewSelect>>", self._on_hist_select)

        # Right Pane: Read-only details panel
        self.h_detail_frame = ttk.Frame(h_paned, padding=10)
        h_paned.add(self.h_detail_frame)  
        self.h_content = tk.Text(self.h_detail_frame, state='disabled', wrap='word', font=("Consolas", 10))
        self.h_content.pack(fill=tk.BOTH, expand=True)

    # === Dashboard & Slot Logic ===

    def _refresh_dashboard(self):
        """Rebuild fermenter cards and update displayed timestamps."""
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
        for i, slot in enumerate(self.manager.slots):
            self._create_slot_card(i, slot)
        self._refresh_history_list()

    def _create_slot_card(self, i, slot):
        """Creates the visual card for a single fermenter slot."""
        f = ttk.Frame(self.scroll_frame, style="Card.TFrame", padding=10)
        f.pack(fill=tk.X, pady=5, padx=5)
        head = ttk.Frame(f)
        head.pack(fill=tk.X)
        name_lbl = ttk.Label(head, text=slot['name'], style="SlotTitle.TLabel")
        name_lbl.pack(side=tk.LEFT)
        
        # Rename fermenter button
        ttk.Button(head, text="✎", width=3, command=lambda idx=i: self.rename_slot_dialog(idx)).pack(side=tk.RIGHT)

        # Create fermenter card
        brew = slot['brew']
        if brew:
            # Display active brew details
            ttk.Label(f, text=brew.name, style="Occupied.TLabel").pack(anchor="w", pady=(5,0))
            met = ttk.Frame(f)
            met.pack(fill=tk.X)
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

    def rename_slot_dialog(self, idx):
        """Renames fermenter slots, checking that the name is not empty."""
        old_name = self.manager.slots[idx]['name']
        new = simpledialog.askstring("Rename", "Enter name for this fermenter:", initialvalue=old_name, parent=self)
        if new and new.strip():
            self.manager.rename_slot(idx, new.strip())
            self._refresh_dashboard()
        elif new == "":
            messagebox.showerror("Error", "Fermenter name cannot be empty.")

    def select_slot(self, idx):
        """Loads the details of the selected brew into the 'Active Brew' tab."""
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

        # Populate the Log Treeview
        for item in self.tree.get_children(): self.tree.delete(item)
        for entry in reversed(brew.log):
            self.tree.insert("", "end", values=(fmt(entry["time"]), entry["type"], entry["text"]))
        
        self.notebook.select(self.detail_tab)

    def save_details(self):
        """
        Saves the contents of the detail panel back to the active Brew object,
        validating numeric inputs and automatically logging metric changes.
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
            
            # Check for significant change to log it (tolerance for floating point comparisons)
            if abs(new_val - old_metrics[key]) > 0.001:
                updates[key] = new_val

        if errors:
            messagebox.showerror("Validation Error", 
                                 "Invalid input for: " + ", ".join(errors) + ". Please enter numbers only.")
            # Stop here if numeric validation failed
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


    def add_event_dialog(self):
        """Opens a dialog to add a new event/log entry to the current brew."""
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

    def delete_log_entry(self):
        """Deletes the selected entry from the Live Log Treeview after confirmation."""
        if self.selected_slot_idx is None:
            return
        
        selected_item = self.tree.selection()
        if not selected_item:
            messagebox.showwarning("Selection Required", "Please select a log entry to delete.")
            return
        
        brew = self.manager.slots[self.selected_slot_idx]['brew']
        if not brew: return

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
    
    def archive_brew(self):
        """Archives the current brew and clears the slot after confirmation."""
        if self.selected_slot_idx is None: return
        if messagebox.askyesno("Archive", "Move this brew to history and empty this fermenter?"):
            self.manager.archive_brew(self.selected_slot_idx)
            self._refresh_dashboard()
            self.selected_slot_idx = None
            self.header_lbl.config(text="Select a fermenter...")
    
    # === Slot Management & Transfer Logic ===
    
    def handle_transfer(self, idx):
        """Initiates or completes a brew transfer operation."""
        if self.transfer_source is None:
            # Phase 1: Pick Source
            if self.manager.slots[idx]['brew'] is None: return
            self.transfer_source = idx
            self._refresh_dashboard()
            messagebox.showinfo("Transfer", f"Source selected: {self.manager.slots[idx]['name']}.\nSelect a target fermenter.")
        elif self.transfer_source == idx:
            # Cancel
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

            # Function to link the two input fields
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
                
                self.manager.transfer(self.transfer_source, idx, loss)
                self.transfer_source = None
                self._refresh_dashboard()
                d.destroy()
                
            ttk.Button(d, text=f"Confirm Transfer to {self.manager.slots[idx]['name']}", command=do_it).pack(pady=20)
            
            d.grab_set() # Modal behavior
            self.wait_window(d) # Wait until dialog closes

    def add_fermenter(self):
        """UI callback -> manager.add_slot(), refresh display"""
        self.manager.add_slot()
        self._refresh_dashboard()
        
    def remove_fermenter(self):
        """UI callback -> remove last empty slot or warn if blocked."""
        if not self.manager.remove_last_slot():
            messagebox.showerror("Error", "Cannot remove. Ensure last slot is empty.")
        else:
            self._refresh_dashboard()

    # === History Viewer Logic ===

    def _refresh_history_list(self):
        """Populates the TreeView list in the 'Brew History' tab."""
        for item in self.hist_tree.get_children(): self.hist_tree.delete(item)
        for i, h in enumerate(self.manager.history):
            d_str = fmt(h.get('start_date'))
            self.hist_tree.insert("", "end", iid=str(i), values=(d_str, h.get('name')))

    def _on_hist_select(self, event):
        """Displays the detailed report for the selected archived brew."""
        sel = self.hist_tree.selection()
        if not sel: return
        idx = int(sel[0])
        data = self.manager.history[idx]
        
        # Build the formatted text report.
        lines = []
        lines.append(f"BREW RECORD: {data.get('name', 'Untitled')}")
        lines.append(f"Category: {data.get('category')}")
        lines.append(f"Started:  {fmt(data.get('start_date'))}")
        lines.append(f"Archived From: {data.get('archived_from', '-')}")
        lines.append("-" * 40)
        lines.append("METRICS")
        
        og = data.get('og', 0)
        fg = data.get('fg', 0)
        abv = calc_abv(og, fg) if (og and fg) else 0
        
        lines.append(f"Original Gravity: {og:.3f}")
        lines.append(f"Final Gravity:    {fg:.3f}")
        lines.append(f"ABV:              {abv:.1f}%")
        lines.append("")
        
        orig_vol = data.get('original_volume', data.get('volume'))
        final_vol = data.get('volume')
        
        lines.append(f"Original Volume:  {orig_vol} L")
        lines.append(f"Final Volume:     {final_vol} L")
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

    def export_json(self):
        """Open save dialog -> dump slots+history JSON externally."""
        f = filedialog.asksaveasfilename(defaultextension=".json")
        if f:
            with open(f, 'w') as file:
                serial_slots = []
                for s in self.manager.slots:
                    serial_slots.append({
                        'name': s['name'],
                        'brew': s['brew'].to_dict() if s['brew'] else None
                    })
                out = {'active': serial_slots, 'history': self.manager.history}
                json.dump(out, file, indent=2)

    def new_brew_dialog(self, idx):
        """Opens the initial dialog for creating a new brew."""
        NewBrewDialog(self, idx)
    
    def _auto_refresh(self):
        """Timer loop; refresh every 30s so age/time displays stay accurate."""
        self._refresh_dashboard()
        self.after(30000, self._auto_refresh)


# --------------------------------------------------------------------------
# Dialogs
# --------------------------------------------------------------------------


class NewBrewDialog(tk.Toplevel):
    """Dialog box for entering basic details of a new brew."""
    def __init__(self, parent, idx):
        super().__init__(parent)
        self.parent = parent
        self.idx = idx
        self.title(f"New Brew in {parent.manager.slots[idx]['name']}")
        
        self.v_name = tk.StringVar()
        self.v_cat = tk.StringVar(value=CATEGORIES[0] if CATEGORIES else "Beer")
        # Use StringVars for input fields to leverage validation later
        self.v_vol = tk.StringVar(value="20.0")
        self.v_og = tk.StringVar(value="1.050")
        
        form = ttk.Frame(self, padding=15)
        form.pack()
        
        ttk.Label(form, text="Name:").grid(row=0, column=0, pady=5)
        ttk.Entry(form, textvariable=self.v_name).grid(row=0, column=1)
        ttk.Label(form, text="Category:").grid(row=1, column=0, pady=5)
        ttk.Combobox(form, textvariable=self.v_cat, values=CATEGORIES).grid(row=1, column=1)
        ttk.Label(form, text="Start Vol (L):").grid(row=2, column=0, pady=5)
        ttk.Entry(form, textvariable=self.v_vol).grid(row=2, column=1)
        ttk.Label(form, text="Est. OG:").grid(row=3, column=0, pady=5)
        ttk.Entry(form, textvariable=self.v_og).grid(row=3, column=1)
        
        ttk.Button(form, text="Create", command=self.save).grid(row=4, columnspan=2, pady=15)
        
    def save(self):
        """Creates the new Brew object, validating inputs first."""
        name = self.v_name.get().strip()
        volume = validate_float(self.v_vol.get(), default=None)
        og = validate_float(self.v_og.get(), default=None)
        
        if not name:
            messagebox.showerror("Error", "Brew name cannot be empty.")
            return
        if volume is None or og is None:
            messagebox.showerror("Error", "Volume and OG must be valid numbers (e.g., 20.0 or 1.050).")
            return

        b = Brew(
            name=name,
            category=self.v_cat.get(),
            volume=volume,
            original_volume=volume,   # Crucial: Tracks the original starting volume
            og=og
        )
        self.parent.manager.create_brew(self.idx, b)
        self.parent._refresh_dashboard()
        self.parent.select_slot(self.idx)
        self.destroy()

if __name__ == "__main__":
    app = App()
    app.mainloop()
