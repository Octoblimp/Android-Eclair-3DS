#!/bin/sh
# Bridge BusyBox udhcpc to Android 2.0 libnetutils' dhcp.<iface> properties.

ACTION="$1"
DEFAULT_SCRIPT=${DEFAULT_SCRIPT:-/usr/share/udhcpc/default.script}
RESOLVCONF_SCRIPT=${RESOLVCONF_SCRIPT:-/etc/android_resolvconf.sh}
SETPROP=${SETPROP:-/system/bin/setprop}

# Let Buildroot configure the address and routes first.
if [ -x "$DEFAULT_SCRIPT" ]; then
	"$DEFAULT_SCRIPT" "$ACTION"
fi

case "$ACTION" in
	bound|renew)
		set -- $router
		gateway="$1"
		set -- $dns
		dns1="$1"
		dns2="$2"

		"$SETPROP" "dhcp.$interface.ipaddress" "${ip:-0.0.0.0}"
		"$SETPROP" "dhcp.$interface.gateway" "${gateway:-0.0.0.0}"
		"$SETPROP" "dhcp.$interface.mask" "${subnet:-0.0.0.0}"
		"$SETPROP" "dhcp.$interface.dns1" "${dns1:-0.0.0.0}"
		"$SETPROP" "dhcp.$interface.dns2" "${dns2:-0.0.0.0}"
		"$SETPROP" "dhcp.$interface.server" "${serverid:-0.0.0.0}"
		"$SETPROP" "dhcp.$interface.leasetime" "${lease:-0}"

		# Name resolution, for both resolvers, before result is published.
		#
		# default.script above does write /etc/resolv.conf, but only via a
		# mktemp staging file in /tmp and only if it got a dns option;
		# nothing at all writes net.dns*, which is what bionic reads.  The
		# musl-linked /system/bin/telco_https reads resolv.conf and nothing
		# else, so a missed write there is the whole difference between
		# 3DSTelco working and "Could not resolve host".  Do it ourselves,
		# with the gateway as a fallback -- see android_resolvconf.sh.
		#
		# Deliberately ahead of dhcp.$interface.result: libnetutils treats
		# that property appearing as "DHCP finished", and the framework
		# starts resolving the moment it does.
		if [ -x "$RESOLVCONF_SCRIPT" ]; then
			"$RESOLVCONF_SCRIPT" "$interface" $dns
		fi

		# Set result last: libnetutils treats its creation as completion.
		"$SETPROP" "dhcp.$interface.result" ok
		;;
esac

exit 0
