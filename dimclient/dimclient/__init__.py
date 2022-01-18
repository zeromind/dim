try:
    import simplejson as json
except:
    import json
from http.cookiejar import LWPCookieJar
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import urlopen, Request, build_opener, HTTPCookieProcessor
import logging
import getpass
import time
import os
import os.path
from pprint import pformat
from typing import Optional
from . import version

__version__ = version.VERSION

logger = logging.getLogger('dimclient')

PROTOCOL_VERSION = 17


class DimError(Exception):
    def __init__(self, message, code=1):
        Exception.__init__(self, message)
        self.code = code

    # Defined so that unicode(DimError) won't blow up
    def __str__(self):
        return self.args[0]


class ProtocolError(DimError):
    pass


class DimClient(object):
    def __init__(self, server_url, cookie_file: Optional[str] = None, cookie_umask: Optional[int] = None):
        self.server_url = server_url
        self.cookie_jar = LWPCookieJar()
        self.session = build_opener(HTTPCookieProcessor(self.cookie_jar))
        if cookie_file:
            self._use_cookie_file(cookie_file, cookie_umask)

    def login(self, username: str, password: str, permanent_session: bool = False) -> bool:
        try:
            self.session.open(self.server_url + '/login',
                              urlencode(dict(username=username,
                                             password=password,
                                             permanent_session=permanent_session)).encode('utf8'))
            self.check_protocol_version()
            self._update_cookie_file()
            return True
        except HTTPError as e:
            logger.error("Login failed: " + str(e))
            return False

    @property
    def logged_in(self) -> bool:
        '''
        Check whether we're already logged in.
        Updates the cookie file with refreshed cookie(s) from the server's response.
        '''
        try:
            self.session.open(self.server_url + '/index.html')
            self._update_cookie_file()
            return True
        except HTTPError as e:
            if e.code == 403:
                return False
            else:
                raise

    def _update_cookie_file(self):
        """Updates cookie file, taking self.cookie_umask into account"""
        if self.cookie_jar.filename and self.save_cookie:
            # Use umask when saving cookie
            if self.cookie_umask is not None:
                old_mask = os.umask(self.cookie_umask)
            self.cookie_jar.save()
            if self.cookie_umask is not None:
                os.umask(old_mask)


    def _use_cookie_file(self, cookie_file: str, cookie_umask: Optional[int], save_cookie: bool = True):
        self.cookie_jar.filename = cookie_file
        self.save_cookie = save_cookie
        self.cookie_umask = cookie_umask
        try:
            self.cookie_jar.load()
        except:
            pass

    def check_protocol_version(self):
        try:
            server_protocol = self.protocol_version()
        except Exception as e:
            raise ProtocolError("The server does not have the JSONRPC interface enabled (%s)" % e)
        if server_protocol != PROTOCOL_VERSION:
            raise ProtocolError("Server protocol version (%s) does not match client protocol version (%s)" %
                                (server_protocol, PROTOCOL_VERSION))

    def raw_call(self, function, *args):
        url = self.server_url + "/jsonrpc"
        json_call = json.dumps(dict(jsonrpc='2.0',
                                    method=function,
                                    params=args,
                                    id=None))
        logger.debug('dim call: %s(%s)' % (function, ', '.join([repr(x) for x in args])))
        start = time.time()
        request = Request(url, data=json_call.encode('utf8'), headers={'Content-Type': 'application/json'})
        response = self.session.open(request).read()
        rpc_response = json.loads(response.decode('utf8'))
        logger.debug('time taken: %.3f' % (time.time() - start))
        if 'error' in rpc_response:
            logger.debug('dim error: ' + str(rpc_response['error']))
            raise DimError(message=rpc_response['error']['message'],
                           code=rpc_response['error']['code'])
        else:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug('dim result: ' + pformat(rpc_response['result']))
            return rpc_response['result']

    def call(self, function, *args, **kwargs):
        '''
        Instead of passing the last argument as a dictionary (usually called
        "options"), you can use keyword arguments.

        .. note::

           Keyword arguments cannot be used for positional jsonrpc arguments.
        '''
        passed_args = args
        if kwargs:
            passed_args += (kwargs,)
        return self.raw_call(function, *passed_args)

    def __getattr__(self, name):
        return lambda *args, **kwargs: self.call(name, *args, **kwargs)

    def ip_list_all(self, **options):
        total = options.get('limit', 10)
        result = []
        while len(result) < total:
            batch = self.ip_list(**options)
            if len(batch) == 0:
                break
            result.extend(batch)
            options['limit'] -= len(batch)
            options['after'] = batch[-1]['ip']
        return result

