"""
DataProvider - the one abstraction every AI tool and agent is allowed to
depend on for hospital data. Nothing above this layer ever imports
FastAPI, psycopg2, or SQLAlchemy.

Two implementations exist (or will exist):
    MockDataProvider   (Phase AI-2) - deterministic fake data, works today.
    BackendDataProvider (future)    - calls the real FastAPI backend once
                                       it exists. Swapping MockDataProvider
                                       for BackendDataProvider should be a
                                       one-line change in wherever the
                                       provider is instantiated - agents
                                       and tools never need to change.

Every method returns None / an empty list rather than raising when data
genuinely doesn't exist - "not found" is a normal, expected outcome in a
hospital device registry, not an error. A method should only raise for
a real fault (e.g. the backend being unreachable once BackendDataProvider
exists) - never to signal "no rows".
"""
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import List, Optional

from ai.models.device import DeviceContext, DeviceProfile
from ai.models.inventory import InventoryContext
from ai.models.maintenance import MaintenanceEvent, MaintenanceSchedule
from ai.models.qa import QAContext
from ai.models.risk import RiskContext
from ai.models.ticket import TicketContext


class DataProvider(ABC):
    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------
    @abstractmethod
    def search_devices(self, query: str, limit: int = 20) -> List[DeviceContext]:
        """Free-text search across device code/name."""

    @abstractmethod
    def get_device(self, device_id: str) -> Optional[DeviceProfile]:
        """Fetch one device by its id. None if it doesn't exist."""

    @abstractmethod
    def get_device_profile(self, device_id: str) -> Optional[DeviceProfile]:
        """Alias of get_device kept distinct per the project brief - a
        BackendDataProvider may one day make these genuinely different
        calls (e.g. profile = device + a few extra joins)."""

    @abstractmethod
    def get_devices_by_status(self, status: str) -> List[DeviceContext]: ...

    @abstractmethod
    def get_devices_by_risk(self, risk_level: str) -> List[DeviceContext]: ...

    @abstractmethod
    def get_devices_by_category(self, category: str) -> List[DeviceContext]: ...

    @abstractmethod
    def get_devices_by_department(self, department: str) -> List[DeviceContext]: ...

    @abstractmethod
    def get_devices_by_location(self, location: str) -> List[DeviceContext]: ...

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------
    @abstractmethod
    def get_maintenance_history(
        self,
        device_id: str,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        maintenance_type: Optional[str] = None,
        technician: Optional[str] = None,
    ) -> List[MaintenanceEvent]: ...

    @abstractmethod
    def get_last_maintenance(self, device_id: str) -> Optional[MaintenanceEvent]: ...

    @abstractmethod
    def get_next_maintenance(self, device_id: str) -> Optional[MaintenanceSchedule]: ...

    @abstractmethod
    def get_preventive_maintenance_status(self, device_id: str) -> Optional[MaintenanceSchedule]: ...

    @abstractmethod
    def get_corrective_maintenance_history(self, device_id: str) -> List[MaintenanceEvent]: ...

    @abstractmethod
    def get_maintenance_statistics(
        self,
        hospital_id: Optional[str] = None,
        department: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> dict: ...

    # ------------------------------------------------------------------
    # Tickets
    # ------------------------------------------------------------------
    @abstractmethod
    def search_tickets(self, query: str, limit: int = 20) -> List[TicketContext]: ...

    @abstractmethod
    def get_ticket(self, ticket_id: str) -> Optional[TicketContext]: ...

    @abstractmethod
    def get_device_tickets(self, device_id: str) -> List[TicketContext]: ...

    @abstractmethod
    def get_open_tickets(
        self, hospital_id: Optional[str] = None, department: Optional[str] = None
    ) -> List[TicketContext]: ...

    @abstractmethod
    def get_resolved_tickets(
        self, hospital_id: Optional[str] = None, date_from: Optional[date] = None
    ) -> List[TicketContext]: ...

    @abstractmethod
    def get_ticket_statistics(
        self,
        priority: Optional[str] = None,
        status: Optional[str] = None,
        department: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> dict: ...

    # ------------------------------------------------------------------
    # Risk
    # ------------------------------------------------------------------
    @abstractmethod
    def get_device_risk(self, device_id: str) -> Optional[RiskContext]:
        """The CURRENT (most recent) risk assessment only."""

    @abstractmethod
    def get_risk_history(self, device_id: str) -> List[RiskContext]:
        """Every assessment ever made for this device, oldest first."""

    @abstractmethod
    def get_high_risk_devices(self) -> List[DeviceContext]: ...

    @abstractmethod
    def get_critical_risk_devices(self) -> List[DeviceContext]: ...

    @abstractmethod
    def get_risk_statistics(self, hospital_id: Optional[str] = None) -> dict: ...

    # ------------------------------------------------------------------
    # QA / Calibration
    # ------------------------------------------------------------------
    @abstractmethod
    def get_device_qa_history(self, device_id: str) -> List[QAContext]: ...

    @abstractmethod
    def get_calibration_history(self, device_id: str) -> List[QAContext]: ...

    @abstractmethod
    def get_failed_qa_records(self, hospital_id: Optional[str] = None) -> List[QAContext]: ...

    @abstractmethod
    def get_upcoming_calibrations(self, within_days: int = 30) -> List[QAContext]: ...

    @abstractmethod
    def get_qa_statistics(self, hospital_id: Optional[str] = None) -> dict: ...

    # ------------------------------------------------------------------
    # Inventory
    # ------------------------------------------------------------------
    @abstractmethod
    def get_part_inventory(self, hospital_id: str, part_name: Optional[str] = None) -> List[InventoryContext]: ...

    @abstractmethod
    def get_low_stock_parts(self, hospital_id: str) -> List[InventoryContext]: ...

    @abstractmethod
    def get_part_usage(self, part_id: str, date_from: Optional[date] = None) -> List[MaintenanceEvent]: ...

    @abstractmethod
    def get_inventory_statistics(self, hospital_id: str) -> dict: ...
