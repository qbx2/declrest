import copy
import functools
import http.client
import inspect
import json
import logging
import re
import urllib.parse
from collections import Sequence
from itertools import zip_longest

logger = logging.getLogger(__name__)


class DeclRESTParams(dict):
    DEFAULTS = {
        'scheme': 'http',
        'method': 'GET',
        'headers': {},
        'body': [None],
        'form': None,
    }

    DEFAULT_FACTORY = list

    def to_base_params(self):
        return copy.deepcopy(self)

    def append(self, key, value):
        try:
            old = super().__getitem__(key)
        except KeyError:
            old = []

        self[key] = old + [value]

    def __setattr__(self, key, value):
        self[key] = value

    def __getattr__(self, key):
        if key.startswith('__') and key.endswidth('__'):
            raise AttributeError

        try:
            return self[key]
        except KeyError:
            raise AttributeError

    def __delattr__(self, key):
        try:
            del self[key]
        except KeyError:
            raise AttributeError

    def __getitem__(self, key):
        try:
            return super().__getitem__(key)
        except KeyError:
            if key in self.DEFAULTS:
                value = self.DEFAULTS[key]
            else:
                value = self.DEFAULT_FACTORY()

            self[key] = value
            return value

    def __repr__(self):
        return f'{type(self).__name__}' \
               f'({repr(self.DEFAULT_FACTORY)}, {super().__repr__()})'

    def copy(self):
        return type(self)(super().copy())


class DeclRESTParamsDescriptor:
    def __init__(self, func):
        assert not isinstance(func, type(self)) and \
               callable(func) or hasattr(func, '__get__')

        self.__func__ = func
        self.declrest_base_params = DeclRESTParams()
        self.instance = None

    def to_base_params(self):
        return self.declrest_base_params.to_base_params()

    def __get__(self, instance=None, owner=None):
        base_params = self.to_base_params()
        return DeclRESTRequest(base_params, self.__func__, instance, owner)

    def __call__(self, *args, **kwargs):
        return self.__get__()(*args, **kwargs)


