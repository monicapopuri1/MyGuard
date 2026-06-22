import uuid
import logging
from datetime import datetime, timezone

from sqlalchemy import create_engine, Column, String, Float, DateTime, text
from sqlalchemy.orm import DeclarativeBase, Session

log = logging.getLogger("store")


class Base(DeclarativeBase):
    pass


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    camera_id = Column(String, nullable=False)
    speed_kmh = Column(Float, nullable=False)
    plate = Column(String, nullable=False)
    timestamp = Column(String, nullable=False)
    clip_path = Column(String, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class IncidentStore:
    def __init__(self, db_path: str = "/data/incidents/garuda.db"):
        self._engine = create_engine(f"sqlite:///{db_path}", echo=False)
        Base.metadata.create_all(self._engine)
        log.info("Incident store ready: %s", db_path)

    def save(self, camera_id: str, speed_kmh: float, plate: str, timestamp: str, clip_path: str = "") -> str:
        incident_id = str(uuid.uuid4())
        with Session(self._engine) as session:
            session.add(Incident(
                id=incident_id,
                camera_id=camera_id,
                speed_kmh=speed_kmh,
                plate=plate,
                timestamp=timestamp,
                clip_path=clip_path,
            ))
            session.commit()
        log.info("Incident stored: %s | plate=%s speed=%.1f", incident_id, plate, speed_kmh)
        return incident_id

    def recent(self, limit: int = 50) -> list[dict]:
        with Session(self._engine) as session:
            rows = session.execute(
                text("SELECT id, camera_id, speed_kmh, plate, timestamp, clip_path, created_at "
                     "FROM incidents ORDER BY created_at DESC LIMIT :lim"),
                {"lim": limit},
            ).fetchall()
        return [
            {
                "id": r[0], "camera_id": r[1], "speed_kmh": r[2],
                "plate": r[3], "timestamp": r[4], "clip_path": r[5], "created_at": str(r[6]),
            }
            for r in rows
        ]
