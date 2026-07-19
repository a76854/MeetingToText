import json
import sqlite3
import threading

from backend.app.config import settings
from backend.app.models.schemas import TaskInfo, TaskStatus, ProgressInfo, TaskResult, TranscriptSegment

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    audio_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    duration REAL DEFAULT 0,
    segments TEXT DEFAULT '[]',
    full_text TEXT DEFAULT '',
    minutes TEXT DEFAULT '',
    error TEXT DEFAULT ''
)
"""


class TaskStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute(SCHEMA)
            conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def create(self, task: TaskInfo) -> TaskInfo:
        with self._lock:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT INTO tasks (id, filename, audio_path, status, created_at, duration, segments, full_text, minutes, error) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        task.id, task.filename, task.audio_path,
                        task.status.value, task.created_at, 0.0, "[]", "", "", ""
                    ),
                )
                conn.commit()
        return task

    def get(self, task_id: str) -> TaskInfo | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_task(row)

    def update_progress(self, task_id: str, status: TaskStatus, error: str | None = None):
        with self._lock:
            with self._get_conn() as conn:
                if error is not None:
                    conn.execute("UPDATE tasks SET status = ?, error = ? WHERE id = ?",
                                 (status.value, error, task_id))
                else:
                    conn.execute("UPDATE tasks SET status = ? WHERE id = ?",
                                 (status.value, task_id))
                conn.commit()

    def save_result(self, task_id: str, result: TaskResult):
        segments_json = json.dumps([s.model_dump() for s in result.segments], ensure_ascii=False)
        with self._lock:
            with self._get_conn() as conn:
                conn.execute(
                    "UPDATE tasks SET status = ?, duration = ?, segments = ?, full_text = ? WHERE id = ?",
                    (TaskStatus.done.value, result.duration, segments_json, result.full_text, task_id),
                )
                conn.commit()

    def save_minutes(self, task_id: str, minutes: str):
        with self._lock:
            with self._get_conn() as conn:
                conn.execute("UPDATE tasks SET minutes = ? WHERE id = ?", (minutes, task_id))
                conn.commit()

    def list_tasks(self, limit: int = 50) -> list[TaskInfo]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def delete(self, task_id: str):
        with self._lock:
            with self._get_conn() as conn:
                conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
                conn.commit()

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> TaskInfo:
        segments_raw = json.loads(row["segments"] or "[]")
        segments = [TranscriptSegment(**s) for s in segments_raw]
        result = TaskResult(
            segments=segments,
            full_text=row["full_text"] or "",
            duration=row["duration"] or 0.0,
        ) if (segments or row["full_text"]) else None

        return TaskInfo(
            id=row["id"],
            status=TaskStatus(row["status"]),
            filename=row["filename"],
            audio_path=row["audio_path"],
            created_at=row["created_at"],
            progress=ProgressInfo(),
            result=result,
            minutes=row["minutes"] or None,
            error=row["error"] or None,
        )


_store: TaskStore | None = None


def get_store() -> TaskStore:
    global _store
    if _store is None:
        _store = TaskStore(settings.db_path)
    return _store
