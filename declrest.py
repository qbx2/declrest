import copy
import functools
import http.client
import json
import re
import urllib.parse
import logging
from collections import defaultdict, Sequence

logger = logging.getLogger(__name__)


class DeclRESTParams(defaultdict):
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


class DeclRESTParamsDescriptor:
    def __init__(self, func):
        assert callable(func) and not isinstance(func, type(self))

        self.params_mutator = func
        self.base_params = DeclRESTParams()
        self.instance = None

    def to_params(self):
        params = copy.deepcopy(self.base_params)

        # noinspection PyProtectedMember
        defaults = {
            'scheme': 'http',
            'method': 'GET',
            'headers': {},
        }

        for k, v in defaults.items():
            params.setdefault(k, v)

        return params

    def __get__(self, instance=None, owner=None):
        return DeclRESTRequest(self.to_params(), self.params_mutator, instance)

    def __call__(self, *args, **kwargs):
        return self.__get__()(*args, **kwargs)


class DeclRESTRequest:
    KEY_VALUE_PARAMS = {
        'query': 'query',
        'form': 'form',
        'header': 'headers',
    }

    def __init__(self, base_params, params_mutator=None, instance=None):
        self.base_params = base_params
        self.params_mutator = params_mutator
        self.instance = instance

    # noinspection PyShadowingNames
    def __call__(self, *args, **kwargs):
        params = self.build_params(*args, **kwargs)

        _endpoint = _single(params, 'endpoint')
        _scheme, _netloc, *_ = \
            urllib.parse.urlsplit(_endpoint, scheme=None)

        if _scheme is None:
            scheme = params.scheme
            _netloc = _endpoint.strip('/')
        else:
            scheme = _scheme.lower()

        params['endpoint'] = _netloc
        params['method'] = _maybe(params, 'method', 'GET')
        params['headers'] = params.headers

        _body = params.get('body', [None])
        assert len(_body) == 1, f'body requires 1 parameter but got {_body}'
        params['body'] = _body[0]

        _path = _maybe(params, 'path', '/')
        _query = params.query
        # use get to prevent defaultdict from creating list() by KeyError
        _form = params.get('form')

        params['timeout'] = _maybe(params, 'timeout')

        format_source = dict(params)
        format_source.update(path=_path, query=_query, form=_form)

        if self.instance is not None:
            format_source['self'] = self.instance

        params = self.format_params(params, format_source)
        logger.debug(f'params: {params}')
        logger.debug(f'endpoint={params.endpoint}, timeout={params.timeout}')

        conn = self.create_connection(scheme, params.endpoint, params.timeout)
        # noinspection PyProtectedMember
        logger.debug(f'{params.method} {params.url} {conn._http_vsn_str}')

        for k, v in params.headers.items():
            logger.debug(f'{k}: {v}')

        if params.get('body'):
            logger.debug('')
            logger.debug(params.get('body'))

        conn.request(
            params.method, params.url, params.get('body'), params.headers)
        ret = conn.getresponse()
        decodes = dict(params.decode)
        logger.debug(f'decodes={decodes}')

        if decodes.get('read'):
            ret = ret.read()

        encoding = decodes.get('decode')

        if encoding is not None:
            ret = ret.decode(encoding)

        regex, flags = decodes.get('findall', (None, None))

        if regex is not None:
            ret = re.findall(regex, ret, flags)

        if decodes.get('json'):
            ret = json.loads(ret)

        logger.debug(f'rethooks={params.rethook}')

        for hook in params.rethook:
            ret = hook(ret)

        return ret

    def build_params(self, *args, **kwargs):
        params = copy.deepcopy(self.base_params)

        for source_key, target_key in self.KEY_VALUE_PARAMS.items():
            # use get to prevent defaultdict from creating list() by KeyError
            source_value = params.get(source_key)

            if source_value is not None:
                params[target_key] = dict(source_value)

                if target_key != source_key:
                    del params[source_key]

        if self.params_mutator is not None:
            new_params = self.params_mutator(params, *args, **kwargs)

            if isinstance(new_params, dict):
                params = new_params

        return params

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
            raise NotImplementedError(f'DeclREST does not support {scheme}')

        return conn

    @staticmethod
    def formatter(format_source):
        # noinspection PyShadowingBuiltins
        def format(obj):
            if isinstance(obj, DeclFormatString):
                formatted_str = obj.format_map(format_source)
                logger.debug(f'format: {obj} -> {formatted_str}')
                return formatted_str

            if isinstance(obj, str):
                return obj

            if isinstance(obj, Sequence):
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
    def format_params(self, params, format_source):
        url = _path = format_source['path']
        _splitter = '?' if '?' not in _path else '&'

        formatted_params = copy.deepcopy(params)

        for item in params.items():
            key, value = map(self.formatter(format_source), item)
            formatted_params[key] = value

        query = urllib.parse.urlencode(formatted_params.query, doseq=True)

        if query:
            url += _splitter + query

        body = formatted_params.get('body')
        _form = formatted_params.get('form')

        if body is None and _form is not None:
            if isinstance(_form, list) or isinstance(_form, tuple) or \
                    isinstance(_form, dict):
                body = urllib.parse.urlencode(_form)
            else:
                raise NotImplementedError(f'Unknown to encode {type(_form)}')
            # elif isinstance(_body, str) or isinstance(_body, bytes):
            #     pass

        formatted_params['url'] = url
        formatted_params['body'] = body
        formatted_params['headers'] = dict(formatted_params.headers)

        return formatted_params


