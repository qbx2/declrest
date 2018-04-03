import copy
import functools
import http.client
import re
import urllib.parse
import logging
from collections import defaultdict, Sequence

logger = logging.getLogger(__name__)


class RESTSpec(defaultdict):
    def __init__(self, default_factory=list):
        super().__init__(default_factory)

    def __setattr__(self, key, value):
        self[key] = value

    def __getattr__(self, key):
        if not key.startswith('_'):
            try:
                return self[key]
            except KeyError:
                pass

        raise AttributeError

    def __delattr__(self, key):
        try:
            del self[key]
        except KeyError:
            raise AttributeError

    def __repr__(self):
        return \
            re.sub(r'^[A-Za-z0-9_]+', type(self).__name__, super().__repr__())


class RESTSpecDescriptor:
    def __init__(self, func):
        assert callable(func) and not isinstance(func, type(self))

        self.spec_mutator = func
        self.base_spec = RESTSpec()
        self.instance = None

    def to_spec(self):
        spec = copy.deepcopy(self.base_spec)

        # noinspection PyProtectedMember
        defaults = {
            'scheme': 'http',
            'method': 'GET',
            'headers': {},
        }

        for k, v in defaults.items():
            spec.setdefault(k, v)

        return spec

    def __get__(self, instance=None, owner=None):
        return RESTRequest(self.to_spec(), self.spec_mutator, instance)

    def __call__(self):
        return self.__get__()()


class RESTRequest:
    KEY_VALUE_SPECS = {
        'query': 'query',
        'body': 'body',
        'header': 'headers',
    }

    def __init__(self, base_spec, spec_mutator=None, instance=None):
        self.base_spec = base_spec
        self.spec_mutator = spec_mutator
        self.instance = instance

    # noinspection PyShadowingNames
    def __call__(self):
        spec = self.build_spec()

        _endpoint = _single(spec, 'endpoint')
        _scheme, _netloc, *_ = \
            urllib.parse.urlsplit(_endpoint, scheme=None)

        if _scheme is None:
            scheme = spec.scheme
            _netloc = _endpoint.strip('/')
        else:
            scheme = _scheme.lower()

        spec['endpoint'] = _netloc
        spec['method'] = _maybe(spec, 'method', 'GET')
        spec['headers'] = spec.headers

        _path = _maybe(spec, 'path', '/')
        _query = spec.query
        # use get to prevent defaultdict from creating list() by KeyError
        _body = spec.get('body')

        spec['timeout'] = _maybe(spec, 'timeout')

        format_source = dict(spec)
        format_source.update(path=_path, query=_query, body=_body)

        if self.instance is not None:
            format_source['self'] = self.instance

        spec = self.format_spec(spec, format_source)
        logger.debug(f'spec: {spec}')
        logger.debug(f'endpoint={spec.endpoint}, timeout={spec.timeout}')

        conn = self.create_connection(scheme, spec.endpoint, spec.timeout)
        # noinspection PyProtectedMember
        logger.debug(f'{spec.method} {spec.url} {conn._http_vsn_str}')

        for k, v in spec.headers.items():
            logger.debug(f'{k}: {v}')

        if spec.get('body'):
            logger.debug('')
            logger.debug(spec.get('body'))

        conn.request(spec.method, spec.url, spec.get('body'), spec.headers)
        return conn.getresponse()

    def build_spec(self):
        spec = copy.deepcopy(self.base_spec)

        for source_key, target_key in self.KEY_VALUE_SPECS.items():
            # use get to prevent defaultdict from creating list() by KeyError
            source_value = spec.get(source_key)

            if source_value is not None:
                spec[target_key] = dict(source_value)

                if target_key != source_key:
                    del spec[source_key]

        if self.spec_mutator is not None:
            new_spec = self.spec_mutator(spec)

            if isinstance(new_spec, dict):
                spec = new_spec

        return spec

    # noinspection PyShadowingNames
    def create_connection(self, scheme, endpoint, timeout=None):
        kwargs = {}

        if timeout is not None:
            kwargs['timeout'] = timeout

        if scheme == 'http':
            conn = http.client.HTTPConnection(endpoint, **kwargs)
        elif scheme == 'https':
            conn = http.client.HTTPSConnection(endpoint, **kwargs)
        else:
            raise NotImplementedError(f'RESTRequest does not support {scheme}')

        return conn

    @staticmethod
    def formatter(format_source):
        # noinspection PyShadowingBuiltins
        def format(obj):
            if isinstance(obj, FormatString):
                formatted_str = obj.format_map(format_source)
                logger.debug(f'format: {obj} -> {formatted_str}')
                return formatted_str

            if isinstance(obj, Sequence) and not isinstance(obj, str):
                return type(obj)(map(lambda o: format(o), obj))

            if isinstance(obj, dict):
                formatted_dict = copy.deepcopy(obj)

                for item in obj.items():
                    key, value = map(format, item)
                    formatted_dict[key] = value

                return formatted_dict

            return obj

        return format

    # noinspection PyShadowingNames
    def format_spec(self, spec, format_source):
        url = _path = format_source['path']
        _splitter = '?' if '?' not in _path else '&'

        formatted_spec = copy.deepcopy(spec)

        for item in spec.items():
            key, value = map(self.formatter(format_source), item)
            formatted_spec[key] = value

        query = urllib.parse.urlencode(formatted_spec.query, doseq=True)

        if query:
            url += _splitter + query

        body = _body = formatted_spec.get('body')

        if _body is not None:
            if isinstance(_body, list) or isinstance(_body, tuple) or \
                    isinstance(_body, dict):
                body = urllib.parse.urlencode(_body)
            # elif isinstance(_body, str) or isinstance(_body, bytes):
            #     pass

        formatted_spec['url'] = url
        formatted_spec['body'] = body
        formatted_spec['headers'] = dict(formatted_spec.headers)

        return formatted_spec


class FormatString(str):
    pass


def _maybe(params, key, default=None):
    value = getattr(params, key, [])

    if not isinstance(value, list) and not isinstance(value, tuple):
        return value

    if len(value) > 1:
        raise ValueError(f'{key} requires 1 parameter but got {value}')

    try:
        return value[0]
    except IndexError:
        return default


def _single(params, key):
    value = getattr(params, key, [])

    if not isinstance(value, list) and not isinstance(value, tuple):
        return value

    if len(value) != 1:
        raise ValueError(f'{key} requires 1 parameter but got {value}')

    return value[0]


# decorator
def _obj_with_attrs(obj, **kwargs):
    if not isinstance(obj, RESTSpecDescriptor):
        desc = RESTSpecDescriptor(obj)
    else:
        desc = obj

    for k, v in kwargs.items():
        desc.base_spec[k] += [v]

    return desc


def endpoint(value):
    return lambda obj: _obj_with_attrs(obj, endpoint=value)


def method(value, path='/'):
    return lambda obj: _obj_with_attrs(obj, method=value, path=path)

GET = functools.partial(method, 'GET')
POST = functools.partial(method, 'POST')
PATCH = functools.partial(method, 'PATCH')
DELETE = functools.partial(method, 'DELETE')
HEAD = functools.partial(method, 'HEAD')
OPTIONS = functools.partial(method, 'OPTIONS')


def header(key, value):
    return lambda obj: _obj_with_attrs(obj, header=(key, value))


def query(key, value):
    return lambda obj: _obj_with_attrs(obj, query=(key, value))


def body(key, value):
    return lambda obj: _obj_with_attrs(obj, body=(key, value))


def timeout(value):
    return lambda obj: _obj_with_attrs(obj, timeout=value)


def formatted(fs):
    return FormatString(fs)
