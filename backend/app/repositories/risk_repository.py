"""Risk assessments (B6 CP1).

Scope: assessments carry organization_id and hospital_id (copied from the device when they are
created), so the caller's DEVICE scope (AccessScope.device_hospital_id: own hospital for engineers
and technicians, None = organization for admins) becomes plain WHERE clauses. Department users have
no access at all (the service refuses them before any lookup). Out of scope = 404.

devices.current_risk_level is written ONLY by the database trigger. This repository merely READS
it: under the device row lock before a write (`lock_device_risk`) and again after the write
(`read_device_risk`), so the service can return and audit what the trigger decided.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.access import AccessScope
from app.core.enums import RiskLevel
from app.models.device import Device
from app.models.risk import RiskAssessment
from app.repositories.device_repository import scope_conditions
from app.repositories.pagination import paginate

SORT = {"assessed_at": RiskAssessment.assessed_at, "created_at": RiskAssessment.created_at,
        "risk_level": RiskAssessment.risk_level}


@dataclass
class RiskFilters:
    device_id: Optional[uuid.UUID] = None
    hospital_id: Optional[uuid.UUID] = None
    risk_level: Optional[RiskLevel] = None
    assessed_by: Optional[uuid.UUID] = None
    assessed_from: Optional[datetime] = None   # inclusive
    assessed_to: Optional[datetime] = None     # exclusive


def _scoped(scope: AccessScope) -> list:
    conditions = [RiskAssessment.organization_id == scope.organization_id]
    if scope.device_hospital_id is not None:
        conditions.append(RiskAssessment.hospital_id == scope.device_hospital_id)
    return conditions


class RiskRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, assessment: RiskAssessment) -> RiskAssessment:
        self.db.add(assessment)
        self.db.flush()
        return assessment

    def get(self, scope: AccessScope, assessment_id: uuid.UUID, for_update: bool = False) -> Optional[RiskAssessment]:
        stmt = select(RiskAssessment).where(RiskAssessment.id == assessment_id, *_scoped(scope))
        if for_update:
            stmt = stmt.with_for_update(of=RiskAssessment)
        return self.db.scalars(stmt.execution_options(populate_existing=True)).first()

    def list(self, scope: AccessScope, f: RiskFilters, sort: str, descending: bool, page: int,
             page_size: int) -> Tuple[List[RiskAssessment], int]:
        stmt = select(RiskAssessment).where(*_scoped(scope))
        for column, value in ((RiskAssessment.device_id, f.device_id), (RiskAssessment.hospital_id, f.hospital_id),
                              (RiskAssessment.risk_level, f.risk_level), (RiskAssessment.assessed_by, f.assessed_by)):
            if value is not None:
                stmt = stmt.where(column == value)
        if f.assessed_from:
            stmt = stmt.where(RiskAssessment.assessed_at >= f.assessed_from)
        if f.assessed_to:
            stmt = stmt.where(RiskAssessment.assessed_at < f.assessed_to)
        column = SORT[sort]
        # deterministic order for equal values: newest created first, then id
        tie = (RiskAssessment.created_at.desc(), RiskAssessment.id.desc()) if descending else \
            (RiskAssessment.created_at.asc(), RiskAssessment.id.asc())
        stmt = stmt.order_by(column.desc() if descending else column.asc(), *tie)
        return paginate(self.db, stmt, page, page_size)

    def same_time_exists(self, device_id: uuid.UUID, assessed_at: datetime,
                         exclude_id: Optional[uuid.UUID] = None) -> bool:
        """Another assessment of the device at exactly this time (D7: the trigger has no tie-breaker).
        Call with the device row locked, so no concurrent writer can add one in between."""
        stmt = select(RiskAssessment.id).where(RiskAssessment.device_id == device_id,
                                               RiskAssessment.assessed_at == assessed_at)
        if exclude_id is not None:
            stmt = stmt.where(RiskAssessment.id != exclude_id)
        return self.db.scalar(stmt.limit(1)) is not None

    def now(self) -> datetime:
        """The database's now() (transaction start): the value PostgreSQL itself would default to."""
        return self.db.scalar(select(func.now()))

    # ---- devices.current_risk_level: READ ONLY (the trigger is its only writer) ---------------------
    def lock_device_risk(self, device_id: uuid.UUID) -> Optional[RiskLevel]:
        """Row lock on the device (only the devices row: no joins), held until commit, returning the
        cached level as it is BEFORE this transaction's write. Every risk writer takes this lock
        first, so each trigger run sees the previous writer's committed row (finding F1)."""
        value = self.db.execute(
            select(Device.current_risk_level).where(Device.id == device_id).with_for_update()
        ).scalar_one()
        return RiskLevel(value) if value is not None else None

    def read_device_risk(self, device_id: uuid.UUID) -> Optional[RiskLevel]:
        """The cached level as the trigger left it (a fresh query, not the ORM identity map)."""
        value = self.db.scalar(select(Device.current_risk_level).where(Device.id == device_id))
        return RiskLevel(value) if value is not None else None

    # ---- CP3: summary (reads the trigger's cache, never recomputes it) ---------------------------------
    def level_counts(self, scope: AccessScope, hospital_id: Optional[uuid.UUID],
                     include_archived: bool) -> Dict[Optional[RiskLevel], int]:
        """Devices in the caller's device scope, counted by devices.current_risk_level (None =
        never assessed). Archived devices only when asked for (admins; checked by the service)."""
        stmt = select(Device.current_risk_level, func.count()).where(*scope_conditions(scope))
        if hospital_id is not None:
            stmt = stmt.where(Device.hospital_id == hospital_id)
        if not include_archived:
            stmt = stmt.where(Device.deleted_at.is_(None))
        rows = self.db.execute(stmt.group_by(Device.current_risk_level)).all()
        return {(RiskLevel(level) if level is not None else None): count for level, count in rows}
