"""Choose the connection for a printer, by the kind of API it has."""

from batchslicer.domain.printers import OCTOPRINT, PrinterHost
from batchslicer.infrastructure.moonraker import MoonrakerClient
from batchslicer.infrastructure.octoprint import OctoPrintClient
from batchslicer.infrastructure.printer_api import PrinterClient


def client_for(host: PrinterHost, *, timeout_seconds: float = 10.0) -> PrinterClient:
    """Return a client for ``host``: OctoPrint's or Moonraker's."""
    if host.kind == OCTOPRINT:
        return OctoPrintClient(host, timeout_seconds=timeout_seconds)
    return MoonrakerClient(host, timeout_seconds=timeout_seconds)
