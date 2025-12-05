"""
Fermenter Manager v3.1
======================
Tkinter-based fermentation tracking suite for home winemakers/brewers.

Purpose:
--------
This program manages multiple fermenter vessels and stores their active batches,
historical records, gravity/ABV data, stage changes, and event logs. Data is 
persisted locally using JSON, requires no internet, and provides a live GUI
dashboard for quick monitoring.

Core Capabilities:
------------------
* Manage multiple fermenter vessels (add/remove/rename slots)
* Create brews with volume, OG/FG, category, notes, recipe
* Track long-term changes using timestamped event logs
* Transfer between vessels w/ automatic loss + logging
* Archive finished batches with full lifetime history
* Export JSON data for backup or external processing

Persistence:
------------
Active slots -> brews.json
Archive history -> brew_history.json
Compatible with legacy pre-v3 save format.
"""

import json
import os
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Persistent file names
STATE_FILE = "brews.json"
HISTORY_FILE = "brew_history.json"

# Configuration Constants
DEFAULT_SLOT_COUNT = 5
CATEGORIES = ["Beer", "Wine", "Mead", "Cider", "Kombucha", "Seltzer"]
STAGES = ["Primary", "Secondary", "Aging", "Cold Crash", "Bottled", "Kegged"]
EVENT_TYPES = [
    "General", 
    "Gravity Reading", 
    "Nutrient Addition", 
    "pH Reading", 
    "Temp Check", 
    "Aeration", 
    "Dry Hop", 
    "Fruit Addition", 
    "Fruit Removal", 
    "Brew Stage Change"
]
# Set the local timezone for display purposes
LOCAL_ZONE = ZoneInfo("America/New_York")
DATE_DISPLAY_FMT = "%Y-%m-%d %H:%M"


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
        dt (datetime|str)

    Returns:
        str formatted using DATE_DISPLAY_FMT or '-' on failure.
    """
    if not dt: return "-"
    if isinstance(dt, str): dt = parse_iso(dt)
    return dt.astimezone(LOCAL_ZONE).strftime(DATE_DISPLAY_FMT)

def human_delta(dt):
    """Return days elapsed since dt in 'Xd' format."""
    if not dt: return "-"
    delta = now_utc() - dt
    days = delta.days
    return f"{days}d"

def calc_abv(og, fg):
    """
    Calculate approximate ABV using standard formula:

        ABV = (OG - FG) * 131.25

    Args:
        og (float|str): Original gravity.
        fg (float|str): Final gravity.

    Returns:
        float: %ABV. Returns 0.0 on invalid input.
    """
    try:
        og, fg = float(og), float(fg)
        return (og - fg) * 131.25
    except:
        return 0.0


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
        self.category = kwargs.get("category", "Beer")
        self.recipe = kwargs.get("recipe", "")
        self.notes = kwargs.get("notes", "")
        
        self.start_date = kwargs.get("start_date") or iso_now()
        self.stage = kwargs.get("stage", "Primary")
        
        # Metrics
        self.volume = kwargs.get("volume", 0.0) 
        # original_volume tracks the initial volume, used for history reports
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

        Args:
            e_type (str): Event category (gravity, transfer, stage, etc.)
            text (str): Human-readable event description.

        Side Effects:
            Mutates self.log, adds a UTC timestamp.
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

    Stores:
        slots   -> list of {name:str, brew:Brew|None}
        history -> list of archived brew dicts

    Key Actions:
        add_slot()              Increase vessel capacity
        remove_last_slot()      Remove only if empty (safety)
        rename_slot(i,name)     Edit vessel label
        create_brew(i,brew)     Insert new active batch
        archive_brew(i)         Move batch -> history file + detach from slot
        transfer(a,b,loss)      Move brew slot -> slot with recorded loss
        load/save_state()       Handle brew.json
        load/save_history()     Handle brew_history.json 
    """
    def __init__(self):
        # self.slots is a list of dictionaries, allowing for named slots:
        # [ {'name': 'Carboy 1', 'brew': BrewObject or None}, ... ]
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
            # Save the fermenter name for history reference
            b_dict = b.to_dict()
            b_dict['archived_from'] = slot['name']
            self.history.insert(0, b_dict)  # Insert at the beginning (newest first)
            self.save_history()
        
        slot['brew'] = None
        self.save_state()

    def transfer(self, src_idx, dest_idx, vol_loss=0):
        """
        Move brew from one slot to another and log volume loss.

        Args:
            src_idx (int): Source slot index.
            dest_idx (int): Destination slot index.
            vol_loss (float): Volume loss in liters.

        Behavior:
            * Volume updated with loss subtracted.
            * Transfer event logged with % loss.
            * Source slot cleared, destination overwritten.
        """
        src_slot = self.slots[src_idx]
        dest_slot = self.slots[dest_idx]
        brew = src_slot['brew']
        
        # Calculate loss and update volume
        old_vol = brew.volume
        new_vol = old_vol - vol_loss
        loss_pct = (vol_loss / old_vol * 100) if old_vol > 0 else 0
        
        brew.volume = round(new_vol, 2)
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
                    # Fallback for unexpected forat
                    self.slots = [{'name': f"Fermenter {i+1}", 'brew': None} for i in range(DEFAULT_SLOT_COUNT)]
        except Exception as e:
            # If load fails, revert to default slots to prevent crashing
            print(f"Load Error: {e}")
            self.slots = [{'name': f"Fermenter {i+1}", 'brew': None} for i in range(DEFAULT_SLOT_COUNT)]

    def save_state(self):
        """Saves the active fermenter slots to the state file."""
        out = []
        # Serialize Brew objects to dicts before saving
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


