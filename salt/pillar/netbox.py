# -*- coding: utf-8 -*-
'''
Reads pillar information from Netbox

============================
Configuration
--------------------
.. code-block:: yaml
    ext_pillar:
      - netbox:
          url: http://netbox.example.com/
          token: <token> (Optional)
          keyfile: <path to private key> (Optional)
          proxy_config: True (Optional)

The ``url`` parameter is required and points to the netbox web server.

If ``proxy_config`` is set to ``True``, then the proxy configuration will be added
to the pillar. It will search for login credentials in Netbox secrets. If Nebtox secret not
found it will search the salt confiuration for ``proxy_auth``, if found it will search
for keys in the following order:
    ``<minion_id>_username``
    ``<minion_id>_password``
    ``<napalm_proxy_type>_username``
    ``<napalm_proxy_type>_password``
    ``username``
    ``password``
If no password is found it will use ssh private key authentication

Proxy Authentication Example:
.. code-block:: yaml
    proxy_auth:
      router1_username: router1
      router1_password: password
      junos_username: junos
      junos_password: password
      username: username
      password: password
'''

from __future__ import absolute_import, print_function, unicode_literals

import logging

log = logging.getLogger(__name__)

try:
    import pynetbox
    HAS_PYNETBOX = True
except ImportError:
    HAS_PYNETBOX = False
    log.error('pynetbox must be installed')

# Pull the following from Netbox
DEVICE_FIELDS = [
    'id',
    'display_name',
    'device_type',
    'device_role',
    'primary_ip',
    'primary_ip4',
    'primary_ip6',
    'custom_fields'
]

INTERFACE_FIELDS = [
    'id',
    'name',
    'enabled',
    'mtu',
    'mac_address',
    'description',
    'form_factor',
    'is_connected',
    'mgmt_only',
    'lag'
]


def __virtual__():
    if HAS_PYNETBOX:
        return True
    return False


def ext_pillar(minion_id,
               pillar,  # pylint: disable=W0613
               url,
               token=None,
               keyfile=None,
               proxy_config=False):
    '''
    Get pillar information from Netbox
    '''

    nb_api = pynetbox.api(url, token=token, private_key_file=keyfile)
    device = nb_api.dcim.devices.get(name=minion_id)
    device_info = {}
    if device:
        device.platform.full_details()
        napalm_driver = device.platform.napalm_driver
        # If a netbox device has a primary_ip address, it's status is active and
        # a napalm driver is assigned to the device platform then add it to salt
        device_info['netbox'] = {}
        if hasattr(device, 'primary_ip') and device.status.label == 'Active' and napalm_driver:
            for device_field in DEVICE_FIELDS:
                device_info['netbox'][device_field] = getattr(device, device_field)
                if isinstance(
                            device_info['netbox'][device_field],
                            (pynetbox.ipam.IpAddresses, pynetbox.lib.response.Record)
                            ):
                    device_info['netbox'][device_field] = str(device_info['netbox'][device_field])

            # If proxy_config enabled in config, then add proxy pillar information
            if proxy_config:
                device_info['proxy'] = {}
                device_info['proxy']['proxytype'] = 'napalm'
                device_info['proxy']['driver'] = napalm_driver
                device_info['proxy']['host'] = str(device.primary_ip.address.ip)

                # Try and pull username/password from Netbox Secrets
                secret = nb_api.secrets.secrets.get(device=minion_id, role='login-credentials')
                if hasattr(secret, 'plaintext'):
                    device_info['proxy']['username'] = secret.name
                    device_info['proxy']['passwd'] = secret.plaintext
                else:
                    # Use credentials in salt config under 'proxy_auth'. If username is configured without a password,
                    # it will use ssh private key for authentication
                    credentials = __salt__['config.get']('proxy_auth')
                    if credentials:
                        if minion_id + '_username' in credentials:
                            device_info['proxy']['username'] = credentials[minion_id + '_username']
                            if minion_id + '_password' in credentials:
                                device_info['proxy']['passwd'] = credentials[minion_id + '_password']
                        elif napalm_driver + '_username' in credentials:
                            device_info['proxy']['username'] = credentials[napalm_driver + '_username']
                            if napalm_driver + '_password' in credentials:
                                device_info['proxy']['passwd'] = credentials[napalm_driver + '_password']
                        elif 'username' in credentials:
                            device_info['proxy']['username'] = credentials['username']
                            if 'password' in credentials:
                                device_info['proxy']['passwd'] = credentials['password']

        # Get interface and ip addressing information from Netbox and add to the pillar
        interfaces = nb_api.dcim.interfaces.filter(device=minion_id)
        device_info['netbox']['interfaces'] = {}
        for interface in interfaces:
            device_info['netbox']['interfaces'][interface.name] = {}
            for field in INTERFACE_FIELDS:
                device_info['netbox']['interfaces'][interface.name][field] = getattr(interface, field)
                if isinstance(
                            device_info['netbox']['interfaces'][interface.name][field],
                            (pynetbox.ipam.IpAddresses, pynetbox.lib.response.Record)
                            ):
                    device_info['netbox']['interfaces'][interface.name][field] = str(
                        device_info['netbox']['interfaces'][interface.name][field]
                    )

            ip_addresses = nb_api.ipam.ip_addresses.filter(interface_id=interface.id)
            if ip_addresses:
                device_info['netbox']['interfaces'][interface.name]['ip_addresses'] = []
                for ip_address in ip_addresses:
                    device_info['netbox']['interfaces'][interface.name]['ip_addresses'].append(
                        str(ip_address)
                    )

    return device_info
