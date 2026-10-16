import time
import uuid
from sqlalchemy import create_engine, String, Float, Integer, JSON, Boolean, UniqueConstraint, Index, LargeBinary
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from .config import DATABASE_URL


def uid():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    config: Mapped[dict] = mapped_column(JSON)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    received: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    payload_pruned: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[str | None] = mapped_column(String, nullable=True)


class Measurement(Base):
    __tablename__ = "measurements"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    event_id: Mapped[str] = mapped_column(String)
    device_id: Mapped[str] = mapped_column(String)
    property: Mapped[str] = mapped_column(String)
    value: Mapped[object] = mapped_column(JSON)
    unit: Mapped[str] = mapped_column(String, default="")
    observed: Mapped[float] = mapped_column(Float, index=True)
    received: Mapped[float] = mapped_column(Float)
    time_known: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (Index("ix_history", "device_id", "property", "observed", "id"),)


class State(Base):
    __tablename__ = "states"
    device_id: Mapped[str] = mapped_column(String, primary_key=True)
    property: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[object] = mapped_column(JSON)
    unit: Mapped[str] = mapped_column(String, default="")
    observed: Mapped[float] = mapped_column(Float)
    received: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String, default="reportado")
    time_known: Mapped[bool] = mapped_column(Boolean, default=True)


class Command(Base):
    __tablename__ = "commands"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    device_id: Mapped[str] = mapped_column(String)
    actor: Mapped[str] = mapped_column(String)
    key: Mapped[str] = mapped_column(String)
    power: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String, default="solicitado")
    response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    updated: Mapped[float] = mapped_column(Float, default=time.time)
    __table_args__ = (UniqueConstraint("actor", "key"), Index("ix_commands_latest", "device_id", "created"))


class Automation(Base):
    __tablename__ = "automations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    definition: Mapped[dict] = mapped_column(JSON)
    runtime: Mapped[dict] = mapped_column(JSON, default=dict)
    updated: Mapped[float] = mapped_column(Float, default=time.time)


class AutomationRun(Base):
    __tablename__ = "automation_runs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    rule_id: Mapped[str] = mapped_column(String, index=True)
    occurrence: Mapped[str] = mapped_column(String)
    definition: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String, default="em execução")
    results: Mapped[list] = mapped_column(JSON, default=list)
    created: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    __table_args__ = (UniqueConstraint("rule_id", "occurrence"),)


class Workflow(Base):
    __tablename__ = 'workflows'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, default='Meu ambiente')
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    graph: Mapped[dict] = mapped_column(JSON)
    runtime: Mapped[dict] = mapped_column(JSON, default=dict)
    updated: Mapped[float] = mapped_column(Float, default=time.time)


class WorkflowRun(Base):
    __tablename__ = 'workflow_runs'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    revision: Mapped[int] = mapped_column(Integer)
    trigger_id: Mapped[str] = mapped_column(String)
    occurrence: Mapped[str] = mapped_column(String)
    graph: Mapped[dict] = mapped_column(JSON)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default='pendente', index=True)
    created: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    updated: Mapped[float] = mapped_column(Float, default=time.time)
    __table_args__ = (UniqueConstraint('revision', 'trigger_id', 'occurrence'),)


class Session(Base):
    __tablename__ = "sessions"
    hash: Mapped[str] = mapped_column(String, primary_key=True)
    csrf: Mapped[str] = mapped_column(String)
    expires: Mapped[float] = mapped_column(Float)


class ApiKey(Base):
    __tablename__ = "api_keys"
    hash: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    control: Mapped[bool] = mapped_column(Boolean, default=False)
    automations: Mapped[bool] = mapped_column(Boolean, default=False)


class Health(Base):
    __tablename__ = "health"
    name: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated: Mapped[float] = mapped_column(Float, default=time.time)


class Wallpaper(Base):
    __tablename__ = "wallpapers"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    image: Mapped[bytes] = mapped_column(LargeBinary)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class Appearance(Base):
    __tablename__ = "appearance"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    selected: Mapped[str] = mapped_column(String, default="solar")


class Rate(Base):
    __tablename__ = "rates"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    window: Mapped[int] = mapped_column(Integer)
    count: Mapped[int] = mapped_column(Integer, default=0)


engine = create_engine(DATABASE_URL, pool_pre_ping=True,
                       **({"connect_args": {"check_same_thread": False}} if DATABASE_URL.startswith("sqlite") else {}))
DB = sessionmaker(engine, expire_on_commit=False)


def health(name, value):
    with DB.begin() as db:
        db.merge(Health(name=name, value=value, updated=time.time()))


def take_rate(key, limit, seconds=60):
    with DB.begin() as db:
        # Rows are initialized during migration/startup; lock serializes API + worker.
        row = db.query(Rate).filter_by(key=key).with_for_update().one()
        window = int(time.time() // seconds)
        if row.window != window:
            row.window, row.count = window, 0
        if row.count >= limit:
            return False
        row.count += 1
        return True
