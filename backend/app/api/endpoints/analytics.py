"""Dashboard & analytics (B10): read-only aggregates for the web dashboard and the AI assistant.

Staff only (administrators: organization; biomedical engineers and technicians: own hospital);
department users get 403. Every number is computed in PostgreSQL inside the caller's scope;
`hospital_id` / `department_id` only narrow it (outside the scope = zeros, never data).
Contract: docs/api/analytics.md.
"""
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser
from app.core.access import scope_for
from app.core.database import get_db
from app.models.user import User
from app.repositories.analytics_repository import AnalyticsFilters
from app.schemas.analytics import (DashboardOverview, DeviceAnalytics, InventoryAnalytics, MaintenanceAnalytics, ProblemDevices,
                                   TicketAnalytics, TrendAnalytics, TrendInterval, TrendMetric)
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])

ACCESS = ("Staff only: administrators (organization), biomedical engineers and technicians (own hospital); "
          "department users get 403. `hospital_id` / `department_id` only narrow your scope (a hospital outside "
          "it gives zeros). Archived devices are left out unless an administrator sets `include_archived=true` "
          "(403 for other roles).")


def analytics_filters(
    hospital_id: Optional[uuid.UUID] = Query(None, description="Narrow to one hospital (within your scope)."),
    department_id: Optional[uuid.UUID] = Query(None, description="Narrow to one department (within your scope)."),
    include_archived: bool = Query(False, description="Administrators only."),
) -> AnalyticsFilters:
    return AnalyticsFilters(hospital_id=hospital_id, department_id=department_id, include_archived=include_archived)


PERIOD = ("Period: `date_from` / `date_to`, inclusive database dates; default the last 30 days ending today; "
          "`date_from` after `date_to` is 422. ")


@dataclass
class PeriodParams:
    date_from: Optional[date]
    date_to: Optional[date]


def period_params(
    date_from: Optional[date] = Query(None, description="Inclusive (database date). Default: 29 days before date_to."),
    date_to: Optional[date] = Query(None, description="Inclusive (database date). Default: today."),
) -> PeriodParams:
    return PeriodParams(date_from, date_to)


@router.get("/overview", response_model=DashboardOverview, summary="Dashboard overview (KPIs)",
            description="One call for the dashboard's first screen: devices by status and risk, tickets open now, "
                        "schedules overdue / due soon, low stock, QA results, and the period's failures, resolutions, "
                        "MTTR, maintenance performed and preventive compliance. The same rules as the detail "
                        "endpoints. " + PERIOD + ACCESS)
def overview(f: AnalyticsFilters = Depends(analytics_filters), p: PeriodParams = Depends(period_params),
             due_soon_days: int = Query(30, ge=0, le=365), user: User = CurrentUser, db: Session = Depends(get_db)):
    return AnalyticsService(db).overview(scope_for(user), f, p.date_from, p.date_to, due_soon_days)


@router.get("/devices", response_model=DeviceAnalytics, summary="Device statistics",
            description="Devices by status, current risk level (plus `unassessed`), criticality, department and "
                        "category. " + ACCESS)
def device_analytics(f: AnalyticsFilters = Depends(analytics_filters), user: User = CurrentUser,
                     db: Session = Depends(get_db)):
    return AnalyticsService(db).devices(scope_for(user), f)


@router.get("/maintenance", response_model=MaintenanceAnalytics, summary="Maintenance statistics and preventive compliance",
            description="Records performed in the period, by type (`preventive` / `corrective` are the types of those "
                        "names, case-insensitive). Preventive compliance today: devices that are not decommissioned, "
                        "by the due date of their active preventive schedule (overdue / due within `due_soon_days` / on "
                        "track / no schedule), with the most overdue devices. " + PERIOD + ACCESS)
def maintenance_analytics(f: AnalyticsFilters = Depends(analytics_filters), p: PeriodParams = Depends(period_params),
                          due_soon_days: int = Query(30, ge=0, le=365), limit: int = Query(20, ge=1, le=100),
                          user: User = CurrentUser, db: Session = Depends(get_db)):
    return AnalyticsService(db).maintenance(scope_for(user), f, p.date_from, p.date_to, due_soon_days, limit)


@router.get("/tickets", response_model=TicketAnalytics, summary="Ticket statistics and MTTR",
            description="Tickets created in the period by status, priority and department; failures (not cancelled); "
                        "tickets open now; MTTR (hours from report to resolution) of the tickets resolved in the period. "
                        "Admin-deleted tickets never count. " + PERIOD + ACCESS)
def ticket_analytics(f: AnalyticsFilters = Depends(analytics_filters), p: PeriodParams = Depends(period_params),
                     user: User = CurrentUser, db: Session = Depends(get_db)):
    return AnalyticsService(db).tickets(scope_for(user), f, p.date_from, p.date_to)


@router.get("/problem-devices", response_model=ProblemDevices, summary="Devices with the most problems",
            description="Devices ranked by failure tickets created in the period, then corrective maintenance in the "
                        "period, then device code. `min_tickets=2` gives repeated failures. " + PERIOD + ACCESS)
def problem_devices(f: AnalyticsFilters = Depends(analytics_filters), p: PeriodParams = Depends(period_params),
                    min_tickets: int = Query(0, ge=0, le=1000), limit: int = Query(10, ge=1, le=100),
                    user: User = CurrentUser, db: Session = Depends(get_db)):
    return AnalyticsService(db).problem_devices(scope_for(user), f, p.date_from, p.date_to, min_tickets, limit)


@router.get("/inventory", response_model=InventoryAnalytics, summary="Spare-part stock and low stock",
            description="Stock rows, parts, units on hand, low stock (at or below the reorder threshold) and out of "
                        "stock, with the emptiest low-stock rows. Stock belongs to a hospital, so only `hospital_id` "
                        "narrows it (administrators: organization; others: own hospital). Staff only; department users "
                        "get 403.")
def inventory_analytics(hospital_id: Optional[uuid.UUID] = Query(None, description="Narrow to one hospital (within "
                                                                                  "your scope)."),
                        limit: int = Query(20, ge=1, le=100), user: User = CurrentUser, db: Session = Depends(get_db)):
    return AnalyticsService(db).inventory(scope_for(user), hospital_id, limit)


@router.get("/trends", response_model=TrendAnalytics, summary="A metric over time",
            description="`tickets` (failures by creation date), `corrective_maintenance` / `preventive_maintenance` / "
                        "`total_maintenance` (records by performed date) or `mttr_hours` (by resolution date), per "
                        "`day`, ISO `week` (from Monday) or `month`, with every bucket of the period (empty ones "
                        "included). Default period: the last 30 days (day), 12 weeks (week) or 12 months (month) ending "
                        "on `date_to` (default today). At most 366 days for `day` and 24 calendar months otherwise "
                        "(else 422). " + ACCESS)
def trend_analytics(metric: TrendMetric = Query("tickets"), interval: TrendInterval = Query("day"),
                    f: AnalyticsFilters = Depends(analytics_filters),
                    date_from: Optional[date] = Query(None, description="Inclusive (database date)."),
                    date_to: Optional[date] = Query(None, description="Inclusive (database date). Default: today."),
                    user: User = CurrentUser, db: Session = Depends(get_db)):
    return AnalyticsService(db).trends(scope_for(user), f, metric, interval, date_from, date_to)
