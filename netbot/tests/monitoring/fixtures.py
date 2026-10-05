"""Payloads representativos de la API de OPNsense usados por las pruebas.

IMPORTANTE: las formas de `system_resources` (memory.total/used) y de los endpoints
documentados están verificadas contra la documentación/código de OPNsense; el resto
(system_time, temperatura, interfaces, leases, firewall) reproducen la forma
observada/esperada y deben contrastarse con un OPNsense real (ver docs/).
"""

CPU_EVENT = {"total": 14, "user": 6, "nice": 0, "sys": 7, "intr": 1, "idle": 86}
CPU_SSE = b'data: {"total": 14, "user": 6, "nice": 0, "sys": 7, "intr": 1, "idle": 86}\n\n'

SYSTEM_RESOURCES = {
    "memory": {
        "total": "8589934592",
        "total_frmt": "8192",
        "used": 2147483648,
        "used_frmt": "2048",
    }
}

SYSTEM_INFORMATION = {
    "name": "fw-evento.localdomain",
    "versions": ["OPNsense 25.1.9-amd64", "FreeBSD 14.2-RELEASE-p3", "OpenSSL 3.0.16"],
}

SYSTEM_TIME = {
    "uptime": "2 days, 03:04:05",
    "datetime": "Sun Oct  4 12:00:00 UTC 2026",
    "boottime": "Fri Oct  2 08:55:55 UTC 2026",
    "config": "Sat Oct  3 10:00:00 UTC 2026",
}

SYSTEM_TEMPERATURE = [
    {
        "device": "cpu.0.temperature",
        "device_seq": "0",
        "temperature": "47.0",
        "type": "cpu",
        "type_translated": "CPU",
    },
    {
        "device": "cpu.1.temperature",
        "device_seq": "1",
        "temperature": "51.5",
        "type": "cpu",
        "type_translated": "CPU",
    },
]

INTERFACES_INFO = {
    "total": 3,
    "rowCount": 3,
    "current": 1,
    "rows": [
        {
            "identifier": "wan",
            "device": "igc0",
            "description": "WAN",
            "status": "up",
            "ipv4": [{"ipaddr": "203.0.113.10", "subnetbits": 24}],
            "ipv6": [{"ipaddr": "fe80::1%igc0", "link-type": "ll"}],
        },
        {
            "identifier": "lan",
            "device": "igc1",
            "description": "LAN",
            "status": "up",
            "ipv4": [{"ipaddr": "192.168.1.1", "subnetbits": 24}],
        },
        {
            "identifier": "opt1",
            "device": "igc1.20",
            "description": "ASISTENTES",
            "status": "no carrier",
            "ipv4": [],
        },
    ],
}

TRAFFIC_INTERFACE = {
    "interfaces": {
        "wan": {
            "name": "WAN",
            "device": "igc0",
            "bytes received": "1000000",
            "bytes transmitted": "250000",
            "packets received": "9000",
            "packets transmitted": "2500",
            "input errors": "3",
            "output errors": "0",
            "collisions": "0",
            "link state": "2",
        },
        "lan": {
            "name": "LAN",
            "device": "igc1",
            "bytes received": "5000",
            "bytes transmitted": "7000",
            "packets received": "50",
            "packets transmitted": "70",
            "input errors": "0",
            "output errors": "0",
            "collisions": "0",
            "link state": "2",
        },
    },
    "time": 1759579200,
}

INTERFACE_STATISTICS = {
    "[WAN] (igc0)": {
        "name": "igc0",
        "address": "aa:bb:cc:00:00:01",
        "received-packets": 9000,
        "received-errors": 3,
        "received-bytes": 1000000,
        "sent-packets": 2500,
        "send-errors": 0,
        "sent-bytes": 250000,
        "collisions": 0,
    },
    "[ASISTENTES] (igc1.20)": {
        "name": "igc1.20",
        "address": "10.20.0.1",
        "received-packets": 10,
        "received-errors": 0,
        "received-bytes": 1000,
        "sent-packets": 20,
        "send-errors": 0,
        "sent-bytes": 2000,
        "collisions": 0,
    },
}

DNSMASQ_LEASES = {
    "total": 4,
    "rowCount": 4,
    "current": 1,
    "rows": [
        {
            "expire": 4102444800,
            "hwaddr": "02:11:22:33:44:55",
            "address": "10.20.0.20",
            "hostname": "iPhone-ab12",
            "if": "igc1.20",
            "if_descr": "ASISTENTES",
        },
        {
            "expire": 1000000000,
            "hwaddr": "02:11:22:33:44:56",
            "address": "10.20.0.21",
            "hostname": "*",
            "if_descr": "ASISTENTES",
        },
        {
            "expire": 0,
            "hwaddr": "AA-BB-CC-DD-EE-FF",
            "address": "192.168.1.50",
            "hostname": "uap-lobby",
            "if": "igc1",
        },
        {
            "expire": 4102444800,
            "hwaddr": "not-a-mac",
            "address": "10.20.0.22",
            "hostname": "broken",
        },
    ],
}

KEA_LEASES = {
    "total": 2,
    "rows": [
        {
            "address": "10.30.0.15",
            "hwaddr": "02:aa:bb:cc:dd:01",
            "hostname": "laptop-staff",
            "expire": 4102444800,
            "state": "0",
            "if_descr": "STAFF",
        },
        {
            "address": "10.30.0.16",
            "hwaddr": "02:aa:bb:cc:dd:02",
            "hostname": "declined",
            "expire": 4102444800,
            "state": "1",
        },
    ],
}

FIREWALL_LOG = [
    {
        "__timestamp__": "2026-10-04T12:00:05+00:00",
        "action": "block",
        "interface": "igc0",
        "src": "198.51.100.7",
        "srcport": "40000",
        "dst": "203.0.113.10",
        "dstport": "22",
        "protoname": "tcp",
        "rid": "abc123",
        "dir": "in",
    },
    {
        "__timestamp__": "2026-10-04T12:00:09+00:00",
        "action": "pass",
        "interface": "igc1.20",
        "src": "10.20.0.20",
        "srcport": "50000",
        "dst": "1.1.1.1",
        "dstport": "53",
        "protoname": "udp",
        "rid": "def456",
    },
    {
        "__timestamp__": "2026-10-04T12:00:07+00:00",
        "action": "rdr",
        "interface": "igc0",
        "src": "198.51.100.8",
        "dst": "203.0.113.10",
        "protoname": "tcp",
    },
    {
        "__timestamp__": "2026-10-04T12:00:01+00:00",
        "action": "block",
        "interface": "igc0",
        "src": "2001:db8::5",
        "dst": "2001:db8::10",
        "proto": "58",
        "label": "ipv6-rule",
    },
    {"__timestamp__": "garbage", "action": "block", "src": "1.2.3.4", "dst": "5.6.7.8"},
]

PF_INFO = {
    "info": {
        "status": "Enabled",
        "state-table": {
            "current entries": "1523",
            "searches": "98765",
            "inserts": "12345",
            "removals": "10822",
        },
        "counters": {"match": "50000", "bad-offset": "0", "fragment": "2", "short": "0"},
    }
}

FIREWALL_STATS = {
    "interfaces": {
        "igc0": {
            "in4_pass_packets": 1000,
            "in4_block_packets": 40,
            "out4_pass_packets": 900,
            "out4_block_packets": 2,
        },
        "igc1": {
            "in4_pass_packets": 500,
            "in4_block_packets": 1,
            "out4_pass_packets": 450,
            "out4_block_packets": 0,
        },
    }
}
