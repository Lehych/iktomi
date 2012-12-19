# -*- coding: utf-8 -*-

__all__ = ['WebHandler', 'cases', 'locations', 'request_endpoint', 'request_filter']

import logging
import types
import httplib
import functools
from webob.exc import HTTPException
from .http import Request, Response, RouteState
from iktomi.utils.storage import VersionedStorage

from copy import copy

logger = logging.getLogger(__name__)


def prepare_handler(handler):
    '''Wrapps functions, that they can be usual WebHandler's'''
    if type(handler) in (types.FunctionType, types.MethodType):
        handler = request_endpoint(handler)
    return handler


class WebHandler(object):
    '''Base class for all request handlers.'''

    def __or__(self, next_handler):
        # XXX copy count depends on chain length geometrically!
        h = self.copy()
        if hasattr(self, '_next_handler'):
            h._next_handler = h._next_handler | next_handler
        else:
            h._next_handler = prepare_handler(next_handler)
        return h

    def handle(self, env, data):
        '''This method should be overridden in subclasses.'''
        return self.next_handler(env, data)

    def _locations(self):
        next_handler = self.next_handler
        # if next_handler is lambda - the end of chain
        if not type(next_handler) is types.FunctionType:
            return next_handler._locations()
        # we are last in chain
        return {}

    def __repr__(self):
        return '%s()' % self.__class__.__name__

    def __call__(self, env, data):
        env._commit()
        data._commit()
        result = self.handle(env, data)
        if result is None:
            if env._modified:
                env._rollback()
            if data._modified:
                data._rollback()
        return result

    @property
    def next_handler(self):
        if hasattr(self, '_next_handler'):
            return self._next_handler
        #XXX: may be request_handler?
        return lambda e, d: None

    def copy(self):
        # to make handlers reusable
        return copy(self)

    def as_wsgi(self):
        from .reverse import Reverse
        root = Reverse.from_handler(self)
        def wsgi(environ, start_response):
            env = VersionedStorage()
            env.request = Request(environ, charset='utf-8')
            env.root = root.bind_to_request(env.request)
            env._route_state = RouteState(env.request)
            data = VersionedStorage()
            try:
                response = self(env, data)
                if response is None:
                    logger.debug('Application returned None '
                                 'instead of Response object')
                    status_int = httplib.NOT_FOUND
                    response = Response(status=status_int, 
                                        body='%d %s' % (status_int, 
                                                        httplib.responses[status_int]))
            except HTTPException, e:
                response = e
            except Exception, e:
                logger.exception(e)
                raise

            headers = response.headers.items()
            start_response(response.status, headers)
            return [response.body]
        return wsgi


class cases(WebHandler):

    def __init__(self, *handlers, **kwargs):
        self.handlers = []
        for handler in handlers:
            self.handlers.append(prepare_handler(handler))

    def __or__(self, next_handler):
        'cases needs to set next handler for each handler it keeps'
        h = self.copy()
        h.handlers = [handler | prepare_handler(next_handler)
                      for handler in self.handlers]
        return h

    def handle(self, env, data):
        for handler in self.handlers:
            result = handler(env, data)
            if result is None:
                continue
            return result

    def _locations(self):
        locations = {}
        for handler in self.handlers:
            handler_locations = handler._locations()
            for k, v in handler_locations.items():
                if k in locations:
                    raise ValueError('Location "%s" already exists' % k)
                locations[k] = v
        return locations

    def __repr__(self):
        return '%s(*%r)' % (self.__class__.__name__, self.handlers)


class _FunctionWrapper2(WebHandler):
    '''
    Wrapper for handler represented by function 
    (2 args, new-style)
    '''

    def __init__(self, func):
        self.handle = func

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, self.handle)


class _FunctionWrapper3(WebHandler):
    '''
    Wrapper for handler represented by function 
    (3 args, old-style)
    '''

    def __init__(self, func):
        self.handler = func

    def handle(self, env, data):
        return self.handler(env, data, self.next_handler)

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, self.handler)


def request_endpoint(func):
    return functools.wraps(func)(_FunctionWrapper2(func))

def request_filter(func):
    return functools.wraps(func)(_FunctionWrapper3(func))


def locations(handler):
    return handler._locations()