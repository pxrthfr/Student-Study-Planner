"""
Student Study Planner
---------------------
A desktop study planner built with Python's standard Tkinter library.

Features
    * Add, edit, delete and complete study tasks (subject, task, due date, priority)
    * Search and filter tasks (All / Pending / Done / Overdue)
    * Overdue tasks are highlighted automatically
    * Progress bar and statistics for completed work
    * Built-in Pomodoro focus timer (focus / break cycles)
    * Tasks are saved automatically to a local SQLite database (study_planner.db)

Team
    Parth Rindhe    (RA2511003011734)
    Divyansh Rai    (RA2511003011744)
    Saniya Sharma   (RA2511003011743)

Run with:  python study_planner.py      (Python 3.8 or newer, no extra packages)
"""

import os
import sqlite3
import tkinter as tk
from datetime import date, datetime
from tkinter import messagebox, ttk

APP_TITLE = "Student Study Planner"
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "study_planner.db")
DATE_FMT = "%Y-%m-%d"
PRIORITIES = ["High", "Medium", "Low"]
PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}
FILTERS = ["All", "Pending", "Done", "Overdue"]
STATUS_PENDING = "Pending"
STATUS_DONE = "Done"


# --------------------------------------------------------------------------- #
# Data layer (no GUI code here, so it can be tested on its own)
# --------------------------------------------------------------------------- #
def parse_date(text):
    """Return a date object for 'YYYY-MM-DD', or None if the text is invalid."""
    try:
        return datetime.strptime(text.strip(), DATE_FMT).date()
    except (ValueError, AttributeError):
        return None


