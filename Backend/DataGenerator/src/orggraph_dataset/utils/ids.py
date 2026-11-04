# Deterministic, collision-safe identifiers
from __future__ import annotations


def company_id(company_index: int) -> str:
    return f"company_{company_index:05d}"


def department_id(company_index: int, local_index: int) -> str:
    return f"dept_{company_index:05d}_{local_index:04d}"


def position_id(company_index: int, local_index: int) -> str:
    return f"pos_{company_index:05d}_{local_index:06d}"


def employee_id(company_index: int, local_index: int) -> str:
    return f"emp_{company_index:05d}_{local_index:06d}"


def observation_id(company_index: int, local_index: int) -> str:
    return f"obs_{company_index:05d}_{local_index:07d}"
