# Student Study Planner

A desktop study planner built with Python Tkinter and SQLite.

## Run
```bash
python study_planner.py
```

No third-party packages are required. Python 3.8+ is recommended.

## Database
The application automatically creates `study_planner.db` beside the Python file.
Tasks are stored in the SQLite `tasks` table. If an older `tasks.json` file exists
in the same folder, its valid tasks are imported once into an empty database.
