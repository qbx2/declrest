import copy
import functools
import http.client
import inspect
import json
import logging
import re
import urllib.parse
from collections import defaultdict, Sequence
from itertools import zip_longest

logger = logging.getLogger(__name__)


class DeclRESTParams(defaultdict):
    def __init__(self, default_factory=list):
        super().__init__(default_factory)

    def to_base_params(self):
        params = copy.deepcopy(self)

        # noinspection PyProtectedMember
        defaults = {
            'scheme': 'http',
            'method': 'GET',
            'headers': {},
        }

        for k, v in defaults.items():
            params.setdefault(k, v)

        return params

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
        assert not isinstance(func, type(self)) and \
               callable(func) or hasattr(func, '__get__')

        self.params_mutator = func
        self.declrest_base_params = DeclRESTParams()
        self.instance = None

    def to_base_params(self):
        return self.declrest_base_params.to_base_params()

    def __get__(self, instance=None, owner=None):
        return DeclRESTRequest(
            self.to_base_params(), self.params_mutator, instance, owner)

    def __call__(self, *args, **kwargs):
        return self.__get__()(*args, **kwargs)


class DeclRESTRequest:
    KEY_VALUE_PARAMS = {
        'query': 'query',
        'form': 'form',
        'header': 'headers',
    }

    def __init__(
            self, base_params, params_mutator=None, instance=None, owner=None):
        self._params_mutator = params_mutator

        try:
            params_mutator = params_mutator.__get__(instance, owner)
        except (AttributeError, TypeError):
            pass

        self.base_params = base_params
        self.params_mutator = params_mutator
        self.instance = instance
        self.owner = owner

    def __call__(self, *args, **kwargs):
        params = self.build_params(*args, **kwargs)

        _endpoint = _single(params, 'endpoint')
        _scheme, _netloc, *_path_components = \
            urllib.parse.urlsplit(_endpoint, scheme=None)

        if _scheme is None:
            scheme = params.scheme
            _netloc = _netloc or re.findall(r'^[:/]*([^/]*)', _endpoint)[0]
        else:
            scheme = _scheme.lower()

        params['endpoint'] = type(_endpoint)(_netloc)
        params['method'] = _maybe(params, 'method', 'GET')
        params['headers'] = params.headers

        _body = params.get('body', [None])
        assert len(_body) == 1, f'body requires 1 parameter but got {_body}'
        params['body'] = _body[0]

        _path = _maybe(params, 'path')

        if _path is None:
            _path, _query, _fragment = _path_components
            _path = _path or '/'

            if _query:
                _path += f'?{query}'

            if _fragment:
                _path += f'#{fragment}'

            params.path = type(_endpoint)(_path)

        _query = params.query
        # use get to prevent defaultdict from creating list() by KeyError
        _form = params.get('form')

        params['timeout'] = _maybe(params, 'timeout')

        _kwargs = copy.deepcopy(kwargs)
        _kwargs.update({
            'query': _query,
            'path': _path,
            'form': _form,
        })
        format_source = self.build_format_source(params, *args, **_kwargs)
        logger.info(f'format_source={format_source}')
        params = self.format_params(params, format_source)
        logger.info(f'params: {params}')
        logger.info(f'endpoint={params.endpoint}, timeout={params.timeout}')

        conn = self.create_connection(scheme, params.endpoint, params.timeout)
        # noinspection PyProtectedMember
        logger.info(f'{params.method} {params.url} {conn._http_vsn_str}')

        for k, v in params.headers.items():
            logger.info(f'{k}: {v}')

        if params.get('body'):
            logger.info('')
            logger.info(params.get('body'))

        conn.request(
            params.method, params.url, params.get('body'), params.headers)
        ret = conn.getresponse()
        decodes = dict(params.decode)
        logger.info(f'decodes={decodes}')

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

        logger.info(f'rethooks={params.rethook}')

        for hook in params.rethook:
            ret = hook(ret)

        return ret

    def build_format_source(self, params, *args, **kwargs):
        format_source = dict(params)
        format_source.update(kwargs)

        if self.params_mutator is not None:
            class _None:
                pass

            sig_params_dict = {}
            sig_params = \
                inspect.signature(self.params_mutator).parameters.items()
            logger.debug(f'sig_params={sig_params}')

            cls = self.get_cls()

            if isinstance(self._params_mutator, classmethod) and \
                    cls is not None:
                sig_params_dict['cls'] = cls

            if self.instance is not None:
                sig_params_dict['self'] = self.instance

            for (k, v), arg in zip_longest(sig_params, args, fillvalue=_None):
                if k == 'params':
                    continue

                if arg is not _None:
                    sig_params_dict[k] = arg
                elif v.default is not inspect.Parameter.empty:
                    sig_params_dict[k] = v.default

            format_source.update(sig_params_dict)

        return format_source

    def get_cls(self):
        instance, owner = self.instance, self.owner
        logger.debug(f'instance={instance}, owner={owner}')

        if instance is not None or owner is not None:
            cls = owner

            if cls is None:
                cls = type(instance)

            return cls

        return None

    def get_declrest_base_params(self, *args):
        cls = self.get_cls()

        if cls is not None:
            try:
                return cls.declrest_base_params.to_base_params()
            except AttributeError:
                pass

        try:
            cls = args[0]

            if inspect.isclass(cls):
                return cls.declrest_base_params.to_base_params()
        except (IndexError, AttributeError):
            pass

        return None

    def build_params(self, *args, **kwargs):
        params = copy.deepcopy(self.get_declrest_base_params(*args))
        logger.debug(f'declrest_base_params={params}')

        if params is None:
            params = copy.deepcopy(self.base_params)
        else:
            params.update(self.base_params)

        for source_key, target_key in self.KEY_VALUE_PARAMS.items():
            # use get to prevent defaultdict from creating list() by KeyError
            source_value = params.get(source_key)

            if source_value is not None:
                params[target_key] = dict(source_value)

                if target_key != source_key:
                    del params[source_key]

        if self.params_mutator is not None:
            new_params = self.params_mutator(*args, **kwargs, params=params)

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

            logger.info(f'format({repr(obj)})')

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
        _path = format_source['path']
        _splitter = '?' if '?' not in _path else '&'

        formatted_params = copy.deepcopy(params)

        for item in params.items():
            key, value = map(self.formatter(format_source), item)
            formatted_params[key] = value

        url = _single(formatted_params, 'path')
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
    if isinstance(obj, DeclRESTParamsDescriptor):
        desc = obj
    elif inspect.isclass(obj):
        if not hasattr(obj, 'declrest_base_params'):
            obj.declrest_base_params = DeclRESTParams()

        desc = obj
    else:
        desc = DeclRESTParamsDescriptor(obj)

    for k, v in kwargs.items():
        desc.declrest_base_params[k] += [v]

    return desc


def endpoint(value):
    """Set endpoint. http and https are supported."""
    return lambda obj: _add_param(obj, endpoint=value)


def method(value, path=None):
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
