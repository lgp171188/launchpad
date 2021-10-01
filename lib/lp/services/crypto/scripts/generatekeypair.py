# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Generate a NaCl key pair.

The resulting private and public keys are base64-encoded and can be stored
in Launchpad configuration files.  The private key should only be stored in
secret overlays on systems that need it.
"""

__all__ = ['main']

import argparse
import base64

from nacl.public import PrivateKey


def encode_key(key):
    return base64.b64encode(key.encode()).decode('ASCII')


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args()

    key = PrivateKey.generate()
    print('Private: ' + encode_key(key))
    print('Public:  ' + encode_key(key.public_key))
