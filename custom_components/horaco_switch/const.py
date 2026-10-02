"""Constants for the HORACO Managed Switch integration."""

DOMAIN = "horaco_switch"

DEFAULT_PORT = 80
DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "admin"
DEFAULT_SCAN_INTERVAL = 30  # seconds

CONF_SCAN_INTERVAL = "scan_interval"

# CGI endpoints — same as byte4geek/switch-dashboard
CGI_LOGIN     = "/login.cgi"
CGI_INFO      = "/info.cgi"
CGI_PORT_STATS = "/port.cgi?page=stats"
CGI_PORT_CFG  = "/port.cgi"
CGI_REBOOT    = "/reboot.cgi"

# RTLPlayground firmware (JSON interface)
CONF_FIRMWARE = "firmware"
FIRMWARE_CGI = "cgi"
FIRMWARE_RTLPLAYGROUND = "rtlplayground"
RTL_LOGIN_PAGE = "/login.html"
RTL_LOGIN  = "/login"
RTL_INFO   = "/information.json"
RTL_STATUS = "/status.json"
RTL_RESET  = "/reset"

def object_id(ip: str, suffix: str) -> str:
    """Language-independent object id, e.g. switch_10_0_1_4_port_1_duplex.

    Set explicitly so that IDs don't follow the (translated) entity name.
    """
    return f"switch_{ip.replace('.', '_')}_{suffix}"


# Port entity key → object id suffix ("" = plain "port_N")
PORT_ID_SUFFIX = {"state": "", "tx_bytes": "tx", "rx_bytes": "rx"}


# Port status values
PORT_STATUS_UP       = "up"
PORT_STATUS_DOWN     = "down"
PORT_STATUS_DISABLED = "disable"
