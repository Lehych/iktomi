# -*- coding: utf-8 -*-

__all__ = ['match', 'method', 'static_files', 'ctype', 'prefix', 'subdomain', 'namespace']

import logging
import httplib
import mimetypes
from os import path
from urllib import quote
from .core import WebHandler
from .http import HttpException, Response
from .url import UrlTemplate


logger = logging.getLogger(__name__)


class match(WebHandler):

    def __init__(self, url, name, convs=None):
        self.url = url
        self.url_name = name
        self.builder = UrlTemplate(url, converters=convs)

    def trace(self, tracer):
        tracer.url_name(self.url_name)
        tracer.builder(self.builder)

    def handle(self, env, data, next_handler):
        matched, kwargs = self.builder.match(env.request.prefixed_path, env=env)
        if matched:
            env.current_url_name = self.url_name
            data.update(kwargs)
            return next_handler(env, data)
        return None

    def __repr__(self):
        return '%s(\'%s\', \'%s\')' % \
                (self.__class__.__name__, self.url, self.url_name)


class method(WebHandler):
    def __init__(self, *names):
        self._names = [name.upper() for name in names]

    def handle(self, env, data, next_handler):
        if env.request.method in self._names:
            return next_handler(env, data)
        return None

    def __repr__(self):
        return 'method(*%r)' % self._names


class ctype(WebHandler):

    xml = 'application/xml'
    json = 'application/json'
    html = 'text/html'
    xhtml = 'application/xhtml+xml'

    def __init__(self, *types):
        self._types = types

    def handle(self, env, data, next_handler):
        if env.request.content_type in self._types:
            return next_handler(env, data)
        return None

    def __repr__(self):
        return '%s(*%r)' % (self.__class__.__name__, self._types)


class static_files(WebHandler):
    def __init__(self, location, url='/static/'):
        self.location = location
        self.url = url

    def add_reverse(self, env):
        def url_for_static(part):
            while part.startswith('/'):
                part = part[1:]
            return path.join(self.url, part)
        env.url_for_static = url_for_static

    def handle(self, env, data, next_handler):
        if env.request.path.startswith(self.url):
            static_path = env.request.path[len(self.url):]
            while static_path.startswith('/'):
                static_path = static_path[1:]
            file_path = path.join(self.location, static_path)
            if path.exists(file_path) and path.isfile(file_path):
                mime = mimetypes.guess_type(file_path)[0]
                response = Response()
                if mime:
                    response.content_type = mime
                with open(file_path, 'r') as f:
                    response.write(f.read())
                return response
            else:
                raise HttpException(httplib.NOT_FOUND)
        return None


class prefix(WebHandler):
    def __init__(self, _prefix, convs=None):
        self.builder = UrlTemplate(_prefix, match_whole_str=False, 
                                   converters=convs)

    def trace(self, tracer):
        tracer.builder(self.builder)

    def handle(self, env, data, next_handler):
        matched, kwargs = self.builder.match(env.request.prefixed_path, env=env)
        if matched:
            data.update(kwargs)
            env.request.add_prefix(self.builder(**kwargs))
            return next_handler(env, data)
        return None

    def __repr__(self):
        return '%s(\'%r\')' % (self.__class__.__name__, self.builder)


class subdomain(WebHandler):
    def __init__(self, _subdomain):
        self.subdomain = unicode(_subdomain)

    def trace(self, tracer):
        if self.subdomain:
            tracer.subdomain(self.subdomain)

    def handle(self, env, data, next_handler):
        subdomain = env.request.subdomain
        #XXX: here we can get 'idna' encoded sequence, that is the bug
        if self.subdomain:
            slen = len(self.subdomain)
            delimiter = subdomain[-slen-1:-slen]
            matches = subdomain.endswith(self.subdomain) and delimiter in ('', '.')
        else:
            matches = not subdomain

        if matches:
            #XXX: here we add subdomain prefix. What codec we need 'utf-8' or 'idna'
            env.request.add_subdomain(quote(self.subdomain.encode('utf-8')))
            #rctx.request.add_subdomain(self.subdomain)
            return next_handler(env, data)
        return None

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, self.subdomain)


class namespace(WebHandler):
    def __init__(self, ns):
        # namespace is str
        self.namespace = ns

    def handle(self, env, data, next_handler):
        if env.namespace:
            env.namespace += '.' + self.namespace
        else:
            env.namespace = self.namespace
        return next_handler(env, data)

    def trace(self, tracer):
        tracer.namespace(self.namespace)
