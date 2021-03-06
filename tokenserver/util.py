# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
import json
import re
from base64 import b32encode
from hashlib import sha1
import binascii
import os

from pyramid.httpexceptions import HTTPError
from webob import Response

from mozsvc.http_helpers import get_url
from mozsvc.exceptions import BackendError

from tokenserver import logger


class ProxyBackend(object):

    def __init__(self, uri, scheme='http', **kw):
        self.scheme = scheme
        self.uri = uri

    def _proxy(self, method, url, data=None, headers=None):
        if data is not None:
            data = json.dumps(data)
        status, headers, body = get_url(url, method, data, headers)
        if body:
            try:
                body = json.loads(body)
            except Exception:
                logger.error("bad json body from sreg (%s): %s" %
                                                        (url, body))
                raise  # XXX
        return status, body

    def _generate_url(self, username, additional_path=None):
        path = "%s://%s/%s" % (self.scheme, self.uri, username)
        if additional_path:
            path = "%s/%s" % (path, additional_path)
        return path


class SRegBackend(ProxyBackend):

    def create_user(self, email):
        username = hash_email(email)
        url = self._generate_url(username)
        password = binascii.b2a_hex(os.urandom(20))[:20]
        payload = {'password': password, 'email': email}
        status, body = self._proxy('PUT', url, payload)
        if status != 200:
            msg = 'Unable to create the user via sreg. '
            msg += 'Received body:\n%s\n' % str(body)
            msg += 'Received status: %d' % status
            raise BackendError(msg, server=url)

        # the result is the username on success
        if body == username:
            return username

        msg = 'Unable to create the user via sreg. '
        msg += 'Received body:\n%s\n' % str(body)
        msg += 'Received status: %d' % status
        raise BackendError(msg, server=url)


class SNodeBackend(ProxyBackend):

    def allocate_user(self, email):
        username = hash_email(email)
        url = self._generate_url(username, 'sync')
        status, body = self._proxy('GET', url)
        if status != 200:
            msg = 'Unable to allocate a note to a user via snode. '
            msg += 'Received body:\n%s\n' % str(body)
            msg += 'Received status: %d' % status
            raise BackendError(msg, server=url)

        # the result is the node on success
        if body is None:
            msg = 'no node for the product is available for assignment '
            raise BackendError(msg, server=url)

        return body


def hash_email(email):
    digest = sha1(email.lower()).digest()
    return b32encode(digest).lower()


def decode_ldap_uri(ldap):
        matchs = re.match(r'(?P<scheme>.+)\:\/\/((?P<username>.+)'\
                           ':(?P<password>.+)@)?(?P<hostname>.+)', ldap)
        if matchs is None:
            raise Exception("wrong ldap scheme defined in the configuration")

        results = matchs.groupdict()

        ldapuri = '%s://%s' % (results['scheme'], results['hostname'])
        bind_password = results['password']
        bind_user = results['username']

        return ldapuri, bind_user, bind_password


class JsonError(HTTPError):
    def __init__(self, status=400, location='body', name='', description=''):
        body = {'status': status, 'errors':
                [{'location': location, 'name': name, 'description': description}]
                }
        Response.__init__(self, json.dumps(body))
        self.status = status
        self.content_type = 'application/json'
