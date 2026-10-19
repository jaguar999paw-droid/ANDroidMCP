"""Input validation shared by the ANDroidMCP servers.

Values here end up as arguments to ``fastboot`` / ``adb`` (always exec'd, never
via a shell), so the goals are: no option injection (leading ``-``), no path
tricks, and bounded length.
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator

_SERIAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,63}$")  # also host:port
_PARTITION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,31}$")
_ADDRESS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,252}:([0-9]{1,5})$")

# Partitions where a bad write can hard-brick a device or destroy user data.
# Compared after stripping an A/B slot suffix.
DANGEROUS_PARTITIONS = frozenset(
    {
        "system", "system_ext", "product", "vendor", "vendor_dlkm", "odm",
        "userdata", "super", "metadata",
        "boot", "init_boot", "vendor_boot", "recovery", "dtbo",
        "vbmeta", "vbmeta_system", "vbmeta_vendor",
        "bootloader", "radio", "modem", "abl", "xbl", "aboot", "sbl1", "tz",
        "preloader", "lk", "persist", "efs", "modemst1", "modemst2", "fsg",
    }
)


def validate_serial(value: str) -> str:
    if not isinstance(value, str) or not _SERIAL_RE.fullmatch(value):
        raise ValueError("invalid device serial")
    return value


def validate_partition(value: str) -> str:
    if not isinstance(value, str) or not _PARTITION_RE.fullmatch(value):
        raise ValueError("invalid partition name")
    return value


def validate_address(value: str) -> str:
    m = _ADDRESS_RE.fullmatch(value) if isinstance(value, str) else None
    if not m or not (0 < int(m.group(1)) <= 65535):
        raise ValueError("address must be host:port")
    return value


def is_dangerous_partition(partition: str) -> bool:
    return re.sub(r"_[ab]$", "", partition.lower()) in DANGEROUS_PARTITIONS


SerialStr = Annotated[str, AfterValidator(validate_serial)]
PartitionStr = Annotated[str, AfterValidator(validate_partition)]
AddressStr = Annotated[str, AfterValidator(validate_address)]
