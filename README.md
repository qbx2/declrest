# DeclREST
Declarative RESTful API Client for python.

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
@findall(r'user-agent.*\s*.*intro-text.*?>([^<]*)')
@rethook(lambda r: r[0])
def get_my_user_agent(params, my_user_agent='DeclREST/1.0'):
    params.headers['User-Agent'] = my_user_agent

get_my_user_agent('Test-UA')  # returns 'Test-UA'
```

- The function body can mutate the request parameters without any limitation.
- `@findall` finds all matches using `re.findall()`.
- `@rethook` hooks the return value and mutates it.

String-formatting is also supported using `str.format()` syntax in python.

(WIP) Also, `self` can be used for formatting in your class.

Checkout test.py for more usage.

Thank you.

## Todo list
- Support for sequenced query/body. ex) filename[]=..&filename[]=..
- Support for classes (global decorator)
- Support for asyncio
- Add details for README.md
