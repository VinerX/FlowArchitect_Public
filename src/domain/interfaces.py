from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.pim_model import Flow


class BaseAdapter(ABC):
    """
    Base interface for PIM -> target platform conversion.
    Concrete adapters (e.g., NiFi, Airflow, Dagster) must implement convert().
    """

    @abstractmethod
    def convert(self, pim: Flow) -> dict:
        raise NotImplementedError
