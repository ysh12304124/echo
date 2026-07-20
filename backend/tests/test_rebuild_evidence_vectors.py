import sqlite3

from scripts.rebuild_evidence_vectors import backup_vector_database


def test_backup_vector_database_creates_readable_snapshot(tmp_path):
    source_path = tmp_path / "vectors.db"
    with sqlite3.connect(source_path) as db:
        db.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        db.execute("INSERT INTO marker (value) VALUES ('before-rebuild')")

    backup_path = backup_vector_database(source_path)

    assert backup_path is not None and backup_path.exists()
    with sqlite3.connect(backup_path) as db:
        assert db.execute("SELECT value FROM marker").fetchone()[0] == "before-rebuild"
