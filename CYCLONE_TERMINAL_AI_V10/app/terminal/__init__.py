"""MOON-AI Terminal — AI-agent execution subsystem.

Public API:
    from app.terminal import (
        terminal_interface,
        execution_engine,
        session_manager,
        process_manager,
        pty_manager,
        environment_manager,
        history_manager,
        get_bus,
        ExecutionRequest,
        ExecutionResult,
        ExecutionState,
        StateMachine,
        TerminalInterface,
    )
"""

from .backend_manager import BackendManager
from .environment_manager import EnvironmentManager, environment_manager
from .event_bus import Event, get_bus
from .execution_engine import ExecutionEngine, execution_engine
from .history_manager import HistoryEntry, HistoryManager, history_manager
from .models import ExecutionRequest, ExecutionResult
from .output_engine import OutputEngine
from .permission_engine import PermissionEngine
from .process_manager import ProcessInfo, ProcessManager, process_manager
from .pty_manager import PTYManager, pty_manager
from .recovery_engine import RecoveryEngine, recovery_engine
from .risk_engine import RiskEngine
from .session_manager import Session, SessionManager, session_manager
from .state_machine import ExecutionState, StateMachine
from .terminal_interface import TerminalInterface, terminal_interface
from .verification_engine import VerificationEngine

__all__ = [
    # Singletons
    "terminal_interface",
    "execution_engine",
    "session_manager",
    "process_manager",
    "pty_manager",
    "environment_manager",
    "history_manager",
    "recovery_engine",
    "get_bus",
    # Classes
    "TerminalInterface",
    "ExecutionEngine",
    "SessionManager",
    "Session",
    "ProcessManager",
    "ProcessInfo",
    "PTYManager",
    "EnvironmentManager",
    "HistoryManager",
    "HistoryEntry",
    "BackendManager",
    "RiskEngine",
    "PermissionEngine",
    "VerificationEngine",
    "RecoveryEngine",
    "OutputEngine",
    "Event",
    # Models
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionState",
    "StateMachine",
]
