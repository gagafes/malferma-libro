"""Private POSIX launcher for bounded document decoders.

Limits are applied in a fresh interpreter, before replacing it with the native
helper. This avoids preexec_fn, which is unsafe in a multithreaded GTK process.
The limits also apply to decoder descendants and redirected diagnostic files.

SPDX-License-Identifier: GPL-3.0-or-later
"""

import os
import resource
import sys


MAX_OUTPUT_FILE_BYTES = 64 * 1024 * 1024
MAX_ADDRESS_SPACE_BYTES = 2 * 1024 * 1024 * 1024


def _limit(kind, maximum):
    soft, hard = resource.getrlimit(kind)
    finite = [value for value in (soft, hard) if value != resource.RLIM_INFINITY]
    bound = min(maximum, *finite) if finite else maximum
    resource.setrlimit(kind, (bound, bound))


def main(arguments=None):
    command = list(sys.argv[1:] if arguments is None else arguments)
    if not command:
        return 2
    _limit(resource.RLIMIT_FSIZE, MAX_OUTPUT_FILE_BYTES)
    _limit(resource.RLIMIT_AS, MAX_ADDRESS_SPACE_BYTES)
    _limit(resource.RLIMIT_CORE, 0)
    try:
        os.execvp(command[0], command)
    except OSError:
        # Do not disclose document paths or helper diagnostics on the console.
        return 127


if __name__ == "__main__":
    raise SystemExit(main())