class DeclFormatString(str):
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
def _add_param(obj, **kwargs):
    if not isinstance(obj, DeclRESTParamsDescriptor):
        desc = DeclRESTParamsDescriptor(obj)
    else:
        desc = obj

    for k, v in kwargs.items():
        desc.base_params[k] += [v]

    return desc


def endpoint(value):
    """Set endpoint. http and https are supported."""
    return lambda obj: _add_param(obj, endpoint=value)


def method(value, path='/'):
    """Set method and path."""
    return lambda obj: _add_param(obj, method=value, path=path)

GET = functools.partial(method, 'GET')
POST = functools.partial(method, 'POST')
PATCH = functools.partial(method, 'PATCH')
DELETE = functools.partial(method, 'DELETE')
HEAD = functools.partial(method, 'HEAD')
OPTIONS = functools.partial(method, 'OPTIONS')


def header(key, value):
    """Set header data."""
    return lambda obj: _add_param(obj, header=(key, value))


def query(key, value):
    """Set query data.
    Path is followed by query string."""
    return lambda obj: _add_param(obj, query=(key, value))


def form(key, value):
    """Set form data.
    Use @urlencoded(), @json_encode() to set encoding method."""
    return lambda obj: _add_param(obj, form=(key, value))


def body(value):
    """Set raw body."""
    return lambda obj: _add_param(obj, body=value)


def timeout(value):
    """Set timeout."""
    return lambda obj: _add_param(obj, timeout=value)


def formatted(fs):
    """Annotate given string to be formatted."""
    return DeclFormatString(fs)

f = formatted


def json_encode(value=True):
    """body = json.dumps(form)"""
    raise NotImplementedError
    return lambda obj: _add_param(obj, encode=('json', value))


def encode(encoding='utf-8'):
    """ret = ret.encode(encoding)"""
    raise NotImplementedError
    return lambda obj: _add_param(obj, encode=('encode', encoding))


def read(value=True):
    """ret = HTTPResponse.read()"""
    return lambda obj: _add_param(obj, decode=('read', value))


def decode(encoding='utf-8'):
    """ret = ret.decode(encoding)"""
    def decorator(obj):
        obj = _add_param(obj, decode=('decode', encoding))
        # Set read=True implicitly
        obj = _add_param(obj, decode=('read', True))
        return obj

    return decorator


def json_decode(value=True):
    """ret = json.loads(ret)"""
    def decorator(obj):
        obj = _add_param(obj, decode=('json', value))

        # if True, set read=True implicitly
        if value:
            obj = _add_param(obj, decode=('read', True))

        return obj

    return decorator


def findall(regex, flags=0):
    """ret = re.findall(regex, ret)"""
    def decorator(obj):
        obj = _add_param(obj, decode=('findall', (regex, flags)))
        # Set read=True implicitly
        obj = _add_param(obj, decode=('read', True))
        obj = _add_param(obj, decode=('decode', 'utf-8'))
        return obj

    return decorator


def rethook(hook):
    """ret = hook(ret)"""
    return lambda obj: _add_param(obj, rethook=hook)
