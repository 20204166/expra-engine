"""Engine error types.

Adapted from ppb/errors.py (PursuedPyBear, Artistic License 2.0).
BadEventHandlerException uses the same diagnostic message style.
"""

from __future__ import annotations


class BadEventHandlerException(TypeError):
    """Raised when an event handler has an incorrect signature.

    Provides a clear diagnostic pointing to the correct signature form.
    """

    def __init__(self, instance: object, method: str, event: object) -> None:
        obj_type = type(instance)
        event_type = type(event)
        o_name = obj_type.__name__
        e_name = event_type.__name__
        article = "an" if e_name.lower()[0] in "aeiou" else "a"
        message = (
            f"\n{o_name}.{method}() signature incorrect; "
            f"it should accept {article} {e_name} object and a signal function.\n\n"
            f"It should look like:\n\n"
            f"    def {method}(self, event: {e_name}, signal):\n"
            f"        ...\n"
        )
        super().__init__(message)


class BadChildException(Exception):
    """Raised when a type (not an instance) is used as a child object."""

    def __init__(self, child: type) -> None:
        type_name = child.__name__
        message = (
            f"child must be an instance, not the type {type_name!r}. "
            f"Try: {type_name}()"
        )
        super().__init__(message)


class NotMyChildError(Exception):
    """Raised when attempting to remove an object that is not a child."""
