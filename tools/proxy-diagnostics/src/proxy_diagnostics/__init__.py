"""Provider-neutral proxy failure diagnostics."""

from .probe import (
    DiagnosticCode,
    ExitCode,
    ProbeConfig,
    ProbeReport,
    run_probe,
)

__all__ = [
    "DiagnosticCode",
    "ExitCode",
    "ProbeConfig",
    "ProbeReport",
    "run_probe",
]

__version__ = "0.1.0"