class DeclRESTRequest:
    KEY_VALUE_PARAMS = {
        'query': 'query',
        'form': 'form',
        'header': 'headers',
    }

    def __init__(self,
                 base_params, params_mutator=None, instance=None, owner=None):
        self.base_params = base_params
        self.params_mutator = params_mutator
        self.instance = instance
        self.owner = owner

        if (instance, owner) != (None, None):
            self.params_mutator = params_mutator.__get__(instance, owner)
            self.unbound_params_mutator = params_mutator
        else:
            self.unbound_params_mutator = None

    def build_params(self, *args, **kwargs):
        params = self.get_declrest_base_params(*args)
        logger.debug(f'declrest_base_params={params}')

        if params is None:
            params = copy.deepcopy(self.base_params)
        else:
            params = copy.deepcopy(params)
            params.update(self.base_params)

        for source_key, target_key in self.KEY_VALUE_PARAMS.items():
            source_value = params[source_key]

            if source_value is not None:
                params[target_key] = dict(source_value)

                if target_key != source_key:
                    del params[source_key]

        if self.params_mutator is not None:
            # TODO: append params to params
            kwargs['params'] = \
                self.update_params(params, kwargs.get('params', {}))
            new_params = self.params_mutator(*args, **kwargs)

            if isinstance(new_params, dict):
                params = type(params)(new_params)

        endpoint_ = _single(params, 'endpoint')
        scheme_, netloc_, *_path_components = \
            urllib.parse.urlsplit(endpoint_, scheme=None)

        if scheme_ is None:
            scheme = params.scheme
            netloc_ = netloc_ or re.findall(r'^[:/]*([^/]*)', endpoint_)[0]
        else:
            scheme = scheme_.lower()

        params.scheme = scheme
        params.endpoint = type(endpoint_)(netloc_)
        params.method = _maybe(params, 'method', 'GET')
        params.headers = params.headers
        params.body = _maybe(params, 'body')

        path_ = _maybe(params, 'path')

        if path_ is None:
            path_, query_, fragment_ = _path_components
            path_ = path_ or '/'

            if query_:
                path_ += f'?{query_}'

            if fragment_:
                path_ += f'#{fragment_}'

            path_ = type(endpoint_)(path_)

        params.path = path_
        params.timeout = _maybe(params, 'timeout')

        # TODO: append params to params
        kwargs.update(params=params)

        format_source = self.build_format_source(*args, **kwargs)
        logger.debug(f'format_source={format_source}')

        params = self.format_params(params, format_source)
        return params

    def build_format_source(self, *args, params, **kwargs):
        format_source = dict(params)

        sig_params_dict = {}
        self_, func = None, None

        if self.unbound_params_mutator is not None:
            self_ = getattr(self.params_mutator, '__self__', None)
            func = getattr(self.params_mutator, '__func__', func)
        elif self.params_mutator is not None:
            func = self.params_mutator

        if func is None:
            format_source.update(kwargs)
            return format_source

        # noinspection PyPep8Naming
        class None_:
            pass

        sig_params = inspect.signature(func).parameters.items()
        logger.debug(f'sig_params={sig_params}')

        if self_ is None:
            given_args = args
        else:
            given_args = (self_,) + args

        logger.debug(f'given_args={given_args}')

        for (k, v), a in zip_longest(sig_params, given_args, fillvalue=None_):
            if k == 'params':
                continue

            if a is not None_:
                sig_params_dict[k] = a
            elif v.default is not inspect.Parameter.empty:
                sig_params_dict[k] = v.default

        format_source.update(sig_params_dict)
        format_source.update(kwargs)
        return format_source

    def __call__(self, *args, **kwargs):
        params = self.build_params(*args, **kwargs)

        logger.debug(f'params: {params}')
        logger.debug(f'endpoint={params.endpoint}, timeout={params.timeout}')

        conn = self.create_connection(
            params.scheme, params.endpoint, params.timeout)
        # noinspection PyProtectedMember
        logger.debug(f'{params.method} {params.url} {conn._http_vsn_str}')

        for k, v in params.headers.items():
            logger.debug(f'{k}: {v}')

        if params.body:
            logger.debug('')
            logger.debug(params.body)

        conn.request(params.method, params.url, params.body, params.headers)
        ret = conn.getresponse()

        logger.debug(f'retmaps={params.retmap}')

        for hook in reversed(params.retmap):
            ret = hook(ret)

        return ret

    def get_cls(self):
        instance, owner = self.instance, self.owner
        logger.debug(f'instance={instance}, owner={owner}')

        if owner is not None:
            return owner

        if instance is not None:
            return type(instance)

        return None

    def get_declrest_base_params(self, *args):
        try:
            self_ = self.params_mutator.__self__
        except AttributeError:
            self_ = None

        try:
            if self_ is not None:
                return self_.declrest_base_params.to_base_params()
        except AttributeError:
            return None

        try:
            cls = args[0]

            if inspect.isclass(cls):
                return cls.declrest_base_params.to_base_params()
        except (IndexError, AttributeError):
            pass

        return None

    # noinspection PyShadowingNames
    def create_connection(self, scheme, endpoint, timeout=None):
        if scheme == 'http':
            conn = http.client.HTTPConnection(endpoint, timeout=timeout)
        elif scheme == 'https':
            conn = http.client.HTTPSConnection(endpoint, timeout=timeout)
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

            logger.debug(f'format({repr(obj)})')

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
        _query = formatted_params.query
        query = urllib.parse.urlencode(_query, doseq=True)

        if query:
            url += _splitter + query

        body = formatted_params.body
        _form = formatted_params.form

        if body is None and _form is not None:
            if isinstance(_form, list) or isinstance(_form, tuple) or \
                    isinstance(_form, dict):
                body = urllib.parse.urlencode(_form)
            else:
                raise NotImplementedError(f'Unknown to encode {type(_form)}')
            # elif isinstance(_body, str) or isinstance(_body, bytes):
            #     pass

        formatted_params.url = url
        formatted_params.body = body
        formatted_params.headers = dict(formatted_params.headers)

        return formatted_params

    @staticmethod
    def update_params(params, new_params):
        # params = old_params.copy()

        for k, v in new_params.items():
            print(k, v)
            if k in params and params[k] is not None:
                if isinstance(params[k], dict):
                    params[k].update(v)
                else:
                    params[k] += v
            else:
                params[k] = v

        return params


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
        desc = functools.update_wrapper(DeclRESTParamsDescriptor(obj), obj)

    for k, v in kwargs.items():
        desc.declrest_base_params.append(k, v)

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


def read():
    """ret = HTTPResponse.read()"""
    return lambda obj: _add_param(obj, retmap=lambda r: r.read())


def decode(encoding='utf-8'):
    """ret = ret.decode(encoding)"""
    def decorator(obj):
        return _add_param(obj, retmap=lambda r: r.decode(encoding))

    return decorator


def json_decode():
    """ret = json.loads(ret)"""
    def decorator(obj):
        return _add_param(obj, retmap=lambda r: json.loads(json))

    return decorator


def findall(regex, flags=0):
    """ret = re.findall(regex, ret)"""
    def decorator(obj):
        return _add_param(obj, retmap=lambda r: re.findall(regex, r, flags))

    return decorator


def retmap(hook):
    """ret = hook(ret)"""
    return lambda obj: _add_param(obj, retmap=hook)