class TaskStore:
    """Stores study tasks in a local SQLite database."""

    def __init__(self, path=DATA_FILE):
        self.path = path
        self.tasks = []
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self._create_table()
        self.load()
        self._import_legacy_json()

    def _create_table(self):
        with self.connection:
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject TEXT NOT NULL,
                    title TEXT NOT NULL,
                    due TEXT NOT NULL,
                    priority TEXT NOT NULL CHECK(priority IN ('High', 'Medium', 'Low')),
                    status TEXT NOT NULL DEFAULT 'Pending'
                        CHECK(status IN ('Pending', 'Done'))
                )
            """)

    def _import_legacy_json(self):
        """Import tasks.json once when migrating from the older version."""
        legacy_path = os.path.join(os.path.dirname(os.path.abspath(self.path)), "tasks.json")
        if not os.path.exists(legacy_path):
            return
        try:
            import json
            with open(legacy_path, "r", encoding="utf-8") as handle:
                legacy_tasks = json.load(handle)
        except (OSError, ValueError):
            return
        if not isinstance(legacy_tasks, list):
            return
        if self.connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] > 0:
            return
        for item in legacy_tasks:
            if not isinstance(item, dict):
                continue
            subject = str(item.get("subject", "")).strip()
            title = str(item.get("title", "")).strip()
            due = str(item.get("due", "")).strip()
            priority = item.get("priority")
            status = item.get("status", STATUS_PENDING)
            if (subject and title and parse_date(due) is not None
                    and priority in PRIORITIES
                    and status in (STATUS_PENDING, STATUS_DONE)):
                self.connection.execute(
                    "INSERT INTO tasks (subject, title, due, priority, status) VALUES (?, ?, ?, ?, ?)",
                    (subject, title, due, priority, status)
                )
        self.connection.commit()
        self.load()

    def load(self):
        rows = self.connection.execute(
            "SELECT id, subject, title, due, priority, status FROM tasks ORDER BY id"
        ).fetchall()
        self.tasks = [dict(row) for row in rows]

    def save(self):
        """SQLite commits each operation; retained for compatibility with the UI."""
        try:
            self.connection.commit()
            self.load()
            return True
        except sqlite3.Error:
            return False

    def add(self, subject, title, due, priority):
        cursor = self.connection.execute(
            "INSERT INTO tasks (subject, title, due, priority, status) VALUES (?, ?, ?, ?, ?)",
            (subject, title, due, priority, STATUS_PENDING)
        )
        self.connection.commit()
        self.load()
        return self.get(cursor.lastrowid)

    def get(self, task_id):
        row = self.connection.execute(
            "SELECT id, subject, title, due, priority, status FROM tasks WHERE id = ?",
            (task_id,)
        ).fetchone()
        return dict(row) if row else None

    def update(self, task_id, subject, title, due, priority):
        cursor = self.connection.execute(
            """UPDATE tasks SET subject = ?, title = ?, due = ?, priority = ?
               WHERE id = ?""",
            (subject, title, due, priority, task_id)
        )
        self.connection.commit()
        self.load()
        return cursor.rowcount > 0

    def delete(self, task_id):
        cursor = self.connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self.connection.commit()
        self.load()
        return cursor.rowcount > 0

    def toggle_done(self, task_id):
        cursor = self.connection.execute(
            """UPDATE tasks
               SET status = CASE WHEN status = 'Done' THEN 'Pending' ELSE 'Done' END
               WHERE id = ?""",
            (task_id,)
        )
        self.connection.commit()
        self.load()
        return cursor.rowcount > 0

    @staticmethod
    def is_overdue(task, today=None):
        today = today or date.today()
        due = parse_date(task["due"])
        return task["status"] == STATUS_PENDING and due is not None and due < today

    def stats(self):
        total = len(self.tasks)
        done = sum(1 for task in self.tasks if task["status"] == STATUS_DONE)
        overdue = sum(1 for task in self.tasks if self.is_overdue(task))
        return {
            "total": total,
            "done": done,
            "pending": total - done,
            "overdue": overdue,
            "percent": (done / total * 100) if total else 0.0,
        }

    def close(self):
        self.connection.close()


# --------------------------------------------------------------------------- #
# Planner tab
# --------------------------------------------------------------------------- #
class PlannerTab(ttk.Frame):
    def __init__(self, master, store):
        super().__init__(master, padding=10)
        self.store = store
        self.selected_id = None

        self.subject_var = tk.StringVar()
        self.title_var = tk.StringVar()
        self.due_var = tk.StringVar(value=date.today().strftime(DATE_FMT))
        self.priority_var = tk.StringVar(value="Medium")
        self.search_var = tk.StringVar()
        self.filter_var = tk.StringVar(value="All")
        self.progress_text = tk.StringVar()

        self._build_form()
        self._build_filters()
        self._build_table()
        self._build_actions()
        self._build_progress()
        self.refresh()

    # -- layout ------------------------------------------------------------------ #
    def _build_form(self):
        form = ttk.LabelFrame(self, text="Task details", padding=10)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        ttk.Label(form, text="Subject:").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(form, textvariable=self.subject_var).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Label(form, text="Task:").grid(row=0, column=2, sticky="w", padx=4)
        ttk.Entry(form, textvariable=self.title_var).grid(row=0, column=3, sticky="ew", padx=4)

        ttk.Label(form, text="Due (YYYY-MM-DD):").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(form, textvariable=self.due_var).grid(row=1, column=1, sticky="ew", padx=4)
        ttk.Label(form, text="Priority:").grid(row=1, column=2, sticky="w", padx=4)
        ttk.Combobox(form, textvariable=self.priority_var, values=PRIORITIES,
                     state="readonly").grid(row=1, column=3, sticky="ew", padx=4)

        buttons = ttk.Frame(form)
        buttons.grid(row=2, column=0, columnspan=4, sticky="e", pady=(8, 0))
        ttk.Button(buttons, text="Add Task", command=self.add_task).pack(side="left", padx=4)
        ttk.Button(buttons, text="Update Selected", command=self.update_task).pack(side="left", padx=4)
        ttk.Button(buttons, text="Clear Form", command=self.clear_form).pack(side="left", padx=4)

    def _build_filters(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(10, 4))
        ttk.Label(bar, text="Search:").pack(side="left")
        entry = ttk.Entry(bar, textvariable=self.search_var, width=28)
        entry.pack(side="left", padx=(4, 12))
        ttk.Label(bar, text="Show:").pack(side="left")
        combo = ttk.Combobox(bar, textvariable=self.filter_var, values=FILTERS,
                             state="readonly", width=10)
        combo.pack(side="left", padx=4)
        self.search_var.trace_add("write", lambda *_: self.refresh())
        combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh())

    def _build_table(self):
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        columns = ("subject", "title", "due", "priority", "status")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        headings = {"subject": ("Subject", 140), "title": ("Task", 280),
                    "due": ("Due Date", 100), "priority": ("Priority", 80),
                    "status": ("Status", 80)}
        for key, (label, width) in headings.items():
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor="w")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.tree.tag_configure("overdue", foreground="#b00020")
        self.tree.tag_configure("done", foreground="#7a7a7a")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

    def _build_actions(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="Mark Done / Undo", command=self.toggle_done).pack(side="left", padx=4)
        ttk.Button(bar, text="Delete Task", command=self.delete_task).pack(side="left", padx=4)

    def _build_progress(self):
        box = ttk.Frame(self)
        box.pack(fill="x", pady=(10, 0))
        self.progress = ttk.Progressbar(box, maximum=100, mode="determinate")
        self.progress.pack(fill="x")
        ttk.Label(box, textvariable=self.progress_text).pack(anchor="w", pady=(4, 0))

    # -- helpers ------------------------------------------------------------------- #
    def read_form(self):
        """Validate the form. Returns (subject, title, due, priority) or None."""
        subject = self.subject_var.get().strip()
        title = self.title_var.get().strip()
        due_text = self.due_var.get().strip()
        priority = self.priority_var.get()
        if not subject or not title:
            messagebox.showwarning(APP_TITLE, "Please enter both a subject and a task.")
            return None
        due = parse_date(due_text)
        if due is None:
            messagebox.showwarning(APP_TITLE, "Please enter the due date as YYYY-MM-DD "
                                              "(for example 2026-12-31).")
            return None
        if priority not in PRIORITIES:
            messagebox.showwarning(APP_TITLE, "Please choose a priority.")
            return None
        return subject, title, due.strftime(DATE_FMT), priority

    def save_store(self):
        if not self.store.save():
            messagebox.showerror(APP_TITLE, "Could not save tasks to disk.\n"
                                            "Check that the folder is writable.")

    def visible_tasks(self):
        query = self.search_var.get().strip().lower()
        mode = self.filter_var.get()
        result = []
        for task in self.store.tasks:
            if query and query not in task["subject"].lower() and query not in task["title"].lower():
                continue
            if mode == "Pending" and task["status"] != STATUS_PENDING:
                continue
            if mode == "Done" and task["status"] != STATUS_DONE:
                continue
            if mode == "Overdue" and not self.store.is_overdue(task):
                continue
            result.append(task)
        result.sort(key=lambda t: (t["status"] == STATUS_DONE, t["due"],
                                   PRIORITY_ORDER[t["priority"]], t["id"]))
        return result

    def refresh(self):
        keep = self.selected_id
        self.tree.delete(*self.tree.get_children())
        for task in self.visible_tasks():
            tags = []
            if task["status"] == STATUS_DONE:
                tags.append("done")
            elif self.store.is_overdue(task):
                tags.append("overdue")
            self.tree.insert("", "end", iid=str(task["id"]), tags=tags,
                             values=(task["subject"], task["title"], task["due"],
                                     task["priority"], task["status"]))
        if keep is not None and self.tree.exists(str(keep)):
            self.tree.selection_set(str(keep))
        else:
            self.selected_id = None

        s = self.store.stats()
        self.progress["value"] = s["percent"]
        self.progress_text.set(
            f"Completed {s['done']} of {s['total']} tasks ({s['percent']:.0f}%)   |   "
            f"Pending: {s['pending']}   |   Overdue: {s['overdue']}")

    def selected_task_id(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo(APP_TITLE, "Please select a task from the list first.")
            return None
        return int(selection[0])

    # -- actions ----------------------------------------------------------------------- #
    def add_task(self):
        values = self.read_form()
        if values is None:
            return
        self.store.add(*values)
        self.save_store()
        self.clear_form()
        self.refresh()

    def update_task(self):
        task_id = self.selected_task_id()
        if task_id is None:
            return
        values = self.read_form()
        if values is None:
            return
        self.store.update(task_id, *values)
        self.save_store()
        self.refresh()

    def toggle_done(self):
        task_id = self.selected_task_id()
        if task_id is None:
            return
        self.store.toggle_done(task_id)
        self.save_store()
        self.refresh()

    def delete_task(self):
        task_id = self.selected_task_id()
        if task_id is None:
            return
        if messagebox.askyesno(APP_TITLE, "Delete the selected task?"):
            self.store.delete(task_id)
            self.selected_id = None
            self.save_store()
            self.refresh()

    def clear_form(self):
        self.subject_var.set("")
        self.title_var.set("")
        self.due_var.set(date.today().strftime(DATE_FMT))
        self.priority_var.set("Medium")
        self.selected_id = None
        self.tree.selection_remove(self.tree.selection())

    def on_select(self, _event):
        selection = self.tree.selection()
        if not selection:
            return
        task = self.store.get(int(selection[0]))
        if task is None:
            return
        self.selected_id = task["id"]
        self.subject_var.set(task["subject"])
        self.title_var.set(task["title"])
        self.due_var.set(task["due"])
        self.priority_var.set(task["priority"])


# --------------------------------------------------------------------------- #
# Pomodoro timer tab
# --------------------------------------------------------------------------- #
class TimerTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=20)
        self.focus_min = tk.StringVar(value="25")
        self.break_min = tk.StringVar(value="5")
        self.mode = "Focus"
        self.remaining = 25 * 60
        self.running = False
        self.job = None
        self.sessions = 0

        self.mode_label = ttk.Label(self, text="Focus", font=("Segoe UI", 16, "bold"))
        self.mode_label.pack(pady=(10, 0))
        self.time_label = ttk.Label(self, text="25:00", font=("Segoe UI", 54, "bold"))
        self.time_label.pack(pady=10)

        controls = ttk.Frame(self)
        controls.pack(pady=6)
        ttk.Button(controls, text="Start", command=self.start).pack(side="left", padx=4)
        ttk.Button(controls, text="Pause", command=self.pause).pack(side="left", padx=4)
        ttk.Button(controls, text="Reset", command=self.reset).pack(side="left", padx=4)

        settings = ttk.LabelFrame(self, text="Settings (minutes)", padding=10)
        settings.pack(pady=16)
        ttk.Label(settings, text="Focus:").grid(row=0, column=0, padx=4)
        ttk.Spinbox(settings, from_=1, to=120, width=5, textvariable=self.focus_min,
                    command=self.apply_settings).grid(row=0, column=1, padx=4)
        ttk.Label(settings, text="Break:").grid(row=0, column=2, padx=4)
        ttk.Spinbox(settings, from_=1, to=60, width=5, textvariable=self.break_min,
                    command=self.apply_settings).grid(row=0, column=3, padx=4)
        ttk.Button(settings, text="Apply", command=self.apply_settings).grid(row=0, column=4, padx=8)

        self.session_label = ttk.Label(self, text="Focus sessions completed: 0")
        self.session_label.pack(pady=4)

    @staticmethod
    def _minutes(var, default, low, high):
        try:
            value = int(var.get())
        except (ValueError, tk.TclError):
            value = default
        value = max(low, min(high, value))
        var.set(str(value))
        return value

    def _duration(self):
        if self.mode == "Focus":
            return self._minutes(self.focus_min, 25, 1, 120) * 60
        return self._minutes(self.break_min, 5, 1, 60) * 60

    def _show(self):
        minutes, seconds = divmod(self.remaining, 60)
        self.time_label.config(text=f"{minutes:02d}:{seconds:02d}")
        self.mode_label.config(text=self.mode)

    def apply_settings(self):
        if not self.running:
            self.remaining = self._duration()
            self._show()

    def start(self):
        if self.running:
            return
        self.running = True
        self._tick()

    def pause(self):
        self.running = False
        self.stop_job()

    def reset(self):
        self.pause()
        self.mode = "Focus"
        self.remaining = self._duration()
        self._show()

    def stop_job(self):
        if self.job is not None:
            try:
                self.after_cancel(self.job)
            except tk.TclError:
                pass
            self.job = None

    def _tick(self):
        if not self.running:
            return
        self.remaining -= 1
        if self.remaining <= 0:
            self.bell()
            if self.mode == "Focus":
                self.sessions += 1
                self.session_label.config(text=f"Focus sessions completed: {self.sessions}")
                self.mode = "Break"
            else:
                self.mode = "Focus"
            self.remaining = self._duration()
        self._show()
        self.job = self.after(1000, self._tick)


# --------------------------------------------------------------------------- #
# Main application window
# --------------------------------------------------------------------------- #
class StudyPlannerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("760x640")
        self.minsize(680, 560)

        self.store = TaskStore()
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)
        self.planner = PlannerTab(notebook, self.store)
        self.timer = TimerTab(notebook)
        notebook.add(self.planner, text="Planner")
        notebook.add(self.timer, text="Focus Timer")

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_close(self):
        self.timer.pause()
        self.store.save()
        self.store.close()
        self.destroy()


def main():
    app = StudyPlannerApp()
    app.mainloop()


if __name__ == "__main__":
    main()