from __future__ import annotations

import os
from contextlib import contextmanager


@contextmanager
def silence_stderr_fd():
    """Temporarily silence low-level stderr writes (C libraries, native bindings)."""
    try:
        stderr_fd = os.dup(2)
    except OSError:
        yield
        return

    try:
        with open(os.devnull, "w") as devnull:
            os.dup2(devnull.fileno(), 2)
            yield
    finally:
        try:
            os.dup2(stderr_fd, 2)
        finally:
            os.close(stderr_fd)


@contextmanager
def silence_stdio_fd():
    """Temporarily silence low-level stdout and stderr writes from native code."""
    try:
        stdout_fd = os.dup(1)
        stderr_fd = os.dup(2)
    except OSError:
        yield
        return

    try:
        with open(os.devnull, "w") as devnull:
            os.dup2(devnull.fileno(), 1)
            os.dup2(devnull.fileno(), 2)
            yield
    finally:
        try:
            os.dup2(stdout_fd, 1)
        finally:
            os.close(stdout_fd)
        try:
            os.dup2(stderr_fd, 2)
        finally:
            os.close(stderr_fd)
