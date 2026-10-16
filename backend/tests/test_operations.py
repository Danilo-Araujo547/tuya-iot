import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event as Signal
from unittest.mock import Mock
import pytest
from sqlalchemy import text
from app.db import DB, Base, Device, Event, Command
from app.commands import submit
from app.worker import maintenance


def test_duplicate_in_flight_command_is_not_resent(database):
    if database.dialect.name == "sqlite":
        pytest.skip("Concurrent transactions require PostgreSQL")
    entered, release = Signal(), Signal()
    adapter = Mock()
    def send(*_):
        entered.set()
        assert release.wait(10)
        return True
    adapter.command.side_effect = send
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(submit, "remote", True, "concurrent-key", "admin", adapter)
        assert entered.wait(10)
        second = submit("remote", True, "concurrent-key", "admin", adapter)
        assert second["status"] == "solicitado"
        release.set()
        assert first.result()["id"] == second["id"]
    adapter.command.assert_called_once()


def test_retention_prunes_payload_keeps_dedup_and_dead_events():
    with DB.begin() as db:
        db.add(Event(id="old", payload={"private": "payload"}, status="processed", received=time.time()-8*86400))
        db.add(Event(id="dead", payload={"unprocessed": True}, status="dead", received=time.time()-100*86400))
    maintenance()
    maintenance()
    with DB() as db:
        assert db.get(Event, "old").payload == {}
        assert db.get(Event, "old").payload_pruned
        assert db.get(Event, "dead").payload == {"unprocessed": True}


def test_sql_migration_is_repeatable_and_preserves_data(database, monkeypatch):
    if database.dialect.name != "postgresql":
        pytest.skip("SQL migration targets PostgreSQL")
    import app.cli as cli
    Base.metadata.drop_all(database)
    with database.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS schema_migrations"))
    monkeypatch.setattr(cli, "engine", database)
    cli.migrate()
    with DB.begin() as db:
        db.add(Device(id="preserved", name="Preserved", config={}))
        from app.db import Appearance, Wallpaper
        db.get(Appearance, 'dashboard').selected = 'studio'
        db.add(Wallpaper(id='preserved-wallpaper', name='Saved', image=b'persisted-bytes'))
    cli.migrate()
    with DB() as db:
        assert db.get(Device, "preserved").name == "Preserved"
        assert db.execute(text("SELECT version FROM schema_migrations ORDER BY version")).scalars().all() == ['001', '002', '003']
        assert db.get(Appearance, 'dashboard').selected == 'studio'
        assert db.get(Wallpaper, 'preserved-wallpaper').image == b'persisted-bytes'
