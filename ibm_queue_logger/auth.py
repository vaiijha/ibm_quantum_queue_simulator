"""QiskitRuntimeService factory."""

from __future__ import annotations

import logging
import sys

from qiskit_ibm_runtime import QiskitRuntimeService

from ibm_queue_logger.config import Settings

logger = logging.getLogger(__name__)


def create_service(settings: Settings) -> QiskitRuntimeService:
    if not settings.instance_crn:
        logger.warning(
            "IBM_INSTANCE_CRN not set; SDK will auto-select an instance. "
            "Set IBM_INSTANCE_CRN to target a specific plan."
        )

    kwargs: dict = {
        "channel": settings.channel,
        "token": settings.api_key,
    }
    if settings.instance_crn:
        kwargs["instance"] = settings.instance_crn
    else:
        kwargs["plans_preference"] = ["open"]

    try:
        service = QiskitRuntimeService(**kwargs)
    except Exception as exc:
        message = str(exc).lower()
        if "401" in message or "unauthorized" in message:
            print(
                "Authentication failed (401). Use your IBM Quantum Platform API key "
                "(IBM_QUANTUM_API_KEY), not a bearer/session token.",
                file=sys.stderr,
            )
        raise

    try:
        active = service.active_instance()
        logger.info("Active instance: %s", active)
    except Exception:
        logger.debug("Could not resolve active_instance()", exc_info=True)

    return service
