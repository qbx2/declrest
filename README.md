# DeclREST
Declarative RESTful API client for python.

Requires python 3.6+

---

Easily declare your RESTful API and use it directly.

```python
@endpoint('https://api.ipify.org')
@decode()
def get_my_ip(params):
    pass

print(get_my_ip())
```

The code above will simply print your IP address.
It's a piece of cake, isn't it?

```python
@endpoint('http://whatsmyuseragent.org')
@header('User-Agent', f('{my_user_agent}'))
@findall(r'user-agent.*\s*.*intro-text.*?>([^<]*)')
@rethook(lambda r: r[0])
def get_my_user_agent(my_user_agent='DeclREST/1.0', params=None):
    # or
    params.headers['User-Agent'] = my_user_agent

get_my_user_agent('Test-UA')  # returns 'Test-UA'
```

- The function body can mutate the request parameters without any limitation.
- `@findall` finds all matches using `re.findall()`.
- `@rethook` hooks the return value and mutates it.

### How about this?

```python
class Repo:
    @classmethod
    @endpoint(f('https://{cls.__name__}.com/{user_id}/{repo}'))
    @decode()
    def get_repo(cls, user_id, repo='declrest', *, params):  # or declare params as keyword argument using *
        # or
        params.endpoint = f'{cls.__name__}.com/{user_id}/{repo}'

class Github(Repo):
    pass

Github.get_repo('qbx2')
```

String-formatting is also supported using `str.format()` syntax in python.
Supported keys are the names of parameters passed to the function and keys in `params`.

Checkout test.py for more usage.

Thank you.

## Todo list
- Support for sequenced query/body. ex) filename[]=..&filename[]=..
- Support for classes (global decorator)
- Support for asyncio
- Add details for README.md