# --------------------------------------------------------------------------
# GUI (Tkinter Application)
# --------------------------------------------------------------------------


class App(tk.Tk):
    """
    Tkinter UI wrapper providing:
        * Dashboard of fermenters
        * Interaction for logging, stage, gravity, transfers
        * JSON import/export
        * Auto-refresh time updates
    """
    def __init__(self):
        super().__init__()
        self.title("Fermenter Manager v3.1")
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

    def _setup_styles(self):
        """Define ttk UI theme + fonts for card display."""
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("Card.TFrame", background="#f4f4f4", relief="raised")
        style.configure("Occupied.TLabel", foreground="#003366", font=("Segoe UI", 11, "bold"))
        style.configure("SlotTitle.TLabel", font=("Segoe UI", 12, "bold"))
        style.configure("Metric.TLabel", font=("Segoe UI", 10))

    def _build_menu(self):
        """Create top menu: File -> Export JSON."""
        menubar = tk.Menu(self)
        fm = tk.Menu(menubar, tearoff=0)
        fm.add_command(label="Export JSON", command=self.export_json)
        menubar.add_cascade(label="File", menu=fm)
        self.config(menu=menubar)

    def _build_ui(self):
        """
        Construct full GUI (Sidebar list + detail panel).

        Contains:
            * Scrollable dashboard
            * Fermenter cards
            * Detail inspector panel
            * Action buttons for logging + transferring + archive
        """
        main_paned = tk.PanedWindow(self, orient=tk.HORIZONTAL, sashwidth=4)
        main_paned.pack(fill=tk.BOTH, expand=True)

        # --- Left: Dashboard (Fermenter List) ---
        self.dash_frame = ttk.Frame(main_paned)
        main_paned.add(self.dash_frame, width=380)
        
        ttk.Label(self.dash_frame, text="Active Fermenters", font=("Arial", 16, "bold")).pack(pady=(10,5))
        
        # --- Control Buttons (Add/Remove Fermenters) ---
        ctrl_frame = ttk.Frame(self.dash_frame)
        ctrl_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=10, padx=10)
        
        ttk.Button(ctrl_frame, text="+ Add Fermenter", command=self.add_fermenter).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        ttk.Button(ctrl_frame, text="- Remove Empty", command=self.remove_fermenter).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        # Scrollable area for the list of fermenter cards
        self.canvas = tk.Canvas(self.dash_frame, bg="#e1e1e1")
        self.scrollbar = ttk.Scrollbar(self.dash_frame, orient="vertical", command=self.canvas.yview)
        self.scroll_frame = ttk.Frame(self.canvas)
        
        # Bind the scroll frame to update the scroll region when contents change
        self.scroll_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw", width=360) 
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # --- Right: Details & History Notebook ---
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
        """Builds the UI for the 'Active Brew' tab."""
        self.header_lbl = ttk.Label(self.detail_tab, text="Select a fermenter...", font=("Arial", 18, "bold"))
        self.header_lbl.pack(anchor="w", pady=(0, 10))

        data_container = ttk.Frame(self.detail_tab)
        data_container.pack(fill=tk.BOTH, expand=True)

        # --- Top: Inputs ---
        top_frame = ttk.Frame(data_container)
        top_frame.pack(fill=tk.X)

        info_frame = ttk.LabelFrame(top_frame, text="Details", padding=10)
        info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        # Variables mapped to the input fields
        self.vars = {
            "name": tk.StringVar(),
            "category": tk.StringVar(),
            "stage": tk.StringVar(),
            "volume": tk.DoubleVar(),
            "og": tk.DoubleVar(),
            "fg": tk.DoubleVar(),
            "ph": tk.DoubleVar(),
            "temp": tk.DoubleVar(),
        }

        # Structure the detail inputs using grids
        r=0
        ttk.Label(info_frame, text="Name:").grid(row=r, column=0, sticky="e"); ttk.Entry(info_frame, textvariable=self.vars["name"]).grid(row=r, column=1, sticky="ew"); r+=1
        ttk.Label(info_frame, text="Category:").grid(row=r, column=0, sticky="e"); ttk.Combobox(info_frame, textvariable=self.vars["category"], values=CATEGORIES).grid(row=r, column=1, sticky="ew"); r+=1
        ttk.Label(info_frame, text="Stage:").grid(row=r, column=0, sticky="e"); ttk.Combobox(info_frame, textvariable=self.vars["stage"], values=STAGES).grid(row=r, column=1, sticky="ew"); r+=1
        ttk.Label(info_frame, text="Current Vol (L):").grid(row=r, column=0, sticky="e"); ttk.Entry(info_frame, textvariable=self.vars["volume"]).grid(row=r, column=1, sticky="ew"); r+=1

        metric_frame = ttk.LabelFrame(top_frame, text="Metrics", padding=10)
        metric_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))

        r=0
        ttk.Label(metric_frame, text="Orig. Gravity:").grid(row=r, column=0, sticky="e"); ttk.Entry(metric_frame, textvariable=self.vars["og"]).grid(row=r, column=1, sticky="ew"); r+=1
        ttk.Label(metric_frame, text="Final Gravity:").grid(row=r, column=0, sticky="e"); ttk.Entry(metric_frame, textvariable=self.vars["fg"]).grid(row=r, column=1, sticky="ew"); r+=1
        ttk.Label(metric_frame, text="pH:").grid(row=r, column=0, sticky="e"); ttk.Entry(metric_frame, textvariable=self.vars["ph"]).grid(row=r, column=1, sticky="ew"); r+=1
        ttk.Label(metric_frame, text="Temp (°C):").grid(row=r, column=0, sticky="e"); ttk.Entry(metric_frame, textvariable=self.vars["temp"]).grid(row=r, column=1, sticky="ew"); r+=1
        
        self.calc_lbl = ttk.Label(metric_frame, text="ABV: -", font=("Arial", 12, "bold"), foreground="green")
        self.calc_lbl.grid(row=r, column=0, columnspan=2, pady=10)

        # --- Middle: Recipe/Notes Text Area ---
        note_frame = ttk.LabelFrame(data_container, text="Recipe & Notes", padding=10)
        note_frame.pack(fill=tk.X, pady=10)
        self.txt_notes = tk.Text(note_frame, height=4, font=("Consolas", 10))
        self.txt_notes.pack(fill=tk.BOTH)

        # --- Action Buttons ---
        btn_frame = ttk.Frame(data_container)
        btn_frame.pack(fill=tk.X, pady=5)
        ttk.Button(btn_frame, text="Save Changes", command=self.save_details).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Add Event / Log", command=self.add_event_dialog).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="Archive & Clear Slot", command=self.archive_brew).pack(side=tk.RIGHT)

        # --- Bottom: Log Treeview ---
        log_frame = ttk.LabelFrame(data_container, text="Live Log", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("Time", "Type", "Description")
        self.tree = ttk.Treeview(log_frame, columns=cols, show="headings", height=6)
        self.tree.heading("Time", text="Time")
        self.tree.heading("Type", text="Type")
        self.tree.heading("Description", text="Details")
        self.tree.column("Time", width=120)
        self.tree.column("Type", width=120)
        self.tree.column("Description", width=400)
        
        vsb = ttk.Scrollbar(log_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_history_panel(self):
        """Builds the UI for the 'Brew History' tab (Master-Detail view)."""
        h_paned = tk.PanedWindow(self.history_tab, orient=tk.HORIZONTAL, sashwidth=4)
        h_paned.pack(fill=tk.BOTH, expand=True)

        # Left Pane: List of archived brews
        left_h = ttk.Frame(h_paned)
        h_paned.add(left_h, width=300)
        ttk.Label(left_h, text="Archived Brews", font=("Arial", 12, "bold")).pack(pady=5)
        ttk.Button(left_h, text="Refresh List", command=self._refresh_history_list).pack(fill=tk.X)
        self.hist_tree = ttk.Treeview(left_h, columns=("Date", "Name"), show="headings")
        self.hist_tree.heading("Date", text="Date")
        self.hist_tree.heading("Name", text="Name")
        self.hist_tree.column("Date", width=100)
        self.hist_tree.pack(fill=tk.BOTH, expand=True)
        self.hist_tree.bind("<<TreeviewSelect>>", self._on_hist_select)

        # Right Pane: Read-only details panel
        self.h_detail_frame = ttk.Frame(h_paned, padding=10)
        h_paned.add(self.h_detail_frame)  
        self.h_content = tk.Text(self.h_detail_frame, state='disabled', wrap='word', font=("Consolas", 10))
        self.h_content.pack(fill=tk.BOTH, expand=True)

    # --- Dashboard & Slot Logic ---
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
        
        # Rename button
        ttk.Button(head, text="✎", width=3, command=lambda idx=i: self.rename_slot_dialog(idx)).pack(side=tk.RIGHT)

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
        """Renames fermenter slots."""
        old_name = self.manager.slots[idx]['name']
        new = simpledialog.askstring("Rename", "Enter name for this fermenter:", initialvalue=old_name, parent=self)
        if new:
            self.manager.rename_slot(idx, new)
            self._refresh_dashboard()

    def select_slot(self, idx):
        """Loads the details of the selected brew into the 'Active Brew' tab."""
        self.selected_slot_idx = idx
        slot = self.manager.slots[idx]
        brew = slot['brew']
        
        if not brew:
            # Handle empty slot selection
            self.header_lbl.config(text=f"{slot['name']} is Empty")
            self.notebook.select(self.detail_tab)
            return

        self.header_lbl.config(text=f"{slot['name']}: {brew.name}")
        
        # Populate UI variables from the Brew object
        self.vars["name"].set(brew.name)
        self.vars["category"].set(brew.category)
        self.vars["stage"].set(brew.stage)
        self.vars["volume"].set(brew.volume)
        self.vars["og"].set(brew.og)
        self.vars["fg"].set(brew.fg)
        self.vars["ph"].set(brew.ph)
        self.vars["temp"].set(brew.temp)
        
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
        """Saves the contents of the detail panel back to the active Brew object."""
        idx = self.selected_slot_idx
        if idx is None: return
        brew = self.manager.slots[idx]['brew']
        if not brew: return

        # Update object fields from UI variables
        brew.name = self.vars["name"].get()
        brew.category = self.vars["category"].get()
        brew.stage = self.vars["stage"].get()
        brew.volume = self.vars["volume"].get()
        brew.og = self.vars["og"].get()
        brew.fg = self.vars["fg"].get()
        brew.ph = self.vars["ph"].get()
        brew.temp = self.vars["temp"].get()
        brew.notes = self.txt_notes.get("1.0", tk.END).strip()

        self.manager.save_state()
        self._refresh_dashboard()
        self.select_slot(idx)   # Re-render to update calculated fields (like ABV)
        messagebox.showinfo("Saved", "Changes saved.")

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

    def archive_brew(self):
        """Archives the current brew and clears the slot after confirmation."""
        if self.selected_slot_idx is None: return
        if messagebox.askyesno("Archive", "Move this brew to history and empty this fermenter?"):
            self.manager.archive_brew(self.selected_slot_idx)
            self._refresh_dashboard()
            self.selected_slot_idx = None
            self.header_lbl.config(text="Select a fermenter...")
    
    # --- Slot Management & Transfer Logic ---
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
            ttk.Label(d, text=f"Starting Vol: {src_brew.volume}L").pack(pady=5)
            ttk.Label(d, text="Volume making it into target (L):").pack()
            
            v = tk.DoubleVar(value=src_brew.volume)
            ttk.Entry(d, textvariable=v).pack(pady=5)
            
            def do_it():
                new_v = v.get()
                loss = src_brew.volume - new_v
                if loss < 0: loss = 0
                self.manager.transfer(self.transfer_source, idx, loss)
                self.transfer_source = None
                self._refresh_dashboard()
                d.destroy()
                
            ttk.Button(d, text="Confirm", command=do_it).pack(pady=10)

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

    # --- History Viewer Logic ---
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
        final_vol = data.get('volume')  # 'volume' at archive time is the final volume
        
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
                # Manually serialize active slots to ensure proper structure
                out = {'active': self.manager.slots, 'history': self.manager.history}
                serial_slots = []
                for s in self.manager.slots:
                    serial_slots.append({
                        'name': s['name'],
                        'brew': s['brew'].to_dict() if s['brew'] else None
                    })
                out['active'] = serial_slots
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
        self.title(f"New Brew")
        
        self.v_name = tk.StringVar()
        self.v_cat = tk.StringVar(value="Beer")
        self.v_vol = tk.DoubleVar(value=20.0)
        self.v_og = tk.DoubleVar(value=1.050)
        
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
        """Creates the new Brew object and places it in the selected slot."""
        if not self.v_name.get(): return
        b = Brew(
            name=self.v_name.get(),
            category=self.v_cat.get(),
            volume=self.v_vol.get(),
            original_volume=self.v_vol.get(),   # Crucial: Tracks the original starting volume
            og=self.v_og.get()
        )
        self.parent.manager.create_brew(self.idx, b)
        self.parent._refresh_dashboard()
        self.parent.select_slot(self.idx)
        self.destroy()

if __name__ == "__main__":
    app = App()
    app.mainloop()
