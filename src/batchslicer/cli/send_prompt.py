"""Ask whether to send the G-code to a printer, in an interactive run.

Offers "Don't send", the printers in the configuration, the printer the last
run sent to, and typing another address. Enter keeps what the last run did:
the printer it sent to, or not sending. This module only handles the
conversation; it does not contact printers.
"""

from collections.abc import Callable, Sequence

from batchslicer.cli.slicer_prompt import SlicerSelectionError
from batchslicer.domain.printers import PrinterHost, PrinterHostError, host_from_address


def prompt_for_printer(
    printers: Sequence[PrinterHost],
    *,
    last: PrinterHost | None = None,
    read_line: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
) -> PrinterHost | None:
    """Return the printer to send to, or None to not send.

    ``printers`` are the configured ones; ``last`` is the printer the last run
    sent to, which is offered too and is the Enter default. Raises
    :class:`SlicerSelectionError` if input ends or is interrupted.
    """
    choices: list[PrinterHost] = list(printers)
    if last is not None and all(last.url != printer.url for printer in choices):
        choices.append(last)
    default = 0
    if last is not None:
        default = next(n for n, printer in enumerate(choices, start=1) if printer.url == last.url)

    write("Send the G-code to a printer?")
    write("  0) Don't send")
    for number, printer in enumerate(choices, start=1):
        note = "  (last time)" if last is not None and printer.url == last.url else ""
        write(f"  {number}) {printer.describe()}{note}")
    write("  Or type another printer's address, such as 192.168.1.50")
    while True:
        try:
            answer = read_line(f"Enter for {default}, a number 0-{len(choices)}, or an address: ").strip()
        except (EOFError, KeyboardInterrupt) as error:
            write("")
            raise SlicerSelectionError("Cancelled.") from error
        if not answer:
            return choices[default - 1] if default else None
        if answer.isdigit() and 0 <= int(answer) <= len(choices):
            return choices[int(answer) - 1] if int(answer) else None
        try:
            typed = host_from_address(answer)
        except PrinterHostError as error:
            write(str(error))
            continue
        if typed is not None:
            return typed
        named = next((p for p in choices if p.name.casefold() == answer.casefold()), None)
        if named is not None:
            return named
        write(f"Please enter a number from 0 to {len(choices)}, or an address.")
