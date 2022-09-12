GeoIP
=====

GeoIP allows us to guess the location of a user based on their IP address.
Our IGeoIP utility provides a couple methods to get location information
from a given IP address.

    >>> from lp.services.geoip.interfaces import IGeoIP
    >>> geoip = getUtility(IGeoIP)

The getCountryByAddr() method will return the country of the given IP
address.

    >>> print(geoip.getCountryByAddr("201.13.165.145").name)
    Brazil

When running tests the IP address will start with '127.', and GeoIP
would, obviously, fail to find the country for that, so we return None.

    >>> print(geoip.getCountryByAddr("127.0.0.88"))
    None

We do the same trick for any IP addresses on private networks.

    >>> print(geoip.getCountryByAddr("10.0.0.88"))
    None

    >>> print(geoip.getCountryByAddr("192.168.0.7"))
    None

    >>> print(geoip.getCountryByAddr("172.16.0.1"))
    None

    >>> print(geoip.getCountryByAddr("::1"))
    None

    >>> print(geoip.getCountryByAddr("fc00::1"))
    None

IGeoIP also provides a getCountryCodeByAddr() method, which returns just the
country code without looking it up in the database.

    >>> print(geoip.getCountryCodeByAddr("201.13.165.145"))
    BR

And again we'll return None if the address is private.

    >>> print(geoip.getCountryCodeByAddr("127.0.0.1"))
    None

If it can't find a GeoIP record for the given IP address, it will return
None.

    >>> print(geoip.getCountryCodeByAddr("255.255.255.255"))
    None
