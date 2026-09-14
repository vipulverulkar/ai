# 💰 Daily Expense Tracker — Desktop App

Modern, standalone desktop app with a **single-file database** (`expenses.db` via SQLite — same idea as an MS Access `.accdb`: no server, just copy the file to back up / move PCs).

Uses **only Python standard library** (`tkinter` + `sqlite3` + `csv`) for running. Build tooling (`PyInstaller`) is installed automatically when you build an EXE.

![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue) ![Platform Windows | macOS | Linux](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey) ![License MIT](https://img.shields.io/badge/License-MIT-green)

---

## ✨ Quick Start (Windows — Recommended)

1. **Download** the project:
   - **Option A — Git:** `git clone <your-repo-url>` → `cd exptracker`
   - **Option B — ZIP:** Download ZIP from GitHub → Right-click → *Extract All* → open the folder

2. **Double-click `run.bat`**

That’s it. The launcher will:
- auto-detect `python` / `py` / `python3`
- check `tkinter` is available
- run `pip install --upgrade pip` and `pip install -r requirements.txt` (no-op for running, needed for building)
- start the app → `expenses.db` is created **beside `run.bat` / `expense_tracker.py`** on first run and seeded with default categories

> To back up / move PCs: just copy `expenses.db` (portable, like `.accdb`).

### 🐧 Quick Start (macOS / Linux)

```bash
git clone <your-repo-url> && cd exptracker
chmod +x run.sh
./run.sh
# — or manually —
pip3 install -r requirements.txt
python3 expense_tracker.py
```

`run.sh` does the same auto-detect + `pip install` as `run.bat` (handles `externally-managed-environment` via `--break-system-packages`).

---

## 📋 Prerequisites

| Requirement | Details | How to get it |
|---|---|---|
| **Python 3.10+** | 3.10, 3.11, 3.12, 3.14 tested | https://www.python.org/downloads/ — **check** `Add python.exe to PATH` **and** `tcl/tk and IDLE` during install |
| **tkinter** | Comes with official Python | If you see `No module named 'tkinter'`: reinstall Python with `tcl/tk and IDLE` checked. On Linux: `sudo apt install python3-tk` (Debian/Ubuntu) / `sudo dnf install python3-tkinter` (Fedora) |
| **pip** | Comes with Python | `python -m ensurepip --upgrade` if missing |
| **OS** | Windows 10/11 (primary), macOS/Linux also supported | — |

No other pip packages are required to **run** the app. `requirements.txt` exists so `pip install -r requirements.txt` always succeeds (it installs `pyinstaller` for building an EXE).

---

## 📥 Download & Install — Step by Step

### 1) Get the code

```bash
# via Git (recommended)
git clone https://github.com/<you>/exptracker.git
cd exptracker

# or download ZIP from GitHub → Extract → open folder in Explorer / Terminal
```

### 2) Install dependencies

**Windows — automatic (recommended):**
```bat
run.bat
```
This does `pip install --upgrade pip` + `pip install -r requirements.txt` automatically before launching. First run may take 5–15s to check pip.

**Windows — manual (alternative):**
```bat
python --version          REM should print 3.10+
pip --version
pip install -r requirements.txt
python expense_tracker.py
```

**macOS / Linux:**
```bash
python3 --version
pip3 --version
pip3 install -r requirements.txt   # no-op for running, installs pyinstaller for building
python3 expense_tracker.py
# or make executable: chmod +x expense_tracker.py && ./expense_tracker.py
```

`requirements.txt`:
```txt
# Runtime: stdlib only — no packages needed to run
pyinstaller>=6.10          # only for building EXE via build_exe.bat
# black, flake8 … (commented, for dev)
```

### 3) Launch

| Method | Command | Notes |
|---|---|---|
| **Windows double-click** | `run.bat` | Auto-installs + launches |
| **Windows terminal** | `python expense_tracker.py` |  |
| **macOS/Linux** | `python3 expense_tracker.py` |  |
| **Python launcher** | `py -3 expense_tracker.py` | Windows `py` launcher |

On first launch the app creates `expenses.db` next to the script (or beside the EXE if you built one) and seeds 6 Income + 11 Expense default categories.

---

## 🖥️ Features

| Area | Details |
|---|---|
| ➕➖ **CRUD transactions** | Add / Edit (double-click) / Delete Income & Expense with date, category, amount, note |
| 🗂 **Categories** | Separate Income & Expense lists, quick add/delete/rename, plus **Category Manager** window (search, filter, usage counts, full CRUD with retag) |
| 🔍 **Transactions tab** | Filter by date range, type, category, text search; live totals (`Income • Expense • Balance`); striped rows; **Export CSV** |
| 📊 **Dashboard** | Modern card metrics (Income / Expense / Balance / Savings %) with accent top border + icon badge, recent 10, bar chart by category |
| 📅 **Daily report** | Pick date (Prev/Next/Today), shows count + totals |
| 🗓 **Monthly report** | Year/month picker, day-wise Income/Expense/Balance table, category breakdown + chart, **Export Month CSV** |
| 📈 **Graphs** | Category **donut pie** with % + legend (Income/Expense toggle), daily **trend** area-line (Income #059669 vs Expense #DC2626), **yearly grouped bars** (12 months) |
| 💾 **Standalone DB** | `expenses.db` — WAL mode, auto-migrates `category_id` FK, `VACUUM` via **🔧 DB Tools** (integrity check, backup) |
| 🎨 **Polished UI** | Light theme `#F1F5F9` app bg, white cards `#FFFFFF` + `#E2E8F0` border, `TNotebook` pill tabs, striped `Treeview` 30px rows, pill legends |

---

## 🏷️ Default Categories

- **Income:** Salary, Business, Freelance, Interest, Gift Received, Other Income
- **Expense:** Food, Groceries, Rent, Transport, Utilities, Shopping, Health, Education, Entertainment, Savings, Other Expense

Add your own in the **Categories** tab (or **🗂 Category Manager**).

---

## 📦 Make a Standalone `.exe` (No Python Needed on Target PC)

**Windows:**

```bat
build_exe.bat
```

This will:
1. Detect `python` / `py` / `python3`
2. `pip install --upgrade pip`
3. `pip install -r requirements.txt` → ensures `pyinstaller` is installed
4. Run `pyinstaller --onefile --windowed --name ExpenseTracker expense_tracker.py --clean --noconfirm`
5. Output: `dist\ExpenseTracker.exe` → double-click to run anywhere (even without Python). `expenses.db` is created **beside the EXE**.

**Manual (any OS):**
```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name ExpenseTracker expense_tracker.py
# or with pipx: pipx run pyinstaller --onefile --windowed --name ExpenseTracker expense_tracker.py
```

---

## 🗂️ Project Files

| File | Purpose |
|---|---|
| `expense_tracker.py` | Whole app (DB layer + modern ttk UI + charts) |
| `requirements.txt` | `pyinstaller>=6.10` (runtime is stdlib-only) — installed by `run.bat`/`run.sh`/`build_exe.bat` |
| `run.bat` | **Windows launcher** — auto-detects `python`/`py`, `pip install -r requirements.txt`, launches app |
| `run.sh` | **Linux/macOS launcher** — same as `run.bat` (`chmod +x run.sh && ./run.sh`) |
| `build_exe.bat` | **Windows builder** — auto-installs `pyinstaller` + builds `dist\ExpenseTracker.exe` |
| `schema.sql` | Canonical SQLite DDL (`category_id` FK + WAL) — also auto-created via `init_db()` |
| `seed_dummy.py` | Demo data: `python seed_dummy.py [months]` (default 6) — uses `expense_tracker.db_add_txn` |
| `expenses.db` | Your data (auto-created, portable single file, WAL + `idx_txn_*`) |
| `.flake8` / `pyproject.toml` | Lint/format config (`black` 100 cols, `flake8` max 100) |

---

## 🛠️ Troubleshooting

| Symptom | Fix |
|---|---|
| `Python was not found` / `python is not recognized` | Install from python.org and **check “Add python.exe to PATH”** → reopen terminal → `python --version` |
| `No module named 'tkinter'` / `_tkinter` | Reinstall Python with **“tcl/tk and IDLE”** checked. Linux: `sudo apt install python3-tk` |
| `pip is not recognized` | `python -m ensurepip --upgrade` → `python -m pip --version` |
| `pip install -r requirements.txt` fails with `externally-managed-environment` (Linux) | Use `pip install --break-system-packages -r requirements.txt` or `pipx` / `venv`: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt` |
| Window doesn’t appear / `TclError` | Ensure display is available (Windows: normal desktop; Linux headless: `xvfb-run python3 expense_tracker.py`) |
| `database is locked` | App uses `WAL` + `busy_timeout 5000` — wait a second and retry; avoid opening `expenses.db` in another SQLite tool while app is writing. Use **🔧 DB Tools → VACUUM** to compact |
| `dist\ExpenseTracker.exe` not found after build | Check console for `Build succeeded!` → `dir dist\*.exe` → ensure antivirus didn’t quarantine it |
| Want to reset DB | Close app → delete `expenses.db` (+ `-wal`/`-shm` if present) → relaunch (re-seeds categories). Or **🔧 DB Tools → VACUUM / Integrity Check** |

---

## 💡 Tips

- **Backup:** Close app → copy `expenses.db` to USB/cloud. To restore, copy back beside the script/EXE.
- **Move PCs:** Copy the whole folder (`.py` + `.db` + `.bat`) or just the EXE + `.db`.
- **Demo data:** `python seed_dummy.py 12` → 12 months of realistic random data (seed 42). Re-running **adds** more rows — delete `expenses.db` to start fresh.
- **CSV:** Transactions tab → *Export CSV* (filtered), Reports → *Export Month CSV* (includes monthly totals).
- **Shortcuts:** `F1` → Help; double-click any transaction/category row to edit.

---

## 📄 License

MIT — do what you want, keep the copyright notice.
