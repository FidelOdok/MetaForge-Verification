"""Linux seccomp network denial inherited by native-engine descendants."""

import ctypes
import ctypes.util
import errno


def deny_network():
    path = ctypes.util.find_library("seccomp")
    if path is None:
        raise RuntimeError("libseccomp is required for native engineering execution")
    library = ctypes.CDLL(path, use_errno=True)
    library.seccomp_init.argtypes = [ctypes.c_uint32]
    library.seccomp_init.restype = ctypes.c_void_p
    library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    library.seccomp_syscall_resolve_name.restype = ctypes.c_int
    library.seccomp_rule_add.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    library.seccomp_load.argtypes = [ctypes.c_void_p]
    library.seccomp_release.argtypes = [ctypes.c_void_p]
    context = library.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
    if not context:
        raise RuntimeError("Cannot initialize network isolation")
    try:
        for name in (b"socket", b"socketpair", b"connect", b"sendto", b"sendmsg", b"sendmmsg"):
            syscall = library.seccomp_syscall_resolve_name(name)
            if syscall < 0 or library.seccomp_rule_add(
                context, 0x00050000 | errno.EPERM, syscall, 0
            ):
                raise RuntimeError("Cannot configure network isolation")
        if library.seccomp_load(context):
            raise RuntimeError("Cannot enable network isolation")
    finally:
        library.seccomp_release(context)
