# DeclREST
Declarative RESTful API Client for python.

Requires python 3.6+

---

Easily declare your RESTful API and use it directly.

```python
@endpoint('https://api.ipify.org')
def get_my_ip(spec):
    pass
```

`print(get_my_ip().read())` will print your IP address. How simple!

The function body can mutate the request parameter without any limitation.

String-formatting is also supported using `str.format()` syntax in python.

(WIP) Also, `self` can be used for formatting in your class.

Checkout test.py for more usage.

Thank you.

## Todo list
- Support for sequenced query/body. ex) filename[]=..&filename[]=..
- Support for classes (global decorator)
- Support for various decoder decorators. ex) @json, @read
- Support for string-formatting by function parameters (kwargs)
- Support for asyncio
- Add details for README.md
