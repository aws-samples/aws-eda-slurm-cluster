#!/usr/bin/env python{{python_minor_version}}

import ssl
print(f"ssl version: {ssl.OPENSSL_VERSION}")
assert ssl.OPENSSL_VERSION.startswith("OpenSSL {{openssl_version}}")
